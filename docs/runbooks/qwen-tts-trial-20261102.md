# DGX Qwen TTS end-to-end trial — 2026-11-02

User requested the current `laya-integration` voice pipeline with TTS changed
to **`Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`**, hosted on DGX port **8001**.
Run **`147f31abef`**, experiment **`laya-glm-qwen-dgx-20261102`**, Pi PID 11068
at startup. Pipeline ready at **10:23:46 Asia/Manila**; greeting playback began
at **10:24:02**. Human trial completed, approximately **10:24–10:35**.

## Completed live results

There were **30 native timed replies** from 34 speech-start events: five initial
checks, 14 direct-set replies (turns 7–21), and 11 contextual replies (22–34).
Set boundaries are inferred from command content. Turns 6 and 11 had no final
ASR. Fragment pairs 28/29 and 33/34 each produced one reply; the second IDs
retain native latency from the preceding speech end. They are excluded from
the stricter same-turn playback sample (28 replies).

| Measurement | Median | P95, nearest rank | Sample |
|---|---:|---:|---:|
| Direct speech end to software bot start | 3.809 s | 9.301 s | 14 replies |
| Contextual speech end to software bot start | 4.668 s | 7.726 s | 11 replies |
| All human native end-to-end | 4.321 s | 9.301 s | 30 replies |
| Strict speech end to first playback write | 4.201 s | 9.297 s | 28 replies |
| Laya CPU server classification, successful results | 0.748 s | 0.802 s | 27 calls |
| Laya Pi client classification wait, successful results | 0.766 s | 0.823 s | 27 calls |
| Qwen first PCM, first request of each reply | 0.171 s | 1.169 s | 30 requests |
| Qwen first PCM, all successful human requests | 0.163 s | 0.505 s | 41 requests |
| Qwen full request, all successful human requests | 0.750 s | 3.225 s | 41 requests |

The previous Magpie run had direct/contextual medians **4.807 / 6.131 s**;
this run is about **1.00 / 1.46 s lower**. Prior first TTS byte medians were
**0.991 / 0.998 s**, versus first-response Qwen PCM **0.173 / 0.171 s** in
these sets. These are observational comparisons: wording, routing, state and
tool calls changed. They do not isolate a causal TTS improvement or establish
performance on an exactly matched replay. Physical acoustic onset is unmeasured.

Several similar command cases illustrate the practical change: direct time
**2.460 → 1.656 s**, direct weather **3.827 → 3.083 s**, thermostat twenty
**5.027 → 4.348 s**, blue lights **4.807 → 3.899 s**, room too bright
**5.899 → 4.947 s**, and alarm six **6.362 → 4.031 s**. Prior numbers use
estimated speech end to playback; current native bot-start differs from its
first playback write by only a few milliseconds on these clean turns.

### Delays and failures

- Turn 5: Qwen first PCM **11.371 s**, including **11.312 s before HTTP
  headers**; complete request **16.523 s**, first voice **14.401 s** after
  speech end. Pipecat marked the audio context empty after about three seconds,
  then recreated it when late audio arrived. No backup TTS voice was selected.
  The trace does not distinguish DGX queuing/compute from network wait.
- Turn 13: **9.301 s** reply. Smart Turn judged the short message-body follow-up
  incomplete; Laya then selected small talk, the local reply path added time,
  and GLM eventually attempted messaging. Qwen first PCM was only **0.169 s**.
  Messaging reported missing configuration rather than successful delivery.
- Turn 31: Manila time **7.680 s**, dominated by the GLM/tool/text path;
  Qwen first PCM **0.179 s**. Context recovered the time intent despite ASR
  losing part of the question.
- Turn 32: the volume-down response began in **4.668 s**, but its second
  sentence failed with `RemoteProtocolError` after **0.359 s**, emitting no
  audio for that request. The first sentence had already played.
- Laya had **one 2.002 s timeout**, **one HTTP-status failure**, and **two
  interrupted classifications**, separate from 27 completed classifications.
  The HTTP failure followed a cancelled fragmented utterance; status code and
  server-side cause were not captured. GLM supplied the eventual responses.

### User-reported voice variation

The user heard different voice types and qualities. The client selected
**Vivian throughout**, and the log contains only **QwenTTSService**, with no
Magpie fallback. Adapter requests fix `voice=vivian`, English, and mono PCM16
at 24 kHz; the live Pulse sink input is also mono PCM16 at 24 kHz.

Responses are synthesized as independent sentence requests without a style
instruction, seed or shared acoustic prompt. Sentence boundaries are therefore
a candidate for continuity differences, not a proven acoustic diagnosis.
[Qwen's official speaker table](https://github.com/QwenLM/Qwen3-TTS#custom-voice)
lists Vivian as Chinese-native, Ryan and Aiden as English-native, and recommends
native-language speakers for best quality. This is another candidate to test.
The slow context recreation and failed follow-up also affect continuity.

No trial waveform or DGX-side speaker/request trace was captured, so logs cannot
verify that the server rendered the requested identity consistently, measure
voice similarity, or rule out playback artifacts. The next controlled check
should compare repeated identical English text with fixed Vivian versus an
English-native speaker, then compare separate-sentence and whole-response
synthesis. Keep that check separate from the completed benchmark. No model,
voice or runtime setting was changed during this assessment.

Results: [summary](../profiling/qwen-tts-trial-20261102/benchmark-summary.json),
[per-turn timings](../profiling/qwen-tts-trial-20261102/per-turn-timings.md),
and metadata-only `timing-events.jsonl` in the same directory. Raw log remains
outside the repository under `/tmp/qwen-live-147f31abef.log`.

## Selected path and access

- ASR stays **Jetson Nemotron**, the existing direct streaming gRPC path.
- Routing stays **ThinkPad CPU Laya + GLM**, with the existing Llama small-talk
  path, thresholds, deadlines, prompts and tool policies. Jev/VPS fallback remain off.
- `TTS_BACKEND=dgx_qwen`, `DGX_TTS_VOICE=vivian`, output **24 kHz mono PCM16**.
- `DGX_TTS_BASE=http://127.0.0.1:18001` on Pi forwards through the ThinkPad to
  DGX **`10.153.60.233:8001`**. The key already in the Pi private environment
  authenticated successfully and `/v1/models` returned the exact model ID.
- The Pi's Laya reverse tunnel had disappeared after reboot; it was restored.
  The resident ThinkPad classifier was already healthy. Both reverse forwards
  currently share a temporary SSH process; they are not installed user units.
- Pi MCP, Jetson SQLite/NVMe state, speakerphone/AEC, VAD 0.3 s, Smart Turn
  two threads, pacat 150 ms and queued diagnostics remain unchanged.

The current `main` ref retains a paused `dgx_services.py` implementation.
Its TTS processor handles only `TTSSpeakFrame` and waits for a complete WAV;
it is not suitable for normal streamed GLM text in this pipeline. The new
`qwen_tts.py` subclasses Pipecat's `TTSService`, covering direct tool receipts,
LLM text aggregation, native audio contexts, interruption and metrics.
No switch to DGX ASR or the old paused acoustic-feedback configuration occurred.

## Streaming contract and checks

The actual server OpenAPI schema documents CustomVoice, `voice=vivian`, PCM,
`sample_rate`, `stream` and `stream_format`. The adapter requests
`stream=true`, `stream_format=audio`, `response_format=pcm`, 24 kHz, English.
This avoids the default SSE response and avoids treating WAV headers as PCM.
Audio frames carry their native TTS context ID. Incomplete/empty/unexpected
audio returns an error without automatic retry or a mid-stream voice switch.

All **92 tests passed on Pi**. Tests cover streaming before full completion,
PCM alignment, failure/no retry, cancellation and both direct-speech and GLM
text through actual Pipecat audio contexts. Real DGX adapter preflights also
produced audio for both paths, using a sink rather than physical speaker output.

Real adapter first PCM waits were **0.280 s** and **0.236 s**. A separate
warm endpoint probe received a first body chunk in **0.097 s**. The earlier
non-streaming WAV probe took **3.780 s** to complete. These sequential probes
use different cache/warmup conditions and are **not a controlled speedup
estimate or end-to-end voice benchmark**.

Live startup validated Qwen audio and speakerphone playback: first PCM
**0.163 s**, full HTTP request **1.056 s**, producing **6.24 seconds** of audio
for the greeting. Greeting is turn 0 and is excluded from human test statistics.
Completed human ASR, routing and total speech-end-to-response results appear above.

## Capture and assessment

Main log: `/home/aldwinrpi4/voice-agent/me3-local-audio.log`.
New startup begins at byte **4580795**. Match run **`147f31abef`**.

Pi RAM traces: `/dev/shm/voice-agent-diagnostics/147f31abef/pi-*.jsonl` and
`mcp-*.jsonl`; Jetson has the matching `state-*.jsonl` worker trace.

For each user turn record:

- Existing Laya `classifier_result` client wait, server inference and overhead.
- `tts_qwen_first_audio`: HTTP-header wait and first complete PCM-frame wait,
  keyed by captured turn and TTS context ID. These are client-observed durations,
  not isolated DGX GPU inference measurements.
- `tts_qwen_complete`: complete HTTP duration, generated audio bytes/duration.
- `tts_qwen_failure` or `tts_qwen_cancelled`: elapsed wait and emitted byte count;
  do not count stopped metrics as successfully delivered first audio.
- Native TTFB/TTFA and `native_user_bot_latency` / earliest
  `first_playback_write`: speech-end to first software response/playback.
- ASR absence, wrong routes/arguments, interruptions and repeats separately
  from successful-reply medians. Physical acoustic onset is not independently measured.

Repeat the prior direct and contextual sets, waiting for each response and
noting their boundary. Compare per-command timings and audio quality with the
Magpie run `26c376b1c3`. Conversation reset on restart; durable state was retained.
The existing argument-guard and pending-confirmation limitations were not changed.

## Rollback and status

Private backup:
`/home/aldwinrpi4/voice-agent-backups/qwen-tts-20261102-102331/`.
Restore `voice-agent-env.before` to `~/.voice-agent-env` (mode 600) and restart
`me3-local-audio.service` for the prior selection. Alternatively explicitly
select `TTS_BACKEND=magpie` and restore the prior experiment marker. The backup
also contains the prior `bot.py`; the new Qwen module can remain unused.
Do not reset databases or change ASR/audio for TTS rollback.

[Activation metadata, real adapter preflight and test record](../profiling/qwen-tts-trial-20261102/)
contain no key values or audio recordings. New implementation changes are
uncommitted on top of `e020464`; model placement remains ThinkPad/DGX as described.
