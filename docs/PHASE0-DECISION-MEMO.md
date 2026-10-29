# Phase 0 decision memo (draft 1) — Raspberry Pi voice agent (aaf-ai231-me3)

Date: 2026-10-29
Repo: https://github.com/awifresnido/aaf-ai231-me3 (cloned to /home/aldlinux/aaf-ai231-me3, empty)
Status: draft, based on environment inspection completed this session.

## 0.1 Reuse survey

Subagent survey of the six candidate repos was dispatched (see NOTICE.md when complete).
Facts verified locally:

- pipecat 1.13.0 installed on the Pi with `webrtc` and `runner` extras.
- Silero VAD is vendored in pipecat 1.13: `pipecat/audio/vad/silero.py` + bundled
  `data/silero_vad.onnx`; the `silero_vad` pip package is NOT needed.
- The `mcp` pip package is NOT installed on the Pi; `pipecat[mcp]` extra would add it.
  For MCP milestone (Phase 0 decision 0.2), install `pipecat-ai[mcp]` or the `mcp` SDK.

## 0.2 Audio path — browser WebRTC primary (per reviewer)

Decision: WebRTC browser route as the primary audio path; Pulse-over-SSH only as a
documented fallback. Rationale: the browser supplies echo cancellation/noise suppression;
Pi still runs Silero VAD (vendored onnx model, CPU cheap); ThinkPad setup shrinks to one
SSH tunnel. Pipecat 1.13 ships `SmallWebRTCTransport` (aiortc backend, verified present)
plus the runner with a web UI.

Open items:
- Measure Pi CPU load under WebRTC + VAD (reviewer's caveat).
- Browser mic requires HTTPS or localhost → SSH tunnel `ssh -L 7860:localhost:7860`
  from the ThinkPad; confirm which interface the media actually uses (Ethernet vs Wi-Fi).

## 0.3 MCP integration style — Option C (switchable) with A inside

Decision: build Option A (per-utterance MCP calls) behind a runtime switch (Option C),
so a benchmark can measure the indirection cost. MCP is the control interface, not the
audio transport. Data path stays direct gRPC/HTTP to the Jetson containers in both modes.
Pipecat's `MCPClient` is for LLM tools; the custom STT/TTS MCP servers will be used via
the MCP Python SDK client directly.

## 0.4 Milestone gates (defer items noted)

1. Infra up: Pi internet stable, ASR/TTS containers reachable, audio in/out working. ← reached (see below)
2. One turn: speech in → Ollama LLM → speech out.
3. Multi-turn: Pi VAD + barge-in (with tegrastats logged during barge-in explicitly).
4. MCP in the loop (A behind switch C).
5. Real-world task: timer + "report Jetson memory and Pi load" (read-only).
6. Benchmark skeleton: IDs + monotonic timestamps logged; numbers by end of draft.

Deferred: DGX investigation, acoustic loopback latency, cold/warm repeat trials, long
sessions, PersonaPlex (out of this iteration).

## 0.5 Turn-taking

Jetson ASR server has baked-in endpointing: `--asr.endpointing.stop_history_eou_ms=1500`
(≈1.5 s floor between end of speech and final transcript). Direct gRPC probes today
(showed): finals arrive ~1.9 s after speech ends regardless of client-side stop_history
tweaks (320→10 frames made no difference; stop_history_eou tweaks made no difference either).
The floor lives in the server, not the client config.

Decision: Pi VAD (Silero, vendored in pipecat) drives turn taking with stop_secs ≈ 0.5–0.8 s,
with the server's 1.5 s final as backstop. The ~1.5 s server-final latency is a known floor,
documented, not treated as a bug. Whether Pipecat 1.13 can trigger a server-side final on
VAD end-of-speech is being verified (subagent delegated); if not, the VAD-driven policy
uses the interim transcript at VAD-stop as the LLM input (pending verification).

## 0.6 Environment facts (verified this session)

- Pi (192.168.5.12, eth0, Raspberry Pi 4B 4GB, Debian 13, kernel 6.18.50, Py 3.13.5):
  - Internet OK via wlan0 (YOTC-D2867F, 192.168.8.44); hotspot profile present but NOT
    autoconnected currently (verified `nmcli c show --active`) — no immediate risk.
  - `docker` not installed on the Pi (not needed — pipeline runs on the Pi, not containers).
  - PulseAudio running; parec via tcp:192.168.8.35:4713 was the old Mac path (deprecated).
  - pipecat-quickstart venv with pipecat 1.13.0, webrtc+runner extras, aiortc, onnxruntime
    (silero VAD model vendored), FastAPI/uvicorn, grpcio 1.84.1.
  - ~47 GB free disk, no dmesg I/O errors.
- Jetson (192.168.5.11, user aldwin, Orin 7.3 GB RAM, reachable from Pi on ports 50051/50052):
  - nemotron-asr-server (host net, 0.0.0.0:50051) — Nemotron streaming ASR.
  - magpie-tts-lan (host net, 0.0.0.0:50052) — Magpie TTS multilingual.
  - Original magpie-tts-server bound to 127.0.0.1 was stopped and removed (duplicate-magpie
    memory hazard avoided; llama-server not running).
  - Both containers healthy; Jetson RAM 4.5/7.3 GiB used with both loaded.
- Verified end-to-end from the Pi via direct riva gRPC:
  - TTS: Pi → Jetson magpie-tts-lan produces 22.05 kHz mono PCM; ~0.65 s to first chunk.
  - ASR: Pi → Jetson ASR transcribes the TTS audio correctly ("hello this is a test of the
    magpie text to speech service"); interim in ~0.1–0.45 s; final ~1.9 s.
- Ollama tool calling (gemma4:31b) verification delegated; fallback models listed.

## 0.7 Provenance rules (carry into NOTICE.md)

Any copied code gets URL + commit + licence + what was copied. Benchmark definitions
mirror the NVIDIA Blueprint's split (ASR+turn-taking, TTS first byte, LLM first token).
