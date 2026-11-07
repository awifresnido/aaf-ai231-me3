import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pi'))
from context_management import trim_history


def test_drops_whole_old_turns_and_preserves_tool_pair():
    messages = [
        {'role': 'system', 'content': 'stable'},
        {'role': 'user', 'content': 'old' * 50},
        {'role': 'assistant', 'content': 'old answer'},
        {'role': 'user', 'content': 'new'},
        {'role': 'assistant', 'tool_calls': [{'id': 'one'}]},
        {'role': 'tool', 'tool_call_id': 'one', 'content': 'done'},
    ]
    kept, before, after = trim_history(messages, 160)
    assert kept == [messages[0], *messages[3:]]
    assert before > after and after <= 160


def test_keeps_oversized_latest_turn_intact():
    latest = {'role': 'user', 'content': 'x' * 400}
    kept, _, after = trim_history([{'role': 'user', 'content': 'old'}, latest], 100)
    assert kept == [latest]
    assert after > 100


def test_llm_usage_logs_counts_without_contents():
    import asyncio
    from types import SimpleNamespace
    from pipecat.frames.frames import MetricsFrame
    from pipecat.metrics.metrics import LLMTokenUsage, LLMUsageMetricsData
    from pipecat.processors.frame_processor import FrameDirection
    from turn_timing import TurnTimingObserver

    events = []
    observer = TurnTimingObserver(experiment='test', emit=events.append)
    usage = LLMTokenUsage(prompt_tokens=120, completion_tokens=20, total_tokens=140,
                          cache_read_input_tokens=80)
    frame = MetricsFrame(data=[LLMUsageMetricsData(processor='LLM', model='test', value=usage)])
    asyncio.run(observer.on_push_frame(SimpleNamespace(frame=frame, first_push=True,
                                                       direction=FrameDirection.DOWNSTREAM)))
    assert events[0]['event'] == 'llm_token_usage'
    assert events[0]['prompt_tokens'] == 120
    assert events[0]['cached_tokens'] == 80
