# Jev + Nemotron + Jetson Llama 3.2 trial

Trial selection, 2026-11-02 15:46 Manila: Nemotron streaming ASR,
Jev 1.14.0, Jetson GPU `meta-llama/Llama-3.2-3B-Instruct` as the small model,
GLM 5.3 Flash fallback, DGX Qwen3 CustomVoice **Aiden** TTS. Pi MCP,
Jetson SQLite worker, speakerphone/AEC, 0.3 s VAD, SmartTurn and routing
thresholds remain as before. Human trial completed; median end-to-end
reply onset **3.901 s** across 24 measured replies. See the
[TTS comparison](../profiling/jev-llama32-tts-comparison-20261102/comparison.md).

Jetson model `/home/aldwin/models/llm/Llama-3.2-3B-Instruct-Q4_K_M.gguf`
(SHA256 `6c99cc00ae910f6a532a80022cb4bc1939094527a089c29294b841c0bd87f74d`)
is served by transient `voice-agent-llama32-trial.service` on
`192.168.5.11:8084` using llama.cpp `--ngl 99`, flash attention, Q8 KV,
one slot and context 4096. The prior Voxtral service was stopped to free
Jetson memory. The Llama server was healthy with zero restarts; GPU probe
sampled 99% activity during a request. Pi small-model preflight: short reply
**0.784 s**, valid thermostat extraction **1.160 s**. A longer counting
prompt exceeded a separate five-second probe and was cancelled. Voice-agent
small-model deadline remains **2.5 s**, with GLM fallback.

Current Pi run **`7373bf308b`**, experiment
`jev-nemotron-jetson-llama32-qwen3-aiden-20261102`. The initial configuration
run `78441be654` was restarted to load the Mac TTS option without selecting
it. Pipeline ready and greeting playback succeeded; first Aiden PCM **0.178 s**.
Private
environment backup before the switch:
`/home/aldwinrpi4/voice-agent-backups/jev-nemotron-llama32-20261102-154419/`.
Pi log activation offset **7959039**; post-adapter restart offset **7993182**.

## MacBook TTS option for the following trial

`TTS_BACKEND=mac_qwen` selects [the Pi adapter](../../pi/mac_qwen_tts.py).
The MacBook at `192.168.5.9` runs an MLX 4-bit Qwen3 CustomVoice server on
port 8099, with `POST /speak` accepting `text`, `voice`, and `lang`, returning
whole mono PCM16 WAV. The adapter validates WAV before playback, emits normal
Pipecat audio frames and timing metadata, and uses no DGX API key. The Mac
server is currently unreachable directly from Pi/ThinkPad on port 8099, but
its localhost endpoint is healthy. Two SSH forwards expose it to the Pi at
`127.0.0.1:18099`; the Pi health check returned HTTP 200. A synthetic Aiden
request produced valid audio, first available at **3.56 s**. This endpoint
returns the whole WAV, so that time includes generation. It is not yet
selected for the current human trial.

For a later switch, ensure these forwards are active from the ThinkPad:

```sh
ssh -N -L 127.0.0.1:18099:127.0.0.1:8099 aldwin@192.168.5.9
ssh -N -R 127.0.0.1:18099:127.0.0.1:18099 aldwinrpi4@192.168.5.12
```

Then set private Pi `TTS_BACKEND=mac_qwen`, `MAC_TTS_BASE=http://127.0.0.1:18099`,
`MAC_TTS_VOICE=Aiden` and restart `me3-local-audio.service`. Keep existing
DGX settings for rollback. The Mac adapter is deployed on Pi but dormant.
Existing implementation changes remain uncommitted. All **113 regression
tests passed** after adding the optional selector, and the Mac adapter's
actual HTTP/audio preflight passed.
