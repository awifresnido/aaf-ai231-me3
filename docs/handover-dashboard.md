# Handover — ME3 Voice Agent Dashboard

> **To the agent receiving this handover:** you are starting a fresh session with
> no prior context on this project. Treat this document as your full brief. Read
> it once, then work from it. Do not re-derive facts stated here.

## Your mission

Build a **dashboard that links the ME3 voice-agent pipeline outputs to a UI
simulation**, in the same spirit as the existing TinyVCM demo app
(`vcm-demo-app`), but with **new functionality specific to this voice-agent
project**. The dashboard is a *read-only simulation*: it ingests real pipeline
diagnostics (already captured on disk) and renders them — it never runs the
pipeline itself and never calls any cloud model.

Deliver a working dashboard (backend + frontend) plus a short runbook. Work on
the git branch **`project-dashboard`** (already created from `laya-integration`
and pushed to origin). Commit local, one logical change per commit.

## The project (what you are visualizing)

The **ME3 voice agent** is a spoken-command assistant running on a Raspberry Pi 4.
Its live pipeline, in order:

```
Pi mic → VAD (Silero) → ASR (whisper large-v3-turbo, Jetson :8090)
      → Laya v2 router (9-group classifier, Jetson :8083, fp16 CUDA, ~0.1 s)
      → route:
           local groups (home/clock/reminders/media/weather/comms)
                → Llama 3.2 3B (Jetson :8084) + MCP tools
           escalate groups (knowledge/workspace/chitchat)
                → GLM (cloud, z-ai/glm-5.3-flash)
      → TTS (DGX Qwen3-TTS "Aiden")
```

**Routing model — Laya v2** is a local fine-tuned 9-group classifier. It answers
*one* coarse question ("which group of tools can serve this utterance?"), then a
second tier picks the concrete tool. Its 9 groups and their tools:

| Group | Tools |
|---|---|
| home | control_lights, set_thermostat |
| clock | get_time, set_timer, set_alarm |
| reminders | add_reminder, list_reminders |
| media | play_music, playback_control |
| weather | get_weather |
| comms | send_message, send_email, place_call |
| knowledge | search, fetch_content |
| workspace | read_file, write_file, edit_file, grep, bash, github_repo, send_file, serve |
| chitchat | (none — conversational reply) |

`knowledge` and `workspace` escalate to the cloud model (GLM); the rest stay
local. Laya has a decision gate (τ=0.90, gap=0.05): a low-confidence decision is
*rejected* and escalates to GLM instead.

## Machines & access (from WSL)

| Host | addr | user | notes |
|---|---|---|---|
| Raspberry Pi 4 | 192.168.5.12 | aldwinrpi4 | runs the bot; diagnostics live here |
| Jetson Orin | 192.168.5.11 | aldwin | whisper + llama + laya routers |
| ThinkPad (WSL) | 192.168.5.10 | aldlinux | this box's LAN peer |
| Mac M2 | 192.168.5.9 | aldwin | TTS (optional) |

SSH from WSL: `ssh -i /opt/data/home/.ssh/id_ed25519 -o IdentitiesOnly=yes -o UserKnownHostsFile=/opt/data/.ssh/known_hosts <user>@<addr>`

The repo in WSL is **`/opt/data/projects/me3-laya`** (worktree on
`project-dashboard`). The Pi's deployed copy of the pipeline lives at
`~/voice-agent/` (the repo's `pi/` directory, flattened) — you normally do NOT
edit that directly; the dashboard only *reads* its diagnostics.

## Data source — pipeline diagnostics

The bot writes turn-by-turn diagnostics as JSONL to
`/dev/shm/voice-agent-diagnostics/<run-id>/` on the Pi (tmpfs — volatile, but the
recent runs persist until reboot). Two files per run:

- `pi-<pid>.jsonl` — turn events + timing measurements.
- `mcp-<pid>.jsonl` — MCP tool-call spans.

**Every line is a JSON object.** The interesting ones have `"event": "turn_event"`
and carry a `"timing_event"` name + a `"fields"` dict. Key fields you will render:

| timing_event | fields of interest |
|---|---|
| `native_user_bot_latency` | `seconds` — end-to-end turn latency |
| `asr_transcript` | `finalized`, `since_speech_end_ms` |
| `classifier_result` | `router_model`, `classifier_s`, `server_classifier_s`, `raw_choice`, `top_prob`, `gap`, `status` |
| `classifier_failure` | `router_model`, `classifier_s`, `status` (timeout/error) |
| `route_glm` | `router_model`, `classifier_s`, `reason` |
| `route_tool` | `tool`, `classifier_s`, `mcp_s` |
| `tts_qwen_first_audio` | `first_audio_s` |
| `tts_qwen_complete` | `request_s` |
| `configuration` | `orchestration_mode`, `router_model`, `tts_backend`, `tts_model` |
| `turn_analysis` | `processor`, `probability`, `e2e_processing_time_ms` |

Each event also has a `turn` (int, turn number), `run` (run id), and `at` (epoch
seconds). `mcp-*.jsonl` has `span_start`/`span_end` records with a `tool` name.

> **Privacy note:** the transcripts themselves are intentionally *not* logged in
> the diagnostics (only metadata + timings). The dashboard works off timings,
> routes, and tool calls — it does not (and cannot) show spoken text. If you want
> a transcript column, you must add that logging separately and re-run a trial.

To fetch a run's logs from WSL:
```bash
scp -i /opt/data/home/.ssh/id_ed25519 -o IdentitiesOnly=yes -o UserKnownHostsFile=/opt/data/.ssh/known_hosts \
  aldwinrpi4@192.168.5.12:/dev/shm/voice-agent-diagnostics/<run-id>/*.jsonl ./data/
```

## What the dashboard must show (new functionality for this project)

1. **Turn feed** — one row per turn: turn #, route group, raw choice, confidence
   (`top_prob`), gate result (accepted/rejected), tool called (or "GLM"), and the
   e2e latency.
2. **Latency waterfall** — per-turn stacked breakdown of ASR → classifier →
   LLM/tool → TTS (use `since_speech_end_ms`, `classifier_s`, `mcp_s`,
   `first_audio_s`, `native_user_bot_latency`). Show median/p95 across the run.
3. **Routing trace** — which of the 9 groups each turn landed in, colour-coded by
   group, with a reject/escalate indicator; aggregate group distribution.
4. **Tool activity** — from the MCP log: count + timeline of tool invocations.
5. **Classifier health** — success vs timeout/error count, classifier latency
   distribution (this run type historically had fp32→CPU→2 s timeouts before the
   fp16 fix; the dashboard should make timeouts visually obvious).
6. **Run comparison** — load multiple runs side by side and rank by median e2e.

## Reference pattern (TinyVCM demo app)

Load the skill **`tinyvcm-demo-app`** (`skill_view(name='tinyvcm-demo-app')`) and
mirror its architecture: a FastAPI hub (`laptop/app/`) that owns all state and a
React+TS frontend (`laptop/frontend/src/`) that **renders state only and never
routes intents**. Reuse its conventions:
- friendly names come from a single `display_names` source, never hardcoded in components;
- **never fake metrics** — missing values are `not_evaluated`/`not_recorded`, never 0;
- the dashboard is read-only; it never runs the pipeline or a cloud model.

You may scaffold the dashboard under a new top-level dir in the repo (e.g.
`dashboard/`), with a lightweight backend + frontend of your choice (FastAPI +
React/TS is the house style, matching VCM). Keep it dependency-light and runnable
in WSL without the Pi's venv.

## Constraints (non-negotiable)

- **Read-only.** The dashboard ingests diagnostics and renders them. It never
  drives the pipeline, never calls whisper/laya/llama/GLM, and never writes to
  the Pi.
- **Honest metrics.** No invented numbers. Missing → `not_recorded`.
- **No weights, no large binaries** committed. Diagnostics are sample data only.
- Commit to `project-dashboard`; prefix messages by area (`dashboard:`,
  `backend:`, `ui:`, `docs:`). `pytest -q` green before commit; build the
  frontend when it changes.

## First steps

1. Confirm you're on `project-dashboard` and `git pull` (already pushed).
2. `skill_view(name='tinyvcm-demo-app')` to absorb the VCM pattern.
3. Pull one run's logs from the Pi (run ids visible under
   `/dev/shm/voice-agent-diagnostics/`; e.g. `ls` via SSH) and inspect the JSONL
   to confirm the schema above.
4. Sketch the data model (turn → route → tool → timings) and the API shape
   (`/api/state`, `/api/runs`, `/api/runs/<id>/turns`).
5. Build the backend, then the frontend, against a captured sample run.

Report back with a working dashboard, the sample data you used, and a runbook.
