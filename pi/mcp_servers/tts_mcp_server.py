"""TTS MCP server (Option A: per-sentence tool call).

Exposes one tool: synthesize(text) -> base64 16-bit mono WAV.
Forwards to the Jetson Magpie TTS container over Riva gRPC via non-streaming
synthesize (the whole sentence is synthesized before returning, which is the
documented Option A cost).

Run: .venv/bin/python tts_mcp_server.py   (stdio transport)
Env: TTS_SERVER (default 192.168.5.11:50052), TTS_VOICE_NAME (default 0)
"""
import base64
import io
import os
import time
import wave

from mcp.server.mcpserver import MCPServer

TTS_SERVER = os.getenv("TTS_SERVER", "192.168.5.11:50052")
TTS_VOICE_NAME = os.getenv("TTS_VOICE_NAME", "0")
TTS_SAMPLE_RATE = int(os.getenv("TTS_SAMPLE_RATE", "22050"))

server = MCPServer(
    name="tts-jetson",
    version="0.1.0",
    instructions=(
        "Text-to-speech. Call synthesize() with one sentence; returns "
        "base64 16-bit mono WAV."
    ),
)


@server.tool(
    name="synthesize",
    description=(
        "Synthesize one sentence to speech. Input: text. Returns a "
        "base64-encoded 16-bit mono WAV plus its sample rate."
    ),
)
def synthesize(text: str) -> dict:
    import riva.client

    if not text.strip():
        return {"audio_wav_b64": "", "sample_rate": 0, "tts_ms": 0, "error": "empty text"}

    auth = riva.client.Auth(uri=TTS_SERVER)
    service = riva.client.SpeechSynthesisService(auth)
    t0 = time.time()
    resp = service.synthesize(
        text=text,
        voice_name=TTS_VOICE_NAME,
        sample_rate_hz=TTS_SAMPLE_RATE,
        language_code="en-US",
    )
    elapsed_ms = (time.time() - t0) * 1000
    audio = resp.audio  # raw PCM bytes (LINEAR_PCM, 16-bit mono)
    if not audio:
        return {
            "audio_wav_b64": "", "sample_rate": TTS_SAMPLE_RATE,
            "tts_ms": round(elapsed_ms), "error": "empty audio",
        }

    # Wrap raw PCM in a WAV container so the client can decode rate/format.
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(TTS_SAMPLE_RATE)
        f.writeframes(audio)
    return {
        "audio_wav_b64": base64.b64encode(buf.getvalue()).decode(),
        "sample_rate": TTS_SAMPLE_RATE,
        "tts_ms": round(elapsed_ms),
        "error": None,
    }


if __name__ == "__main__":
    server.run("stdio")
