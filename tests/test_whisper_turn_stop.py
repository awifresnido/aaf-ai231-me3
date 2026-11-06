from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))
from whisper_stt import WhisperSTTService
from whisper_turn_stop import LatestWhisperTurnStopStrategy


@pytest.mark.asyncio
async def test_turn_waits_for_newest_segment_after_earlier_fragment():
    stt = SimpleNamespace(_segment_id=4)
    timing = SimpleNamespace(record=Mock())
    strategy = LatestWhisperTurnStopStrategy(stt=stt, timing=timing, turn_analyzer=Mock())
    strategy._turn_complete = True
    strategy._vad_stopped = True
    strategy._last_segment_received = 3
    with patch.object(TurnAnalyzerUserTurnStopStrategy, "_maybe_trigger_user_turn_stopped", new_callable=AsyncMock) as release:
        await strategy._maybe_trigger_user_turn_stopped()
        release.assert_not_awaited()
        timing.record.assert_called_once_with("turn_wait_latest_asr", expected_segment=4, received_segment=3)
        frame = WhisperSTTService()._transcript("complete instruction", 4)
        with patch.object(TurnAnalyzerUserTurnStopStrategy, "_handle_transcription", new_callable=AsyncMock):
            await strategy._handle_transcription(frame)
        await strategy._maybe_trigger_user_turn_stopped()
        release.assert_awaited_once()


@pytest.mark.asyncio
async def test_turn_without_an_outstanding_segment_uses_normal_strategy():
    strategy = LatestWhisperTurnStopStrategy(stt=SimpleNamespace(_segment_id=2), turn_analyzer=Mock())
    strategy._turn_complete = True
    strategy._vad_stopped = True
    strategy._last_segment_received = 2
    with patch.object(TurnAnalyzerUserTurnStopStrategy, "_maybe_trigger_user_turn_stopped", new_callable=AsyncMock) as release:
        await strategy._maybe_trigger_user_turn_stopped()
        release.assert_awaited_once()
