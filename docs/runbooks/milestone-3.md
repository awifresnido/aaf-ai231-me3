# Milestone 3: multi-turn conversation with Pi VAD turn-taking

Status: working (verified live 2026-10-29).

## What changed since dafdd0e (Milestone 2)

- **bot.py**:
  - VAD stop raised 0.7s -> 0.8s: with the Jetson ASR container endpointing
    retuned to `stop_history_eou_ms=320`, ASR finals arrive ~0.6s after speech
    end, so 0.8s VAD silence keeps the final inside the turn.
  - ASR stop_history retuned to 320 (Blueprint default): server-side endpointing
    backstop instead of `stop_history=-1`, cutting ASR final latency from
    ~1.9s to ~0.6s (measured via direct gRPC probe).
  - Fixed greeting: `TTSSpeakFrame` instead of LLM greet — gemma4:31b on Ollama
    Cloud returns empty content for a developer-only turn (no user message).
  - Shorter conversational system instruction (1-3 spoken sentences).
  - No-LLM echo mode kept as smoke path (mic -> ASR -> TTS loopback).
- **dgx_services.py** (NEW, paused):
  - `DGXSTTService` / `DGXTTSService`: vLLM HTTP backends (Qwen2-Audio ASR,
    Qwen3-TTS) as a `SPEECH_BACKEND=dgx` switch. Built and wired; testing
    paused after an acoustic feedback loop (bot transcribing its own speaker
    output) and non-streaming first-audio latency. Retained for later
    evaluation with a headset.
- **Pipecat 1.13 pipeline quirk (found, unfixed)**:
  - Inserting a FrameProcessor between `tts` and `transport.output()` silently
    drops all TTS audio (TTS synthesizes + TTFA logs, zero frames flow
    downstream). The audio-context playback path only works with the
    quickstart topology (`... tts -> transport.output() -> assistant_agg`).
  - Consequence for benchmarking: tap TTS audio by monkeypatching
    `RawAudioTrack.add_audio_bytes` (bot_tee.py) rather than inserting a
    processor.

## Turn-taking behaviour (live log)

- ASR finals mid-session (not only at teardown) after the 320ms retune.
- Smart-turn (LocalSmartTurn v3) ends turns; VAD 0.8s is the backstop.
- Multi-turn context verified: follow-up "Did you hear what I just said?"
  answered correctly from prior turns.

## Open item: speech onset quality

Raw TTS audio probes (one-shot and streaming, byte-exact to Pipecat's request
shape) show clean onsets — no truncation, no codec cold-start. The reported
"cut / unnatural start of each sentence" is therefore downstream of TTS
(resampler / WebRTC pacer / browser). bot_tee.py records the exact bytes
handed to the WebRTC track at /tmp/tee_out.wav for the next measurement.
