"""Wait for the latest Whisper segment before releasing a completed turn."""
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy


class LatestWhisperTurnStopStrategy(TurnAnalyzerUserTurnStopStrategy):
    def __init__(self, *, stt, timing=None, **kwargs):
        super().__init__(**kwargs)
        self._whisper = stt
        self._timing = timing
        self._last_segment_received = 0
        self._last_wait_logged = None

    async def _handle_transcription(self, frame):
        segment = (frame.metadata or {}).get("whisper_segment_id")
        if isinstance(segment, int):
            self._last_segment_received = max(self._last_segment_received, segment)
        await super()._handle_transcription(frame)

    async def _maybe_trigger_user_turn_stopped(self):
        expected = self._whisper._segment_id
        if (self._wait_for_transcript and self._turn_complete and self._vad_stopped
                and self._last_segment_received < expected):
            if self._timing and self._last_wait_logged != expected:
                self._timing.record("turn_wait_latest_asr", expected_segment=expected,
                                    received_segment=self._last_segment_received)
                self._last_wait_logged = expected
            return
        await super()._maybe_trigger_user_turn_stopped()
