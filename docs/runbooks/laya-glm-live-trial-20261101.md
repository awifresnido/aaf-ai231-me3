# Laya + GLM contextual speakerphone trial

User requested a final same-command contextual test, swapping Jev for Laya.
Activated **2026-11-01 22:47 Asia/Manila**, run **`26c376b1c3`**, experiment
`laya-glm-context-pi-mcp-nvme-20261101`, Pi PID 60029 at startup. Pipeline was
ready at 22:47:53 and greeting playback began at 22:48:09. The user completed
direct and contextual sets; see the [benchmark results](laya-glm-results-20261101.md).

## Active path

`ORCHESTRATION_MODE=two_brain_plusjev`, `ROUTER_MODEL=laya` selects the resident
ThinkPad classifier through Pi loopback `18082`. Jev is not instantiated or
called. Laya uses its exact trained question, external temperature **1.995**,
and **0.50/0.05** gate. The per-turn classifier deadline is **two seconds**.
`other`, rejection, unsupported direct arguments or classifier failure reaches
the existing **GLM 5.3 Flash** service with the conversation intact. Accepted
small talk retains the existing ThinkPad Llama reply path. VPS fallback is off.

This uses the classifier slot in the existing two-brain processor, not the
separate Laya-only local-VCM mode. Explicit compounds/reminders retain existing
pre-classifier handling and log their bypass. Laya fast tools require separately
grounded and validated arguments; they do not invent values through a Llama
extractor. Contextual interpretation remains GLM's responsibility.

Pi MCP, Jetson worker/database, audio/AEC, VAD 0.3, Smart Turn two threads,
pacat 150 ms, queued logging, GLM settings and tool inventory are preserved.
Conversation was reset by restart; persisted state was retained. Thus the new
round is not an identical-state statistical A/B test. Laya's trained question,
gate and stricter fast-path argument check also differ from the old Jev path.

Eighty-four regression tests passed. Four actual classifier/controller preflights
passed with a synthetic MCP receipt and no real tool execution. Warm Pi client
classification waits were **0.693–0.775 s**, server inference **0.686–0.768 s**.
An earlier first preflight exceeded two seconds and correctly fell through to
GLM; it is not included in those successful warm timings. No threshold was tuned.

## Per-turn measurements

Main log: `/home/aldwinrpi4/voice-agent/me3-local-audio.log`, starting byte
**3871303**. Match run **`26c376b1c3`** in `TURN_TIMING` records.

- `classifier_result`: `classifier_s` = Pi wall time awaiting Laya;
  `server_classifier_s` = ThinkPad inference/gate duration;
  `client_outside_server_s` = difference of elapsed durations, covering
  HTTP/tunnel/client overhead. Also logs choice, probability, gap and fast route.
- `classifier_failure`: elapsed wait, timeout/error status, exception class.
  A client timeout does not establish completed server inference duration.
- `classifier_bypass`: existing explicit-reminder shortcut, zero classifier time.
- `argument_result`: extraction time, source and validation verdict, separately
  from route confidence. `route_tool` records `laya_s`, MCP and total router time.
- `route_glm` / `route_smalltalk`: selected downstream path and classification
  cost. GLM generation and TTS first-byte metrics remain in the main log.
- `native_user_bot_latency`, `first_playback_write`: estimated final speech-end
  to first software response/playback. They do not measure physical acoustic onset.
- Diagnostic spans: `classifier_client`, `argument_extraction`,
  `small_model_reply`, plus existing MCP/RPC/commit spans.

Metadata files use `/dev/shm/voice-agent-diagnostics/26c376b1c3/`: Pi `pi-*`
and `mcp-*`, Jetson `state-*`. Record per-turn Laya wait/inference, downstream
GLM/Llama time, tool/storage, TTS, total first response, and actual completion.
Keep missing ASR and interrupted waits in separate counts; successful-only
medians do not account for silence or repetition. Startup greeting self-hearing
occurred again and must be separated from user commands.

Laya tool ownership suppresses duplicate context execution and preserves cloud
tool-result continuations without reclassification. An uncertain issued fast
write produces an uncertain receipt instead of falling through to GLM and
potentially issuing the action again. New spoken repetitions still have new IDs.

## Rollback and review

Private source/config backup:
`/home/aldwinrpi4/voice-agent-backups/laya-glm-live-20261101-224739/`.
Restore its `bot.py`, `orchestration.py`, `local_vcm.py` and
`voice-agent-env.before` (to `~/.voice-agent-env`, mode 600), then restart
`me3-local-audio.service` for the exact preceding Jev + GLM setup. Newly added
Laya modules may remain unused. Do not overwrite or reset state for rollback.

[Activation hashes and safe configuration](../profiling/laya-glm-live-20261101/activation.json)
are saved. The completed results include Laya layer p50/p95, per-command
end-to-end timing and contextual correctness. The user subsequently requested
committing the implementation and assessment progress on `laya-integration`.
