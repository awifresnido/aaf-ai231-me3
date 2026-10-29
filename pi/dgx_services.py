"""DGX speech services (vLLM HTTP APIs) for the Pi voice agent.

DGXSTTService: buffers mic audio while the user speaks; when Pipecat signals
the user stopped (VAD), it POSTs the utterance as base64 WAV to Qwen2-Audio
(chat/completions with input_audio) and emits a TranscriptionFrame.

Echo suppression: while the bot is speaking (BotStartedSpeakingFrame..Bot
StoppedSpeakingFrame), the buffer is cleared and mic frames are NOT buffered.
This prevents the bot transcribing its own TTS output picked up by the mic
(acoustic feedback loop). Refusal-style model responses are also dropped.

DGXTTSService: per-sentence synthesis via /v1/audio/speech (Qwen3-TTS),
emitting OutputAudioRawFrame. Non-streaming: first audio waits for the full
sentence (documented draft limitation).

Both are Pipecat services, so the rest of the pipeline (VAD, aggregators,
interruption) is unchanged.
"""

import base64
import io
import os
import re
import time
import wave
from typing import AsyncGenerator

import httpx
from loguru import logger

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    ErrorFrame,
    Frame,
    OutputAudioRawFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

DGX_ASR_BASE = os.getenv("DGX_ASR_BASE", "http://127.0.0.1:18000")
DGX_TTS_BASE = os.getenv("DGX_TTS_BASE", "http://127.0.0.1:18001")
DGX_API_KEY = os.getenv("DGX_API_KEY", "")
ASR_MODEL = os.getenv("DGX_ASR_MODEL", "Qwen/Qwen2-Audio-7B-Instruct")
TTS_MODEL = os.getenv("DGX_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
TTS_VOICE = os.getenv("DGX_TTS_VOICE", "vivian")

IN_RATE = 16000  # mic/ASR rate
OUT_RATE = 24000  # Qwen3-TTS output rate

TRANSCRIBE_PROMPT = (
    "Transcribe the audio exactly. Output only the transcription text, "
    "nothing else."
)

# Qwen2-Audio sometimes answers conversationally instead of transcribing
# (especially on silence/noise). These responses must never become user turns.
_REFUSAL_PATTERNS = [
    re.compile(r"^i'?m sorry", re.I),
    re.compile(r"^sorry", re.I),
    re.compile(r"^i (?:cannot|can't|am unable)", re.I),
    re.compile(r"cannot transcribe", re.I),
    re.compile(r"provide (?:me )?(?:the |with the )?(?:audio|file|link)", re.I),
]
# Qwen2-Audio wraps output like: The transcription of the audio is: 'xxx'
_WRAPPER_RE = re.compile(
    r"^(?:the transcription(?: of the audio)?(?: is)?[:\s]*|transcription[:\s]*)['\"]?(.*?)['\"]?[. ]*$",
    re.I,
)


def _pcm_to_wav_b64(pcm: bytes, rate: int = IN_RATE) -> str:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return base64.b64encode(buf.getvalue()).decode()


def _is_refusal(text: str) -> bool:
    t = text.strip()
    return any(p.search(t) for p in _REFUSAL_PATTERNS)


def _unwrap(text: str) -> str:
    m = _WRAPPER_RE.match(text.strip())
    return m.group(1).strip() if m else text.strip()


class DGXSTTService(FrameProcessor):
    """Utterance-buffered ASR via Qwen2-Audio on the DGX, with echo suppression."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._buffer = bytearray()
        self._bot_speaking = False
        self._client = httpx.AsyncClient(timeout=60)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, BotStartedSpeakingFrame):
            # The bot is about to speak: the mic will pick up its output
            # (acoustic echo). Reset capture so we never transcribe it.
            self._bot_speaking = True
            self._buffer.clear()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
        elif isinstance(frame, UserStoppedSpeakingFrame):
            pcm = bytes(self._buffer)
            self._buffer.clear()
            if not self._bot_speaking and len(pcm) > IN_RATE // 2:
                await self._transcribe(pcm)
        elif not self._bot_speaking:
            audio = getattr(frame, "audio", None)
            if audio and getattr(frame, "sample_rate", 0) == IN_RATE:
                # Buffer only while the bot is silent. Cap at ~20 s.
                self._buffer.extend(audio)
                if len(self._buffer) > IN_RATE * 2 * 20:
                    del self._buffer[: IN_RATE * 2 * 10]

        await self.push_frame(frame, direction)

    async def _transcribe(self, pcm: bytes):
        t0 = time.monotonic()
        try:
            resp = await self._client.post(
                f"{DGX_ASR_BASE}/v1/chat/completions",
                headers=_headers(),
                json={
                    "model": ASR_MODEL,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": TRANSCRIBE_PROMPT},
                            {"type": "input_audio",
                             "input_audio": {"data": _pcm_to_wav_b64(pcm), "format": "wav"}},
                        ],
                    }],
                    "max_tokens": 200,
                },
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            text = _unwrap(text)
            dt = time.monotonic() - t0
            if _is_refusal(text):
                # Silence/noise or leaked echo: drop it, do not create a turn.
                logger.info(f"DGXSTT: {dt:.2f}s -> refusal dropped ({text[:60]!r})")
                return
            logger.info(f"DGXSTT: {dt:.2f}s -> {text!r}")
            if text:
                await self.push_frame(TranscriptionFrame(text, "dgx-user", ""))
        except Exception as e:  # noqa: BLE001
            logger.error(f"DGXSTT error: {e}")
            await self.push_frame(ErrorFrame(f"DGX ASR error: {e}"))


class DGXTTSService(FrameProcessor):
    """Per-utterance TTS via Qwen3-TTS on the DGX."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._client = httpx.AsyncClient(timeout=120)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TTSSpeakFrame) and frame.text.strip():
            await self._synthesize(frame.text.strip())

        await self.push_frame(frame, direction)

    async def _synthesize(self, text: str):
        t0 = time.monotonic()
        try:
            resp = await self._client.post(
                f"{DGX_TTS_BASE}/v1/audio/speech",
                headers=_headers(),
                json={
                    "model": TTS_MODEL,
                    "input": text,
                    "voice": TTS_VOICE,
                    "response_format": "wav",
                },
            )
            resp.raise_for_status()
            pcm = _wav_pcm(resp.content)
            dt = time.monotonic() - t0
            logger.info(f"DGXTTS: {dt:.2f}s, {len(pcm)} bytes pcm for {len(text)} chars")
            chunk = OUT_RATE * 2 // 10  # 100 ms
            for i in range(0, len(pcm), chunk):
                await self.push_frame(OutputAudioRawFrame(
                    pcm[i:i + chunk], sample_rate=OUT_RATE, num_channels=1))
        except Exception as e:  # noqa: BLE001
            logger.error(f"DGXTTS error: {e}")
            await self.push_frame(ErrorFrame(f"DGX TTS error: {e}"))


def _headers():
    return {"Authorization": f"Bearer {DGX_API_KEY}", "Content-Type": "application/json"}


def _wav_pcm(data: bytes) -> bytes:
    w = wave.open(io.BytesIO(data))
    return w.readframes(w.getnframes())
