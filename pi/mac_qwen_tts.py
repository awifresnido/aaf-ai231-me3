"""Pipecat adapter for the MacBook MLX Qwen3 CustomVoice service.

Two transports, selected by MAC_TTS_STREAM:

* MAC_TTS_STREAM=0 (default, previous trial): POST /speak returns one complete
  WAV; the adapter can only emit audio after generation finishes.
* MAC_TTS_STREAM=1: POST /speak?stream=1 returns chunked PCM16LE (24 kHz mono)
  and each HTTP chunk is forwarded to the pipeline as it arrives, so first audio
  tracks the codec's first flush instead of the whole utterance.

Timing event names are identical in both modes (tts_mac_first_audio,
tts_mac_complete, tts_mac_cancelled, tts_mac_failure) so the existing
summariser/comparison tooling keeps working; streaming adds `stream: true`
and `http_headers_s` to the records.
"""

import asyncio
from contextlib import nullcontext
import io
import os
import time
import wave

import httpx
from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame
from pipecat.services.tts_service import TTSService, TTSSettings

SAMPLE_RATE = 24000


class MacQwenTTSService(TTSService):
    def __init__(self, *, timing_observer=None, client=None, **kwargs):
        self.model_name = "qwen3-tts-customvoice-mlx-4bit"
        self.voice_name = os.getenv("MAC_TTS_VOICE", "Aiden")
        self.base_url = os.getenv("MAC_TTS_BASE", "http://127.0.0.1:18099").rstrip("/")
        self.stream = os.getenv("MAC_TTS_STREAM", "0").strip() == "1"
        self.interval = os.getenv("MAC_TTS_STREAM_INTERVAL", "").strip()
        self.timing = timing_observer
        self.diagnostics = getattr(timing_observer, "diagnostics", None)
        timeout_s = float(os.getenv("MAC_TTS_TIMEOUT_SECS", "45"))
        # A whole-WAV response needs the audio context held open until the
        # bounded request finishes; streaming keeps the same bound.
        super().__init__(sample_rate=SAMPLE_RATE, push_start_frame=True,
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

    def _payload(self, text):
        body = {"text": text, "voice": self.voice_name, "lang": "English"}
        url = self.base_url + "/speak"
        if self.stream:
            url += "?stream=1"
            if self.interval:
                url += "&interval=" + self.interval
        return url, body

    async def run_tts(self, text, context_id):
        if not text.strip():
            return
        if self.stream:
            async for frame in self._run_tts_stream(text, context_id):
                yield frame
            return
        async for frame in self._run_tts_whole(text, context_id):
            yield frame

    async def _run_tts_whole(self, text, context_id):
        turn = self.timing.turn if self.timing else None
        started = time.monotonic()
        scope = (self.diagnostics.span("tts_mac_http", turn=turn,
                 context_id=context_id, chars=len(text)) if self.diagnostics else nullcontext())
        try:
            await self.start_ttfb_metrics()
            with scope:
                url, body = self._payload(text)
                response = await self.client.post(url, json=body)
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
                        first_audio_s=first_audio_s, sample_rate=rate, chars=len(text),
                        stream=False)
            for offset in range(0, len(pcm), rate // 50 * 2):
                yield TTSAudioRawFrame(pcm[offset:offset + rate // 50 * 2], rate, 1,
                                       context_id=context_id)
            self.record("tts_mac_complete", turn, context_id=context_id,
                        request_s=time.monotonic() - started, first_audio_s=first_audio_s,
                        audio_bytes=len(pcm), audio_s=len(pcm) / (rate * 2), chars=len(text),
                        stream=False)
        except asyncio.CancelledError:
            self.record("tts_mac_cancelled", turn, context_id=context_id,
                        request_s=time.monotonic() - started, stream=False)
            raise
        except (httpx.HTTPError, ValueError, OSError, EOFError) as exc:
            self.record("tts_mac_failure", turn, context_id=context_id,
                        request_s=time.monotonic() - started,
                        error=type(exc).__name__, stream=False)
            yield ErrorFrame(error=f"Mac Qwen TTS failed ({type(exc).__name__})")

    async def _run_tts_stream(self, text, context_id):
        turn = self.timing.turn if self.timing else None
        started = time.monotonic()
        audio_bytes = 0
        first_audio_s = None
        rate = SAMPLE_RATE
        scope = (self.diagnostics.span("tts_mac_http", turn=turn, context_id=context_id,
                 chars=len(text)) if self.diagnostics else nullcontext())
        try:
            await self.start_ttfb_metrics()
            with scope:
                url, body = self._payload(text)
                async with self.client.stream("POST", url, json=body) as response:
                    response.raise_for_status()
                    headers_s = time.monotonic() - started
                    media = response.headers.get("content-type", "").split(";", 1)[0].strip()
                    if media not in {"audio/pcm", "audio/raw", "application/octet-stream"}:
                        raise ValueError("Mac Qwen TTS returned an unexpected audio format")
                    try:
                        rate = int(response.headers.get("x-sample-rate", SAMPLE_RATE))
                    except ValueError:
                        rate = SAMPLE_RATE
                    await self.start_tts_usage_metrics(text)
                    pending = bytearray()
                    async for chunk in response.aiter_bytes(960):
                        pending.extend(chunk)
                        size = len(pending) // 2 * 2
                        if not size:
                            continue
                        pcm = bytes(pending[:size])
                        del pending[:size]
                        if first_audio_s is None:
                            first_audio_s = time.monotonic() - started
                            await self.stop_ttfb_metrics()
                            self.record("tts_mac_first_audio", turn, context_id=context_id,
                                        first_audio_s=first_audio_s, http_headers_s=headers_s,
                                        sample_rate=rate, chars=len(text), stream=True)
                        audio_bytes += len(pcm)
                        yield TTSAudioRawFrame(pcm, rate, 1, context_id=context_id)
                    if pending or not audio_bytes:
                        raise ValueError("Mac Qwen TTS returned empty or incomplete PCM")
            self.record("tts_mac_complete", turn, context_id=context_id,
                        request_s=time.monotonic() - started, first_audio_s=first_audio_s,
                        audio_bytes=audio_bytes, audio_s=audio_bytes / (rate * 2),
                        chars=len(text), stream=True)
        except asyncio.CancelledError:
            self.record("tts_mac_cancelled", turn, context_id=context_id,
                        request_s=time.monotonic() - started, audio_bytes=audio_bytes,
                        stream=True)
            raise
        except (httpx.HTTPError, ValueError, OSError) as exc:
            self.record("tts_mac_failure", turn, context_id=context_id,
                        request_s=time.monotonic() - started, audio_bytes=audio_bytes,
                        error=type(exc).__name__, stream=True)
            yield ErrorFrame(error=f"Mac Qwen TTS failed ({type(exc).__name__})")
