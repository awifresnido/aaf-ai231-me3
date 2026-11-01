"""Metadata-only timing for endpointing experiments on the Pi."""

import json
import time
import uuid
from contextlib import nullcontext

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame, LLMContextFrame, MetricsFrame, TranscriptionFrame,
    UserStartedSpeakingFrame, UserTurnInferenceCompletedFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver
from pipecat.processors.frame_processor import FrameDirection


class TurnTimingObserver(BaseObserver):
    def __init__(self, *, experiment, clock=time.time, emit=None):
        super().__init__(observe_every_push=False)
        self.experiment = experiment
        self.run = uuid.uuid4().hex[:10]
        self.turn = 0
        self._clock = clock
        self._emit = emit
        self._speech_end = None
        self.diagnostics = None

    def record(self, event, *, turn=None, **fields):
        item = dict(run=self.run, experiment=self.experiment, turn=self.turn if turn is None else turn,
                    event=event, at=self._clock(), **fields)
        if self._emit:
            self._emit(item)
        else:
            if self.diagnostics:
                self.diagnostics.emit("turn_event", timing_event=event,
                                      timing_at=item["at"], turn=item["turn"], fields=fields)
            scope = self.diagnostics.span("timing_log", timing_event=event, turn=item["turn"]) if self.diagnostics else nullcontext()
            with scope:
                logger.info("TURN_TIMING {}", json.dumps(item, separators=(",", ":")))

    def _since_speech_end(self):
        return None if self._speech_end is None else round((self._clock() - self._speech_end) * 1000, 2)

    def playback_write(self, context_id):
        self.record("first_playback_write", context_id=context_id,
                    since_speech_end_ms=self._since_speech_end())

    async def on_push_frame(self, data):
        # Broadcasts create separate upstream/downstream sibling frames.
        # Count the downstream copy so a single user turn stays a single ID.
        if not data.first_push or data.direction != FrameDirection.DOWNSTREAM:
            return
        frame = data.frame
        if isinstance(frame, UserStartedSpeakingFrame):
            self.turn += 1
            self._speech_end = None
            self.record("user_turn_started")
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self._speech_end = frame.timestamp - frame.stop_secs
            self.record("vad_stop", vad_confirmed_at=frame.timestamp,
                        stop_secs=frame.stop_secs, estimated_speech_end_at=self._speech_end)
        elif isinstance(frame, TranscriptionFrame):
            self.record("asr_transcript", frame_id=frame.id, finalized=frame.finalized,
                        chars=len(frame.text), since_speech_end_ms=self._since_speech_end())
        elif isinstance(frame, LLMContextFrame):
            self.record("routing_context_ready", since_speech_end_ms=self._since_speech_end())
        elif isinstance(frame, UserTurnInferenceCompletedFrame):
            # This marker follows context processing; it is not the start of routing.
            self.record("turn_inference_completed_marker", since_speech_end_ms=self._since_speech_end())
        elif isinstance(frame, BotStartedSpeakingFrame):
            self.record("bot_started", since_speech_end_ms=self._since_speech_end())
        elif isinstance(frame, MetricsFrame):
            for metric in frame.data:
                if hasattr(metric, "is_complete") and hasattr(metric, "e2e_processing_time_ms"):
                    values = {key: getattr(metric, key) for key in
                              ("processor", "is_complete", "probability", "e2e_processing_time_ms",
                               "inference_time_ms", "server_total_time_ms") if hasattr(metric, key)}
                    self.record("turn_analysis", **values)
