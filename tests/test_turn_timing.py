"""Check endpoint timing boundaries without audio hardware or network."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))
from turn_timing import TurnTimingObserver
from pipecat.frames.frames import (
    LLMContextFrame, TranscriptionFrame, UserStartedSpeakingFrame,
    UserTurnInferenceCompletedFrame, VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection


class TimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_endpointing_includes_vad_silence_once(self):
        now = [99.0]
        events = []
        observer = TurnTimingObserver(experiment="test", clock=lambda: now[0], emit=events.append)
        async def push(frame, first=True, direction=FrameDirection.DOWNSTREAM):
            await observer.on_push_frame(SimpleNamespace(frame=frame, first_push=first, direction=direction))
        await push(UserStartedSpeakingFrame())
        await push(UserStartedSpeakingFrame(), direction=FrameDirection.UPSTREAM)
        now[0] = 100.1
        await push(VADUserStoppedSpeakingFrame(stop_secs=0.4, timestamp=100.0))
        now[0] = 100.2
        transcript = TranscriptionFrame(text="private utterance", user_id="", timestamp="", finalized=True)
        await push(transcript)
        await push(transcript, first=False)
        now[0] = 100.4
        await push(LLMContextFrame(context=SimpleNamespace()))
        now[0] = 100.9
        observer.playback_write("context")
        self.assertAlmostEqual(events[1]["estimated_speech_end_at"], 99.6)
        self.assertEqual(events[2]["since_speech_end_ms"], 600.0)
        self.assertTrue(events[2]["finalized"])
        self.assertEqual(events[3]["since_speech_end_ms"], 800.0)
        self.assertEqual(events[3]["event"], "routing_context_ready")
        self.assertEqual(events[3]["turn"], 1)
        self.assertEqual(events[4]["since_speech_end_ms"], 1300.0)
        self.assertEqual(len(events), 5)
        self.assertNotIn("private utterance", str(events))

    async def test_greeting_has_no_user_latency(self):
        events = []
        observer = TurnTimingObserver(experiment="test", emit=events.append)
        observer.playback_write("greeting")
        self.assertIsNone(events[0]["since_speech_end_ms"])
