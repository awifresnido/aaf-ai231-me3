# Jev + Nemotron + Jetson Llama + MacBook Qwen3 TTS (streaming) trial

Activated **19:26:20 Asia/Manila** on 2026-11-02, run **`23dff71cba`**,
experiment `jev-nemotron-jetson-llama32-mac-qwen-stream-20261102`.

This run isolates a single change from the completed MacBook Qwen3 Aiden
trial (`9c5da96c89`, median end-to-end onset 5.478 s): the MacBook TTS
transport now **streams PCM as the codec produces it** instead of returning one
complete WAV. Everything else is identical — Nemotron ASR, Jev 1.14.0 with the
same deadline/acceptance gate, Jetson GPU Llama 3.2 3B as the small model,
GLM 5.3 Flash fallback, Aiden voice, Pi MCP, Jetson SQLite state, VAD 0.3 s,
Smart Turn two threads, AEC/pacat settings and diagnostics.

## Configuration (unchanged except the transport)

```text
TTS_BACKEND=mac_qwen
MAC_TTS_BASE=http://127.0.0.1:18099        # Pi loopback → Mac 127.0.0.1:8099
MAC_TTS_VOICE=Aiden
MAC_TTS_TIMEOUT_SECS=45
MAC_TTS_STREAM=1                            # NEW: chunked PCM instead of whole WAV
MAC_TTS_STREAM_INTERVAL=0.25                # NEW: 0.25 s of audio per flush
ROUTER_MODEL=jev
SMALL_LLM_MODEL=meta-llama/Llama-3.2-3B-Instruct
VAD_STOP_SECS=0.3
ORCHESTRATION_MODE=two_brain_plusjev
SPEECH_MODE=direct / SPEECH_BACKEND=local
VOICE_DIAGNOSTICS=1 → /dev/shm/voice-agent-diagnostics/23dff71cba/
```

## What changed in code

* **Mac server** (`~/qwen3-tts/serve.py` on `192.168.5.9`): `POST /speak?stream=1`
  returns `Content-Type: audio/pcm`, `X-Sample-Rate: 24000`, `X-Channels: 1`,
  `Transfer-Encoding: chunked`. Each MLX `streaming_interval` flush is written
  and flushed immediately; `/speak` (no `stream`) still returns one WAV.
* **Pi adapter** (`pi/mac_qwen_tts.py`): `MAC_TTS_STREAM=1` switches `run_tts`
  to `httpx` streaming and yields `TTSAudioRawFrame` per HTTP chunk. Timing
  event names are unchanged (`tts_mac_first_audio`, `tts_mac_complete`,
  `tts_mac_cancelled`, `tts_mac_failure`) so the existing summariser works;
  records now also carry `stream: true` and `http_headers_s`.
  Deployed hash `a4fd0f1235b9d79b2d3db7300f453981f82b3d36a782e0c55dd3da11b8a5d15c`
  (previous whole-WAV build `8578cdb83506…`).

## Preflight (synthetic, not E2E)

Same text ("Ready for the next voice trial", Aiden), measured from the Pi
through the 18099 forward:

| transport | first audio | full request | audio |
|---|---:|---:|---:|
| whole WAV (`/speak`) | 2.02 s | 2.02 s | 2.00 s |
| streaming (`/speak?stream=1&interval=0.25`) | **0.32 s** | 2.00 s | 2.00 s |

Mac-side sweep (same utterance, 2.0 s audio): interval 0.4 → 0.63 s first
audio / 2.60 s total; **0.25 → 0.39 s / 2.66 s**; 0.2 → 0.19 s / 2.85 s.
0.25 s was chosen: first audio close to the DGX streaming baseline (0.171 s)
without the ~10 % total-generation penalty seen at 0.2 s.

Startup greeting (turn 0, excluded from live statistics): first audio
**0.404 s**, first audio median across its 10 sentence requests **0.423 s**,
audio 5.68 s, full request 6.69 s. The previous whole-WAV build greeted at
**5.618 s** first audio. No `empty audio context` error occurred.

Two startup quirks observed: the first request after a server restart took
54.7 s once (Metal kernel/page-in warmup) and 2.0–2.3 s on every repeat — the
preflight above is the steady-state figure.

## Running the human trial

Speak the same script/number of replies as the previous trial (~30 replies,
same wording) so the comparison stays usable. Greeting turn 0 is excluded.
Capture:

* `native_user_bot_latency` → end-to-end speech-end to first bot audio
* `tts_mac_first_audio.first_audio_s`, `tts_mac_complete.request_s`
* `classifier_result.classifier_s`, route events, classifier failures
* `asr_transcript.since_speech_end_ms` (finalised only)

## Summarise with the same checks

```bash
python3 scripts/summarize_tts_trial.py /dev/shm/voice-agent-diagnostics/23dff71cba \
    --label mac-stream
```

The script reproduces the published numbers of both earlier runs exactly for
end-to-end onset, classifier timing, ASR-to-transcript and route mix
(`7373bf308b`: 24 / 3.901 s median; `9c5da96c89`: 30 / 5.478 s median), so the
new column is directly comparable. TTS counts may differ by one request where
a cancelled utterance overlaps a turn boundary.

## Rollback

Recreate the prior whole-WAV Mac trial:

```bash
python3 /tmp/set_env.py TTS_BACKEND=mac_qwen MAC_TTS_STREAM=0 \
  VAD_EXPERIMENT=jev-nemotron-jetson-llama32-mac-qwen3-aiden-20261102
systemctl --user restart me3-local-audio.service
```

Restore the DGX Aiden selection:

```bash
python3 /tmp/set_env.py TTS_BACKEND=dgx_qwen \
  VAD_EXPERIMENT=jev-nemotron-jetson-llama32-dgx-qwen3-aiden-restored-20261102
systemctl --user restart me3-local-audio.service
```

Private backups from immediately before this switch:
`/home/aldwinrpi4/voice-agent-backups/mac-tts-stream-20261102-1923/`
(`mac_qwen_tts.py`, `.voice-agent-env`). The TTS SSH forwards on Pi ports
18099/18001/18000 are transient; verify them after any reboot.

Pi log: `/home/aldwinrpi4/voice-agent/me3-local-audio.log`, activation byte
offset **9,275,378**.
