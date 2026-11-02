# Qwen3-TTS voice-trial comparison

All times are median estimated speech end to native software response onset, seconds. Rows are observational runs with differing words, routes/state and failed/interrupted turns excluded from latency when no onset exists. See each summary for reliability and bounds.

| Configuration | Direct | Context | Overall | Timed onsets |
|---|---:|---:|---:|---:|
| Nemotron ASR / Jev / Llama small / Aiden | 1.48 | 4.96 | 2.56 | 23 |
| Nemotron ASR / Jev / Llama small / Ryan | 2.67 | 4.98 | 3.19 | 23 |
| Nemotron ASR / Jetson CUDA Laya / Llama small / Aiden | 3.26 | 3.98 | 3.45 | 27 |
| Nemotron ASR / ThinkPad CPU Laya / Llama small / Vivian | 3.81 | 4.67 | 4.32 | 30 |
| Qwen2-Audio ASR / Jev / Qwen2 small / Aiden (current) | 4.43 | 4.50 | 4.49 | 27 |

Current Qwen2-Audio ASR produced refusals/commentary, wrapper text and answer-like outputs. Current conversational small-model role had no calls, and its one extraction failed validation. These rows do not establish intrinsic voice/model speed or recognition accuracy.
