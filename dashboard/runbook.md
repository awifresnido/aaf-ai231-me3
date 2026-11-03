# Runbook — ME3 voice-agent dashboard

Operational guide: pull diagnostics, load them, and read the views.

## 1. Pull a run from the Pi

Diagnostics live on the Pi (tmpfs, volatile — cleared on reboot) at
`/dev/shm/voice-agent-diagnostics/<run-id>/`, two JSONL files per run:

- `pi-<pid>.jsonl` — turn events + timing measurements.
- `mcp-<pid>.jsonl` — MCP tool-call spans.

List what's available:

```bash
ssh -i /opt/data/home/.ssh/id_ed25519 -o IdentitiesOnly=yes \
  -o UserKnownHostsFile=/opt/data/.ssh/known_hosts \
  aldwinrpi4@192.168.5.12 'ls /dev/shm/voice-agent-diagnostics/'
```

Pull one or more run ids (the helper does the scp for you):

```bash
bash dashboard/scripts/fetch_runs.sh 7ead383cab ecf65b32d7
# -> copies into dashboard/data/<run-id>/
```

Or by hand:

```bash
scp -i /opt/data/home/.ssh/id_ed25519 -o IdentitiesOnly=yes \
  -o UserKnownHostsFile=/opt/data/.ssh/known_hosts \
  aldwinrpi4@192.168.5.12:/dev/shm/voice-agent-diagnostics/<run-id>/*.jsonl \
  dashboard/data/<run-id>/
```

The backend reads every directory under `dashboard/data/` (or
`DASHBOARD_DATA_DIR`). Just drop a run's JSONL files in a subdirectory and reload
the page.

## 2. Run it

```bash
cd /opt/data/projects/me3-laya
.venv/bin/python -m uvicorn backend.app:app --app-dir dashboard --host 127.0.0.1 --port 8000
# frontend (already built) is served at http://127.0.0.1:8000/
```

## 3. Reading the views

- **Turn feed** — one row per turn: group, raw classifier choice, confidence
  (`top_prob`), gate, what handled it (tool / GLM / local LLM), and end-to-end
  latency. A `→ GLM` pill on the group marks a cloud escalation.
- **Latency waterfall** — per-turn stacked bars for ASR → classifier →
  tool/LLM → TTS first-audio, scaled to the run's max e2e. The four measured
  stages do **not** sum to e2e: the gap is unmeasured time (VAD, queue wait,
  dispatch). Median/p95 cards summarise each stage.
- **Routing trace** — aggregate distribution across the 9 groups (colour-coded)
  plus `rejected` / `timeout` / `error` / `multiple_actions` buckets.
  knowledge/workspace always escalate to GLM.
- **Tool activity** — MCP tool-call counts + a timeline of invocations.
- **Classifier health** — success vs timeout/error counts and the classifier
  latency histogram. The fp32→CPU era shows a spike at the ~2 s timeout ceiling;
  fp16 CUDA should sit well under 1 s. Timeouts are rendered red.
- **Run comparison** — all loaded runs ranked by median e2e.

## 4. Schema notes (read this before trusting a number)

The diagnostics span multiple router generations, so the parser is defensive:

- **Two contracts.** `raw_choice` is a *group* name (`home`, `clock`, …) in
  runs using the 9-group contract, and a *tool* name (`control_lights`,
  `get_time`, …) or the legacy labels `other` / `small_talk` in older runs.
  `Run.schema()` reports `v2_9group` / `v4_tool` / `unknown` per run.
- **Gate is reconstructed, not re-computed.** The diagnostics record the
  classifier result and the *dispatch*, but not an explicit accepted/rejected
  flag. We label:
  - `accepted` — classifier ran, handled locally (tool / smalltalk).
  - `escalated` — classifier correctly chose an escalate group (knowledge/
    workspace) → GLM by design.
  - `rejected` — classifier chose a fast/chitchat group but the turn went to
    GLM (low confidence / legacy `other`).
  - `timeout` / `error` — `classifier_failure`.
  - `bypass` — `classifier_bypass` (explicit override, e.g. `explicit_reminder`).
  - `multiple_actions` — `route_glm` with `reason=multiple_actions`
    (classifier skipped).
  - `unknown` — nothing classifiable recorded for that turn.
- **`router_model` is reported verbatim** (the data mixes `jev` and `laya`); the
  dashboard does not assume one router.
- **Transcripts are not logged** (by design) — the dashboard only ever sees
  timings, routes, and tool names.

## 5. Sample data

The three committed runs are real diagnostics with only `loop_heartbeat` /
`event_loop_lag` and (in the Pi file) redundant internal `span_*` lines removed
to keep the repo small. Every `turn_event` and MCP tool span is verbatim:

- `7ead383cab` — 9-group, clean (0 timeouts), 26 turns.
- `ecf65b32d7` — 9-group, fp32/CPU era: 27 timeouts + 1 error, 64 turns.
- `3ba3a6592d` — older tool-level contract (24 turns), exercises `other` /
  `small_talk` / reject.

## 6. Tests

```bash
cd /opt/data/projects/me3-laya && .venv/bin/python -m pytest dashboard/tests -q
```
