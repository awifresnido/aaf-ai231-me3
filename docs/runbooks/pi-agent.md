# Runbook — Raspberry Pi voice agent (draft)

## Topology (draft)

```
ThinkPad browser (mic + speakers)
  │  WebRTC media + signalling over Ethernet
  ▼
Raspberry Pi 4 (192.168.5.12)
  Pipecat 1.13 runner :7860   ← Pi-hosted VAD (Silero), pipeline orchestration
  │  gRPC over Ethernet
  ▼
Jetson Orin Nano (192.168.5.11)
  Nemotron ASR :50051 · Magpie TTS :50052
  │  HTTPS
  └─ Ollama Cloud (gemma4:31b)
```

## Start the agent (on the Pi)

```bash
cd ~/voice-agent
~/pipecat-quickstart/server/.venv/bin/python bot.py -t webrtc --host 0.0.0.0 --port 7860
```

Expected: `🚀 Bot ready! (WebRTC)` and a listener on `0.0.0.0:7860`.

## Connect from the ThinkPad

One tunnel, then open the browser:

```bash
ssh -L 7860:localhost:7860 aldwinrpi4@192.168.5.12
```

Then open <http://localhost:7860> and allow the microphone.

## Stop

`Ctrl+C` on the Pi process (or `pkill -f "bot.py -t webrtc"`), and `Ctrl+C` the tunnel.

## Speech services (Jetson)

```bash
# ASR (host network, 0.0.0.0:50051)
docker start nemotron-asr-server

# TTS LAN (host network, 0.0.0.0:50052)
docker start magpie-tts-lan

# The original TTS container is preserved, stopped, bound to 127.0.0.1:50052.
# Never run both at once (Magpie loads twice into 7.3 GiB).
docker ps --format '{{.Names}} | {{.Status}}'
```

## Secrets

Copy `pi/env.example` to `~/.config/voice-agent/env`, fill in the Ollama key,
`chmod 600` it, and export before starting the bot. Never commit it.
