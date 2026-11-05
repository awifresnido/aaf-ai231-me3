#!/usr/bin/env bash
# Fetch one or more run-id diagnostics dirs from the Pi into dashboard/data/.
# Usage: bash dashboard/scripts/fetch_runs.sh <run-id> [<run-id> ...]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # dashboard/
BASE="$(cd "$HERE/../.." && pwd)"                          # /opt/data (container) = ~/.hermes (host)
SSH_KEY="${DASHBOARD_SSH_KEY:-$BASE/home/.ssh/id_ed25519}"
KNOWN_HOSTS="${DASHBOARD_KNOWN_HOSTS:-$BASE/.ssh/known_hosts}"
PI=aldwinrpi4@192.168.5.12
REMOTE_DIR=/dev/shm/voice-agent-diagnostics
DATA_DIR="${DASHBOARD_DATA_DIR:-$HERE/data}"

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <run-id> [<run-id> ...]" >&2
  echo "list available runs first:" >&2
  echo "  ssh -i $SSH_KEY -o IdentitiesOnly=yes -o UserKnownHostsFile=$KNOWN_HOSTS \\" >&2
  echo "      $PI 'ls $REMOTE_DIR/'" >&2
  exit 1
fi

for run in "$@"; do
  mkdir -p "$DATA_DIR/$run"
  echo "fetching $run -> $DATA_DIR/$run/"
  scp -i "$SSH_KEY" -o IdentitiesOnly=yes -o UserKnownHostsFile="$KNOWN_HOSTS" \
    "$PI:$REMOTE_DIR/$run/"*.jsonl "$DATA_DIR/$run/"
done

echo "done. restart the dashboard (or reload the page) to pick up the new runs."
