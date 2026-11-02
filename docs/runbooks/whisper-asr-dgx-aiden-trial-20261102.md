# Whisper ASR + DGX Aiden TTS trial

Activated **23:57 Asia/Manila** on 2026-11-02, run **`6989207f98`**, experiment
`whisper-large-v3-turbo-dgx-qwen3-aiden-20261102`.

Only the ASR backend changed (Nemotron → Whisper) plus the TTS selection
(MacBook → DGX Aiden). Jev routing, Llama 3.2 3B small model, GLM 5.3 Flash
fallback, Pi MCP, Jetson SQLite state, VAD 0.3 s and speakerphone settings are
unchanged.

## What Whisper is (and is not)

`ggml-large-v3-turbo.bin` is the whisper.cpp conversion of OpenAI Whisper
large-v3-turbo: a **plain encoder-decoder ASR**, not an LLM. It takes a 30 s
mel window and emits text; it cannot follow instructions, use tools, or reason
about content. (Contrast: `Qwen/Qwen2-Audio-7B-Instruct`, the other ASR option
in this repo, *is* a speech-LLM.) Server: whisper.cpp `whisper-server`, built
on the Jetson with CUDA (compute 8.7), 1.62 GB model, `-t 4`.

## Configuration

```text
ASR_BACKEND=whisper
WHISPER_ASR_BASE=http://192.168.5.11:8090
WHISPER_ASR_PATH=/inference
WHISPER_ASR_MODEL=whisper-large-v3-turbo
WHISPER_ASR_LANG=en
TTS_BACKEND=dgx_qwen
DGX_TTS_VOICE=aiden
```

The Pi adapter (`pi/whisper_stt.py`) is a `SegmentedSTTService`: VAD closes the
turn, the whole segment is posted as multipart WAV to `POST /inference`, and the
`{"text": ...}` result becomes a `TranscriptionFrame`. It does **not** stream
partials, unlike Nemotron's gRPC streaming ASR.

## Service layout on the Jetson (7.3 GiB board)

* `whisper-server` on `:8090`, CUDA0, 1.62 GB weights
* `nemotron-asr-server` container **stopped** (replaced for this trial)
* `magpie-tts-lan` container left running (not used; TTS is on DGX)

## Measured preflight (TTS-generated probes, no microphone)

| clip | audio | whisper.cpp wall | text |
|---|---:|---:|---|
| "Turn on the lights." | 0.88 s | 1.05–1.21 s | exact |
| long lights + thermostat sentence | 3.28 s | 1.23–1.39 s | exact |

There is a **fixed ~1.0 s cost per request** (30 s window encode + decode) that
barely grows with clip length up to ~3 s. Nemotron's streaming endpointing gave
0.43–0.49 s speech-end→transcript on the same board, so Whisper should add
roughly **+0.6 s per turn** while improving transcript accuracy on phrases the
Nemotron path garbled ("During underlights", "Turn on delight").

## Speakerphone level

The unit pins `amixer -c JV801P sset PCM 100%` before every start, which silently
reverted earlier manual changes. A drop-in
`~/.config/systemd/user/me3-local-audio.service.d/pcm60.conf` now appends
`ExecStartPre=/usr/bin/amixer -c JV801P sset PCM 60% unmute`, so 60 % survives
restarts and reboots. Verified `599/999 (60%)` after restart.

## Startup evidence

* Pipeline active, TTS greeting first audio **0.167 s**, 5.52 s audio in 0.93 s
* Pi → whisper.cpp round trip from the Pi itself: 1.08–1.21 s for the 0.88 s clip

## Rollback

```bash
python3 /tmp/set_env.py ASR_BACKEND=nemotron TTS_BACKEND=mac_qwen \
  MAC_TTS_STREAM=1 VAD_EXPERIMENT=jev-nemotron-jetson-llama32-mac-qwen-stream-pcm60-20261102
docker start nemotron-asr-server          # on the Jetson
systemctl --user restart me3-local-audio.service
```

Backups before the switch: `/home/aldwinrpi4/voice-agent-backups/whisper-asr-*`
(`bot.py`, `.voice-agent-env`).
