"""DGX Qwen3 CustomVoice streaming PCM in Pipecat's normal TTS lifecycle."""

import asyncio
from contextlib import nullcontext
import os
import time

import httpx
from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame
from pipecat.services.tts_service import TTSService, TTSSettings


QWEN_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
SAMPLE_RATE = 24000


class QwenTTSService(TTSService):
    """Handle both direct speak frames and aggregated GLM text via TTSService."""

    def __init__(self, *, timing_observer=None, client=None, **kwargs):
        self.model_name = os.getenv("DGX_TTS_MODEL", QWEN_MODEL)
        self.voice_name = os.getenv("DGX_TTS_VOICE", "vivian")
        self.base_url = os.getenv("DGX_TTS_BASE", "http://127.0.0.1:18001").rstrip("/")
        self.api_key = os.getenv("DGX_API_KEY", "").strip()
        if not self.api_key:
            raise ValueError("DGX_API_KEY is required for Qwen TTS")
        super().__init__(sample_rate=SAMPLE_RATE, push_start_frame=True,
                         push_stop_frames=True,
                         settings=TTSSettings(model=self.model_name, voice=self.voice_name, language=None), **kwargs)
        self.client = client if client is not None else httpx.AsyncClient(
            timeout=httpx.Timeout(float(os.getenv("DGX_TTS_TIMEOUT_SECS", "45")), connect=5),
            trust_env=False)
        self.timing = timing_observer
        self.diagnostics = getattr(timing_observer, "diagnostics", None)

    def can_generate_metrics(self):
        return True

    def record(self, event, turn, **fields):
        if self.timing:
            self.timing.record(event, turn=turn, tts_backend="dgx_qwen",
                               tts_model=self.model_name, **fields)

    async def cleanup(self):
        await self.client.aclose()
        await super().cleanup()

    async def run_tts(self, text, context_id):
        if not text.strip():
            return
        turn = self.timing.turn if self.timing else None
        started = time.monotonic()
        audio_bytes = 0
        first_audio_s = None
        scope = self.diagnostics.span("tts_qwen_http", turn=turn,
                    context_id=context_id, chars=len(text)) if self.diagnostics else nullcontext()
        try:
            await self.start_ttfb_metrics()
            with scope:
                async with self.client.stream("POST", self.base_url + "/v1/audio/speech",
                    headers={"Authorization": "Bearer " + self.api_key},
                    json={"model": self.model_name, "input": text, "voice": self.voice_name,
                          "task_type": "CustomVoice", "language": "English",
                          "response_format": "pcm", "sample_rate": SAMPLE_RATE,
                          "stream": True, "stream_format": "audio"}) as response:
                    response.raise_for_status()
                    headers_s = time.monotonic() - started
                    media = response.headers.get("content-type", "").split(";", 1)[0].strip()
                    if media not in {"audio/pcm", "audio/raw", "application/octet-stream"}:
                        raise ValueError("Qwen returned an unexpected audio format")
                    await self.start_tts_usage_metrics(text)
                    # 20 ms of mono PCM16; buffer alignment across HTTP chunks.
                    pending = bytearray()
                    async for chunk in response.aiter_bytes(960):
                        pending.extend(chunk)
                        size = len(pending) // 2 * 2
                        if not size:
                            continue
                        pcm = bytes(pending[:size])
                        del pending[:size]
                        if first_audio_s is None:
                            if pcm.startswith(b"RIFF"):
                                raise ValueError("Qwen returned WAV instead of raw PCM")
                            first_audio_s = time.monotonic() - started
                            await self.stop_ttfb_metrics()
                            self.record("tts_qwen_first_audio", turn, context_id=context_id,
                                        first_audio_s=first_audio_s, http_headers_s=headers_s,
                                        sample_rate=SAMPLE_RATE, chars=len(text))
                        audio_bytes += len(pcm)
                        yield TTSAudioRawFrame(pcm, SAMPLE_RATE, 1, context_id=context_id)
                    if pending or not audio_bytes:
                        raise ValueError("Qwen returned empty or incomplete PCM")
            self.record("tts_qwen_complete", turn, context_id=context_id,
                        request_s=time.monotonic()-started, first_audio_s=first_audio_s,
                        audio_bytes=audio_bytes, audio_s=audio_bytes/(SAMPLE_RATE*2), chars=len(text))
        except asyncio.CancelledError:
            self.record("tts_qwen_cancelled", turn, context_id=context_id,
                        request_s=time.monotonic()-started, audio_bytes=audio_bytes)
            raise
        except (httpx.HTTPError, ValueError, OSError) as exc:
            self.record("tts_qwen_failure", turn, context_id=context_id,
                        request_s=time.monotonic()-started, audio_bytes=audio_bytes,
                        error=type(exc).__name__)
            # Do not retry or switch voices after audio may already have played.
            yield ErrorFrame(error=f"DGX Qwen TTS failed ({type(exc).__name__})")
