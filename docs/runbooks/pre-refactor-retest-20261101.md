# Retest before tool ownership refactor

Session: 2026-11-01 14:08:46–14:13:34 Asia/Manila. Pi run
`8aacc03a3f`, experiment `vad-0.3-threads-2-aec-20261101`.
Deployed Python files match commit `b612047`; the live MCP inventory has
13 tools and excludes `play_radio`. VAD silence is 0.3 s, Smart Turn uses
two threads, and input/output use the paired JV801P echo-cancellation devices.
Jev deadline is 1.2 s; each small-model endpoint has a 2.5 s HTTP timeout.

This assessment made no runtime configuration, service, or routing changes.
The Pi bot remained active. Source: Pi `me3-local-audio.log`, ThinkPad
`voice-agent-llama.service` journal, and VPS `llama-server.service` journal.
The ThinkPad/VPS journals were correlated by time, converting VPS UTC to
Asia/Manila. Raw logs were inspected locally and were not added to the repo.

## Measurements

Fourteen observed user turns produced thirteen spoken replies. The first
music search was interrupted before a reply. Latencies start at VAD's
estimated speech end and end at the first software bot-speech event; they
exclude unmeasured hardware playback delay. Repeated playback writes and
post-response context pushes are not counted as new replies.

| Measurement | Result |
|---|---:|
| Speech end to first bot speech, 13 replies | Median 8.995 s; range 2.022–26.612 s |
| Smart Turn processing, 18 evaluations | Median 420 ms; range 389–457 ms |
| Speech end to first routing context, 14 turns | Median 812 ms; range 697–4,281 ms |
| Endpoint/context waits below 1.5 s, 11 turns | Median 751 ms; range 697–866 ms |
| TTS time to first byte, 13 logged measurements | Median 1.048 s; range 0.935–1.276 s |
| Completed fast tool routes | 1: current time |
| Completed small-talk routes | 1: “Just say hello” |
| GLM routes | 12 of 14 turns |
| Jev timeouts | 3 of 13 classification attempts; compound stop/lights bypassed Jev |

The previous AEC sample's median was 6.225 s across eleven replies, but the
utterances and paths differ. This trial's higher median does not establish
that removing radio or changing audio settings caused a regression.

| Recognized request | Path | First speech delay | Main observation |
|---|---|---:|---|
| Can you hear me | Small-model attempts → GLM | 11.28 s | Router waited 5.669 s; both Llama tasks cancelled |
| Turn on the lights | Jev timeout → GLM | 6.44 s | Jev wait 1.204 s; MCP about 0.064 s |
| Room temperature 28 degrees | Jev timeout → GLM | 26.61 s | GLM pre-tool generation 12.83 s; MCP 8.88 s |
| Send a message to my contact | GLM | 4.51 s | Asked for message content; no message sent |
| Just say hello | ThinkPad small talk | 4.99 s | Endpoint wait 3.289 s; Jev 0.384 s; Llama 0.355 s |
| “me a love song” | Low-confidence music → GLM | No reply | Music tool interrupted after about 18.7 s pending |
| “Playing a song” | Uncertain → GLM | 24.92 s | Two music searches, about 3.71 s and 11.85 s; three GLM calls |
| Lights blue and increase volume | GLM | 9.00 s | Tools completed in about 0.03/0.05 s; post-tool first-token wait 4.45 s |
| Weather today | Jev timeout → GLM | 11.87 s | Weather MCP about 3.03 s; two GLM calls |
| Time now | Fast tool, direct arguments | 2.02 s | Endpoint 0.715 s + Jev 0.323 s + MCP 0.008 s + output about 0.97 s |
| Stop music and turn off lights | GLM, explicit compound | 13.70 s | Endpoint/context wait 4.281 s; three GLM calls; stop MCP about 3.08 s |
| Date today | GLM, get_time | 6.65 s | Correct date derived after a tool call and another GLM call |
| Location right now | GLM | 5.96 s | Claimed configured area; no location tool/GPS lookup |
| Weather in “Siblu City” | Low-confidence weather → GLM | 12.64 s | Tool about 3.59 s; final answer named “Silay City” |

## Causes and correctness issues

1. **Jev timeout changes ownership.** Lights, thermostat, and ordinary
   weather all missed the 1.2 s classifier deadline and were sent to GLM.
   This consumed about 3.61 s of classifier waiting across those requests,
   followed by additional GLM calls. Basic time stayed fast. A deterministic
   validated command should not need cloud classification before execution;
   a recognizable VCM request should remain with its worker after timeout.

2. **The small-model fallback budget accumulates.** For the opening hearing
   check, ThinkPad journal task 139 ran about 3.05 s before cancellation
   (prompt evaluation about 2.65 s), and VPS task 12 was also cancelled at
   the client's timeout. Router fallback occurred after 5.669 s. The 2.5 s
   HTTP timeout is per endpoint/operation, not a global request deadline.
   Later ThinkPad task 149 completed in 0.341 s, matching the Pi's 0.355 s
   Llama measurement. This confirms the ThinkPad served that successful turn;
   it does not establish why the earlier prompt evaluation was slow.

3. **Follow-up context is lost on the small-talk path.** After GLM asked
   what the message should say, “Just say hello” was classified as small talk
   and answered “Hello.” The small client receives only the latest utterance.
   Pending workflows and their slots must be considered before intent routing.

4. **Endpoint waits have a separate tail.** “Just say hello” and the first
   music request reached the Smart Turn three-second silence limit after an
   incomplete result. The music turn also logged “no audio received while
   speaking, forcing speech stop,” and ASR lacked the request's leading
   verb. For compound stop/lights, analysis completed at 14:12:15.023 and
   inference triggered at 14:12:15.036, but context was not ready until
   14:12:18.503. That additional approximately 3.47 s needs aggregator/task
   scheduling investigation; it was not ONNX inference time. Keep the audio
   settings fixed while measuring this tail.

5. **Tool turnaround has unexplained local spikes.** The thermostat MCP
   request spanned 14:09:38.883–14:09:47.766 despite its simple state update.
   Lights updates in the same trial completed in milliseconds. The logs
   cannot separate SQLite, server scheduling, stdio transport, and client
   waiting. Add server-entry/execution/response timing before attributing
   the spike to storage. Music/weather also include external network work.

6. **GLM post-tool replies add avoidable confirmation delay.** The compound
   light/volume tools finished at 14:11:27.507; TTS was requested at
   14:11:32.214. A validated spoken execution receipt can avoid another model
   call for routine confirmations. Complex plans still require explicit
   completion tracking, especially after interruption.

7. **Weather identity and media claims need validation.** The final city
   transcription was “Siblu City,” but the spoken reply used “Silay City.”
   The weather tool accepted coordinates without returning a resolved place
   identity. Clarify ambiguous place names and bind spoken location to a
   verified resolution. The music result was an unrelated catalog item;
   current media tools update metadata/state and do not operate a player.
   “Now playing” or “volume up” is not evidence of physical playback/control.

No repeated bot self-conversation or runtime error appeared in the test
window. The final speech stopped at 14:13:34.508 and the log remained quiet
through the subsequent inspection. This does not independently prove every
transcription was user speech. Older ASR connection-refused bursts at 12:13
precede this process/session and are not counted as failures of this trial.

## Recommended sequence

1. Refactor ownership with pending-workflow context and execution receipts:
   routine VCM worker, bounded GLM delegation for mixed plans, explicit
   owner-aware fallback after Jev timeout. Preserve current audio settings.
2. Instrument endpoint selection, per-host model timing/cancellation, and
   MCP server versus client timing. Enforce an overall small-worker budget
   rather than stacking full waits for both hosts and then GLM.
3. Profile the three-second silence cases, missing leading speech, and the
   gap between inference trigger and context readiness. Avoid treating these
   as evidence that ONNX threads alone need adjustment.
4. Repeat a fixed script containing time, lights, thermostat, weather, a
   message follow-up, and a mixed command. Compare per-request paths and
   verified action/confirmation times, not just the aggregate median.

The proposed ownership design remains in
[Tool ownership](../TWO-BRAIN-TOOL-OWNERSHIP.md); it was not implemented or
deployed during this assessment.
