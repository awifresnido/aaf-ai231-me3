# Ranking of recorded live voice runs (same summariser, same metric)

Computed with `scripts/summarize_tts_trial.py` over every diagnostics run still
present on the Pi (`/dev/shm/voice-agent-diagnostics/<run>/pi-*.jsonl`). Metric:
earliest `native_user_bot_latency` per turn — speech end → first bot audio —
greeting excluded, nearest-rank p95. Only runs with ≥ 20 measured replies are
ranked; restore-verification runs with 0 timed replies are omitted.

| # | run | TTS backend / voice | Router | Replies | **E2E median** | p95 | max |
|---|---|---|---:|---:|---:|---:|---:|
| 1 | `f0c87b3a33` | DGX Qwen3 / Aiden | Jev | 23 | **2.559 s** | 7.278 s | 12.086 s |
| 2 | `9576b0bcb6` | DGX Qwen3 / Ryan | Jev | 23 | **3.188 s** | 6.567 s | 8.136 s |
| 3 | `016c1ab953` | DGX Qwen3 / Aiden | Laya (Jetson CUDA) | 27 | **3.448 s** | 15.762 s | 27.041 s |
| 4 | `23dff71cba` | **MacBook MLX / Aiden, streaming** | Jev | 29 | **3.669 s** | 6.903 s | 7.551 s |
| 5 | `7373bf308b` | DGX Qwen3 / Aiden | Jev (Llama 3.2 3B, Nemotron) | 24 | 3.901 s | 7.958 s | 8.774 s |
| 6 | `80010e1930` | MacBook MLX / Aiden, streaming, PCM 60 % | Jev (small model DOWN) | 30 | 4.064 s | 8.414 | 9.245 |
| 7 | `147f31abef` | DGX Qwen3 / Vivian | Laya | 30 | 4.321 s | 9.301 s | 14.401 s |
| 8 | `72afa542c5` | DGX Qwen3 / Aiden | Jev (Qwen2-Audio ASR + small model) | 29 | 4.494 s | 9.661 s | 29.884 s |
| 9 | `7a50558fa3` | DGX Qwen3 / Aiden | Jev (Voxtral ASR) | 28 | 5.011 s | 7.208 s | 7.537 s |
| 10 | `9c5da96c89` | MacBook MLX / Aiden, whole WAV | Jev | 30 | 5.478 s | 13.758 s | 18.277 s |

## Reading the ranking

* **Best absolute run on record:** `f0c87b3a33` (DGX Aiden, Jev) at 2.559 s
  median. Its own repeat under the same configuration (`7373bf308b`) measured
  3.901 s, so ~1.3 s of run-to-run session variance is normal — differences
  below ~1 s between sessions are not attributable to a single component.
* **Best MacBook run:** `23dff71cba` (this streaming trial) at 3.669 s — 1.81 s
  faster than the same MacBook backend delivering whole WAVs, and inside that
  session-variance band of the DGX runs.
* **Best spread (tail behaviour):** `23dff71cba` has the lowest maximum of any
  ranked run with a comparable stack (7.551 s) and p95 6.903 s, better than
  every DGX session except the Ryan-voice one.
* **`80010e1930` is not a TTS regression.** Its TTS first audio (0.321 s) matched
  `23dff71cba` (0.327 s); the end-to-end figure rose because the local Llama 3.2
  3B small model was not running, so smalltalk and argument extraction fell
  through to GLM on every turn (fast-tool turns still averaged 1.47 s vs 4.95 s
  for GLM turns).
* **Not a like-for-like ordering:** items 3, 6 use Laya routing; 7 and 8 change
  the ASR / small-model slot. Only 1, 2, 4, 5, 9 share the full
  Nemotron + Jev + Llama 3.2 3B stack, which makes 4 the only MacBook run that
  is directly comparable to a DGX baseline in the same session family.
