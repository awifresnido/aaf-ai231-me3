# Jev + DGX Qwen2-Audio ASR/small-model trial — 2026-11-02

The user requested returning to Jev and testing DGX port **8000**,
**`Qwen/Qwen2-Audio-7B-Instruct`**, as the small model, asking whether its
audio/LLM capabilities fit the configuration. This trial selects it for
**both transcription and the small-model role**. An optional clarification
was offered; in its absence this interpretation was stated before activation.
Qwen3 **Aiden** TTS and GLM **`z-ai/glm-5.3-flash`** remain selected.

Activated **12:44:50 Asia/Manila**, run **`72afa542c5`**. Pipeline ready
**12:45:04**, greeting first playback **12:45:19**. Startup first PCM
**0.244 s**, complete greeting HTTP request **1.766 s**. Human trial completed.

## Completed latency comparison

Main command window **12:48:33–12:55:12 Manila**, turns **3–30**. Earlier
greeting/refusal exchanges **0–2** are retained separately from the main
command statistics. There were **27 native reply onsets**: 16 direct-set
replies (3–19), one transition hearing check (20), and ten contextual replies
(21–30). Bounds are inferred from content. Turn 9's reply was interrupted;
turn 10 had no independent reply, and turn 11 inherited timing from its
preceding ASR segment. These are reply-onset statistics, not task success.

All earlier rows below used **Nemotron ASR and Llama as the small model**.
The current row uses **Qwen2-Audio for both roles**. Every row uses Qwen3 TTS.

| Router / TTS voice | Direct median | Context median | Overall median | Timed onsets |
|---|---:|---:|---:|---:|
| Jev / Aiden, Nemotron + Llama | **1.477 s** | 4.960 s | **2.559 s** | 23 |
| Jev / Ryan, Nemotron + Llama | 2.668 s | 4.975 s | 3.188 s | 23 |
| Jetson CUDA Laya / Aiden | 3.259 s | **3.980 s** | 3.448 s | 27 |
| ThinkPad CPU Laya / Vivian | 3.809 s | 4.668 s | 4.321 s | 30 |
| **Current: Jev / Aiden, Qwen2-Audio ASR + small model** | **4.433 s** | **4.502 s** | **4.494 s** | **27** |

The current overall median is about **76% higher** than the previous
Jev/Nemotron/Llama/Aiden sample; direct median is about **3×** its earlier
value. Context median is a little lower than that earlier sample, but higher
than the Jetson Laya sample. Wording, model roles, state, route mix and remote
waits differ, so these are observational comparisons rather than controlled
voice/model speed or accuracy estimates.

### Current layers and tails

| Measurement | Median | P95, nearest rank | Sample |
|---|---:|---:|---:|
| Native speech end to software response | **4.494 s** | 9.661 s | 27 onsets |
| Direct native response | **4.433 s** | 29.884 s | 16 onsets |
| Context native response | **4.502 s** | 9.380 s | 10 onsets |
| Qwen2-Audio transcription HTTP | **0.744 s** | 1.264 s | 28 completed segments |
| ASR queue wait | **0.0035 s** | 0.0041 s | 29 segments |
| Speech end to final transcript | **1.052 s** | 1.571 s | 28 markers |
| Jev successful client wait | **0.290 s** | 0.343 s | 25 calls |
| Qwen3 first PCM | **0.172 s** | 0.386 s | 40 started requests |
| Qwen3 complete request | **0.843 s** | 2.251 s | 39 completed requests |

Transcription HTTP ranged **0.463–2.050 s**. Unlike streaming Nemotron, the
new ASR request starts after VAD closes the segment, so its generation is
added after speech stops. Queueing was negligible. Jev and typical TTS
first-audio time stayed near their prior Jev/Aiden values (**0.283 / 0.165 s**).
Green-lights turn 4 also had an endpoint wait: its transcript arrived at
0.906 s, while routing began around 3.3 s after speech end. ASR HTTP alone
does not explain every longer response.

Five replies used fast tools, median **2.358 s**; 22 timed replies used GLM,
median **4.693 s**. There was **one 1.202 s Jev timeout** (23), followed by
GLM fallback.

The largest outlier, turn **6**, took **29.884 s** to begin speaking. Its
Qwen3 request waited **26.697 s** for first PCM and completed in **33.982 s**.
Pipecat declared the context empty after about three seconds and later
recreated it when audio arrived. This is a separate TTS stall, not ASR time.
All 39 completed human TTS requests returned audio; one additional request
(9) was cancelled after emitting some audio. No captured HTTP TTS failures
occurred. Completion time can include network/server and output backpressure.

### Transcription-contract and small-model findings

Transport success did not guarantee a faithful transcript. The private
context history shows ASR output containing:

- Model refusals or meta-commentary, including claims that it is a text-only
  platform or cannot hear audio (initial checks and 10, 12, 20).
- Natural-language no-speech reports (6, 9) that did not equal the exact
  `[NO_SPEECH]` sentinel, so the adapter forwarded them as user speech.
- Transcript wrappers (5, 7, 8, 19) rather than only spoken words.
- Answer-like weather and clock statements (16–18, 28). Without recorded
  audio, the exact intended words and recognition error rate cannot be proven.

The transcription-only prompt was therefore not a reliable contract for this
live model/serving configuration, despite passing a synthetic imperative-command
preflight. These outputs changed Jev's inputs and caused GLM to respond to
model-generated commentary. There were **29 main-window ASR requests**:
28 text outputs and one exact no-speech sentinel, with no HTTP failures.
One turn had two segments; observer turn IDs are not one-to-one with segments.

Crucially, the configured Qwen2-Audio **conversational small-model role had
zero calls**. No turns entered accepted `route_smalltalk`; all chat replies
came from GLM. Only one model argument-extraction attempt occurred (30), took
**1.258 s**, failed validation and reached GLM. Other fast arguments were
deterministic. This run primarily evaluates Qwen2-Audio as ASR and does not
establish its conversational small-model latency or accuracy.

The earlier Jev/Nemotron/Llama/Aiden run remains the best observed direct and
overall latency sample. A useful next isolation is **Nemotron ASR + Jev +
Qwen2-Audio only as the small model**, with explicit accepted small-talk and
extraction cases. Do not count replies to non-transcription outputs as
successful voice-command recognition. No settings were changed in this review.

### Measurement checks and artifacts

One old-response playback write appeared under turn 9 at 0.529 s, before its
own TTS audio. The analysis excludes writes preceding the turn's first TTS
PCM; the actual new reply onset was **2.475 s**. Turn 11 has no same-turn VAD
end but native latency **2.037 s** spans the preceding reminder segment. Thus
26 replies have aligned same-turn playback and 27 have native onset timing.
Primary comparisons consistently use native onset. Physical acoustic onset,
WER and ground-truth task accuracy were not measured.

Saved [comparison table](../profiling/jev-qwen2-audio-trial-20261102/comparison.md),
[summary](../profiling/jev-qwen2-audio-trial-20261102/benchmark-summary.json),
[per-turn timings](../profiling/jev-qwen2-audio-trial-20261102/per-turn-timings.md),
and metadata-only `timing-events.jsonl`. Raw speech/context log and Pi/MCP
trace capture remain outside Git as `/tmp/jev-qwen2-audio-live-72afa542c5*`.
The selected pipeline remains active; assessment made no runtime/source change
and required no test-suite rerun.

## Model roles and verified endpoint capabilities

[Qwen's model card](https://huggingface.co/Qwen/Qwen2-Audio-7B-Instruct)
describes audio understanding, voice chat and textual responses to spoken
instructions. It is an audio-language model capable of transcription and
language generation. In this pipeline those are **separate calls**, because
Jev must receive a transcript before deciding the downstream path:

```text
speakerphone/AEC audio
  -> VAD-bounded Qwen2-Audio transcription (DGX :8000)
  -> Jev classification
  -> direct validated tool / Qwen2-Audio small reply or extraction / GLM
  -> existing Qwen3 Aiden streaming TTS (DGX :8001)
```

The small-model slot replaces ThinkPad Llama; the ASR slot replaces active
Jetson Nemotron calls. Neither checkpoint/container was removed or changed.
The user can retain only the small-model replacement by selecting
`ASR_BACKEND=nemotron`; the new ASR module remains optional.

Actual `/v1/models` on port 8000 returned the exact Qwen2-Audio model, maximum
context 8192. Live OpenAPI and real requests confirmed:

- `/v1/chat/completions` accepts text-only messages and WAV `input_audio`.
- Audio transcription uses chat with a transcription-only instruction;
  this deployment does not advertise `/v1/audio/transcriptions`.
- Text-only chat and JSON-shaped outputs work, but requesting JSON schema
  does **not** guarantee a valid extraction from this model/deployment.

DGX port 8000 is reached from Pi **`127.0.0.1:18000`**, through a new temporary
ThinkPad reverse SSH process to **`10.153.60.233:8000`**. The existing port
18001 TTS forward is unchanged. Credentials remain in the private Pi
environment and a mode-600 key file outside Git; no key values are in artifacts.

## Implementation and preserved configuration

New native **`QwenAudioSTTService(SegmentedSTTService)`** integrates with the
existing upstream VAD broadcasts and Pipecat transcription lifecycle. It does
not use the old paused DGX processor, which depended on different stop frames
and is not selected by the active speech builder.

`ASR_BACKEND=dgx_qwen2_audio` inside `SPEECH_MODE=direct` selects the adapter.
It sends mono PCM16 WAV at 16 kHz, with the SDK's default 0.5-second trailing
silence padding (no extra real-time sleep). Transcription runs off the audio
path. It requests literal speech rather than an answer or tool execution.
Complete transcripts are finalized; `[NO_SPEECH]` creates no user message.
Invalid/truncated/non-text completions, tool calls, invalid WAV and HTTP errors
fail without automatic retry or silent ASR switching. Segments over 35 seconds,
including padding, are rejected rather than silently truncated.

ASR request timeout is **15 seconds**. Existing VAD **0.3 s**, Smart Turn
**two threads**, speakerphone/AEC and volume, pacat **150 ms**, MCP placement
on Pi, Jetson SQLite/NVMe persistence, GLM endpoint/prompt, Qwen3 TTS and
queued diagnostics are preserved. Jev uses **1.14.0**, **1200 ms**, gate
**0.90 / 0.20**. Small-model deadline remains **2500 ms**, secondary URL blank.
Conversation resets on restart; durable state is retained.

Qwen2-Audio is selected through existing `SmallModelClient` configuration:

```text
ROUTER_MODEL=jev
ASR_BACKEND=dgx_qwen2_audio
DGX_ASR_BASE=http://127.0.0.1:18000
DGX_ASR_MODEL=Qwen/Qwen2-Audio-7B-Instruct
DGX_ASR_TIMEOUT_SECS=15
SMALL_LLM_PRIMARY_URL=http://127.0.0.1:18000
SMALL_LLM_PRIMARY_PROTOCOL=openai
SMALL_LLM_PRIMARY_MODEL=Qwen/Qwen2-Audio-7B-Instruct
SMALL_LLM_MODEL=Qwen/Qwen2-Audio-7B-Instruct
VAD_EXPERIMENT=jev-qwen2-audio-asr-small-qwen3-aiden-20261102
```

`SMALL_LLM_PRIMARY_API_KEY_FILE` points to the private key file whose path is
recorded in sanitized activation metadata. Only `bot.py` and the new optional
ASR module were deployed; router/argument policies were not changed.
The Jetson Laya endpoint remains available but is deselected and not called.

## Validation and known limitation

**105 tests passed on Pi in 8.947 seconds**, including transcription payload,
finalization, no-speech handling, legitimate spoken apologies, bad/truncated
responses, invalid audio, original-turn metadata, cancellation and actual
Pipecat VAD/segmentation processing while HTTP transcription is pending.

An actual native pipeline preflight fed synthetic 16-kHz speech through
**Silero VAD + Smart Turn + DGX Qwen2-Audio + Jev**, ending in a **mocked MCP
receipt**. No device state or physical speaker playback occurred. The expected
`control_lights` arguments arrived; Qwen ASR request **0.700 s**, Jev
**0.283 s**, negligible synthetic tool time. This is not a live voice benchmark.

Actual small-client checks: conversational reply **0.492 s**, valid thermostat
extraction **1.006 s**. **Light-color extraction was rejected** (1.334 s on
repeat): an earlier captured response included malformed JSON, trailing
explanation and a lowercase color incompatible with the existing contract.
The JSON-schema request alone did not prevent it. Existing parsing/validation
correctly returned no arguments, allowing GLM fallback. This limitation may
affect tool-path latency; no validation was relaxed to make the preflight pass.
An initial all-success adapter probe failed its color-extraction assertion;
that is recorded as a model/deployment limitation rather than a test pass.

## Capture and assessment

Pi log `/home/aldwinrpi4/voice-agent/me3-local-audio.log`, new startup byte
**6760685**. Select run **`72afa542c5`**. Matching Pi/MCP traces are under
`/dev/shm/voice-agent-diagnostics/72afa542c5/`; Jetson has matching state-worker
traces. Exclude greeting and distinguish self-hearing/untimed exchanges.

- `asr_qwen2_start/complete/no_speech/failure/cancelled` record captured turn,
  segment ID, audio duration/bytes, queue wait and HTTP duration. Transcription
  content is not duplicated in these metadata events. The ordinary private
  Pipecat speech log still carries transcripts for assessment.
- `asr_qwen2_http` spans isolate the HTTP phase. Total ASR onset also includes
  VAD detection, queue wait and segment handling. This ASR is per-segment,
  unlike the preceding streaming Nemotron configuration.
- Existing Jev/argument/MCP/GLM/Qwen-TTS timings and earliest playback/native
  response measurements are retained. The legacy `llama_s` small-talk field
  and extraction label `llama` now refer to the configured **Qwen2-Audio**
  small client; they do not imply Llama was called. Read the selected model
  in configuration/activation metadata. Small-model input scope remains the
  latest utterance; pending follow-up limitations are not fixed in this trial.

Repeat direct and contextual commands. Assess transcript completeness and
accuracy, ASR queueing, Jev paths, small-model extraction/replies, GLM escalation,
TTS, total software onset, missed turns and action correctness. No raw audio
recording is enabled. Compare with Jev/Aiden `f0c87b3a33` descriptively: both
ASR and the small model changed, and two Qwen calls can occur in one turn.

## Rollback and restart

Private backup:
`/home/aldwinrpi4/voice-agent-backups/jev-qwen2-audio-20261102-124450/`.
`voice-agent-env.before` restores Jetson Nemotron + ThinkPad Llama + Jetson
Laya + Aiden when copied to `~/.voice-agent-env` and the voice service restarted.
To return specifically to the earlier **Jev/Nemotron/Llama/Aiden** trial,
restore that environment and explicitly select `ROUTER_MODEL=jev` with a fresh
experiment marker. The new optional ASR source can remain unused; the backup
also contains the prior `bot.py`. Configuration rollback does not undo state.

Port 18000 is a temporary SSH reverse forward, as is the existing DGX TTS
forward. Re-establish and authenticate both endpoints after reboot before
starting this selection. No Nemotron, Magpie, Llama or SQLite service was
stopped. New implementation/documentation changes remain uncommitted.

[Sanitized activation, native/small-model preflight and validation artifacts](../profiling/jev-qwen2-audio-trial-20261102/)
contain only synthetic test content and safe metadata, without credentials.
