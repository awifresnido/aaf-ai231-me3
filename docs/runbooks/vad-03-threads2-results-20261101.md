# VAD 0.3 s / two-thread trial and echo feedback

Trial run `6fc43f81b9`, Pi-local JV801P, 2026-11-01 11:18–11:24
Asia/Manila. Subsequent turns after 11:24:54 include confirmed acoustic
feedback and are excluded from the ten-response latency summary below.

| Measurement | Previous 0.4 s / 1 thread | 0.3 s / 2 threads |
|---|---:|---:|
| Reported Smart Turn processing median | 649 ms, 19 evaluations | 422 ms, 12 evaluations |
| Endpoint estimate to inference median | 1.072 s, 18 triggers | 0.851 s, 9 valid boundaries |
| Native estimated speech-end to bot speech median | 8.385 s, 15 responses | 21.236 s, first 10 responses |

The utterance sets differ, so these are observed group summaries rather than
a controlled causal comparison. Local model processing got faster, while
the downstream response path became slower. Most ordinary new endpoints
were 0.71–0.89 s. A short message-content turn took 3.08 s and the weather
request took 4.49 s to endpoint after INCOMPLETE analysis and the existing
3 s fallback. These tails remain despite the faster model computation.

Eight of the first ten completed requests used GLM; two used the fast tool
path. Three Jev timeouts sent basic requests to GLM. One single command,
“And turn off the lights,” was falsely classified as multiple actions by
the deterministic guard and took 39.92 s to bot speech. That connective
guard is now corrected, retaining GLM routing for actual combined commands.

Examples before the feedback loop:

| Request | Route | Estimated speech end to bot speech | Main observed wait |
|---|---|---:|---|
| Lights on | Jev timeout / GLM | 24.29 s | GLM first tokens and tool planning; MCP only 0.024 s |
| Lights red | Low-confidence / GLM, split turn | 18.18 s | MCP 6.64 s plus model calls |
| Thermostat 25 C | Jev timeout / GLM | 41.98 s | About 27.6 s from first token to tool invocation, then MCP 4.80 s |
| Reminder to study | Parser rejected / GLM | 25.65 s | Multiple GLM stages and MCP 3.93 s |
| Lights blue | Fast | 2.93 s | Router 1.26 s including MCP 0.90 s |
| Current weather | Fast | 8.07 s | Endpoint 4.49 s, router 2.68 s |
| Lights off, leading “And” | False multi-action / GLM | 39.92 s | Second GLM first token 22.39 s |

The Pi reported no throttling (`0x0`), approximately 52.6 C and load average
1.60 on four cores at inspection. These snapshots do not rule out transient
event-loop or single-core contention, but there is no observed thermal cause
for the long GLM waits.

## Confirmed feedback

At 11:24:52 the bot said “Done, the lights are off now.” ASR then reported
“The lines are off now,” and later repeated “The lights are off right now”
and “Lights are off” after matching bot replies. Eventually its own “All
right, I'll be here…” reply was also transcribed. These turns began through
`TranscriptionUserTurnStartStrategy`, without requiring a fresh VAD start.
The user confirmed being quiet during the exchanges.

The agent was stopped to halt the loop. PulseAudio had no echo-cancel module
loaded. Plain `pulse` microphone capture and `pacat` playback reached the
physical JV801P directly. Changing inference threads cannot fix this path.

## Echo cancellation deployment

The installed PulseAudio 17 WebRTC echo canceller creates a paired virtual
source/sink over the physical JV801P. The bot unit now pins
`PULSE_SOURCE=voice_agent_aec_source` and `PULSE_SINK=voice_agent_aec_sink`.
The global hardware defaults remain the JV801P. Playback must use the virtual
sink so the canceller has a reference signal. Capture stays live during TTS;
full-duplex interruption is not replaced with microphone muting.

`pi/ensure_echo_cancel.py` runs at service startup, including after reboot.
It validates existing paired devices or loads the module, with analog/digital
automatic gain control disabled. A fresh module-creation check and two
idempotency checks succeeded. All sixteen regression tests passed, including
the expanded leading-connective case. Real stream inspection confirmed the
Python recorder on the virtual source and `pacat` on the virtual sink.

While the bot was stopped, a repeated synthetic speech sample was played
through the reference sink. Simultaneous raw and filtered mic captures showed
16.9 dB lower RMS over the full capture and 14.6 dB lower RMS in the tail
window. This is an indicative signal-level comparison, not a calibrated ERLE
measurement or proof of human double-talk performance. Temporary microphone
PCM files were deleted after measurement.

The new audio experiment label is `vad-0.3-threads-2-aec-20261101`.
VAD remains 0.3 s and Smart Turn remains two threads so the audio repair can
be evaluated separately. Pi code/unit/private-env backups use suffix
`.bak-aec-20261101-113116`. Physical PCM remains 100%.

After the repair, the 11:31:43 greeting played and the agent remained active
without any ASR transcripts or new user starts through 11:32:26. This is an
encouraging quiet-playback check, not proof across all volumes and room
conditions. Near-end speech and barge-in still require a user test.

Next validate near-end speech and barge-in, then compare latency again. Do not attribute future changes solely
to VAD/thread settings across the echo-cancellation change.

Primary configuration references:

- [PulseAudio echo-cancel module](https://wiki.freedesktop.org/www/Software/PulseAudio/Documentation/User/Modules/)
- [PulseAudio stream-selection environment variables](https://wiki.freedesktop.org/www/Software/PulseAudio/FAQ/)
