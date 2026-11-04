"""Conversational backchanneling for the ME3 voice agent (Phase 1: deadline mode).

Design (handover §6): pre-rendered PCM fillers ("mm-hm", "one moment", ...)
pushed as OutputAudioRawFrame — zero runtime synthesis, no GPU contention
(§5A: Qwen2-Audio ASR and Qwen3-TTS share one DGX GPU).

Placement: BETWEEN the STT service and the user aggregator.
  - VADUserStarted/StoppedSpeakingFrame travel UPSTREAM from the user
    aggregator, so they are visible here (downstream processors never see
    them).
  - TranscriptionFrame / InterimTranscriptionFrame from the STT flow DOWNSTREAM
    through here toward the aggregator (which consumes them internally).

Filler audio path: pushed DIRECTLY into the output transport's queue,
bypassing the LLM and TTS entirely — LLMService.process_frame drops frames it
does not handle, and TTSService queues non-system frames behind pending audio
contexts. The direct push keeps the filler O(1) (§8 trap 6) and gives free
barge-in cancellation: InterruptionFrame flushes the transport queue.

Echo gates (§5B lesson: frame events describe the synthesis pipeline, not the
acoustic room — never gate on BotStoppedSpeakingFrame):
  1. Measured playback: PacatAudioOutput tracks cumulative bytes written and
     exposes playback_busy_until (write time + PCM duration + pacat buffer).
  2. Mic energy: RMS over the 1 s window after VAD stop (recorded for Phase 0);
     fire requires recent mic RMS below BACKCHANNEL_ECHO_RMS (0 disables).
"""

import asyncio
import math
import os
import random
import struct
import time
import wave

from loguru import logger
from pipecat.frames.frames import (CancelFrame, EndFrame, ErrorFrame,
                                   InputAudioRawFrame,
                                   InterimTranscriptionFrame, OutputAudioRawFrame,
                                   StartFrame, TranscriptionFrame,
                                   UserStartedSpeakingFrame,
                                   VADUserStartedSpeakingFrame,
                                   VADUserStoppedSpeakingFrame)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


def _load_clips(clip_dir):
    """Load 24 kHz mono PCM16 WAV clips; return {name: (pcm_bytes, duration_s)}."""
    clips = {}
    if not os.path.isdir(clip_dir):
        return clips
    for fname in sorted(os.listdir(clip_dir)):
        if not fname.endswith(".wav"):
            continue
        path = os.path.join(clip_dir, fname)
        try:
            with wave.open(path, "rb") as w:
                rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
                if rate != 24000 or ch != 1 or width != 2:
                    logger.error(
                        "Backchannel clip {} is {} Hz/{} ch/{} B — expected 24000/1/2 (pitch bug)",
                        fname, rate, ch, width)
                    continue
                pcm = w.readframes(w.getnframes())
            clips[fname[:-4]] = (pcm, len(pcm) / (2 * rate))
        except Exception as exc:
            logger.error("Backchannel clip {} unreadable: {}", fname, type(exc).__name__)
    return clips


def _rms(pcm_bytes):
    """RMS of mono PCM16 bytes (0-32767 scale). O(n) but n is one 10-20 ms chunk."""
    n = len(pcm_bytes) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"<{n}h", pcm_bytes[:n * 2])
    acc = 0
    for s in samples:
        acc += s * s
    return math.sqrt(acc / n)


class BackchannelProcessor(FrameProcessor):
    """Phase 1 (deadline mode): fire a cached filler if the turn stays silent.

    Trigger: VADUserStoppedSpeakingFrame → deadline timer anchored at the
    estimated speech end (the frame itself arrives stop_secs≈0.3 s late, so
    anchoring there would mathematically miss the ≤400 ms gate).
    Cancel: transcript arrival (any), VAD re-start, bot speech, turn end.
    Gate: measured playback busy + mic RMS. Max once per turn, cooldown.
    """

    def __init__(self, timing_observer=None, output_transport=None, **kwargs):
        super().__init__(**kwargs)
        self.timing = timing_observer
        self.output = output_transport
        self.enabled = os.getenv("BACKCHANNEL", "0").strip() == "1"
        self.mode = os.getenv("BACKCHANNEL_MODE", "deadline").strip().lower()
        self.deadline_ms = float(os.getenv("BACKCHANNEL_DEADLINE_MS", "600"))
        self.cooldown_s = float(os.getenv("BACKCHANNEL_COOLDOWN_S", "8"))
        self.echo_rms = float(os.getenv("BACKCHANNEL_ECHO_RMS", "0"))
        clip_dir = os.getenv("BACKCHANNEL_CLIP_DIR",
                             "/home/aldwinrpi4/voice-agent/assets/backchannel")
        self.clips = _load_clips(clip_dir) if self.enabled else {}
        if self.enabled and not self.clips:
            logger.error("BACKCHANNEL=1 but no valid 24 kHz clips in {} — feature OFF", clip_dir)
            self.enabled = False
        # per-turn state
        self._deadline_task = None
        self._turn_transcript = False      # any transcript this turn (final or partial)
        self._user_speaking = False
        self._filled_this_turn = False
        self._last_fill_at = 0.0
        self._deck = []
        self._last_clip_name = None
        self._speech_end_mono = None
        # mic RMS ring buffer over the trailing 1 s (ts_mono -> rms)
        self._rms_ring = []
        # interruptibility evidence: mic energy while the bot plays
        self._pb_window_rms = 0.0
        self._pb_window_at = 0.0
        # predict mode (Phase 2): classify the latest in-speech partial with
        # Laya (Jetson :8083, not the shared DGX GPU — no ASR contention).
        # Budget: ONE classify HTTP call per turn, async, never blocking STT.
        self._last_partial_text = ""
        self._armed = None
        self._classified_this_turn = False
        self._classify_task = None
        laya_url = os.getenv("LAYA_ROUTER_URL", "http://192.168.5.11:8083").rstrip("/")
        self._laya_classify_url = laya_url + "/classify"
        self._escalate_groups = frozenset(
            os.getenv("BACKCHANNEL_ARM_GROUPS",
                      "knowledge,workspace,multiple_actions").split(","))
        # Phase 3 "still working": one follow-up clip for genuinely long waits.
        # Run 4ba4de83d3: GLM turns sat 3-17 s silent AFTER the first filler.
        self.long_wait_s = float(os.getenv("BACKCHANNEL_LONG_WAIT_S", "8"))
        self.long_clip_name = os.getenv("BACKCHANNEL_LONG_CLIP", "still_working")
        self._long_task = None
        self._filler_burst_prev = None
        # Interruptibility trial: RMS-based barge-in bypassing the AEC.
        # Calibrated on run 3deabb0044 (207 windows during playback):
        # median idle 30.7, speech tail 300-981 -> 250 / 200 ms / 2 s.
        self.barge = os.getenv("BARGE_IN_VAD_BYPASS", "0").strip() == "1"
        self.barge_rms = float(os.getenv("BACKCHANNEL_BARGE_RMS", "250"))
        self.barge_ms = float(os.getenv("BACKCHANNEL_BARGE_MS", "200"))
        self.barge_cooldown_s = float(os.getenv("BACKCHANNEL_BARGE_COOLDOWN_S", "2"))
        self._barge_hot_since = 0.0
        self._barge_last_fire = 0.0
        self._barge_fires = 0
        if self.barge:
            logger.info("Barge-in bypass: rms>{} for {}ms while playback busy "
                        "(cooldown {}s)", self.barge_rms, self.barge_ms,
                        self.barge_cooldown_s)
        if self.enabled:
            logger.info("Backchannel: mode={} deadline_ms={} cooldown_s={} clips={}",
                        self.mode, self.deadline_ms, self.cooldown_s, list(self.clips))

    # ---------- diagnostics ----------

    def record(self, event, **fields):
        if self.timing:
            self.timing.record(event, **fields)

    # ---------- clip selection ----------

    def _pick_clip(self):
        """Shuffled-deck rotation (Phase 3): cycle through all clips in random
        order, reshuffle when the deck empties. Never repeats until every
        other clip has played. Run 4ba4de83d3 lesson: both the timestamp hash
        AND a skip-last counter settled into a 3-clip cycle (mm_hm: 0/25)."""
        # Shuffled-deck rotation EXCLUDES the long-wait clip: "still working"
        # only ever plays as the Phase 3 follow-up, never as a first filler.
        names = sorted(n for n in self.clips if n != self.long_clip_name)
        if not names:
            return None
        if not self._deck:
            self._deck = names[:]
            random.shuffle(self._deck)
            # avoid the reshuffle dealing the just-played clip first
            if len(self._deck) > 1 and self._deck[0] == self._last_clip_name:
                self._deck[0], self._deck[1] = self._deck[1], self._deck[0]
        return self._deck.pop()

    async def _classify_partial(self, text):
        """Phase 2: arm the filler only for groups whose answers come slow."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=httpx.Timeout(1.5, connect=0.8),
                                         trust_env=False) as client:
                resp = await client.post(self._laya_classify_url, json={"text": text})
                resp.raise_for_status()
                payload = resp.json()
            choice = str(payload.get("intent") or payload.get("choice") or
                         payload.get("group") or "").strip().lower()
            conf = float(payload.get("confidence", 0.0) or 0.0)
            armed = choice in self._escalate_groups or conf < 0.5
            self._armed = choice if armed else None
            self.record("bc_classify", group=choice, conf=round(conf, 3),
                        armed=bool(armed), words=len(text.split()))
        except Exception as exc:
            self.record("bc_classify_error", error=type(exc).__name__)

    # ---------- trigger / cancel ----------

    def _arm_deadline(self, frame):
        if not self.enabled or self._filled_this_turn:
            return
        if self.mode != "deadline" and self.mode != "predict":
            return
        stop_secs = getattr(frame, "stop_secs", 0.0) or 0.0
        now = time.monotonic()
        # The VAD frame is emitted stop_secs after real speech end; anchor the
        # deadline at estimated speech end so the filler can land ≤400 ms.
        self._speech_end_mono = now - stop_secs
        self._turn_transcript = False
        self._cancel_task()
        delay = self.deadline_ms / 1000.0 - stop_secs
        if delay <= 0.05:
            delay = 0.05
        self._deadline_task = asyncio.get_event_loop().create_task(self._fire(delay))

    def _cancel_task(self):
        if self._deadline_task is not None and not self._deadline_task.done():
            self._deadline_task.cancel()
        self._deadline_task = None

    async def _fire(self, delay_s):
        try:
            await asyncio.sleep(delay_s)
        except asyncio.CancelledError:
            return
        turn = self.timing.turn if self.timing else None
        now = time.monotonic()
        # cancel conditions
        if self._turn_transcript:
            self.record("bc_skip", reason="transcript_arrived")
            return
        if self._user_speaking:
            self.record("bc_skip", reason="user_speaking")
            return
        if self.output is not None:
            busy_until = getattr(self.output, "playback_busy_until", 0.0)
            if busy_until and busy_until > now - 0.05:
                self.record("bc_skip", reason="playback_busy")
                return
        if self.echo_rms > 0:
            recent = [r for ts, r in self._rms_ring if now - ts <= 1.0]
            if recent and max(recent) > self.echo_rms:
                self.record("bc_skip", reason="mic_rms", rms=round(max(recent), 1))
                return
        if now - self._last_fill_at < self.cooldown_s:
            self.record("bc_skip", reason="cooldown")
            return
        name = self._pick_clip()
        if name is None:
            return
        self._last_clip_name = name
        pcm, dur = self.clips[name]
        # stamp the transport-side echo window: playback end + 150 ms margin
        if self.output is not None:
            try:
                self.output.playback_busy_until = now + dur + 0.15
            except Exception:
                pass
        self._filled_this_turn = True
        self._last_fill_at = now
        self.record("bc_fired", clip=name, duration_s=round(dur, 3),
                    after_speech_end_ms=round((now - (self._speech_end_mono or now)) * 1000, 1),
                    mode=self.mode)
        try:
            if self.output is not None:
                # burst id BEFORE queueing: the filler itself becomes burst
                # prev+1; anything beyond that is the real answer / barge-in
                self._filler_burst_prev = getattr(self.output, "_playback_burst_id", None)
                await self.output.queue_frame(OutputAudioRawFrame(
                    audio=pcm, sample_rate=24000, num_channels=1))
                self._arm_long_wait(self._speech_end_mono)
            else:
                await self.push_frame(OutputAudioRawFrame(
                    audio=pcm, sample_rate=24000, num_channels=1))
        except Exception as exc:
            self.record("bc_error", error=type(exc).__name__)
            logger.error("Backchannel push failed: {}", exc)

    # ---------- long-wait follow-up (Phase 3) ----------

    def _arm_long_wait(self, speech_end_mono):
        """Schedule the 'still working' clip at speech_end + long_wait_s.
        Fires only if the SAME turn is still unanswered; cancelled on
        transcript-final, user speech, turn end, or the first filler never
        having fired (it would pop out of nowhere)."""
        if self.long_wait_s <= 0 or self.long_clip_name not in self.clips:
            return
        if self._long_task is not None and not self._long_task.done():
            self._long_task.cancel()
        delay = self.long_wait_s + (time.monotonic() - speech_end_mono)
        self._long_task = asyncio.get_event_loop().create_task(self._fire_long(delay))

    async def _fire_long(self, delay_s):
        try:
            await asyncio.sleep(delay_s)
        except asyncio.CancelledError:
            return
        now = time.monotonic()
        if self._user_speaking or not self._filled_this_turn:
            return
        if self.output is not None:
            busy_until = getattr(self.output, "playback_busy_until", 0.0)
            if busy_until and busy_until > now - 0.05:
                return
            # only fire if NO new playback burst started since the filler —
            # the filler itself is burst prev+1; a burst beyond that means the
            # real answer (or a barge-in) already played
            burst_now = getattr(self.output, "_playback_burst_id", None)
            if (self._filler_burst_prev is not None and burst_now is not None
                    and burst_now > self._filler_burst_prev + 1):
                self.record("bc_skip_long", reason="answer_played")
                return
        pcm, dur = self.clips[self.long_clip_name]
        if self.output is not None:
            try:
                self.output.playback_busy_until = now + dur + 0.15
            except Exception:
                pass
        self.record("bc_fired_long", clip=self.long_clip_name, duration_s=round(dur, 3),
                    after_speech_end_ms=round((now - (self._speech_end_mono or now)) * 1000, 1))
        try:
            if self.output is not None:
                await self.output.queue_frame(OutputAudioRawFrame(
                    audio=pcm, sample_rate=24000, num_channels=1))
        except Exception as exc:
            self.record("bc_error", error=type(exc).__name__)

    def _cancel_long(self):
        if self._long_task is not None and not self._long_task.done():
            self._long_task.cancel()
        self._long_task = None

    # ---------- frame handling ----------

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, (EndFrame, CancelFrame)):
            self._cancel_task()
            self._cancel_long()
            await self.push_frame(frame, direction)
            return

        if direction == FrameDirection.UPSTREAM:
            # VAD lifecycle frames from the user aggregator (upstream broadcast)
            if isinstance(frame, VADUserStartedSpeakingFrame):
                self._user_speaking = True
                now = time.monotonic()
                if self.output is not None and getattr(
                        self.output, "playback_busy_until", 0.0) > now - 0.05:
                    self.record("vad_during_playback",
                                rms_max=round(self._pb_window_rms, 1) if self._pb_window_rms else None)
                self._cancel_task()
                self._cancel_long()
                await self.push_frame(frame, direction)
                return
            if isinstance(frame, VADUserStoppedSpeakingFrame):
                self._user_speaking = False
                self._filled_this_turn = False
                self._arm_deadline(frame)
                await self.push_frame(frame, direction)
                return
            # anything else upstream: forward unchanged
            await self.push_frame(frame, direction)
            return

        # DOWNSTREAM
        if isinstance(frame, InputAudioRawFrame):
            # 16 kHz mono PCM16 from the transport input — track mic RMS
            if frame.sample_rate == 16000 and frame.num_channels == 1:
                r = _rms(bytes(frame.audio))
                now = time.monotonic()
                self._rms_ring.append((now, r))
                cutoff = now - 1.2
                while self._rms_ring and self._rms_ring[0][0] < cutoff:
                    self._rms_ring.pop(0)
                # evidence accumulation while the bot is playing
                if self.output is not None and getattr(
                        self.output, "playback_busy_until", 0.0) > now - 0.05:
                    if r > self._pb_window_rms:
                        self._pb_window_rms = r
                    if now - self._pb_window_at >= 0.5:
                        self.record("bc_mic_while_bot", rms_max=round(self._pb_window_rms, 1))
                        self._pb_window_rms = 0.0
                        self._pb_window_at = now
                    # RMS barge-in bypass (AEC swallows near-end speech):
                    # sustained high RMS while playback measured-busy -> fire.
                    if self.barge and r >= self.barge_rms:
                        if not self._barge_hot_since:
                            self._barge_hot_since = now
                        elif (now - self._barge_hot_since >= self.barge_ms / 1000.0
                              and now - self._barge_last_fire >= self.barge_cooldown_s):
                            self._barge_last_fire = now
                            self._barge_fires += 1
                            self.record("bc_barge_fired", rms=round(r, 1),
                                        hot_for_ms=round((now - self._barge_hot_since) * 1000),
                                        fire_n=self._barge_fires)
                            # Real interruption, pushed DOWNSTREAM from here:
                            # router passes it, LLM cancels generation, TTS
                            # clears, transport flushes its queues and the
                            # flush-kill drops the pacat pipe instantly.
                            from pipecat.frames.frames import InterruptionFrame
                            await self.push_frame(InterruptionFrame(), direction)
                        # stay hot; cooldown gate re-arms on the next window
                    elif r < self.barge_rms * 0.6:
                        self._barge_hot_since = 0.0
                elif self._pb_window_at:
                    self._pb_window_rms = 0.0
                    self._pb_window_at = 0.0
                    self._barge_hot_since = 0.0
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TranscriptionFrame):
            # Spec §6: cancel on transcript arrival — the FINAL transcript.
            # Interim/partial frames arrive only DURING speech (the whisper
            # partial loop is cancelled at VAD stop); pre-cancelling on them
            # would suppress precisely the long-wait turns this targets.
            if (frame.text or "").strip():
                self._turn_transcript = True
                self._cancel_task()
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, InterimTranscriptionFrame):
            text = (frame.text or "").strip()
            if text:
                # Feed predict mode; do NOT cancel the deadline (final-only).
                self._last_partial_text = text
                if self.mode == "predict" and not self._classified_this_turn and len(text.split()) >= 3:
                    self._classified_this_turn = True
                    self._classify_task = asyncio.get_event_loop().create_task(
                        self._classify_partial(text))
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, UserStartedSpeakingFrame):
            # turn boundary (downstream copy): reset per-turn state
            self._cancel_task()
            self._filled_this_turn = False
            self._turn_transcript = False
            self._last_partial_text = ""
            self._armed = None
            self._classified_this_turn = False
            if self._classify_task is not None and not self._classify_task.done():
                self._classify_task.cancel()
            self._classify_task = None
            self._cancel_long()
            self._filler_burst_prev = None
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, ErrorFrame):
            self._cancel_task()
            await self.push_frame(frame, direction)
            return

        await self.push_frame(frame, direction)