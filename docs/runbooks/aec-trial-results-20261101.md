# Echo-cancelled JV801P trial

Session: 2026-11-01 11:34–11:40 Asia/Manila. Run `289f6218cf`,
experiment `vad-0.3-threads-2-aec-20261101`. VAD stop silence 0.3 s,
Smart Turn two threads, paired PulseAudio WebRTC echo cancellation.

## Audio and turn handling

- Recording was attached to `voice_agent_aec_source` and `pacat` playback to
  `voice_agent_aec_sink`; both share the physical JV801P reference pair.
- No repeating self-conversation appeared in this session. After the final
  reply stopped at 11:40:05, no further transcription or bot reply was logged
  through 11:41:11. This is evidence for the current room/volume conditions,
  not a guarantee against all acoustic echo.
- At 11:35:47.844 an interruption was broadcast while the bot was beginning
  its second messaging sentence. Software output reported stopped at
  11:35:47.864, about 20 ms later. The user's new reminder speech was then
  recognized. Physical audible interruption was not measured; the audio sink
  can still contain buffered samples.
- Fourteen user turns each reached inference once. Three were interrupted
  before a spoken response, leaving eleven completed response measurements.
  No late-final duplicate inference was observed in this sample.

## Timing

All endpoint timings use VAD's estimated speech end. Output timing ends at
software bot speech/first playback write, excluding hardware speaker delay.

| Measurement | Result |
|---|---:|
| Smart Turn analysis processing | Median 409 ms, range 391–469 ms, 15 evaluations |
| Estimated speech end to routing context | Median 820 ms, range 704–883 ms, 14 turns |
| Completed speech-end to bot-speech delay | Median 6.225 s, range 2.088–42.911 s, 11 replies |

Earlier mixed-session medians were 649 ms analysis / 1.072 s endpointing
with 0.4 s and one thread; the previous 0.3 s / two-thread trial reported
422 ms analysis and 0.851 s endpointing. These were different utterances, so
they are observational summaries, not a controlled causal comparison.

| Request | Route | Speech-end to bot speech | Main timing |
|---|---|---:|---|
| Can you hear my voice? | Llama small talk | 4.88 s | Jev 0.66 s, Llama 2.45 s |
| Lights on | Jev timeout → GLM | 42.91 s | GLM first tokens 16.28 s and 8.43 s; MCP only 0.063 s |
| Lights green | Fast | 6.23 s | MCP 4.17 s |
| Thermostat 26 C | Fast | 2.95 s | Jev 0.52 s, MCP 0.60 s |
| Messaging | Jev timeout → GLM | 12.00 s | Returned unconfigured-messaging result |
| Repeated study reminder | Direct reminder | 4.29 s | MCP 0.068 s, but delayed while prior turn was being cancelled |
| Play a love song | Fast | 17.83 s | Music search/MCP 15.67 s; selected an irrelevant catalog item |
| Current weather | Fast | 4.50 s | MCP 2.51 s |
| Current time | Fast | 2.09 s | Jev 0.35 s, MCP 0.006 s |
| Blue lights + volume increase | GLM | 21.01 s | Three model calls, both tools completed |
| Confirmation of stopped music/lights | GLM | 28.26 s | 16.42 s first-token delay although actions were already done |

Two other requests were interrupted while GLM was working: the first study
reminder and an earlier blue-lights/volume command. The combined stop-music
and lights-off request completed its tools at 11:38:57 and 11:39:03 but
had not spoken a confirmation when the user asked about status at 11:39:30.
Thus action latency and spoken-confirmation latency differ substantially.

## Remaining issues

1. Echo control and ordinary endpointing now look stable in this test. Keep
   them fixed during the next routing/executor investigation.
2. Jev timed out on two requests; explicit basic commands can still lose the
   fast route. Validate complete deterministic intents before requiring Jev.
3. Separate MCP server execution and SQLite/network time from stdio transport
   waiting. Even the local lights update waited 4.17 s, while other state
   calls finished in milliseconds. Music search is a separate network-bound
   tool and took 15.67 s here.
4. A study reminder tool completed at 11:36:18 without a spoken confirmation.
   The user repeated it during cancellation and another study reminder
   completed at 11:36:25. Preserve tool receipts across interruptions to
   avoid executing a repeated action just because its confirmation was lost.
5. GLM post-tool generation delays confirmation of already completed actions.
   Structured spoken tool receipts can provide earlier, accurate feedback.
6. Music tools still update metadata/state rather than operating a real player.
   This trial does not demonstrate actual song playback or volume control.

No configuration or service changes were made during this log assessment.
The Pi local bot remains active at 0.3 s / two threads with echo cancellation.
