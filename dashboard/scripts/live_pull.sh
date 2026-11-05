#!/usr/bin/env bash
# Live-pull: continuously copy the Pi's active diagnostics run into the local
# data dir so the dashboard tracks a running trial in (near) real time.
#
# Usage:  bash dashboard/scripts/live_pull.sh
# Env:    LIVE_POLL_SECS (default 3)   DASHBOARD_DATA_DIR (default dashboard/data)
#         DASHBOARD_SSH_KEY / DASHBOARD_KNOWN_HOSTS override the repo-relative SSH paths.
#
# Finds the *active* run by the most recently appended pi-*.jsonl and overwrites
# the local copy every poll.  Read-only: it only ever scp's JSONL down.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # dashboard/
REPO="$(cd "$HERE/.." && pwd)"                             # repo root
BASE="$(cd "$REPO/../.." && pwd)"                          # /opt/data (container) = ~/.hermes (host)
SSH_KEY="${DASHBOARD_SSH_KEY:-$BASE/home/.ssh/id_ed25519}"
KNOWN_HOSTS="${DASHBOARD_KNOWN_HOSTS:-$BASE/.ssh/known_hosts}"
PI="${PI_USER:-aldwinrpi4}@${PI_HOST:-192.168.5.12}"
REMOTE_DIR=/dev/shm/voice-agent-diagnostics
DATA_DIR="${DASHBOARD_DATA_DIR:-$HERE/data}"
POLL="${LIVE_POLL_SECS:-3}"

SSH_OPTS=(-i "$SSH_KEY" -o IdentitiesOnly=yes -o UserKnownHostsFile="$KNOWN_HOSTS" -o ConnectTimeout=6 -o BatchMode=yes)

echo "live-pull: polling $PI:$REMOTE_DIR every ${POLL}s -> $DATA_DIR  (Ctrl-C to stop)"

while true; do
  # Newest pi-*.jsonl across all run dirs = the active session.
  latest=$(ssh "${SSH_OPTS[@]}" "$PI" \
    "ls -t $REMOTE_DIR/*/pi-*.jsonl 2>/dev/null | head -1" 2>/dev/null || true)
  if [ -n "$latest" ]; then
    run="$(basename "$(dirname "$latest")")"
    mkdir -p "$DATA_DIR/$run"
    scp "${SSH_OPTS[@]}" "$PI:$REMOTE_DIR/$run/"*.jsonl "$DATA_DIR/$run/" >/dev/null 2>&1 || true
  fi
  sleep "$POLL"
done
