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

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

from mcp.server.mcpserver import MCPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stall_diagnostics import Diagnostics, META_KEY

diagnostics = Diagnostics.from_env("mcp")


class ProfiledWorkspaceServer(MCPServer):
    async def call_tool(self, name, arguments, context=None):
        if diagnostics is None:
            return await super().call_tool(name, arguments, context)
        ctx = context if context is not None else self.get_context()
        try:
            call_id = (ctx.request_context.meta or {}).get(META_KEY, "")
        except (ValueError, AttributeError):
            call_id = ""
        if not isinstance(call_id, str) or not re.fullmatch(r"[0-9a-f]{32}", call_id):
            call_id = uuid.uuid4().hex
        # Record metadata for the demo without logging file contents or shell commands.
        safe_args = {k: v for k, v in (arguments or {}).items() if k in {"path", "port"}}
        if isinstance((arguments or {}).get("content"), str):
            safe_args["content_chars"] = len(arguments["content"])
        with diagnostics.call(call_id), diagnostics.span("mcp_server_call", tool=name, arguments=safe_args) as fields:
            result = await super().call_tool(name, arguments, ctx)
            payload = getattr(result, "structured_content", None)
            if payload is None:
                content = getattr(result, "content", [])
                payload = getattr(content[0], "text", None) if content else None
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except ValueError:
                    payload = None
            if isinstance(payload, dict):
                fields["result"] = {k: payload[k] for k in ("ok", "path", "url", "size", "pid", "reused") if k in payload}
            return result


server = ProfiledWorkspaceServer(
    name="workspace-tools",
    version="0.1.0",
    instructions=(
        "Workspace tools for the voice agent: files, shell, and GitHub. All "
        "paths must be relative to the workspace directory; use '.' to serve "
        "the workspace. write_file requires path and content. Return short dicts "
        "safe to speak back to the user."
    ),
)


@server.tool(
    name="get_system_inventory",
    description="Get the voice agent's configured models, locations, and registered MCP servers. Use when asked what the agent is running; values are configuration, not a live health check.",
)
def get_system_inventory() -> dict:
    raw = os.getenv("ME3_SYSTEM_INVENTORY", "")
    if not raw:
        return {"ok": False, "spoken": "The current system inventory is unavailable."}
    try:
        inventory = json.loads(raw)
        if not isinstance(inventory, dict):
            raise ValueError("Invalid inventory")
        return {"ok": True, "spoken": "I found the current system configuration.",
                "inventory": inventory, "source": "voice agent startup configuration"}
    except (ValueError, TypeError):
        return {"ok": False, "spoken": "The current system inventory is unavailable."}

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
    description="Write text to a workspace-relative path. Supply both path and content; create parent directories as needed.",
)
def write_file(path: str, content: str) -> dict:
    if not (path or "").strip():
        return {"ok": False, "spoken": "I need a filename."}
    try:
        target = _resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"ok": True, "spoken": f"Wrote {len(content)} characters to {target.name}.",
                "path": str(target.relative_to(WORKSPACE_ROOT))}
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


def _cluster_address():
    """Use the Pi's address on the cluster route, not a placeholder or loopback."""
    configured = os.getenv("WORKSPACE_PUBLIC_HOST", "").strip()
    if configured:
        return configured
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect((os.getenv("WORKSPACE_ROUTE_TARGET", "192.168.5.11"), 9))
        address = probe.getsockname()[0]
    if address.startswith("127.") or address == "0.0.0.0":
        raise OSError("No usable cluster address")
    return address


def _listener_ready(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=.2):
            return True
    except OSError:
        return False


def _existing_http_server(port, base, proc_root=Path("/proc")):
    """Identify a matching local Python HTTP server; never claim other listeners."""
    for process in proc_root.glob("[0-9]*"):
        try:
            parts = (process / "cmdline").read_bytes().decode("utf-8").split("\0")
            index = parts.index("http.server")
            directory = parts[parts.index("--directory") + 1]
            if parts[index - 1] == "-m" and parts[index + 1] == str(port) and Path(directory).resolve() == base:
                return int(process.name)
        except (OSError, UnicodeError, ValueError, IndexError):
            continue
    return None


def _launch_http_server(port, base):
    """Prefer a separate user service so restarting the voice bot keeps the page up."""
    command = [sys.executable, "-m", "http.server", str(port), "--directory", str(base)]
    runtime = Path(f"/run/user/{os.getuid()}")
    runner = shutil.which("systemd-run")
    if os.getenv("WORKSPACE_SYSTEMD", "1") == "1" and runner and (runtime / "bus").exists():
        unit = f"me3-workspace-http-{port}-{uuid.uuid4().hex[:8]}"
        env = {**os.environ, "XDG_RUNTIME_DIR": str(runtime)}
        started = subprocess.run([runner, "--user", "--quiet", "--collect", "--unit", unit, *command],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, timeout=8)
        if started.returncode == 0:
            for _ in range(40):
                pid = _existing_http_server(port, base)
                if pid is not None and _listener_ready(port):
                    return {"pid": pid, "survives_bot_restart": True, "unit": unit}
                time.sleep(.05)
            subprocess.run(["systemctl", "--user", "stop", unit], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, env=env, timeout=8)
            raise OSError("Web service did not become ready")
    proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        if proc.poll() is not None:
            raise OSError("Web server exited")
        if _listener_ready(port):
            return {"pid": proc.pid, "survives_bot_restart": False}
        time.sleep(.05)
    proc.terminate()
    raise OSError("Web server did not become ready")


@server.tool(
    name="serve",
    description="Serve a workspace-relative directory over HTTP. Use path '.' for the workspace root. Returns its usable LAN URL.",
)
def serve(path: str = "", port: int = 8000) -> dict:
    try:
        base = _resolve(path) if path.strip() else WORKSPACE_ROOT
        if not base.is_dir():
            return {"ok": False, "spoken": "I couldn't find that directory."}
        port = max(1024, min(int(port or 8000), 65535))
        address = _cluster_address()
        if _listener_ready(port):
            existing = _existing_http_server(port, base)
            if existing is None:
                return {"ok": False, "spoken": f"Port {port} is already in use by another service."}
            return {"ok": True, "spoken": f"The workspace is already served on port {port}.",
                    "url": f"http://{address}:{port}/", "pid": existing,
                    "directory": str(base), "reused": True}
        server_info = _launch_http_server(port, base)
        return {"ok": True, "spoken": f"Serving {base.name} on port {port}.",
                "url": f"http://{address}:{port}/", **server_info,
                "directory": str(base), "reused": False}
    except ValueError as exc:
        return {"ok": False, "spoken": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "spoken": "I couldn't start the server.", "error": exc.__class__.__name__}


if __name__ == "__main__":
    server.run("stdio")
