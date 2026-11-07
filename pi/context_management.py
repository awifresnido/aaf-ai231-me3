"""Bound older conversation history and record model usage without content."""
import json

from pipecat.services.openai.llm import OpenAILLMService


def trim_history(messages, max_chars):
    """Drop oldest complete user turns; preserve the latest turn and system messages.

    A single recent turn may exceed this soft history limit. Tool calls and their
    results are kept together in the same user-turn group.
    """
    system = [m for m in messages if isinstance(m, dict) and m.get("role") in ("system", "developer")]
    rest = [m for m in messages if not (isinstance(m, dict) and m.get("role") in ("system", "developer"))]
    groups = []
    for message in rest:
        if not groups or isinstance(message, dict) and message.get("role") == "user":
            groups.append([])
        groups[-1].append(message)
    def size(items):
        return len(json.dumps(items, ensure_ascii=False, default=str))
    before = size(rest)
    while len(groups) > 1 and size([m for group in groups for m in group]) > max_chars:
        groups.pop(0)
    kept = [m for group in groups for m in group]
    return system + kept, before, size(kept)


class ContextManagedLLM(OpenAILLMService):
    def __init__(self, *args, timing, history_chars=24000, **kwargs):
        super().__init__(*args, **kwargs)
        self._context_timing = timing
        self._history_chars = history_chars

    async def get_chat_completions(self, context):
        messages = context.get_messages()
        kept, before, after = trim_history(messages, self._history_chars)
        removed = len(messages) - len(kept)
        if removed:
            context.set_messages(kept)
        self._context_timing.record("llm_context_size", messages=len(kept),
            history_chars=after, before_chars=before, removed_messages=removed,
            history_char_limit=self._history_chars, limit_exceeded=after > self._history_chars)
        return await super().get_chat_completions(context)
