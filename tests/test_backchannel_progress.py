"""Long-wait progress must continue only while the answer is outstanding."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))
from backchannel import BackchannelProcessor


@pytest.mark.asyncio
async def test_long_wait_repeats_and_stops_when_answer_plays():
    output = SimpleNamespace(playback_busy_until=0.0, _playback_burst_id=0, frames=[])
    async def queue_frame(frame):
        output.frames.append(frame)
        output._playback_burst_id += 1
    output.queue_frame = queue_frame
    processor = BackchannelProcessor(output_transport=output)
    processor.clips = {processor.final_clip_name: (b"\0\0", 0.0)}
    processor.final_repeat_s = 0.01
    processor._filled_this_turn = True
    processor.record = Mock()
    await processor._fire_final(0, 0)
    await asyncio.sleep(0.25)
    assert len(output.frames) == 2
    output._playback_burst_id += 1  # the real answer starts
    await asyncio.sleep(0.25)
    assert len(output.frames) == 2
    assert any(c.args[0] == "bc_skip_final" for c in processor.record.call_args_list)
    processor._cancel_long()


@pytest.mark.asyncio
async def test_new_user_speech_cancels_scheduled_progress():
    output = SimpleNamespace(playback_busy_until=0.0, _playback_burst_id=0, frames=[])
    async def queue_frame(frame): output.frames.append(frame)
    output.queue_frame = queue_frame
    processor = BackchannelProcessor(output_transport=output)
    processor.clips = {processor.final_clip_name: (b"\0\0", 0.0)}
    processor._filled_this_turn = True
    processor._final_task = asyncio.create_task(processor._fire_final(.05, 0))
    processor._cancel_long()
    await asyncio.sleep(.08)
    assert not output.frames


@pytest.mark.asyncio
async def test_answer_after_second_filler_cancels_third():
    output = SimpleNamespace(playback_busy_until=0.0, _playback_burst_id=0, frames=[])
    async def queue_frame(frame):
        output.frames.append(frame)
        output._playback_burst_id += 1
    output.queue_frame = queue_frame
    processor = BackchannelProcessor(output_transport=output)
    processor.clips = {processor.long_clip_name: (b"\0\0", 0.0),
                       processor.final_clip_name: (b"\0\0", 0.0)}
    processor.long_wait_s = .01
    processor.final_wait_s = .02
    processor._filled_this_turn = True
    processor.record = Mock()
    await processor._fire_long(0)
    assert len(output.frames) == 1
    output.playback_busy_until = 0.0
    output._playback_burst_id += 1  # real answer starts after the long filler
    await asyncio.sleep(.25)
    assert len(output.frames) == 1
    assert any(c.args[0] == "bc_skip_final" for c in processor.record.call_args_list)
    processor._cancel_long()
