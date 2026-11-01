# VPS-only voice trial results

Session: 2026-11-01 15:01–15:08 Asia/Manila, run `fc95bf51f3`, experiment
`vcm-vps-only-nojev-20261101`. Sources: Pi `me3-local-audio.log` from offset
2,446,064 bytes, plus VPS model journal for 07:01–07:09 UTC. Pi service,
VPS tunnel, and model health were still active/healthy during inspection.
No runtime configuration or service changes were made during assessment.

## Outcome and comparison

The ThinkPad was more responsive in the observed voice trials. All fifteen
VPS outcome events identify `model_host=vps`; Jev, GLM, and ThinkPad fallback
remained absent. Prompt, schema, controller behavior, deadlines, tool set,
and audio settings were preserved from the preceding ThinkPad trial.

| Measurement | ThinkPad trial | VPS trial |
|---|---:|---:|
| Native speech-end to first bot speech | Median 6.368 s; 16 replies | Median 9.442 s; 15 replies |
| Range of native latency | 4.356–15.881 s | 6.595–19.074 s |
| Replies retaining a speech-end estimate under same timing ID | Median 5.940 s; 14 replies | Median 9.245 s; 13 replies |
| Completed model decisions | Median 2.874 s, excluding greeting echo; 15 decisions | Median 6.226 s; 14 decisions |
| Smart Turn processing | Median 415 ms; 22 evaluations | Median 419 ms; 26 evaluations |
| First routing context for measured outcome rows | Median 808 ms | Median 789 ms |
| TTS first byte, including greeting | Median 1.083 s | Median 1.026 s |

The request mixes differ and include unsupported/error replies and wrong
tool choices. Two VPS native latency records lost their timing observer's
speech-end reference during split turns; other turns have delayed VAD
timestamps. These are software timing proxies, excluding physical speaker
delay, not ground-truth per-user-command measurements. Native summaries
retain slow split outcomes rather than selectively dropping them. The
roughly 2.2-times model-call median difference is observational, not a
controlled causal estimate of network or CPU cost.

Twenty-one observed starts produced fifteen completed route outcomes:
eleven tool results, two text replies, and two failure replies. Tool success
here means execution completed, not that the tool matched the user's intent.
Three intervening starts correspond to cancelled/restarted model work; three
later starts had no transcript and did not produce replies. Do not count
every observer start as a separate spoken command.

## Request examples

| Request/transcription | First bot speech | VPS model call | MCP wait | Result |
|---|---:|---:|---:|---|
| Can you hear my voice? | 6.60 s | 4.70 s | 0.019 s | Incorrectly called get_time |
| Repeated hearing check | 8.47 s | 6.57 s | — | Replied, but described itself as text-based |
| Who are you? | 11.97 s | 10.17 s | — | Correct Voice of Pi identity |
| “turn off … the light turn on the lights” | 8.44 s | 6.64 s | 0.010 s | Chose off despite contradictory/corrected transcript |
| Turn on the light | 9.25 s | 4.82 s | 2.86 s | Lights on |
| Light color green, split turn | 14.98 s | 5.67 s | 6.72 s | Lights green; timing reference has delayed VAD timestamp |
| Temperature twenty degrees | 6.60 s | 4.75 s | 0.043 s | Thermostat 20 |
| “to my contact” | 6.97 s | No completed decision record | — | ValueError before tool issuance; invalid decision/outcome path |
| Reminder to study, split turn | 11.78 s native | 6.57 s | 0.91 s | Added reminder; timing observer reference reset |
| Delete all my reminders | 10.14 s | 8.28 s | 0.015 s | Incorrectly listed reminders |
| Repeated delete request, split turn | 15.08 s native | 11.24 s | 0.013 s | Listed again; timing observer reference reset |
| Play me a love song | 8.59 s | 6.69 s | — | play_music selected but validation rejected arguments |
| Light color blue | 19.07 s | 5.89 s | 9.76 s | Lights blue; another 1.63 s outside model/MCP measurements |
| Weather today | 17.57 s | 3.87 s | 12.00 s | Current-local weather result |
| Turn off the lights | 9.44 s | 4.97 s | 0.92 s | Lights off; another 1.79 s outside model/MCP measurements |

The trial does not expose a delete-reminders tool. The deletion requests
called list_reminders only; they did not delete reminders. They should have
received an explicit unsupported-capability response. Likewise the first
hearing check was not a real request for current time and must not be
presented as a successful time-command latency sample.

For comparison, ThinkPad lights-on was 6.44 s, thermostat 27 C 4.82 s,
weather 6.29 s, and lights-off 14.74 s. The VPS lights-off reply happened
to be faster overall because its MCP wait was only 0.92 s versus 7.81 s
previously, even though the VPS model call itself was slower. Do not infer
host speed from one end-to-end row without separating the tool wait.

## Where the extra delay occurs

1. **VPS inference is slower with conversation context.** Fourteen completed
   VPS server timing records show median prompt evaluation 2.746 s, decoding
   1.239 s, and server total 4.063 s (range 2.950–5.407 s). These component
   medians are not additive. Ordinary VPS prompt evaluation ran around
   27–38 tokens/s and generation roughly 10–13 tokens/s; the preceding
   ThinkPad examples were about 50 and 16–17 tokens/s. The VPS is configured
   for two CPU threads versus six on ThinkPad. These are deployed-service
   comparisons, not an intrinsic difference between model architectures.

2. **Client/model-path time also exceeds server compute.** Identity reply:
   Pi model call 10.171 s versus server task 285 total 5.407 s. Repeated
   deletion/listing: 11.243 s versus task 418 total 4.777 s. Weather:
   3.869 s versus task 466 total 3.525 s. The variable excess could involve
   request transport, queue/cancellation, server preprocessing, or Pi
   scheduling; server compute metrics do not isolate those components. Do
   not attribute all of this excess to WAN round-trip latency. Use durations
   and request order for correlation; wall clocks are not assumed perfectly
   synchronized. Cancellation records occurred for tasks 347, 385, and 416.

3. **The shared Pi/tool delays remain.** Blue lights took 9.76 s in MCP;
   weather took 12.00 s; other state reads/writes took 10–43 ms. The gap
   between a logged decision and the next synchronous log/tool-start code
   was about 1.63 s for blue lights and 1.79 s for final lights-off. Similar
   stalls existed on ThinkPad selection. Profile MCP server entry, SQLite
   execution/commit, response transport, logging, and event-loop scheduling
   before changing model routing to solve them.

4. **Audio endpointing and TTS typical latency did not increase.** Smart Turn
   stayed near 0.42 s, ordinary endpointing near 0.8 s, and TTS first byte
   near 1.0 s (range 0.714–1.120 s, sixteen measurements). The large VPS
   response increase is primarily later in the pipeline. There was one
   audio-idle forced-stop warning and several split/no-transcript starts.

5. **Short warm text probes overestimated live readiness.** All fourteen
   preflight cases had passed at median 2.013 s after a cold 12 s timeout.
   Live conversation includes prior replies/receipts, corrections, and noisy
   ASR. This produced slower calls and wrong or rejected decisions. No
   12 s model deadline failure was logged during the voice session itself;
   the two failure outcomes were ValueError, before any tool execution.
   The exact arguments/validation reason are not logged, so the music
   rejection cannot be diagnosed further from these logs alone.

No greeting-text transcription or repeating self-conversation was observed
in this VPS session. This does not prove the echo issue is fixed: audio
configuration was unchanged, and the previous ThinkPad greeting had leaked.
The final response ended at approximately 15:08:05 and the log remained quiet
through inspection.

## Recommendation

Use ThinkPad as the preferred small-model host for the current deployment,
with VPS reserved for availability fallback after the comparison is complete.
The VPS remains selected after this read-only assessment; no automatic switch
was performed. Before another architecture change, profile the shared Pi/MCP
stalls, reduce repeated model context without losing pending clarification,
and reject unsupported or corrected intents accurately. A later fixed-script
comparison should include model server/client timings and correctness, not
only the aggregate reply median.

Related: [VPS setup](vps-vcm-trial-20261101.md),
[ThinkPad results](local-vcm-results-20261101.md).
