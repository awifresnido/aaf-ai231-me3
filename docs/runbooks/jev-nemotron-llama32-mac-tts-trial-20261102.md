# Jev + Nemotron + Jetson Llama + MacBook Qwen3 TTS trial

Activated **15:56:06 Asia/Manila** on 2026-11-02. The only selected
pipeline change from the completed Jetson Llama/DGX Aiden trial is
`TTS_BACKEND=mac_qwen`. Nemotron ASR, Jev 1.14.0, Jetson GPU Llama 3.2 3B
as the small model, GLM 5.3 Flash fallback, Aiden voice, Pi MCP, Jetson
SQLite state and speakerphone settings remain selected. Experiment:
`jev-nemotron-jetson-llama32-mac-qwen3-aiden-20261102`. Human trial completed;
median end-to-end reply onset **5.478 s** across 30 measured replies. See the
[TTS comparison](../profiling/jev-llama32-tts-comparison-20261102/comparison.md).

The first startup greeting generated valid Mac audio in **5.489 s**, but
Pipecat's default three-second idle audio-context timer marked the context
empty before the whole-WAV response arrived. Playback began after the context
was recreated, with a misleading no-audio error. The Mac adapter now keeps
its context open until the bounded 45-second HTTP request can finish
(`stop_frame_timeout_s=47`). Service restarted at **15:57:31 Manila**, run
**`9c5da96c89`**. The corrected greeting produced first audio in **5.618 s**
and played without the no-audio error.
Pi log offset for this corrected run: **8,644,656**. The adapter source hash
on Pi is `8578cdb83506e3e6056fbbdcf4214f3e8d837f5a87e5aaa36f1a5bf806361812`.

The MacBook MLX 4-bit Qwen3 CustomVoice server responds at its own
`127.0.0.1:8099`. Two existing SSH forwards expose it to the Pi at
`127.0.0.1:18099`. Its `/health` responded HTTP 200, and an actual Pi
adapter preflight of “Ready for the next voice trial” produced 92 PCM frames
and 88,320 PCM bytes in **2.977 s**, without an error. The server returns a
whole WAV, so first audio cannot arrive until generation finishes. This
preflight is synthetic and does not count as an end-to-end voice latency.

Pi log activation byte offset: **8,609,958** in
`/home/aldwinrpi4/voice-agent/me3-local-audio.log`.
Private pre-switch configuration backup:
`/home/aldwinrpi4/voice-agent-backups/jev-llama32-mac-tts-20261102-155602/private-env`.
Restoring that file and restarting `me3-local-audio.service` selects the
prior DGX Qwen3 Aiden backend. The TTS SSH forwards are transient and must
be restored after a reboot. Implementation changes remain uncommitted.
