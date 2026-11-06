"""VAD-segmented transcription with a local whisper.cpp server (Jetson).

Whisper is a plain encoder-decoder ASR: it returns text only. Unlike
Qwen2-Audio it is not a speech-LLM and cannot follow instructions, so no prompt
is sent beyond a language hint.

Server contract (whisper.cpp `whisper-server`):
  POST {base}/inference            multipart file=@audio.wav, response_format=json
  -> {"text": "..."}
A newer build may expose /v1/audio/transcriptions; set WHISPER_ASR_PATH to use
it (the body is the same multipart form).

Streaming mode (WHISPER_STREAM=1, default): while the user is STILL SPEAKING,
the service transcribes a rolling partial buffer every WHISPER_PARTIAL_INTERVAL_S
seconds (~0.9 s GPU each, fully hidden behind speech). When VAD stops, if a
partial finished within WHISPER_PROMOTE_MAX_AGE_S of the stop, it is promoted
to the final transcript immediately (near-zero post-speech ASR wait); the full
segment is still transcribed in the background and the comparison is recorded
in diagnostics (asr_whisper_verify) — the promoted text is what the pipeline
uses, so accuracy is measured honestly per turn.
"""

import asyncio
from collections import deque
from contextlib import nullcontext
import io
import os
import time
import wave

import httpx
from pipecat.frames.frames import (ErrorFrame, InterimTranscriptionFrame,
                                   TranscriptionFrame)
from pipecat.services.stt_service import SegmentedSTTService, STTSettings
from pipecat.utils.time import time_now_iso8601


class WhisperSTTService(SegmentedSTTService):
    def __init__(self, *, timing_observer=None, client=None, **kwargs):
        self.model_name = os.getenv("WHISPER_ASR_MODEL", "whisper-large-v3-turbo")
        self.base_url = os.getenv("WHISPER_ASR_BASE", "http://192.168.5.11:8090").rstrip("/")
        self.path = os.getenv("WHISPER_ASR_PATH", "/inference")
        self.language = os.getenv("WHISPER_ASR_LANG", "en")
        self.streaming = os.getenv("WHISPER_STREAM", "1").strip() == "1"
        self.promote = os.getenv("WHISPER_PROMOTE", "0").strip() == "1"
        self.partial_interval_s = float(os.getenv("WHISPER_PARTIAL_INTERVAL_S", "0.8"))
        self.promote_max_age_s = float(os.getenv("WHISPER_PROMOTE_MAX_AGE_S", "1.0"))
        trailing = float(os.getenv("WHISPER_TRAILING_SILENCE_SECS", "0.15"))
        kwargs.setdefault("trailing_silence_secs", trailing)
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
        # streaming-partial state
        self._partial_queue = asyncio.Queue()
        self._partial_task = None
        self._last_partial_text = None
        self._last_partial_at = 0.0
        self._partial_attempts = 0

    def can_generate_metrics(self):
        return True

    async def cleanup(self):
        await self.client.aclose()
        await super().cleanup()

    async def _handle_user_started_speaking(self, frame):
        self._reset_partials()
        if self.streaming and self.is_usable:
            self._partial_task = asyncio.create_task(self._partial_loop())
        await super()._handle_user_started_speaking(frame)

    async def _handle_user_stopped_speaking(self, frame):
        if self._partial_task is not None and not self._partial_task.done():
            self._partial_task.cancel()
            self._partial_task = None
        if self.is_usable:
            self._segment_id += 1
            self._segment_metadata.append((self._segment_id,
                self.timing.turn if self.timing else None, time.monotonic()))
        await super()._handle_user_stopped_speaking(frame)

    def _reset_partials(self):
        self._last_partial_text = None
        self._last_partial_at = 0.0
        self._partial_attempts = 0
        self._partial_queue = asyncio.Queue()

    def push_partial_audio(self, pcm_bytes):
        """Called from SpecTap with raw PCM16 mono 16 kHz chunks during speech."""
        if not self.streaming:
            return
        try:
            self._partial_queue.put_nowait(pcm_bytes)
        except Exception:
            pass

    def record(self, event, turn, **fields):
        if self.timing:
            self.timing.record(event, turn=turn, asr_backend="whisper",
                               asr_model=self.model_name, **fields)

    def _transcript(self, text, segment_id):
        frame = TranscriptionFrame(text, self._user_id, time_now_iso8601(), finalized=True)
        if segment_id is not None:
            frame.metadata["whisper_segment_id"] = segment_id
        return frame

    async def _transcribe_wav(self, wav_bytes):
        """POST a WAV to the whisper server, return stripped text."""
        resp = await self.client.post(
            self.base_url + self.path,
            files={"file": ("partial.wav", wav_bytes, "audio/wav")},
            data={"response_format": "json", "temperature": "0",
                  "language": self.language, "model": self.model_name},
        )
        resp.raise_for_status()
        payload = resp.json()
        return (payload.get("text") or "").strip() if isinstance(payload, dict) else ""

    async def _partial_loop(self):
        """Rolling-partial transcription while the user speaks (~0.9 s GPU each)."""
        buffer = bytearray()
        last_done = 0.0
        try:
            while True:
                chunk = await self._partial_queue.get()
                if chunk is None:
                    return
                buffer.extend(chunk)
                audio_s = len(buffer) / (2 * 16000)
                if audio_s < 1.2 or audio_s - last_done < self.partial_interval_s:
                    continue
                last_done = audio_s
                if audio_s > 12:
                    buffer = buffer[-int(12 * 2 * 16000):]
                buf = io.BytesIO()
                with wave.open(buf, "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                    w.writeframes(bytes(buffer))
                started = time.monotonic()
                try:
                    text = await self._transcribe_wav(buf.getvalue())
                    request_s = time.monotonic() - started
                    self._partial_attempts += 1
                    words = len(text.split())
                    if words >= 2:
                        self._last_partial_text = text
                        self._last_partial_at = time.monotonic()
                        self.record("asr_whisper_partial", self.timing.turn if self.timing else None,
                                    request_s=request_s, words=words, audio_s=audio_s)
                        await self.push_frame(InterimTranscriptionFrame(
                            text, self._user_id, time_now_iso8601()))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.record("asr_whisper_partial_error",
                                self.timing.turn if self.timing else None,
                                error=type(exc).__name__, request_s=time.monotonic() - started)
        except asyncio.CancelledError:
            pass

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

            # Streaming promotion: a fresh partial becomes the transcript now.
            partial_age = time.monotonic() - self._last_partial_at
            if (self.streaming and self.promote and self._last_partial_text
                    and partial_age <= self.promote_max_age_s):
                text = self._last_partial_text
                self.record("asr_whisper_promoted", turn, request_s=0.0,
                            partial_age_s=round(partial_age, 3), chars=len(text),
                            partial_attempts=self._partial_attempts, **common)
                yield self._transcript(text, segment_id)
                # Background verification with the full segment; recorded only.
                asyncio.create_task(self._verify_full(audio, turn, text, common))
                return

            scope = (self.diagnostics.span("asr_whisper_http", turn=turn,
                     segment_id=segment_id, audio_s=audio_s)
                     if self.diagnostics else nullcontext())
            with scope:
                text = await self._transcribe_wav(audio)
            if not text:
                self.record("asr_whisper_no_speech", turn, request_s=time.monotonic() - started, **common)
                return
            self.record("asr_whisper_complete", turn, request_s=time.monotonic() - started,
                        chars=len(text), **common)
            yield self._transcript(text, segment_id)
        except asyncio.CancelledError:
            self.record("asr_whisper_cancelled", turn, request_s=time.monotonic() - started, **common)
            raise
        except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError,
                wave.Error, EOFError) as exc:
            self.record("asr_whisper_failure", turn, request_s=time.monotonic() - started,
                        error=type(exc).__name__, **common)
            yield ErrorFrame(error=f"Whisper ASR failed ({type(exc).__name__})")

    async def _verify_full(self, audio, turn, promoted_text, common):
        """Full-segment transcription after promotion; comparison is recorded."""
        started = time.monotonic()
        try:
            full_text = await self._transcribe_wav(audio)
            self.record("asr_whisper_verify", turn,
                        request_s=time.monotonic() - started,
                        promoted_chars=len(promoted_text),
                        full_chars=len(full_text or ""),
                        match=(full_text or "").strip() == promoted_text,
                        promoted=promoted_text, full=full_text, **common)
        except Exception as exc:
            self.record("asr_whisper_verify_error", turn,
                        error=type(exc).__name__, request_s=time.monotonic() - started, **common)
