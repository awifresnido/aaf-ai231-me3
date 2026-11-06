# VAD 0.4 s experiment

Started 2026-11-01, 10:54 Asia/Manila on the Pi-local JV801P bot.
Experiment label: `vad-0.4-20261101`.

Results and telemetry corrections are recorded in
`docs/runbooks/vad-04-results-20261101.md`. The current setting remains 0.4 s.

The previous setting was the bot's default 0.8 s (no private environment
override). `VAD_STOP_SECS=0.4` is now set in the Pi's private environment.
Smart Turn, ASR, Jev, model, and TTS settings are unchanged for this comparison.
The 0.2 s candidate is pending review of the user's 0.4 s test.

The new `TURN_TIMING` JSON records contain a run identifier, turn number,
experiment label, timestamps, and metadata for VAD stop, ASR finalized status,
turn-analysis metrics, turn release, routing stages, bot speech start, and the
first successful write to the local audio player. Native Pipecat user/bot
latency is also logged. No transcript text is added to these new records.
The bot's existing transcription logs still contain speech text.

Estimated speech end is VAD confirmation timestamp minus its configured
silence duration. This is an audio-detector estimate rather than an acoustic
ground truth annotation. The first playback write is after the `pacat` pipe
drain; the 150 ms sink buffer and hardware playback are downstream of it.
Playback without a context identifier uses an idle-gap heuristic for its first
write marker. Turn numbers follow aggregator start events; late finals and
interruptions should be reviewed with their timestamps and context identifiers.

Validation: 16 tests passed in the Pi's Pipecat 1.13 environment before
deployment, including timing offset, per-hop deduplication, greeting handling,
and routing regressions.

## User test

Repeat short commands from the previous sessions, including current time,
lights, brightness, thermostat, current weather, and reminder listing.
Include longer questions, combined commands, and natural pauses before a
number or final argument. First let replies finish; test interruption
separately so those effects can be distinguished from endpointing.

Afterward compare endpointing delay and total response delay, missing final
words/numbers, premature responses, duplicate turns/actions, and interruption
behavior. Historical 0.8 s logs lack the new per-frame timing, so identical
utterance replay at both settings may still be needed for a controlled result.

## Deployment and rollback

Pi backups use suffix `.bak-vad-20261101-105451` for existing project files.
The private environment backup is
`~/.voice-agent-env.bak-vad-20261101-105451` (mode 600).

To revert only this experiment, set `VAD_STOP_SECS=0.8` and a new
`VAD_EXPERIMENT` label in the private environment, then restart
`me3-local-audio.service`. Preserve other private environment settings.
Instrumentation can remain enabled while reverting the silence threshold.
