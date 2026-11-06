# ME3 voice-agent dashboard

A **read-only** dashboard that links the ME3 voice-agent pipeline's on-disk
diagnostics to a UI. It ingests the JSONL diagnostics the Pi writes under
`/dev/shm/voice-agent-diagnostics/<run-id>/` and renders a turn feed, latency
waterfall, routing trace, tool activity, classifier health, a **simulated smart
home** (device state reconstructed from tool-call arguments), plus side-by-side
run comparison. It **never runs the pipeline and never calls a cloud model**; it
only reads and renders already-captured measurements.

Built in the same spirit (and house style) as the TinyVCM demo app: a FastAPI
hub owns all state, and a React + TypeScript frontend **renders state only**.

## Layout

```
dashboard/
  backend/          FastAPI hub (read-only): groups.py, metrics.py, ingest.py, app.py
  frontend/         React + TS + Vite (renders state only)
  data/<run-id>/    sample diagnostics (committed, verbatim turn/tool events)
  scripts/          fetch_runs.sh — pull runs from the Pi over scp
  tests/            pytest for ingestion + API
  README.md         this file
  runbook.md        operations + how to interpret the views
  requirements.txt  backend deps
```

## Quick start (WSL)

```bash
# 0) (optional) pull fresh runs from the Pi — see runbook.md
bash dashboard/scripts/fetch_runs.sh <run-id> [<run-id> ...]

# 1) backend deps + run
cd /opt/data/projects/me3-laya
uv venv .venv && uv pip install --python .venv/bin/python -r dashboard/requirements.txt uvicorn
.venv/bin/python -m uvicorn backend.app:app --app-dir dashboard --host 127.0.0.1 --port 8000

# 2) frontend (first time)
cd dashboard/frontend && npm install && npm run build
```

Then open http://127.0.0.1:8000/ — the backend serves the built frontend and
`/api/*`. For live frontend edits use `npm run dev` (Vite proxies `/api` to the
backend).

## API (all read-only, JSON)

| Endpoint | Returns |
|---|---|
| `GET /api/state` | run summaries + display names + the 9 groups |
| `GET /api/runs` | run summaries (for run comparison) |
| `GET /api/runs/<id>` | full detail: turns, aggregates, distributions, health, tool activity |
| `GET /api/runs/<id>/turns` | just the turn feed |

Set `DASHBOARD_DATA_DIR` to point at a different diagnostics directory.

## Honesty rules (non-negotiable)

- **No invented numbers.** A missing measurement is `null` in the API and
  rendered "not recorded" — never `0` or an estimate.
- **Read-only.** The dashboard ingests diagnostics and renders them; it never
  drives the pipeline, never writes to the Pi, and never calls
  whisper/laya/llama/GLM.
- **No weights or large binaries.** Only sample JSONL diagnostics are committed.
- Friendly names live in one place — `backend/groups.py` (`GROUP_DISPLAY`,
  `TOOL_DISPLAY`) — and are served as `display_names`; the frontend never
  hardcodes a name.

## The pipeline being visualised

```
Pi mic → VAD (Silero) → ASR (whisper large-v3-turbo, Jetson :8090)
      → Laya v2 router (9-group, Jetson :8083, fp16 CUDA)
      → local groups → Llama 3.2 3B (Jetson :8084) + MCP tools
      → escalate groups (knowledge/workspace) → GLM (cloud)
      → TTS (DGX Qwen3-TTS "Aiden")
```

The nine groups and their tools are vendored in `backend/groups.py` from
`pi/group_schema.py`.
