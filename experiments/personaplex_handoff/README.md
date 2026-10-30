# PersonaPlex / cascade speech handoff experiment

Test whether Pipecat can move speech ownership between a PersonaPlex frontdesk
and the existing cascade while keeping one browser WebRTC connection. The
cascade speaks its own task answers through its existing TTS service.

Start with [HERMES_PROMPT.md](HERMES_PROMPT.md) for the complete handover and
[PLAN.md](PLAN.md) for implementation stages and acceptance criteria.

## What is implemented

The runnable harness uses real Pipecat 1.13.0 TTS context/playback processing,
SmallWebRTC, ICE/DTLS/SRTP, Opus, and a receiving aiortc peer on the same machine.
It substitutes a 440 Hz tone for PersonaPlex speech and an 880 Hz tone for
cascade TTS. The latter exercises 22.05 kHz to 24 kHz resampling; decoded
receiver audio is 48 kHz.

It checks both audio sources, a processor after TTS, a deliberate no-flush
negative control, 60 ownership transitions, stale audio and TTS lifecycle
rejection, delayed backend responses, ordered output fences, source order,
transition timing, and RTP timestamp continuity. Twenty checks are expected.

It does not call PersonaPlex, Jetson ASR/TTS, Ollama, or MCP tools, and it does
not capture a microphone. Browser rendering, physical playback, voice quality,
lost words, context restoration, network jitter, and Pi performance need the
live tests in the plan. Running both WebRTC peers on a Pi also adds work that
the eventual Pi-to-ThinkPad topology will distribute between two machines.

## Run on the Pi using the existing environment

From the repository root:

```bash
~/pipecat-quickstart/server/.venv/bin/python -B experiments/personaplex_handoff/run.py
```

Inspect the environment first. The harness requires Python 3.11+ and Pipecat
1.13.0 because the output adapter uses inspected 1.13 interfaces. Do not upgrade
the production virtual environment to run it. If its dependencies differ, report
the incompatibility or create an isolated compatible environment.

The wrapper uses the same interpreter for both experiment and analysis. Each
invocation creates a fresh ignored directory under `artifacts/` with:

- `run.json`: exact commands and exit codes;
- `lab.log` and `analysis.log`;
- `results/summary.json`: checks, versions, run ID, platform, and metrics;
- per-scenario events, RTP timing, and sender/receiver tone WAV files.

Exit zero means the experiment and analysis both passed. A missing or failed
run is not validated by an old summary. The analyzer verifies run identity and
WAV/timing consistency. An unaligned decoded source sequence leaves dependent
timing checks explicitly unrun and the overall result failing.

Choose another artifact parent if the checkout should remain entirely read-only:

```bash
~/pipecat-quickstart/server/.venv/bin/python -B experiments/personaplex_handoff/run.py --artifacts-dir /tmp/me3-handoff-runs
```

For a separate development environment, Python 3.12 is the cloud-tested default:

```bash
python3.12 -m venv experiments/personaplex_handoff/.venv
experiments/personaplex_handoff/.venv/bin/python -m pip install -r experiments/personaplex_handoff/requirements.txt
experiments/personaplex_handoff/.venv/bin/python -B experiments/personaplex_handoff/run.py
```

`requirements.txt` pins the main harness dependencies. The exact environment
snapshot used for the committed cloud reference is in
[reference/cloud-requirements.lock](reference/cloud-requirements.lock).
Do not install that snapshot into an existing production environment.

Individual commands, when debugging, are:

```bash
python -B experiments/personaplex_handoff/lab.py --output-dir /tmp/new-handoff-results
python -B experiments/personaplex_handoff/analyze_receiver.py /tmp/new-handoff-results
```

The results directory passed to `lab.py` must not already exist. For diagnosis,
run the analyzer after a failing lab if that run produced a summary, and preserve
both exit codes. The wrapper does this automatically.

## Findings carried forward from cloud testing

The original run passed 20/20 checks. Its decoded-peer transition p95 was about
141 ms; the deliberately unflushed negative control incurred about 900 ms of
backlog. The committed [cloud baseline](reference/cloud-baseline.json) contains
the numerical results of the repository harness verification run.

These findings change the initial implementation plan:

1. Feed PersonaPlex PCM through the output transport's public `send_audio()` API
   while keeping the existing cascade path. Do not create a second audio track.
2. Revoke the old owner/epoch, queue an `InterruptionFrame`, await the output's
   `on_after_process_frame` event for that exact frame, then admit the new owner.
3. Gate stale TTS audio, start/stop events, and associated text. Associate TTS
   contexts with the request epoch in `on_tts_request`, before start emission.
4. Preserve normal SmallWebRTC backpressure. The cloud run did not establish a
   need to replace or clear private media-track queues.
5. A correctly forwarding identity processor after TTS did not reproduce the
   earlier reported audio-drop issue. Check the original Pi application
   separately; do not assume a universal framework defect.
6. An ordered fence establishes sender-side consumption toward WebRTC. It does
   not acknowledge browser-speaker playback.

The adapter is an experiment, not a production PersonaPlex integration. It uses
a local output-factory adaptation tied to Pipecat 1.13's `_client`/`_output`
layout. The sender observation wraps one track's `recv()` and returns exactly
the original frames. No installed-package source is modified. RTP re-chunking
does not preserve every custom field, so epoch checks happen before buffering
and interruption clears already-admitted old audio. A live implementation also
needs admission control for untagged LLM text and context updates before TTS.

## References and provenance

This folder's harness was developed in the Codex cloud workspace. No upstream
source files were copied or vendored. Runtime dependencies retain their own
licenses. Architecture references:

- [NVIDIA PersonaPlex](https://github.com/NVIDIA/personaplex): continuous audio,
  startup persona prompt, and reference WebSocket protocol.
- [NVIDIA frontend/backend Pipecat example](https://github.com/NVIDIA-AI-Blueprints/nemotron-voice-agent/tree/main/src/examples/frontend_backend_agent):
  delegation, cancellation, and direct backend-response-to-TTS behavior.
- [Pipecat](https://github.com/pipecat-ai/pipecat): output transport and pipeline APIs.

Keep generated recordings, logs, environment files, authentication material, and
device connection reports out of commits. This handover requires no cloud VPN
connection; Hermes runs hardware tests and relays evidence for review.
