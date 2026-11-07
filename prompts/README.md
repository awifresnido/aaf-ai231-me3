# Versioned system prompts

These files record the exact model instructions used by this repository at version **1.0.0**:

| Versioned snapshot | Runtime source | Scope |
| --- | --- | --- |
| [Voice v1.0.0](voice-system-v1.0.0.txt) | [`pi/bot.py`](../pi/bot.py) `OpenAILLMService.Settings.system_instruction` | Voice assistant LLM in `single` and `two_brain_plusjev` modes |
| [Telegram v1.0.0](telegram-system-v1.0.0.txt) | [`pi/telegram_bridge.py`](../pi/telegram_bridge.py) `SYSTEM` | Telegram text interface; GitHub summaries append an additional instruction in code |

The Python runtime strings are the source of truth; these files are versioned, human-readable snapshots and do not change deployment behavior. The initial version denotes the first repository snapshot, not the first prompt used during the project. Git records when each snapshot was added. When changing a runtime prompt, add a new versioned file, update this index and the snapshot references in [`tests/test_prompt_snapshots.py`](../tests/test_prompt_snapshots.py), and record the change in the commit. Never include credentials or private conversation data.

Additional, task-specific instructions exist in [`pi/orchestration.py`](../pi/orchestration.py) for argument extraction and local replies, and in [`pi/local_vcm.py`](../pi/local_vcm.py) for the separate local VCM trial. Routing, tool validation, audio interruption and access control are enforced by code and configuration; the voice system prompt alone does not define them.
