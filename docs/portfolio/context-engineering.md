# Context engineering

The agent coordinates conversation history, speech events, and tool results across a Pipecat pipeline. The table distinguishes model-facing context from events that control when that context is ready.

| Input or event | How ME3 handles it |
| --- | --- |
| System prompt and persona | The cloud voice model receives the [versioned voice instruction](../../prompts/voice-system-v1.0.0.txt); Telegram has a separate [text instruction](../../prompts/telegram-system-v1.0.0.txt). The runtime Python strings remain authoritative. |
| ASR partials and finals | Whisper can emit rolling interim transcripts when streaming is enabled. Completed transcripts feed turn processing; optional partial promotion is disabled by default. The latest-segment guard can hold turn completion until pending Whisper output arrives. Availability depends on the selected ASR mode. |
| VAD turn events | Silero VAD and SmartTurn mark speech and turn boundaries; these are pipeline control and timing events, not necessarily literal messages in the LLM prompt. |
| MCP tool results | The Pipecat MCP client executes registered tools and makes their results available to the LLM conversation when a model-driven tool call is used. Some fast routes execute validated tools and speak their result directly, without another model call. |
| Memory / RAG | Optional, not claimed as a general persistent memory or RAG subsystem. Conversation context and tool-backed state are distinct from a retrieval-augmented memory system. |

## Managing a turn

The interaction can be understood as **idle → listen → think → speak**, with VAD, turn analysis, routing, model/tool processing and audio output driving transitions. This is an explanatory lifecycle rather than a claim that the implementation has one explicit four-state machine. A barge-in interrupts playback, flushes queued stale audio and requests cancellation of the active response; see the [live evidence and remaining ASR race limitation](../runbooks/demo-evidence-20261107.md).

- **Budget and trimming:** In the separate `local_vcm` trial, only the six most recent user/assistant messages are included and each message is capped at 600 characters. Small-model extraction calls also bound output tokens. These limits do **not** establish a global token budget, automatic summarization, or a bounded history for the normal cloud voice path.
- **Stable-prefix caching:** The system instruction is stable for a given version, but explicit provider-side prompt caching and its TTFT benefit have not been established by this repository. Cached filler audio is a separate mechanism and is not LLM prompt caching.
- **Context-size measurement:** Pipecat usage metrics are enabled, and the external benchmark reported context size for the measured run. For the direct 6 November session, the report recorded an estimated/usage prompt-token median of **1,867**, maximum **3,549**, and first-to-last call **1,331 → 2,335**; message counts were median **31**, maximum **63**, first-to-last **1 → 63**. These are one run's reported measurements, not a guaranteed per-run dashboard feature or a fixed token budget. Raw benchmark artifacts remain local; see [evaluation provenance](evaluation.md).

Code references: [`pi/bot.py`](../../pi/bot.py), [`pi/whisper_stt.py`](../../pi/whisper_stt.py), [`pi/whisper_turn_stop.py`](../../pi/whisper_turn_stop.py), [`pi/orchestration.py`](../../pi/orchestration.py), [`pi/local_vcm.py`](../../pi/local_vcm.py), and [`pi/backchannel.py`](../../pi/backchannel.py).
