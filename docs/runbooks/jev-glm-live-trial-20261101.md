# Jev + GLM speakerphone trial, reactivated 2026-11-01

The user requested this trial on `laya-integration` after the Laya preflight.
At **22:05 Asia/Manila**, the existing Pi service was switched from `local_vcm`
to **`two_brain_plusjev`** and restarted. Run **`2a664e268a`**, experiment
**`jev-glm-pi-mcp-nvme-20261101`**, Pi PID 56818 at startup.
The pipeline was ready at 22:05:40; greeting first playback was at 22:05:56.
The user completed testing and confirmed some commands needed repetition.
The [completed assessment](jev-glm-live-results-20261101.md) measured 14 replies
at median 4.761 s and identified five speech segments with no final transcript.
No latency conclusion is drawn from startup alone.

## Selected path

- Jev **`jev-1.14.0`**, existing deadline **1,200 ms** and gate **0.90/0.20**.
- Fast accepted tools use deterministic parsing or the existing bounded Llama
  extractor; receipts go directly to TTS. Existing explicit-reminder bypass remains.
- Small talk uses ThinkPad Llama 3.2 3B through Pi loopback port 18080.
- Rejected/unsupported routes, compounds and failures pass to
  **`z-ai/glm-5.3-flash`** through the existing OpenRouter configuration.
- VPS small-model fallback is explicitly disabled with
  `SMALL_LLM_SECONDARY_URL=`. Laya is not selected or called by this mode.

Only three private environment settings changed: `ORCHESTRATION_MODE`,
`VAD_EXPERIMENT`, and the secondary small-model URL. No Python source was
deployed; live bot/router hashes still match `b059cd4`. The local uncommitted
Laya implementation is preserved for review.

Pi-hosted MCP and the Jetson SQLite worker still use the existing NVMe trial
directory `/home/aldwin/voice-agent-vcm/state/trials/nvme-20261101`. No database
was reset, copied or moved. Speakerphone PCM remains 100%, AEC source/sink are
paired, VAD is 0.3 s, Smart Turn two threads, pacat 150 ms, diagnostics on,
and queued logging on. ASR and TTS containers remained healthy on Jetson.

Preflight sent synthetic, non-tool requests directly to both providers:
Jev HTTP 200 with `get_time`, 0.901 s; GLM HTTP 200 with a nonempty text
completion, 2.146 s. These are connectivity checks, not live voice benchmarks.

## Capture and assessment

Main Pi log: `/home/aldwinrpi4/voice-agent/me3-local-audio.log`.
The new startup begins at byte **3312364** in this append-only log.
Match `TURN_TIMING` records to run `2a664e268a`; greeting is turn 0.
The process can serve multiple passes without a restart, retaining conversation.

Metadata traces:

```text
Pi:     /dev/shm/voice-agent-diagnostics/2a664e268a/pi-*.jsonl
Pi:     /dev/shm/voice-agent-diagnostics/2a664e268a/mcp-*.jsonl
Jetson: /dev/shm/voice-agent-diagnostics/2a664e268a/state-*.jsonl
```

The existing router logs `route_tool`, `route_smalltalk`, and `route_glm`, with
Jev/extraction/MCP times where applicable. GLM service logs include TTFB,
generation and tool activity; TTS logs record first byte and first audio.
`TURN_TIMING` records endpoint/context readiness, native latency and first
playback against estimated speech end. Worker traces retain RPC/commit detail.
Separate time spent waiting for Jev from time subsequently spent in GLM.

After the user finishes, collect the matching traces and inspect the run's
private speech log locally. Report per-route response latency, median/tails,
Jev timeouts, Llama extraction, GLM pre/post-tool calls, MCP/commit, endpointing,
TTS and correctness. Existing `summarize_stall_diagnostics.py` handles storage
spans. The local-VCM-specific decision/outcome fields in
`summarize_voice_trial.py` do not describe this older router; use `route_tool`,
`route_smalltalk`, `route_glm` and GLM service records for routing analysis.
Do not infer missing decisions solely from absent `local_decision` events.

Compare the historical **5.468 s** Llama-only baseline descriptively unless
the command mix and boundaries match. Record failed/interrupted turns and
incorrect or partial actions as well as successful replies. Do not publish
raw private transcripts or environment values.

## Backup and rollback

Private pre-switch configuration, mode 600:

`/home/aldwinrpi4/voice-agent-backups/jev-glm-live-20261101-220526/voice-agent-env.before`

Restore that file to `/home/aldwinrpi4/.voice-agent-env` and restart
`me3-local-audio.service` to return to the previous Llama-only selection and
experiment marker. Restoring configuration does not undo state changes made
by the user's live commands. The prior model, audio and storage setup remains
available; no source rollback is needed.

[Sanitized activation metadata](../profiling/jev-glm-live-20261101/activation.json)
contains the backup path, selected models and source hashes, without keys.
The user requested this live reactivation; keep it selected for the test.
