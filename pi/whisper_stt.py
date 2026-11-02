"""VAD-segmented transcription with a local whisper.cpp server (Jetson).

Whisper is a plain encoder-decoder ASR: it returns text only. Unlike
Qwen2-Audio it is not a speech-LLM and cannot follow instructions, so no prompt
is sent beyond a language hint.

Server contract (whisper.cpp `whisper-server`):
  POST {base}/inference            multipart file=@audio.wav, response_format=json
  -> {"text": "..."}
A newer build may expose /v1/audio/transcriptions; set WHISPER_ASR_PATH to use
it (the body is the same multipart form).
"""

import asyncio
from collections import deque
from contextlib import nullcontext
import io
import os
import time
import wave

import httpx
from pipecat.frames.frames import ErrorFrame, TranscriptionFrame
from pipecat.services.stt_service import SegmentedSTTService, STTSettings
from pipecat.utils.time import time_now_iso8601


class WhisperSTTService(SegmentedSTTService):
    def __init__(self, *, timing_observer=None, client=None, **kwargs):
        self.model_name = os.getenv("WHISPER_ASR_MODEL", "whisper-large-v3-turbo")
        self.base_url = os.getenv("WHISPER_ASR_BASE", "http://192.168.5.11:8090").rstrip("/")
        self.path = os.getenv("WHISPER_ASR_PATH", "/inference")
        self.language = os.getenv("WHISPER_ASR_LANG", "en")
        super().__init__(sample_rate=16000,
                         settings=STTSettings(model=self.model_name, language=self.language),
                         **kwargs)
        self.client = client if client is not None else httpx.AsyncClient(
            timeout=httpx.Timeout(float(os.getenv("WHISPER_ASR_TIMEOUT_SECS", "30")), connect=5),
            trust_env=False)
        self.timing = timing_observer
        self.diagnostics = getattr(timing_observer, "diagnostics", None)
        self._segment_metadata = deque()
        self._segment_id = 0

    def can_generate_metrics(self):
        return True

    async def cleanup(self):
        await self.client.aclose()
        await super().cleanup()

    async def _handle_user_stopped_speaking(self, frame):
        if self.is_usable:
            self._segment_id += 1
            self._segment_metadata.append((self._segment_id,
                self.timing.turn if self.timing else None, time.monotonic()))
        await super()._handle_user_stopped_speaking(frame)

    def record(self, event, turn, **fields):
        if self.timing:
            self.timing.record(event, turn=turn, asr_backend="whisper",
                               asr_model=self.model_name, **fields)

    async def run_stt(self, audio):
        started = time.monotonic()
        segment_id, turn, queued_at = (self._segment_metadata.popleft()
            if self._segment_metadata else
            (None, self.timing.turn if self.timing else None, started))
        common = dict(segment_id=segment_id, queue_wait_s=started - queued_at)
        try:
            with wave.open(io.BytesIO(audio), "rb") as wav:
                if wav.getframerate() != 16000 or wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                    raise ValueError("Whisper ASR requires mono PCM16 WAV at 16 kHz")
                audio_s = wav.getnframes() / wav.getframerate()
            if not 0 < audio_s <= 35:
                raise ValueError("Whisper ASR segment must be at most 35 seconds")
            common.update(audio_s=audio_s, audio_bytes=len(audio))
            self.record("asr_whisper_start", turn, **common)
            scope = (self.diagnostics.span("asr_whisper_http", turn=turn,
                     segment_id=segment_id, audio_s=audio_s)
                     if self.diagnostics else nullcontext())
            with scope:
                response = await self.client.post(
                    self.base_url + self.path,
                    files={"file": ("segment.wav", audio, "audio/wav")},
                    data={"response_format": "json", "temperature": "0",
                          "language": self.language, "model": self.model_name},
                )
                response.raise_for_status()
                payload = response.json()
            text = (payload.get("text") or "").strip() if isinstance(payload, dict) else ""
            if not text:
                self.record("asr_whisper_no_speech", turn, request_s=time.monotonic() - started, **common)
                return
            self.record("asr_whisper_complete", turn, request_s=time.monotonic() - started,
                        chars=len(text), **common)
            yield TranscriptionFrame(text, self._user_id, time_now_iso8601(), finalized=True)
        except asyncio.CancelledError:
            self.record("asr_whisper_cancelled", turn, request_s=time.monotonic() - started, **common)
            raise
        except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError,
                wave.Error, EOFError) as exc:
            self.record("asr_whisper_failure", turn, request_s=time.monotonic() - started,
                        error=type(exc).__name__, **common)
            yield ErrorFrame(error=f"Whisper ASR failed ({type(exc).__name__})")
