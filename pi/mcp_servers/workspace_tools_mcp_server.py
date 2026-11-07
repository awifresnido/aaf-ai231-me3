"""Workspace tools for the voice agent (MCP stdio).

Eight tools for the ``workspace`` group — multi-step work on files, code, a
shell, or GitHub — which the 4-tier router escalates to the cloud LLM. All file
and shell operations are path-scoped to WORKSPACE_ROOT (default ~/workspace) so
the surface stays safe. No API keys; only stdlib + the gh CLI for GitHub.

  read_file    — read a text file
  write_file   — write text to a file (creates parent dirs)
  edit_file    — exact find/replace (single occurrence)
  grep         — regex search across workspace files
  bash         — run one shell command (guarded, time-boxed)
  github_repo  — gh CLI wrapper (list / clone / create / issue_list / issue_create)
  send_file    — copy a file into the outbox for retrieval
  serve        — serve a directory over HTTP on a port (background)

Run: .venv/bin/python workspace_tools_mcp_server.py   (stdio transport)
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer

server = MCPServer(
    name="workspace-tools",
    version="0.1.0",
    instructions=(
        "Workspace tools for the voice agent: files, shell, and GitHub. All "
        "paths are relative to the workspace directory. Return short dicts "
        "safe to speak back to the user."
    ),
)

WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", str(Path.home() / "workspace"))).expanduser().resolve()
OUTBOX = WORKSPACE_ROOT / "outbox"
MAX_READ_CHARS = 8000
MAX_GREP_MATCHES = 50
_BASH_TIMEOUT = 30

# Shell commands that are never allowed, regardless of path scoping.
_DENY = (
    r"\bsudo\b",
    r"\brm\s+-[a-z]*rf\s+/(\s|$|\*)",     # rm -rf / or /* (scoped rm -rf is fine)
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\b(shutdown|reboot|halt|poweroff)\b",
    r":\(\)\s*\{",                          # fork bomb
)

try:
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
except OSError:
    pass


def _resolve(relpath: str) -> Path:
    """Resolve a workspace-relative path and refuse escapes/absolutes outside."""
    relpath = (relpath or "").strip() or "."
    if relpath.startswith(("/", "~")):
        raise ValueError("path must be relative to the workspace")
    target = (WORKSPACE_ROOT / relpath).resolve()
    if target != WORKSPACE_ROOT and WORKSPACE_ROOT not in target.parents:
        raise ValueError("path escapes the workspace")
    return target


@server.tool(
    name="read_file",
    description="Read a text file from the workspace. Path is relative to the workspace directory.",
)
def read_file(path: str = "") -> dict:
    try:
        target = _resolve(path)
        if not target.is_file():
            return {"ok": False, "spoken": "I couldn't find that file."}
        text = target.read_text(encoding="utf-8", errors="replace")
        truncated = text[:MAX_READ_CHARS]
        return {"ok": True, "spoken": f"Read {len(text)} characters from {target.name}.",
                "path": str(target), "content": truncated}
    except ValueError as exc:
        return {"ok": False, "spoken": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "spoken": "I couldn't read that file.", "error": exc.__class__.__name__}


@server.tool(
    name="write_file",
    description="Write text to a file in the workspace, creating parent directories as needed.",
)
def write_file(path: str = "", content: str = "") -> dict:
    if not (path or "").strip():
        return {"ok": False, "spoken": "I need a filename."}
    try:
        target = _resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"ok": True, "spoken": f"Wrote {len(content)} characters to {target.name}.",
                "path": str(target)}
    except ValueError as exc:
        return {"ok": False, "spoken": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "spoken": "I couldn't write that file.", "error": exc.__class__.__name__}


@server.tool(
    name="edit_file",
    description="Replace one exact occurrence of a string in a workspace file.",
)
def edit_file(path: str = "", old_string: str = "", new_string: str = "") -> dict:
    try:
        target = _resolve(path)
        if not target.is_file():
            return {"ok": False, "spoken": "I couldn't find that file."}
        if not old_string:
            return {"ok": False, "spoken": "I need the text to replace."}
        text = target.read_text(encoding="utf-8", errors="replace")
        if old_string not in text:
            return {"ok": False, "spoken": "I couldn't find that text to replace."}
        occurrences = text.count(old_string)
        target.write_text(text.replace(old_string, new_string, 1), encoding="utf-8")
        return {"ok": True, "spoken": f"Replaced one match in {target.name}.",
                "occurrences": occurrences, "path": str(target)}
    except ValueError as exc:
        return {"ok": False, "spoken": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "spoken": "I couldn't edit that file.", "error": exc.__class__.__name__}


@server.tool(
    name="grep",
    description="Search workspace files for a regex pattern. Optional path narrows to a subdirectory or file.",
)
def grep(pattern: str = "", path: str = "") -> dict:
    pattern = (pattern or "").strip()
    if not pattern:
        return {"ok": False, "spoken": "I need a search pattern."}
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return {"ok": False, "spoken": "That pattern isn't valid.", "error": str(exc)}
    try:
        base = _resolve(path) if path.strip() else WORKSPACE_ROOT
    except ValueError as exc:
        return {"ok": False, "spoken": str(exc)}
    matches = []
    files = [base] if base.is_file() else base.rglob("*")
    try:
        for p in files:
            if not p.is_file() or p.is_symlink() or OUTBOX in p.parents:
                continue
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(lines, 1):
                if rx.search(line):
                    matches.append({"file": str(p.relative_to(WORKSPACE_ROOT)),
                                    "line": lineno, "text": line[:200]})
                    if len(matches) >= MAX_GREP_MATCHES:
                        return {"ok": True, "spoken": f"Found {len(matches)} matches (capped).",
                                "matches": matches}
    except OSError:
        pass
    if not matches:
        return {"ok": True, "spoken": "No matches found.", "matches": []}
    return {"ok": True, "spoken": f"Found {len(matches)} matches.", "matches": matches}


@server.tool(
    name="bash",
    description="Run one shell command inside the workspace directory. Time-boxed and guarded against destructive commands.",
)
def bash(command: str = "") -> dict:
    command = (command or "").strip()
    if not command:
        return {"ok": False, "spoken": "I need a command to run."}
    for pat in _DENY:
        if re.search(pat, command, re.I):
            return {"ok": False, "spoken": "I'm not allowed to run that command."}
    try:
        proc = subprocess.run(command, shell=True, cwd=str(WORKSPACE_ROOT),
                              capture_output=True, text=True, timeout=_BASH_TIMEOUT)
        return {"ok": proc.returncode == 0,
                "spoken": "Command finished." if proc.returncode == 0 else "Command failed.",
                "exit_code": proc.returncode,
                "stdout": (proc.stdout or "")[:4000],
                "stderr": (proc.stderr or "")[:2000]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "spoken": "That command took too long and was stopped."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "spoken": "I couldn't run that command.", "error": exc.__class__.__name__}


@server.tool(
    name="github_repo",
    description=(
        "GitHub operations via the gh CLI. action is one of: list, clone, create, "
        "issue_list, issue_create. 'repo' is 'owner/name' where needed; 'title' and "
        "'body' are for issue_create."
    ),
)
def github_repo(action: str = "", repo: str = "", title: str = "", body: str = "") -> dict:
    if not shutil.which("gh"):
        return {"ok": False, "spoken": "The gh CLI isn't installed on this device."}
    action = (action or "").strip().lower()
    repo = (repo or "").strip()
    if action not in ("list", "clone", "create", "issue_list", "issue_create"):
        return {"ok": False, "spoken": "I don't know that GitHub action."}

    def _run(cmd, timeout=30):
        proc = subprocess.run(cmd, cwd=str(WORKSPACE_ROOT), capture_output=True,
                              text=True, timeout=timeout)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    try:
        if action == "list":
            rc, out = _run(["gh", "repo", "list", "--limit", "20"])
        elif action == "clone":
            if not repo:
                return {"ok": False, "spoken": "I need a repository to clone."}
            rc, out = _run(["gh", "repo", "clone", repo], timeout=120)
        elif action == "create":
            name = (repo or "").split("/")[-1]
            if not name:
                return {"ok": False, "spoken": "I need a repository name."}
            rc, out = _run(["gh", "repo", "create", name, "--private"])
        elif action == "issue_list":
            if not repo:
                return {"ok": False, "spoken": "I need a repository to list issues for."}
            rc, out = _run(["gh", "issue", "list", "--repo", repo, "--limit", "20"])
        else:  # issue_create
            if not repo or not title:
                return {"ok": False, "spoken": "I need a repository and a title."}
            cmd = ["gh", "issue", "create", "--repo", repo, "--title", title]
            if body:
                cmd += ["--body", body]
            rc, out = _run(cmd)
        return {"ok": rc == 0, "spoken": "Done." if rc == 0 else "GitHub command failed.",
                "exit_code": rc, "output": out[:3000]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "spoken": "That GitHub command took too long and was stopped."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "spoken": "I couldn't run that GitHub command.", "error": exc.__class__.__name__}


@server.tool(
    name="send_file",
    description="Copy a workspace file into the outbox directory for retrieval.",
)
def send_file(path: str = "") -> dict:
    try:
        target = _resolve(path)
        if not target.is_file():
            return {"ok": False, "spoken": "I couldn't find that file."}
        OUTBOX.mkdir(parents=True, exist_ok=True)
        dest = OUTBOX / target.name
        shutil.copy2(target, dest)
        return {"ok": True, "spoken": f"Copied {target.name} to the outbox.",
                "path": str(dest), "size": dest.stat().st_size}
    except ValueError as exc:
        return {"ok": False, "spoken": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "spoken": "I couldn't send that file.", "error": exc.__class__.__name__}


@server.tool(
    name="serve",
    description="Serve a workspace directory over HTTP on a port (background process).",
)
def serve(path: str = "", port: int = 8000) -> dict:
    try:
        base = _resolve(path) if path.strip() else WORKSPACE_ROOT
        port = max(1024, min(int(port or 8000), 65535))
        proc = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port), "--directory", str(base)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return {"ok": True, "spoken": f"Serving {base.name} on port {port}.",
                "url": f"http://<device-ip>:{port}/", "pid": proc.pid, "directory": str(base)}
    except ValueError as exc:
        return {"ok": False, "spoken": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "spoken": "I couldn't start the server.", "error": exc.__class__.__name__}


if __name__ == "__main__":
    server.run("stdio")
