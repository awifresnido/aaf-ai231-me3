#!/usr/bin/env python3
"""Pre-render backchannel filler clips via DGX Qwen3-TTS (:18001, tunnel).

Output: 24 kHz mono PCM16 WAV in ~/voice-agent/assets/backchannel/.
If TTS fails for any clip, exit 1 (caller falls back to a tone-free silence
check — never synthesize placeholders silently).
"""
import io
import json
import os
import sys
import urllib.request
import wave

BASE = os.environ.get("DGX_TTS_BASE", "http://127.0.0.1:18001").rstrip("/")
KEY = os.environ.get("DGX_API_KEY", "")
VOICE = os.environ.get("DGX_TTS_VOICE", "aiden")
OUT = "/home/aldwinrpi4/voice-agent/assets/backchannel"

CLIPS = {
    "mm_hm":        "Mm-hm.",
    "one_moment":   "One moment.",
    "let_me_check": "Let me check.",
    "sure_one_sec": "Sure, one sec.",
}

os.makedirs(OUT, exist_ok=True)
ok = True
for name, text in CLIPS.items():
    body = json.dumps({
        "model": os.environ.get("DGX_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"),
        "input": text,
        "voice": VOICE,
        "response_format": "wav",
    }).encode()
    req = urllib.request.Request(
        BASE + "/v1/audio/speech", data=body, method="POST",
        headers={"Authorization": "Bearer " + KEY,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        with wave.open(io.BytesIO(data), "rb") as w:
            rate, ch, width, frames = (w.getframerate(), w.getnchannels(),
                                       w.getsampwidth(), w.getnframes())
            pcm = w.readframes(frames)
        dur = frames / rate
        if not (0.2 <= dur <= 0.9):
            print(f"{name}: {rate} Hz {ch} ch {dur:.2f}s — OUT OF RANGE, keeping")
            ok = False
        out_path = os.path.join(OUT, name + ".wav")
        with wave.open(out_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(pcm)   # server returns 24 kHz mono already; re-mux to be sure
        print(f"{name}: {rate}->{24000} Hz, {dur:.2f}s, {len(pcm)} bytes -> {out_path}")
    except Exception as exc:
        print(f"{name}: FAILED {type(exc).__name__}: {exc}")
        ok = False

sys.exit(0 if ok else 1)