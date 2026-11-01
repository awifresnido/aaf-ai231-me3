# ThinkPad-only VCM speakerphone results

Session: 2026-11-01 14:38–14:44 Asia/Manila. Run `666312d1d8`, label
`local-vcm-thinkpad-nojev-20261101`. Sources: Pi `me3-local-audio.log`
starting at deployment offset 2,290,699 bytes, and the ThinkPad model service
journal for the same interval. No runtime changes were made during analysis.

The active pipeline used only ThinkPad Llama for model decisions. Jev,
GLM, and VPS fallback were absent from this mode. VAD remained 0.3 s,
Smart Turn two threads, and audio used the paired echo-cancellation devices.
Pi service and ThinkPad health were still active/healthy during inspection.

## Counts and measurement limits

The observer recorded twenty starts, not twenty independently verified user
commands. One start transcribed part of the bot's own greeting. Other starts
split an existing request or had no transcript. Seventeen local outcome
events were recorded: eleven tool results, three text replies, and three
failure replies. The eleven tool results include the probable greeting echo
and a partially handled compound request. Three starts had no completed
route; model journal cancellation records corroborate interrupted work.

Timing ends at the first software bot-speech event, excluding hardware delay.
The native latency observer emitted sixteen values: median **6.368 s**,
range **4.356–15.881 s**. Two values belong to split-turn cases whose timing
observer lost the speech-end reference. Keeping all native records avoids
selectively dropping their slow outcomes, but the turn association is weaker.

Fourteen replies retain both a speech-end estimate and a bot-start event
under the same timing turn: median **5.940 s**, range **4.355–15.880 s**.
This subset includes clarification/unsupported/error responses, not just
successful actions. Nine successful tool replies in that subset have median
**6.441 s**. Do not present the 5.940 s subset as every request's latency.

| Stage | Measurement |
|---|---:|
| Successful model decisions excluding greeting echo | Median 2.874 s; range 1.760–7.830 s; 15 values |
| Additional local model deadline failure | 12.002 s; no tool issued |
| Smart Turn processing | Median 415 ms; range 392–478 ms; 22 evaluations |
| First routing context, fourteen complete matched rows | Median 808 ms; range 700–3,317 ms |
| Ordinary matched endpoint waits below 1.5 s | Median 797 ms; range 700–1,000 ms; 12 rows |
| TTS first byte, including greeting and replies | Median 1.083 s; range 0.963–4.013 s; 18 values |

The matched endpoint summary omits cancelled/reset turns; the first exercise
request reached context after 1.407 s before being interrupted, and the first
blue-lights/volume context took 2.412 s before another start reset the turn.

## Request examples

| Request | Speech-end to first speech | Local model | MCP wait | Observation |
|---|---:|---:|---:|---|
| Hearing check | 4.35 s | 2.44 s | — | Local text reply |
| Lights on | 6.44 s | 1.76 s | 2.78 s | Tool completed |
| Lights green | 15.88 s | 2.87 s | 8.91 s | Additional 2.21 s synchronous gap after decision timing |
| Thermostat 27 degrees | 4.82 s | 2.93 s | 0.037 s | Tool completed |
| Send a message | 5.59 s | 3.70 s | — | Correctly unavailable in this trial |
| First exercise reminder | 15.37 s native, split association | Timeout 12.00 s | — | No tool issued; no GLM/VPS fallback |
| Repeated exercise reminder | 15.32 s | 7.83 s | 4.84 s | Reminder added once in this successful request |
| Play me a song | 5.00 s | 2.37 s | — | Selected playback_control; validation rejected it before execution |
| Blue lights and volume | 8.15 s native, split association | 3.44 s on final attempt | 0.070 s | Only lights executed; volume did not |
| Current weather | 6.29 s | 2.46 s | 1.88 s | Correct current-local tool result |
| Current time | 4.75 s | 3.03 s | 0.007 s | Correct tool result |
| Date | 11.47 s | 4.12 s | — | No date tool; 3.32 s endpoint wait plus 4.01 s TTS first byte |
| Stop music and turn off lights | 4.47 s | 2.56 s | — | Validation rejected compound request; no tool issued |
| Study reminder | 5.35 s | 2.60 s | 0.91 s | Reminder added |
| List reminders | 6.87 s | 2.45 s | 0.013 s | Three-second endpoint wait; long existing reminder list |
| Lights off | 14.74 s | 4.50 s | 7.81 s | Additional about 0.60 s synchronous gap after decision timing |

Model and MCP medians cannot simply be added to reconstruct the aggregate
reply median. There are also logging/scheduling gaps, input waits, and output
delays; the rows' values are rounded independently.

## Comparison with the previous Jev/GLM trial

The previous trial had thirteen measured replies and median 8.995 s. This
trial's sixteen native measurements have median 6.368 s, while its fourteen
stable matched measurements have median 5.940 s. These are different request
mixes, include failed/unsupported responses, and have different controller,
schema, prompt, deadline, and model-selection behavior. They do not establish
the isolated causal cost of Jev.

| Comparable command type | Previous | ThinkPad-only | Interpretation |
|---|---:|---:|---|
| Current time | 2.02 s | 4.75 s | A full model decision costs more than Jev + direct arguments here |
| Lights on | 6.44 s | 6.44 s | New tool wait offsets the benefit of avoiding GLM |
| Thermostat | 26.61 s at 28 C | 4.82 s at 27 C | Avoids GLM; MCP also happened to be much faster |
| Current local weather | 11.87 s | 6.29 s | No GLM calls; weather API/MCP also faster |

The local path removed cloud handoffs, but slow local state updates and model
processing still dominate several requests. Basic replies remain seconds,
not subsecond, even without Jev.

## Findings and next profiling priorities

1. **Profile Pi tool turnaround and synchronous stalls first.** Green lights
   took 8.91 s in the MCP call and lights-off 7.81 s, versus thermostat
   0.037 s and list-reminders 0.013 s. These are local state/read operations;
   external weather/music APIs cannot explain all of the waits. The green
   light decision timing logged at 14:39:18.277, but the next logger call in
   the same synchronous `record()` method occurred at 14:39:20.489. That
   approximately 2.21 s gap is outside both recorded model time and MCP wait.
   Logging/storage blocking or process scheduling is a hypothesis, not a
   diagnosed cause. Add server-entry, execution, SQLite commit, response, and
   client timings plus event-loop lag before changing the executor. Post-test
   read-only checks found 3.2 GiB available RAM, no swap use, root filesystem
   `/dev/sda2` ext4 with 47 GiB free, and no kernel journal entries in the
   interval. An idle `vmstat` sample does not rule out earlier stalls.

2. **The local model has measurable context/prefill cost.** ThinkPad journal
   confirms actual model execution. For thermostat, prompt evaluation was
   2.098 s for 107 new tokens and decoding 0.807 s; server total 2.905 s
   matches the Pi's 2.926 s call. Other ordinary requests reprocessed roughly
   90–105 prompt tokens in about 1.8–2.1 s, with output usually another
   0.6–1.0 s. Reduce repeated conversation/receipt text and structured output
   length while preserving pending clarification state. The exercise retry
   shows Pi client 7.830 s versus server compute 4.489 s; the remaining time
   needs transport/queue/scheduling measurement, not attribution entirely to
   Llama inference. Do not increase deadlines as a latency optimization.

3. **Echo and turn integrity need another pass.** At 14:38:07.561, ASR
   transcribed “I can help with time,” matching the new greeting, interrupted
   that greeting, and caused a get_time call. This is strong evidence of
   residual greeting echo, though microphone audio was not independently
   recorded. It did not turn into a continuing self-conversation. Five
   “no audio received while speaking” warnings also occurred. The exercise
   and blue-lights/volume requests each acquired another start without a new
   transcript, cancelling/restarting model work and losing the timing
   reference. Diagnose the input gaps and ASR aggregation before interpreting
   every observer start as a new user request.

4. **Validate complete requests, not only successful text probes.** “Play me
   a song” was misclassified as playback_control; the guard prevented the
   wrong action. The blue-lights/volume command executed only the lights;
   the compound detector does not cover all verb forms, and turn splitting
   complicates which context reached the model. A combined stop/lights
   request was rejected correctly. Improve compound/slot handling without
   silently claiming unexecuted steps. The date response is unsupported
   behavior in this narrow trial, not a failed date tool invocation. Music
   remains metadata/state only, not real playback.

Keep this model selection and audio configuration fixed for the next
diagnostic pass. Instrument the tool/scheduling waits first, then compare
the same short VCM script after a narrowly scoped change. Startup greeting
echo and interrupted-turn correctness must remain part of acceptance.

Related: [trial setup](local-vcm-trial-20261101.md),
[previous results](pre-refactor-retest-20261101.md).
