"""Pipecat adapter for the MacBook MLX Qwen3 CustomVoice /speak service."""

import asyncio
from contextlib import nullcontext
import io
import os
import time
import wave

import httpx
from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame
from pipecat.services.tts_service import TTSService, TTSSettings


class MacQwenTTSService(TTSService):
    def __init__(self, *, timing_observer=None, client=None, **kwargs):
        self.model_name = "qwen3-tts-customvoice-mlx-4bit"
        self.voice_name = os.getenv("MAC_TTS_VOICE", "Aiden")
        self.base_url = os.getenv("MAC_TTS_BASE", "http://127.0.0.1:18099").rstrip("/")
        self.timing = timing_observer
        self.diagnostics = getattr(timing_observer, "diagnostics", None)
        timeout_s = float(os.getenv("MAC_TTS_TIMEOUT_SECS", "45"))
        # The Mac service returns one complete WAV after generation. Keep the
        # audio context open until the bounded HTTP request can finish.
        super().__init__(sample_rate=24000, push_start_frame=True,
                         push_stop_frames=True, stop_frame_timeout_s=timeout_s + 2,
                         settings=TTSSettings(model=self.model_name, voice=self.voice_name, language=None),
                         **kwargs)
        self.client = client if client is not None else httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s, connect=5),
            trust_env=False)

    def can_generate_metrics(self):
        return True

    def record(self, event, turn, **fields):
        if self.timing:
            self.timing.record(event, turn=turn, tts_backend="mac_qwen",
                               tts_model=self.model_name, **fields)

    async def cleanup(self):
        await self.client.aclose()
        await super().cleanup()

    async def run_tts(self, text, context_id):
        if not text.strip():
            return
        turn = self.timing.turn if self.timing else None
        started = time.monotonic()
        scope = (self.diagnostics.span("tts_mac_http", turn=turn,
                 context_id=context_id, chars=len(text)) if self.diagnostics else nullcontext())
        try:
            await self.start_ttfb_metrics()
            with scope:
                response = await self.client.post(self.base_url + "/speak",
                    json={"text": text, "voice": self.voice_name, "lang": "English"})
                response.raise_for_status()
                if response.headers.get("content-type", "").split(";", 1)[0] != "audio/wav":
                    raise ValueError("Mac Qwen TTS returned non-WAV audio")
                with wave.open(io.BytesIO(response.content), "rb") as wav:
                    if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                        raise ValueError("Mac Qwen TTS requires mono PCM16 WAV")
                    rate = wav.getframerate()
                    if not 8000 <= rate <= 48000:
                        raise ValueError("Mac Qwen TTS returned invalid sample rate")
                    pcm = wav.readframes(wav.getnframes())
                if not pcm:
                    raise ValueError("Mac Qwen TTS returned empty WAV")
            first_audio_s = time.monotonic() - started
            await self.stop_ttfb_metrics()
            await self.start_tts_usage_metrics(text)
            self.record("tts_mac_first_audio", turn, context_id=context_id,
                        first_audio_s=first_audio_s, sample_rate=rate, chars=len(text))
            for offset in range(0, len(pcm), rate // 50 * 2):
                yield TTSAudioRawFrame(pcm[offset:offset + rate // 50 * 2], rate, 1,
                                       context_id=context_id)
            self.record("tts_mac_complete", turn, context_id=context_id,
                        request_s=time.monotonic()-started, first_audio_s=first_audio_s,
                        audio_bytes=len(pcm), audio_s=len(pcm)/(rate*2), chars=len(text))
        except asyncio.CancelledError:
            self.record("tts_mac_cancelled", turn, context_id=context_id,
                        request_s=time.monotonic()-started)
            raise
        except (httpx.HTTPError, ValueError, OSError, wave.Error, EOFError) as exc:
            self.record("tts_mac_failure", turn, context_id=context_id,
                        request_s=time.monotonic()-started, error=type(exc).__name__)
            yield ErrorFrame(error=f"Mac Qwen TTS failed ({type(exc).__name__})")
