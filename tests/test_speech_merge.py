"""Regression checks for the merged Whisper and speculative-tap integration."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from pathlib import Path
import sys

import pytest
from pipecat.frames.frames import InterimTranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))
from spec_tap import SpecTap
from whisper_stt import WhisperSTTService


def test_whisper_streaming_can_be_disabled(monkeypatch):
    monkeypatch.setenv("WHISPER_STREAM", "0")
    service = WhisperSTTService()
    assert service.streaming is False


@pytest.mark.asyncio
async def test_partial_is_forwarded_when_speculator_has_no_text_support(monkeypatch):
    monkeypatch.setattr(FrameProcessor, "process_frame", AsyncMock())
    tap = SpecTap(SimpleNamespace())
    tap.push_frame = AsyncMock()
    frame = InterimTranscriptionFrame("hello there", "user", "now")
    await tap.process_frame(frame, FrameDirection.DOWNSTREAM)
    tap.push_frame.assert_awaited_once_with(frame, FrameDirection.DOWNSTREAM)
