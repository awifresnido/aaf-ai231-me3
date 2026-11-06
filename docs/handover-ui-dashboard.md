# Handover — ME3 voice-agent dashboard (project-dashboard)

> **To the next session:** read this once, then work from it. Do not re-derive
> anything stated here. This is the *current* state after the smart-home +
> live-mode work; the original mission brief is `docs/handover-dashboard.md`.

## Branch & repo state (verified)

- Branch **`project-dashboard`**, HEAD `86eebf5` (`docs: document live mode`).
- Fully pushed: `origin/project-dashboard` == local HEAD (confirm with
  `git ls-remote origin project-dashboard`; the local `origin/project-dashboard`
  ref may show as "unknown revision" — that's a git-worktree quirk, not a problem).
- 24 tests passing (`pytest dashboard/tests -q`); frontend builds clean.
- Working tree is clean **except** two untracked live-pull data dirs:
  `dashboard/data/8f6a121e03/` and `dashboard/data/c2fd3a0d84/` — do **not**
  commit these. The committed sample data is exactly three curated runs:
  `3ba3a6592d`, `7ead383cab`, `ecf65b32d7`.

## What this is

A **read-only** FastAPI + React/TS dashboard that visualises the ME3 voice-agent
pipeline from on-disk diagnostics. It ingests and renders; it never runs the
pipeline and never calls a cloud model. Architecture mirrors the TinyVCM demo
app (`tinyvcm-demo-app` skill): the FastAPI hub owns all state, the frontend
renders state only.

## Pipeline being visualised

```
Pi mic → VAD (Silero) → ASR (whisper large-v3-turbo, Jetson :8090)
      → Laya v2 router (9-group, Jetson :8083, fp16 CUDA)
      → local groups (home/clock/reminders/media/weather/comms) → Llama 3.2 3B (Jetson :8084) + MCP tools
      → escalate groups (knowledge/workspace/chitchat) → GLM (cloud z-ai/glm-5.3-flash)
      → TTS (DGX Qwen3-TTS "Aiden")
```

Nine groups + tools are vendored in `dashboard/backend/groups.py` (source of
truth: `pi/group_schema.py`).

## Data source

Pi tmpfs `/dev/shm/voice-agent-diagnostics/<run-id>/` with two JSONL files per
run: `pi-<pid>.jsonl` (turn events + timings) and `mcp-<pid>.jsonl` (tool-call
spans). Every line is a JSON object. The interesting lines are
`"event":"turn_event"` carrying a `timing_event` name + a `fields` dict.

## Layout

```
dashboard/
  backend/    groups.py (taxonomy+display), metrics.py (honest stats),
              ingest.py (JSONL→domain + gate reconstruction),
              devices.py (smart-home state reconstruction), app.py (FastAPI)
  frontend/   React+TS+Vite. components/: TurnFeed, Waterfall, RoutingTrace,
              ToolActivity, ClassifierHealth, RunCompare, SmartControls
  data/       3 committed sample runs (verbatim turn/tool events)
  scripts/    fetch_runs.sh, live_pull.sh, serve.sh
  tests/      test_ingest.py, test_api.py, test_devices.py
pi/mcp_servers/voice_tools_mcp_server.py   (enriched: logs tool arguments)
```

## Key decisions & gotchas (learned, do not re-derive)

1. **Gate reconstruction** — the diagnostics record the classifier result + the
   dispatch but *no* accepted/rejected boolean. Reconstruct it from the dispatch
   (see `ingest.py`): `accepted` (local tool/smalltalk), `escalated` (escalate
   group → GLM by design), `rejected` (fast/chitchat group → GLM), `timeout`/
   `error` (`classifier_failure`), `bypass` (`classifier_bypass`),
   `multiple_actions` (`route_glm reason=multiple_actions`), `unknown`.
2. **Two router contracts coexist** — `raw_choice` is a *group* name (v2) or a
   *tool* name / `other` / `small_talk` (v4). `Run.schema()` reports which.
   `router_model` mixes `jev` and `laya` — report verbatim.
3. **Smart-home state is RECONSTRUCTED from tool arguments**, not read from the
   live SQLite `state.db` on the Jetson. `devices.py` deterministically replays
   each tool call's effect. Caveat: `play_music` shows the *requested query*, not
   the resolved track.
4. **Tool arguments are only logged since the `pi/` enrichment** (the
   `mcp_server_call` span now carries `arguments`, deployed to the Pi
   2026-11-05). Runs captured before that carry no args → the panel shows
   "args not recorded" and default device state.
5. **Honest metrics** — missing values are `null`/"not recorded", never 0.
   Classifier latency stats must exclude bypass/multiple_actions turns.
6. **Filter before dedupe** — keep only `event==turn_event` rows, then dedupe on
   `(turn, timing_event, timing_at)`. Ignore `loop_heartbeat`, `event_loop_lag`,
   and internal `span_start`/`span_end`.

## Live mode (added)

- Frontend auto-refreshes every 2 s (pulses a "live" dot) and auto-selects the
  newest run.
- `dashboard/scripts/live_pull.sh` continuously scp's the Pi's *active* run
  (newest `pi-*.jsonl`) into `dashboard/data/` every 3 s.
- `serve.sh` prints the live-mode hint. Run both in separate terminals for a demo.

## How to run (from the ThinkPad host)

```bash
# dashboard (serves built frontend + /api/*)
cd ~/.hermes/projects/me3-laya && bash dashboard/scripts/serve.sh
# live pull (second terminal)
cd ~/.hermes/projects/me3-laya && bash dashboard/scripts/live_pull.sh
# fetch a specific run (one-shot)
cd ~/.hermes/projects/me3-laya && bash dashboard/scripts/fetch_runs.sh <run-id>
```

> Path note: the Hermes agent runs in a container where `/opt/data` is a
> bind-mount of the ThinkPad's `/home/aldlinux/.hermes`. The user runs commands
> in WSL2, so give them `~/.hermes/projects/me3-laya`, never `/opt/data/...`.
> SSH key for the Pi lives at `~/.hermes/home/.ssh/id_ed25519` (known_hosts at
> `~/.hermes/.ssh/known_hosts`); the scripts resolve these repo-relative.

## Non-negotiables

- Read-only; never drives the pipeline or calls whisper/laya/llama/GLM.
- No invented metrics; missing → `null`/`not_recorded`.
- No weights or large binaries; sample JSONL only.
- Commit to `project-dashboard`, prefix by area (`pi:`, `backend:`, `ui:`,
  `scripts:`, `docs:`, `tests:`). `pytest -q` green before commit; `npm run
  build` when the frontend changes.

## Known issue (separate from the UI, unresolved)

The bot stopped producing *spoken* replies: `QwenTTSService#0: service is no
longer usable, not speaking` after a ~168 s TTFB hang (`TTFB: 167.803s`). The
LLM/text/tools still work; only TTS audio is wedged. Suspect the DGX Qwen3-TTS
endpoint (`DGX_TTS_BASE`, default `http://127.0.0.1:18001` reached via an SSH
tunnel) hung and Pipecat marked the service unusable. To investigate: check the
DGX TTS vLLM service health and the Pi's TTS tunnel; likely a bot restart clears
it. This is NOT part of the dashboard/UI work.
