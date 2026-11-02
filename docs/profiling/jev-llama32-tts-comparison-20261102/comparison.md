# Jetson Llama 3.2 3B: DGX vs MacBook Aiden TTS (whole WAV) vs MacBook Aiden TTS (streaming)

All three live trials used Nemotron ASR, Jev 1.14.0, Jetson GPU Llama 3.2 3B as
the small model and GLM 5.3 Flash fallback. Only the TTS backend changed.
Times are seconds from native speech end to first bot audio unless stated
otherwise. Greeting turn 0 is excluded. P95 uses nearest rank. Turn
numbering, utterances and route mix differ between sessions, so this is an
observational comparison, not a paired test.

| Measurement | DGX Qwen3 Aiden (`7373bf308b`) | MacBook MLX whole WAV (`9c5da96c89`) | MacBook MLX **streaming** (`23dff71cba`) |
|---|---:|---:|---:|
| Measured reply onsets | 24 | 30 | 29 |
| **End-to-end median** | **3.901 s** | **5.478 s** | **3.669 s** |
| End-to-end p95 | 7.958 s | 13.758 s | 6.903 s |
| End-to-end maximum | 8.774 s | 18.277 s | 7.551 s |
| TTS first audio median | 0.171 s (41) | 1.725 s (45) | **0.327 s** (41) |
| TTS first audio p95 | 0.203 s | 4.200 s | 0.637 s |
| TTS first audio maximum | 1.491 s | 6.010 s | 0.791 s |
| TTS request completion median | 0.649 s | 1.731 s | 3.292 s |
| Jev classification median | 0.294 s (22) | 0.285 s (30) | 0.283 s (27) |
| Speech end to available ASR transcript median | 0.467 s (25) | 0.486 s (21) | 0.441 s (22) |
| Routes to GLM / fast tools / smalltalk | 20 / 2 / 2 | 22 / 7 / 1 | 23 / 6 / 0 |
| Jev classifier failures | 1 timeout | 0 | 0 |
| TTS HTTP failures / cancellations | 0 / 0 | 0 / 1 | 0 / 0 |

Streaming cut median end-to-end onset by **1.809 s** versus the same MacBook
backend delivering whole WAVs, and by **0.232 s** versus the DGX backend. TTS
first audio fell from 1.725 s to **0.327 s** (DGX: 0.171 s); the remaining gap
is Mac prefill plus the first 0.25 s codec flush.

## Why the Mac stream sounds rougher than DGX even though it starts faster

Generation rate, not transport, is now the limiting factor:

| | median audio/request ratio | requests slower than realtime | worst |
|---|---:|---:|---:|
| DGX Qwen3 (vLLM) | **3.80×** | 0 % | 1.25× |
| MacBook MLX 4-bit (`23dff71cba`) | **0.91×** | **59 %** | 0.71× |

Playback consumes 1.0× realtime. When the Mac synthesises at 0.91×, the
Pipecat/pacat buffer starves between flushes, which is audible as choppiness
even though the first chunk arrives in a third of a second. The DGX never
starves, so it streams smoothly.

Deficit per reply (request time − audio duration): median 0.39 s, p90 0.94 s;
only 3 of 41 utterances need more than 1 s. So starting playback after ~1.0 s
of buffered audio would remove essentially all underruns at a cost of about
+0.7 s onset (≈1.0 s TTS first audio, ≈4.4 s end-to-end) — still much better
than the 5.5 s whole-WAV run and only slightly behind DGX.

### Chunk-seam check (rules out codec seams as the cause)

A 0.25 s-interval stream of the test sentence (3.36 s audio, 13 seams) was
compared with an unstreamed render. Windowed |sample delta| at chunk seams
sits inside the normal speech distribution (median 0.0043 vs 0.0069 globally;
percentiles 6.5-97.8), i.e. no systematic clicks or discontinuities at flush
boundaries. The perceived roughness is therefore buffer starvation, not the
streaming decoder.
