"""Explicit Pi/Jetson VCM stdio placement and a restricted SSH entry point."""

import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shlex
import sys


JETSON_ROOT = "/home/aldwin/voice-agent-vcm"
TOOL_SETTINGS = ("VOICE_TOOLS_TZ", "WEATHER_LAT", "WEATHER_LON")
SSH_SETTINGS = ("VCM_JETSON_SSH_TARGET", "VCM_JETSON_SSH_KEY", "VCM_JETSON_KNOWN_HOSTS", "VCM_JETSON_DATA_DIR")


@dataclass
class VCMServerSpec:
    host: str
    command: str
    args: list[str]
    env: dict[str, str]

    @property
    def transport(self):
        return "ssh_stdio" if self.host == "jetson" else "local_stdio"

    @property
    def state_backend(self):
        return self.env.get("VCM_STATE_BACKEND", "local_sqlite")

    def server_params(self):
        from mcp import StdioServerParameters
        return StdioServerParameters(command=self.command, args=self.args, env=self.env)


def build_vcm_server(project_dir, *, diagnostics=None, environ=None):
    env = os.environ if environ is None else environ
    host = env.get("VCM_TOOL_SERVER_HOST", "pi").strip().lower()
    if host not in {"pi", "jetson"}:
        raise ValueError("VCM_TOOL_SERVER_HOST must be pi or jetson")
    settings = {key: env[key] for key in TOOL_SETTINGS if key in env}
    if host == "pi":
        backend = env.get("VCM_STATE_BACKEND", "jetson_sqlite").strip().lower()
        if backend not in {"local_sqlite", "jetson_sqlite"}:
            raise ValueError("VCM_STATE_BACKEND must be local_sqlite or jetson_sqlite")
        child_env = {**settings, "VCM_TOOL_SERVER_HOST": "pi", "VCM_STATE_BACKEND": backend}
        child_env.update({key: env[key] for key in (*SSH_SETTINGS, "VCM_STATE_TIMEOUT_SECS") if key in env})
        if env.get("VOICE_TOOLS_DATA"):
            child_env["VOICE_TOOLS_DATA"] = env["VOICE_TOOLS_DATA"]
        if diagnostics:
            child_env.update(diagnostics.server_env())
        return VCMServerSpec(host, env.get("VENV_PY", "/home/aldwinrpi4/pipecat-quickstart/server/.venv/bin/python"),
                             [str(Path(project_dir) / "mcp_servers" / "voice_tools_mcp_server.py")], child_env)

    return build_ssh_spec(env, settings=settings, diagnostics=diagnostics, kind="voice-agent-vcm")


def build_state_worker(*, diagnostics=None, environ=None):
    return build_ssh_spec(os.environ if environ is None else environ, settings={},
                          diagnostics=diagnostics, kind="voice-agent-state")


def build_ssh_spec(env, *, settings, diagnostics, kind):
    target = env.get("VCM_JETSON_SSH_TARGET", "aldwin@192.168.5.11")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9_][A-Za-z0-9_.-]*", target):
        raise ValueError("Invalid VCM_JETSON_SSH_TARGET")
    key = env.get("VCM_JETSON_SSH_KEY", "/home/aldwinrpi4/.ssh/id_ed25519_vcm_jetson")
    known_hosts = env.get("VCM_JETSON_KNOWN_HOSTS", "/home/aldwinrpi4/.ssh/known_hosts_vcm_jetson")
    if not all(Path(p).is_absolute() for p in [key, known_hosts]):
        raise ValueError("Jetson SSH key and known-hosts paths must be absolute")
    request = {"data_dir": env.get("VCM_JETSON_DATA_DIR", JETSON_ROOT + "/state"),
               "settings": settings, "diagnostics_run": diagnostics.run if diagnostics else None}
    token = base64.urlsafe_b64encode(json.dumps(request, separators=(",", ":")).encode()).decode()
    # The authorized key forces --serve below. This is an inert request, never
    # a user-controlled shell command, executable path, or forwarded API key.
    command = shlex.join([kind, token])
    return VCMServerSpec("jetson", "ssh", ["-F", "/dev/null", "-T", "-i", key,
        "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        "-o", "UserKnownHostsFile=" + known_hosts, "-o", "ConnectTimeout=5",
        "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2", target, command], {})


def decode_remote_request(command, *, state_root, kind="voice-agent-vcm"):
    parts = shlex.split(command)
    if kind not in {"voice-agent-vcm", "voice-agent-state"} or len(parts) != 2 or parts[0] != kind or len(parts[1]) > 8192:
        raise ValueError("Expected a bounded voice-agent-vcm request")
    try:
        request = json.loads(base64.b64decode(parts[1], altchars=b"-_", validate=True))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid VCM request encoding") from exc
    if not isinstance(request, dict) or set(request) != {"data_dir", "settings", "diagnostics_run"}:
        raise ValueError("Invalid VCM request fields")
    if not isinstance(request["data_dir"], str) or not Path(request["data_dir"]).is_absolute():
        raise ValueError("VCM state directory must be absolute")
    root = Path(state_root).resolve()
    data_dir = Path(request["data_dir"]).resolve()
    if not data_dir.is_relative_to(root):
        raise ValueError("VCM state directory must remain under the Jetson state root")
    settings = request["settings"]
    if not isinstance(settings, dict) or not set(settings) <= set(TOOL_SETTINGS):
        raise ValueError("Only VCM timezone/weather settings may be forwarded")
    if any(not isinstance(v, str) or len(v) > 256 or any(ord(c) < 32 for c in v) for v in settings.values()):
        raise ValueError("Invalid VCM setting value")
    child_env = {**settings, "VOICE_TOOLS_DATA": str(data_dir), "VCM_TOOL_SERVER_HOST": "jetson",
                 "VOICE_DIAGNOSTICS": "0", "VCM_STATE_BACKEND": "local_sqlite"}
    run = request["diagnostics_run"]
    if run is not None:
        if not isinstance(run, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run):
            raise ValueError("Invalid VCM diagnostic run")
        child_env.update(VOICE_DIAGNOSTICS="1", VOICE_DIAGNOSTICS_RUN=run,
                         VOICE_DIAGNOSTICS_DIR="/dev/shm/voice-agent-diagnostics")
    return child_env


def serve_remote():
    root = Path(__file__).resolve().parent.parent
    command = os.environ.get("SSH_ORIGINAL_COMMAND", "")
    parts = shlex.split(command)
    kind = parts[0] if parts else ""
    settings = decode_remote_request(command, state_root=root / "state", kind=kind)
    os.umask(0o077)
    child_env = {**os.environ, **settings}
    child_env.pop("SSH_ORIGINAL_COMMAND", None)
    server = (root / "pi" / "vcm_state_worker.py" if kind == "voice-agent-state" else
              root / "pi" / "mcp_servers" / "voice_tools_mcp_server.py")
    os.execve(sys.executable, [sys.executable, str(server)], child_env)


if __name__ == "__main__":
    if sys.argv[1:] != ["--serve"]:
        raise SystemExit("This entry point is only for the restricted VCM SSH key")
    serve_remote()
