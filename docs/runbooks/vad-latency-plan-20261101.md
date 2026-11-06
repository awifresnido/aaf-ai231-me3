# VAD, turn detection, and wake-word latency plan

Read-only assessment, 2026-11-01. No VAD, ASR, or wake-word configuration
was changed for this plan. Sources are the Pi's installed Pipecat 1.13 code,
its private environment settings (selected non-secret values only), and the
JV801P retest log from 10:16–10:22.

## Actual configuration

| Component | Current setting |
|---|---|
| Silero VAD | confidence 0.7, start 0.2 s, stop 0.8 s, min_volume 0.6 |
| Turn policy | Default `TurnAnalyzerUserTurnStopStrategy(LocalSmartTurnAnalyzerV3)` |
| Smart Turn | Local ONNX, default one CPU worker; 3 s silence fallback |
| ASR | Nemotron via Nvidia/Riva streaming; configured stop_history 320 ms |
| Transcript handling | Wait for transcript; finalized transcripts can release a completed turn immediately |
| STT safety budget | Installed Nvidia service defaults to TTFS P99 1.0 s; no locally calibrated override |

The explicit 0.8 s VAD setting was originally chosen to allow late ASR finals
to arrive before responding. However, Smart Turn is also active. Its
integration recommends 0.2 s VAD stop silence and the installed service logs a
warning about our 0.8 s setting. A long silence gate can delay the first
opportunity for semantic turn analysis.

## Observed delay

The log lacks the last voiced audio-sample timestamp and VAD-stop frame
timestamps, so it cannot isolate acoustic speech-end to VAD stop. The
following is last logged ASR text chunk to turn inference, a combined
ASR/endpointing proxy rather than a measurement of VAD alone:

| Request | Last ASR chunk to turn inference |
|---|---:|
| Lights on | 0.920 s |
| Current time | 1.273 s |
| Brightness 80% | 1.245 s |
| Thermostat 25 C | 2.042 s |
| Current weather | 1.279 s |
| List reminders | 1.391 s |
| Garbled red-lights request | 3.240 s |

Across twelve ordinary turns, the proxy median was 1.276 s and range
0.920–3.240 s. A separate initial transcription-fallback turn (0.004 s) is
excluded. The garbled request produced INCOMPLETE and reached the explicit
3 s silence fallback. For the thermostat, Smart Turn logged COMPLETE about
0.84 s before inference was triggered, showing a further wait after semantic
completion. Model inference duration itself is not logged.

The previous response-latency reports started at turn inference, so this
pre-routing delay was outside their totals. ASR endpointing, VAD silence, and
transcript waits overlap; their settings must not simply be added together.

## Reduction plan

1. **Instrument before tuning.** Use the installed `UserBotLatencyObserver`
   plus turn-analysis metrics. Log the VAD speech-to-silence transition,
   confirmation timestamp/stop_secs, final ASR timestamp and finalized flag,
   Smart Turn inference duration/probability, turn release, router stages,
   and first playback write. Keep a turn identifier through those events.
   This also distinguishes late-final duplicates from genuine interruptions.
2. **Establish a JV801P baseline.** Repeat a fixed set of short commands,
   sentences with mid-utterance pauses, numbers split by pauses, and complex
   requests. Record endpointing and total latency along with truncations,
   unnecessary clarification, and duplicate actions.
3. **Reduce VAD stop silence in two steps.** Compare 0.8 s with 0.4 s, then
   0.2 s while keeping Smart Turn and transcript-final handling active.
   Nominal silence-gate reductions are 0.4 and 0.6 s; actual total savings
   may be smaller if ASR or the analyzer remains the limiting stage. Change
   only this variable per comparison; retain 0.8 s as the rollback value.
4. **Calibrate the ASR wait.** Measure Nemotron/Riva final-transcript delay
   against audio speech end, then set `ttfs_p99_latency` from the measured
   distribution. Preserve the finalized-transcript signal and transcript
   requirement. Do not turn off transcript waiting in a text-driven tool
   pipeline to manufacture a lower timing number.
5. **Profile Smart Turn on the Pi.** If inference is a material part of
   endpointing, evaluate CPU worker settings before considering another
   host. A remote analyzer adds network and availability dependencies. Never
   assume desktop/Cloud inference times apply to the Pi 4.
6. **Evaluate the 3 s fallback last.** For a distinct short-command mode,
   compare a 1.5–2 s fallback only after the pause tests pass. Preserve a
   longer conversational fallback for complex speech and clarification.

Acceptance requires lower endpointing latency without truncating the test
utterances, losing final arguments, causing duplicate tool calls, or regressing
barge-in. Keep utterances and downstream services constant when comparing.
VAD tuning will not remove Jev timeouts, slow MCP calls, or GLM generation
delays documented in the other reports.

## Wake-word assessment

A wake word controls when interaction starts. It does not decide when the
command ends, so VAD and turn detection are still needed afterward.

- Requiring a wake phrase for every command adds spoken activation time and
  detection work. A wake phrase detected only in a final ASR transcript can
  add an ASR finalization wait before activation.
- A local acoustic detector can reduce accidental/background turns while
  idle. Use a rolling audio prebuffer so “wake word + command” can be spoken
  continuously. Keep ASR/model services warm to avoid startup latency.
- For this full-duplex project, prefer wake once from IDLE, then a 20–30 s
  conversation window refreshed by activity. Allow normal barge-in during
  that window and return to IDLE after inactivity. These times are proposed
  trial settings, not measured optima. Requiring a wake word to interrupt
  every response would make the current conversational experience slower.
- Benchmark detector CPU use, false activations, misses, and command clipping
  on the Pi. Wake-word gating will not repair garbled ASR or improve the
  semantics of a recognized command by itself.

Recommendation: improve endpointing first; add optional local wake-word gating
later for interaction control, not as the primary response-latency fix.

## Primary references

- [Pipecat Smart Turn configuration](https://github.com/pipecat-ai/docs/blob/main/api-reference/server/utilities/turn-detection/smart-turn-overview.mdx)
- [Pipecat turn-stop strategies](https://reference-server.pipecat.ai/en/latest/api/pipecat.turns.user_stop.html)
- [Pipecat wake-phrase strategy](https://reference-server.pipecat.ai/en/stable/api/pipecat.turns.user_start.html)
- [openWakeWord](https://github.com/dscripka/openWakeWord)

Online documentation can describe newer versions; implementation choices must
be checked against the installed Pipecat 1.13 APIs before deployment.
