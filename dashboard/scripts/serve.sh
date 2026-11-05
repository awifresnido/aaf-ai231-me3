#!/usr/bin/env bash
# One-command launcher for the ME3 voice-agent dashboard.
#
# Bootstraps everything if missing (python venv -> deps -> frontend build),
# then runs the FastAPI server.  Read-only: never touches the Pi or any model.
#
# Binds 0.0.0.0 by default so the dashboard is reachable from another machine
# on the LAN (e.g. a laptop) via http://<this-host-ip>:<port>/.
#   HOST=127.0.0.1 bash dashboard/scripts/serve.sh   # local-only
#   PORT=9000   bash dashboard/scripts/serve.sh       # different port
#
# Usage:  bash dashboard/scripts/serve.sh
set -euo pipefail

# Repo root = dashboard/scripts/../..
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

echo "==> repo: $REPO"

# 1) Python venv
if [ ! -x .venv/bin/python ]; then
  echo "==> creating .venv ..."
  if command -v uv >/dev/null 2>&1; then
    uv venv .venv
  else
    python3 -m venv .venv
  fi
fi

# 2) Backend deps
if ! .venv/bin/python -c "import fastapi, uvicorn, httpx" >/dev/null 2>&1; then
  echo "==> installing backend deps ..."
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python .venv/bin/python -r dashboard/requirements.txt "uvicorn>=0.29"
  else
    .venv/bin/python -m pip install -r dashboard/requirements.txt "uvicorn>=0.29"
  fi
fi

# 3) Frontend build (skip if already built)
if [ ! -f dashboard/frontend/dist/index.html ]; then
  echo "==> building frontend (first run, needs node/npm) ..."
  (cd dashboard/frontend && npm install && npm run build)
fi

# 4) Run
LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "==> serving on http://127.0.0.1:${PORT}/  (Ctrl-C to stop)"
[ -n "$LAN_IP" ] && [ "$HOST" != "127.0.0.1" ] && \
  echo "==> from another machine on the LAN: http://${LAN_IP}:${PORT}/"
echo "==> for a LIVE trial, also run in a second terminal:"
echo "      bash dashboard/scripts/live_pull.sh"
cd dashboard
exec ../.venv/bin/python -m uvicorn backend.app:app --host "$HOST" --port "$PORT"
