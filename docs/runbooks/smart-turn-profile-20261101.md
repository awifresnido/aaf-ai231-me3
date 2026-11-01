# Smart Turn processing profile

Profiled on the Pi 4, 2026-11-01, approximately 11:10–11:12 Asia/Manila.
The live bot remained running with VAD stop silence 0.4 s and the default
one-thread Smart Turn analyzer. Production code/settings were not changed.

## Method

The installed Pipecat 1.13 `LocalSmartTurnAnalyzerV3` uses the bundled
`smart-turn-v3.2-cpu.onnx` model. A standalone script exercised the installed
`_predict_endpoint` method with a generated 2.875 s, mono 16 kHz PCM WAV of
“Set the room temperature to twenty five degrees.” No user audio was captured.

Timing wrappers measured feature computation, ONNX `session.run`, resampling,
the complete prediction call, and executor queue/caller time. An initial
seven-sample series collected cProfile call attribution. The headline table
below uses separate fresh processes per thread count: two warmups and twelve
measured iterations, without cProfile overhead. The live agent was idle but
still streaming its microphone; this is not a loaded live-turn benchmark.

Each input is padded/truncated to eight seconds by the installed analyzer, so
this short utterance still exercises the full model window. Its output
probability was 0.9859892129898071, COMPLETE, for all measured thread counts.
That agreement on one sample is not a general classification regression test.

## Fresh-process measurements

| ONNX threads | Feature median | ONNX median | Total prediction median | Total min–max |
|---|---:|---:|---:|---:|
| 1 (current) | 21.4 ms | 598.0 ms | 621.0 ms | 618.0–629.9 ms |
| 2 | 23.3 ms | 372.4 ms | 397.9 ms | 393.0–431.2 ms |
| 3 | 25.5 ms | 317.1 ms | 344.7 ms | 323.4–359.1 ms |

Executor queue medians were 0.105–0.139 ms. Native-rate resampling was a
no-op, about 0.002 ms; padding and other work were about 0.6 ms. Stage medians
are separate summaries, so their sum need not equal the total median.
cProfile independently attributed about 96% of one-thread prediction time to
ONNX inference. The standalone one-thread result closely reproduces the live
reported 615–669 ms prediction metric.

The installed `BaseSmartTurn._process_speech_segment` starts its reported
prediction timer after audio-buffer concatenation and before `_predict_endpoint`.
That reported metric excludes executor queueing, VAD silence, and the earlier
buffer assembly. Thus those earlier stages cannot account for the reported
0.65 s itself, though they can add to total endpointing latency.

## Host state

Pi 4 Cortex-A72, four CPU cores, maximum frequency 1.8 GHz. The governor was
`ondemand`, current frequency read 1.8 GHz, temperature approximately 51 C
before and 54 C after the initial series. `get_throttled` returned `0x0`.
The Pi had about 3.2 GiB available RAM. No thermal/power throttling or memory
pressure was observed in these snapshots. They do not establish behavior
under all workloads. The live audio service remained active during profiling.

## Recommended next experiment

Use `LocalSmartTurnAnalyzerV3(cpu_count=2)` in an explicit
`TurnAnalyzerUserTurnStopStrategy` while holding VAD at 0.4 s and all other
settings fixed. Two threads saved about 223 ms (36%) against the benchmark's
one-thread baseline. This suggests ordinary endpointing could fall from about
1.05 s toward 0.8 s, conditional on live ASR timing and scheduling.

Three threads were faster by a further 53 ms, but leave less CPU capacity for
the streaming bot. Start with two and compare actual endpointing, audio gaps,
barge-in, CPU load, and split/late-final behavior using the same utterances.
Retain one thread as rollback. Do not lower VAD to 0.2 s in the same experiment.

## Artifacts and reproduction

- `scripts/profile_smart_turn.py`
- `docs/profiling/smart-turn-call-profile-20261101.json` (initial call profiles)
- `docs/profiling/smart-turn-1thread-20261101.json`
- `docs/profiling/smart-turn-2threads-20261101.json`
- `docs/profiling/smart-turn-3threads-20261101.json`

On the Pi, from a checkout containing the script:

```bash
ffmpeg -hide_banner -loglevel error -y -f lavfi \
  -i "flite=text=Set the room temperature to twenty five degrees:voice=slt" \
  -ar 16000 -ac 1 -c:a pcm_s16le /tmp/smart-turn-profile.wav
/home/aldwinrpi4/pipecat-quickstart/server/.venv/bin/python \
  scripts/profile_smart_turn.py --wav /tmp/smart-turn-profile.wav \
  --threads 2 --repeats 12 --json-output /tmp/smart-turn-profile-2.json
```

Use separate invocations for independent thread-count comparisons. The
script's use of private Pipecat methods is confined to the profiling process.
