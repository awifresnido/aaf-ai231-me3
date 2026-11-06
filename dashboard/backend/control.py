"""Pipeline control for the dashboard.

The dashboard is read-only EXCEPT for two demo affordances the operator asked
for (both opt-in and isolated here so the rest of the codebase stays read-only):

- **New test** — SSH to the Pi and restart the bot's *user* service, which
  starts a fresh diagnostics run (a new run-id). This is the only path that
  drives the pipeline.
- **Save** — copy a run's diagnostics into a durable ``data/saved/`` archive so
  a good demo run can be kept.

Both fail cleanly (and are reported by the API as a 500) if the SSH key, host,
or service are unreachable. They never touch a cloud model.
"""

import os
import shutil
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]            # .../me3-laya
BASE = (REPO / ".." / "..").resolve()                 # /opt/data (container) / ~/.hermes (host)
DASHBOARD_DIR = REPO / "dashboard"
DATA_DIR = Path(os.environ.get("DASHBOARD_DATA_DIR", str(DASHBOARD_DIR / "data")))
SAVED_DIR = Path(os.environ.get("DASHBOARD_SAVED_DIR", str(DATA_DIR / "saved")))
LOCAL_CONTROL = os.environ.get("DASHBOARD_LOCAL_CONTROL", "0") == "1"

PI_USER = os.environ.get("PI_USER", "aldwinrpi4")
PI_HOST = os.environ.get("PI_HOST", "192.168.5.12")
SERVICE = os.environ.get("ME3_SERVICE", "me3-local-audio")
REMOTE_DIR = "/dev/shm/voice-agent-diagnostics"

_legacy_key = BASE / "home" / ".ssh" / "id_ed25519"
_legacy_hosts = BASE / ".ssh" / "known_hosts"
SSH_KEY = os.environ.get("DASHBOARD_SSH_KEY", str(_legacy_key) if _legacy_key.is_file() else "")
KNOWN_HOSTS = os.environ.get("DASHBOARD_KNOWN_HOSTS", str(_legacy_hosts) if _legacy_hosts.is_file() else "")
SSH_CONFIG = os.environ.get("DASHBOARD_SSH_CONFIG", "")

_SSH_BASE = ["ssh"]
if SSH_CONFIG:
    _SSH_BASE += ["-F", SSH_CONFIG]
if SSH_KEY:
    _SSH_BASE += ["-i", SSH_KEY, "-o", "IdentitiesOnly=yes"]
if KNOWN_HOSTS:
    _SSH_BASE += ["-o", "UserKnownHostsFile=" + KNOWN_HOSTS]
_SSH_BASE += ["-o", "ConnectTimeout=6", "-o", "BatchMode=yes", f"{PI_USER}@{PI_HOST}"]


def _run_ssh(remote_cmd: str, timeout: int = 20):
    return subprocess.run(
        _SSH_BASE + [remote_cmd], capture_output=True, text=True, timeout=timeout
    )


def newest_run_id():
    """Most recently modified diagnostics dir on the Pi, or None."""
    if LOCAL_CONTROL:
        files = list(Path(REMOTE_DIR).glob("*/pi-*.jsonl"))
        return max(files, key=lambda p: p.stat().st_mtime).parent.name if files else None
    r = _run_ssh(f"ls -t {REMOTE_DIR} 2>/dev/null | head -1")
    out = (r.stdout or "").strip().splitlines()
    return out[0] if out else None


def restart_bot():
    """Restart the bot service and wait for a fresh run-id to appear.

    Returns the new run-id, or the previous one if no new run showed up within
    the poll window (the UI treats that as a soft failure).
    """
    before = newest_run_id()
    r = (subprocess.run(["systemctl", "--user", "restart", SERVICE],
                        capture_output=True, text=True, timeout=20)
         if LOCAL_CONTROL else _run_ssh(
             "export XDG_RUNTIME_DIR=/run/user/$(id -u); "
             f"systemctl --user restart {SERVICE}"))
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip()
        raise RuntimeError(f"restart failed ({detail or 'no output'})")

    deadline = time.time() + 15
    while time.time() < deadline:
        new = newest_run_id()
        if new and new != before:
            return new
        time.sleep(1)
    return before


def save_run(run_id: str):
    """Archive a run's diagnostics under ``data/saved/<run_id>/``."""
    src = DATA_DIR / run_id
    if not src.is_dir():
        raise FileNotFoundError(f"no such run: {run_id}")
    dst = SAVED_DIR / run_id
    SAVED_DIR.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return str(dst)
