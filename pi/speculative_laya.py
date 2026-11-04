"""Speculative Laya classification during speech (pre-final transcript).

Goal: hide the ~1.4 s ASR latency for local-tool commands. While the user is
STILL SPEAKING (VAD start), we transcribe the partial audio and run Laya on the
partial transcript. When VAD stop arrives and the final transcript is ready, the
router checks whether the speculation is still valid:

  - If the final transcript's group == speculated group and the gate accepted
    both, tier-2 dispatch starts with zero classifier wait.
  - If they disagree (user added words that changed intent), the router falls
    back to the normal classify path (one extra 0.11 s — same as today).
  - If speculation never produced an accepted group (partial too short/ambiguous),
    the router behaves exactly as it does today.

Safety: a speculation is ONLY a routing hint; the argument grammar (tier 2)
still runs on the FINAL transcript, so a wrongly-specced group can't fire a
tool with wrong arguments — the grammar would just not match and the turn
escalates/falls back the same as today.

Cost model: whisper on a partial (~1 s of speech) takes ~0.3-0.4 s on the
Jetson GPU vs 0.9 s for a full utterance; Laya is 0.1 s. Both run on the
Jetson while the user is still talking, i.e. fully hidden behind speech time.

Toggle: SPECULATIVE_LAYA=1 (default on), SPEC_LAYA_MIN_AUDIO_S (default 1.2).
"""
import asyncio
import io
import os
import time
import wave

import httpx
from loguru import logger


class SpeculativeLaya:
    """Runs partial-transcript Laya classification while the user speaks."""

    def __init__(self, whisper_base=None, laya_url=None, *, timing=None):
        self.whisper_base = (whisper_base or os.getenv("WHISPER_ASR_BASE",
                             "http://192.168.5.11:8090")).rstrip("/")
        self.laya_url = (laya_url or os.getenv("LAYA_ROUTER_URL",
                         "http://192.168.5.11:8083")).rstrip("/")
        self.min_audio_s = float(os.getenv("SPEC_LAYA_MIN_AUDIO_S", "1.2"))
        self.max_audio_s = float(os.getenv("SPEC_LAYA_MAX_AUDIO_S", "12"))
        self.enabled = os.getenv("SPECULATIVE_LAYA", "1").strip() == "1"
        self.timing = timing
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(5, connect=2), trust_env=False)
        # per-turn speculation state
        self._spec_turn = None
        self._task = None
        self._spec_group = None
        self._spec_conf = 0.0
        self._spec_clf_s = 0.0
        self._spec_whisper_s = 0.0
        self._spec_audio_s = 0.0
        self._spec_attempts = 0
        self._audio_queue = asyncio.Queue()

    # ---------------------------------------------------------------- events
    def on_user_started_speaking(self, turn):
        """VAD start: begin collecting; first speculation fires at min_audio_s."""
        self._reset()
        if not self.enabled:
            return
        self._spec_turn = turn
        self._task = asyncio.create_task(self._speculate_loop())

    def on_user_stopped_speaking(self, turn):
        """VAD stop: cancel any in-flight speculation; result (if any) is kept."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            self._task = None

    def push_audio(self, pcm_bytes):
        """Called from the audio path with raw PCM16 mono 16 kHz chunks."""
        if not self.enabled:
            return
        try:
            self._audio_queue.put_nowait(pcm_bytes)
        except Exception:
            pass

    def _reset(self):
        self._spec_group = None
        self._spec_conf = 0.0
        self._spec_clf_s = 0.0
        self._spec_whisper_s = 0.0
        self._spec_audio_s = 0.0
        self._spec_attempts = 0
        self._task = None
        self._audio_queue = asyncio.Queue()

    # ------------------------------------------------------------- internals
    def record(self, event, **fields):
        if self.timing:
            self.timing.record(event, turn=self._spec_turn, spec_layer=True, **fields)

    async def _speculate_loop(self):
        """One speculative pass per ~0.8s of new speech, until VAD stops us."""
        buffer = bytearray()
        last_classified_len = 0
        try:
            while True:
                chunk = await self._audio_queue.get()
                if chunk is None:
                    return
                buffer.extend(chunk)
                audio_s = len(buffer) / (2 * 16000)  # PCM16 mono 16k
                if audio_s < self.min_audio_s:
                    continue
                if audio_s - last_classified_len < 0.8:
                    continue
                last_classified_len = audio_s
                if audio_s > self.max_audio_s:
                    buffer = buffer[-int(self.max_audio_s * 2 * 16000):]
                await self._classify_partial(bytes(buffer), audio_s)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.record("spec_laya_error", error=type(exc).__name__)

    async def _classify_partial(self, pcm_bytes, audio_s):
        started = time.monotonic()
        try:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(pcm_bytes)
            wav_bytes = buf.getvalue()
            resp = await self.client.post(
                self.whisper_base + "/inference",
                files={"file": ("partial.wav", wav_bytes, "audio/wav")},
                data={"response_format": "json", "temperature": "0", "language": "en"},
            )
            resp.raise_for_status()
            text = (resp.json().get("text") or "").strip()
            self._spec_whisper_s = time.monotonic() - started
            if len(text.split()) < 2:
                return
            clf_started = time.monotonic()
            lresp = await self.client.post(self.laya_url + "/classify", json={"text": text})
            lresp.raise_for_status()
            payload = lresp.json()
            self._spec_clf_s = time.monotonic() - clf_started
            probs = payload.get("probabilities") or {}
            choice = payload.get("raw_choice")
            top = float(payload.get("top_prob") or 0)
            self._spec_attempts += 1
            self.record("spec_laya_attempt", group=choice, top_prob=top,
                        whisper_s=self._spec_whisper_s, clf_s=self._spec_clf_s,
                        audio_s=audio_s, words=len(text.split()),
                        partial_chars=len(text))
            if payload.get("accepted") and choice:
                self._spec_group = choice
                self._spec_conf = top
                self._spec_audio_s = audio_s
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.record("spec_laya_error", error=type(exc).__name__,
                        whisper_s=self._spec_whisper_s, audio_s=audio_s)

    # --------------------------------------------------------------- results
    @property
    def result(self):
        """Return (group, conf) if a valid speculation exists, else (None, 0)."""
        return (self._spec_group, self._spec_conf)

    def spec_data(self):
        return {"group": self._spec_group, "conf": self._spec_conf,
                "clf_s": self._spec_clf_s, "whisper_s": self._spec_whisper_s,
                "audio_s": self._spec_audio_s, "attempts": self._spec_attempts}

    def record_outcome(self, turn, final_group, used):
        """Log whether the speculation matched the final decision."""
        self.record("spec_laya_outcome", turn=turn, speculated=self._spec_group,
                    final=final_group, used=used,
                    match=(self._spec_group == final_group) if final_group else None)
