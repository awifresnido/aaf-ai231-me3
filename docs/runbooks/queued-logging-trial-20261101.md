# Queued logging trial and latency comparison

Both consecutive tests are assessed in
[Queued logging results](queued-logging-results-20261101.md): reply medians
7.014 s and 6.931 s. Caller-side logging stalls and loop delays disappeared
at the earlier scale, but repeated SQLite commits took up to 14.714 s.

Requested 2026-11-01 after profiling identified synchronous logging stalls
of 0.416–1.807 s and a separate SQLite commit spike of 1.978 s. This trial
changes only normal Pi logging delivery, while retaining the same latency
and stall instrumentation. A voice retest is required before claiming an
improvement.

## Configuration

```text
ORCHESTRATION_MODE=local_vcm
LOCAL_VCM_MODEL_HOST=thinkpad
VOICE_DIAGNOSTICS=1
VOICE_QUEUED_LOGGING=1
VAD_EXPERIMENT=vcm-thinkpad-queued-log-20261101
```

Jev, GLM, and VPS fallback remain disabled. ThinkPad endpoint, Voice of Pi
greeting/instruction, schema, tools, context/validation, 12 s model deadline,
20 s tool deadline, VAD 0.3 s, Smart Turn two threads, paired AEC, PCM 100%,
and pacat buffer 150 ms remain fixed. SQLite settings and tool/network
behavior are unchanged.

The inspected normal log configuration was DEBUG on stderr, with the default
Loguru format and synchronous writes. `pi/queued_logging.py` retains DEBUG,
stderr, format, and the service's append-to-file destination, adding
`enqueue=True` with installed Loguru 0.7.3. Sink writes run in its worker;
the calling thread still formats/enqueues records. The existing timing spans
therefore measure enqueue-side cost and any remaining contention. Graceful
shutdown drains queued records with `logger.complete()`. Disabling the flag
leaves the original handlers untouched.

The separate RAM trace remains active on both Pi and MCP. Normal log records
may reach disk later; use their embedded timing values and RAM monotonic
timestamps rather than file arrival time for analysis.

## Latency measurements to report after the retest

Keep the previous definition: estimated speech end through the first
software bot-speech/first-playback event, excluding unmeasured physical
speaker delay. Record per-request outcomes and distinguish failed or wrong
actions from successful commands. Report counts, median, and range.

| Measurement | Previous profiling trial baseline |
|---|---:|
| End-to-end reply delay | Median 5.497 s; range 3.784–7.803 s; 12 replies |
| Model call | Median 3.515 s |
| Endpoint/context event | Median 784 ms |
| Smart Turn processing | Median 430 ms |
| TTS first byte | Median 1.047 s |
| Largest measured normal logging call | 1.807 s |
| Largest user-turn Pi loop-lag event | 1.754 s |
| Slow SQLite commit | 1.978 s |
| Normal local state-call MCP totals | 36.9–70.2 ms, excluding the 2.006 s spike |

Report the same table for this trial, plus per-call MCP/session/RPC/server,
SQL execution/commit, and HTTP durations. Compare the same command types
and note changed utterances or correctness. The previous median was a mixed
reply sample, not a guarantee of improvement for every command. Keep SQLite
spikes distinct from logging improvement; queued output does not change the
database's durability policy or remove the ordinary model cost.

## Suggested speakerphone test

Repeat commands from the preceding test, waiting for each reply. To capture
intermittent local waits, repeat the lights cycle two or three times:

1. “What time is it?”
2. “Turn on the lights.”
3. “Set the lights to green.”
4. “Set the room temperature to twenty-six degrees.”
5. “Set the lights to blue.”
6. “Turn off the lights.”
7. “What is the weather today?”

Single commands make latency attribution clearer. Intent errors, unsupported
requests, compound partial execution, and echo remain acceptance issues;
this trial does not change them. After testing, say “done” for analysis.

## Validation, records, and rollback

All 37 regression checks passed on the Pi. The added test deliberately blocks
a sink, verifies that it executes on a different thread while the event loop
and another record proceed, then checks ordered DEBUG/INFO delivery after
flush. Another check verifies that disabled mode leaves handlers alone.

Service: `me3-local-audio.service`. Normal log:
`/home/aldwinrpi4/voice-agent/me3-local-audio.log`.
Metadata: `/home/aldwinrpi4/voice-agent/queued-log-trial.json`, containing
the start/log offset, previous trial pointer, backups, and actual run/trace
directory once startup is verified. RAM files remain under
`/dev/shm/voice-agent-diagnostics/RUN_ID/`; collect them before Pi reboot.
The preceding traces are already preserved in the workspace.

Deployment verified: run `597aabcb5a`, ThinkPad-only, `queued_logging=true`,
pipeline active, both diagnostic streams present, and normal latency events
being recorded. Start/log offset: 2,717,253 bytes; backup suffix:
`.bak-queued-log-20261101-155055`. Live bot/helper hashes match the workspace.

Backups use `.bak-queued-log-TIMESTAMP` for the private environment and
existing Python files. Restore them to reproduce the synchronous-logging
baseline, or set `VOICE_QUEUED_LOGGING=0`, restore the desired experiment
label, and restart the same service. Queued mode persists through reboot
until its setting is changed. This implementation and the two-test report
are included in the local checkpoint on `two-brain-plusjev`.

Related: [previous profiling results](thinkpad-mcp-profile-results-20261101.md),
[profiling setup and trace interpretation](thinkpad-mcp-profile-20261101.md).
