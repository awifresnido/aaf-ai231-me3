# Jetson Llama 3.2 3B: DGX versus MacBook Aiden TTS

Both live trials used Nemotron ASR, Jev, Jetson GPU Llama 3.2 3B as the
small model and GLM 5.3 Flash fallback. The selected TTS backend changed.
Times are seconds from native speech end to first bot audio unless stated
otherwise. The whole human run after greeting is included; turn numbering,
utterances and route mix differ. P95 uses nearest rank.

| Measurement | DGX Qwen3 Aiden (`7373bf308b`) | MacBook MLX Qwen3 Aiden (`9c5da96c89`) |
|---|---:|---:|
| Measured reply onsets | 24 | 30 |
| **End-to-end median** | **3.901 s** | **5.478 s** |
| End-to-end p95 | 7.958 s | 13.758 s |
| End-to-end maximum | 8.774 s | 18.277 s |
| TTS first audio median | 0.171 s (41) | **1.725 s** (45) |
| TTS first audio p95 | 0.203 s | **4.200 s** |
| TTS request completion median | 0.649 s | 1.731 s |
| Jev classification median | 0.294 s (22) | 0.285 s (30) |
| Speech end to available ASR transcript median | 0.467 s (25) | 0.486 s (21) |
| Routes to GLM / fast tools / smalltalk | 20 / 2 / 2 | 22 / 7 / 1 |
| Jev classifier failures | 1 timeout | 0 |

MacBook TTS raised median end-to-end onset by **1.577 s** and TTS first-audio
time by **1.554 s**. The Mac service generates a complete WAV before sending
audio; the DGX service streams PCM early. This is the dominant observed
backend difference. Mac first-audio maximum was **6.010 s** during human
turns, and the run had no TTS HTTP failures. One Mac request was cancelled
after user interruption. The longest Mac end-to-end turn, **18.277 s** (turn
30), went through GLM and two TTS requests, so its entire delay cannot be
attributed to a single TTS call. The longest DGX turn was **8.774 s** (turn
23), also through GLM. Jev and the observed ASR transcript timing stayed
similar, but their measured samples do not cover every turn. The changed
route mix and wording prevent a controlled paired comparison or an accuracy
conclusion. These figures measure first audible response, not task success.

The restored live selection is DGX Qwen3 Aiden, run **`01993d4520`**, active
after **16:10:17 Manila**. Pi pipeline ready and greeting first PCM **0.175 s**.
Private environment backup from immediately before restoration:
`/home/aldwinrpi4/voice-agent-backups/restore-dgx-tts-20261102-161014/`.
The two trial timing-event files and `summary.json` contain metadata only.
