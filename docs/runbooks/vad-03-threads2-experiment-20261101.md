# VAD 0.3 s and two-thread Smart Turn trial

Started 2026-11-01, about 11:17 Asia/Manila, Pi-local JV801P agent.
Experiment label: `vad-0.3-threads-2-20261101`.

Results and the subsequently confirmed echo-feedback repair are in
`docs/runbooks/vad-03-threads2-results-20261101.md`. The current label adds
`-aec-` after installing a paired PulseAudio echo-cancel path; VAD and thread
count remain 0.3 s and two.

The user requested both changes together:

| Setting | Previous trial | Current trial |
|---|---:|---:|
| VAD stop silence | 0.4 s | 0.3 s |
| Smart Turn ONNX intra-op threads | 1 | 2 |

The private Pi environment now contains `VAD_STOP_SECS=0.3` and
`SMART_TURN_CPU_COUNT=2`. The bot explicitly constructs
`LocalSmartTurnAnalyzerV3(cpu_count=SMART_TURN_CPU_COUNT)` within the existing
turn-analyzer stop strategy, retaining the default start strategies and
transcript-finalization policy. All other pipeline settings remain as in the
previous trial. Timing configuration records include the selected CPU count.

Validation before deployment: all sixteen regression tests passed on the Pi;
a staged startup check imported the bot with these settings and asserted that
the ONNX session's actual `intra_op_num_threads` is two. Live speech quality
and total latency are awaiting the user's test.

The prior offline profile suggested about 0.40 s prediction processing with
two threads. Combined with 0.3 s VAD silence, ordinary endpointing might
approach 0.7 s, compared with approximately 1.05 s in the previous trial.
This is an estimate, not an observed live result. ASR-final waits, pauses,
thread contention, and fallback behavior can change it. Since two variables
changed together, this trial measures their combined effect.

## Test and review

Repeat lights, brightness, thermostat, reminders, and current weather requests.
Include short requests, pauses before a number or final argument, and complex
commands. Let replies finish first; test barge-in separately. Review estimated
speech-end to routing and playback, analysis processing, clipping/split turns,
incorrect arguments, duplicates, and audio continuity. Keep Jev/GLM/MCP delays
separate from endpointing measurements.

Do not adjust the threshold again until this test is reviewed. Results from
the previous trial are in `docs/runbooks/vad-04-results-20261101.md`; the
thread profile is in `docs/runbooks/smart-turn-profile-20261101.md`.

## Backups and rollback

The Pi's previous code is `~/voice-agent/bot.py.bak-vad03-threads2-20261101-111725`.
The private environment backup is
`~/.voice-agent-env.bak-vad03-threads2-20261101-111725` (mode 600).

To revert the experiment while keeping the new configurable code, set
`VAD_STOP_SECS=0.4`, `SMART_TURN_CPU_COUNT=1`, and a new experiment label in
the private environment, then restart `me3-local-audio.service`. Preserve
other environment settings and credentials.
