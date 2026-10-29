"""ASR MCP server (Option A: per-utterance tool call).

Exposes one tool: transcribe(audio_wav_b64) -> transcript text.
Input is a base64-encoded 16-bit mono WAV of a VAD-bounded user utterance.
Forwards to the Jetson Nemotron ASR container over Riva gRPC via offline
recognize (not streaming — that is the documented Option A cost).

Run: .venv/bin/python asr_mcp_server.py   (stdio transport)
Env: ASR_SERVER (default 192.168.5.11:50051), ASR_SAMPLE_RATE (default 16000)
"""
import base64
import io
import os
import time
import wave

from mcp.server.mcpserver import MCPServer

ASR_SERVER = os.getenv("ASR_SERVER", "192.168.5.11:50051")

server = MCPServer(
    name="asr-jetson",
    version="0.1.0",
    instructions=(
        "Speech-to-text. Call transcribe() with a base64 WAV of one "
        "VAD-bounded user utterance; returns the transcript text."
    ),
)


def _wav_b64_to_pcm(audio_wav_b64: str) -> tuple[bytes, int]:
    raw = base64.b64decode(audio_wav_b64)
    with wave.open(io.BytesIO(raw), "rb") as f:
        rate = f.getframerate()
        channels = f.getnchannels()
        width = f.getsampwidth()
        if width != 2 or channels != 1:
            raise ValueError(f"expected 16-bit mono WAV, got {width*8}-bit x{channels}")
        return f.readframes(f.getnframes()), rate


@server.tool(
    name="transcribe",
    description=(
        "Transcribe one complete user utterance (VAD-bounded) to text. "
        "Input: base64-encoded 16-bit mono WAV. Returns the transcript."
    ),
)
def transcribe(audio_wav_b64: str) -> dict:
    import riva.client
    from riva.client.proto.riva_audio_pb2 import AudioEncoding

    pcm, rate = _wav_b64_to_pcm(audio_wav_b64)
    if not pcm:
        return {"text": "", "error": None}

    auth = riva.client.Auth(uri=ASR_SERVER)
    service = riva.client.ASRService(auth)
    config = riva.client.RecognitionConfig(
        encoding=AudioEncoding.LINEAR_PCM,
        language_code="en-US",
        max_alternatives=1,
        enable_automatic_punctuation=True,
        sample_rate_hertz=rate,
        audio_channel_count=1,
    )
    t0 = time.time()
    response = service.offline_recognize(pcm, config, future=False)
    elapsed_ms = (time.time() - t0) * 1000

    texts = []
    for r in getattr(response, "results", []):
        if r.alternatives:
            texts.append(r.alternatives[0].transcript)
    text = " ".join(texts).strip()
    return {"text": text, "asr_ms": round(elapsed_ms), "error": None}


if __name__ == "__main__":
    server.run("stdio")
