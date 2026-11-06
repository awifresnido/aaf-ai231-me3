# Jev + GLM live speakerphone results, 2026-11-01

Run **`2a664e268a`**, experiment `jev-glm-pi-mcp-nvme-20261101`.
User test: approximately **22:06:48–22:12:49 Asia/Manila**. Jev 1.14.0,
GLM 5.3 Flash via OpenRouter, Pi-hosted MCP, Jetson SQLite worker. Laya and
VPS small-model fallback remained off. No settings or services were changed
during this assessment; the same Pi PID 56818 remained active.

This page assesses the **initial test, through turn 20**. The user subsequently
identified turns 21 onward as contextual tool-deduction tests. Their
[separate assessment](jev-glm-context-results-20261101.md) covers turns 21–35:
eleven timed replies, two Jev timeouts and three cloud waits interrupted by
repetition. Do not generalize the initial window's no-Jev-timeout finding to
the full run. Both windows together have 25 timed replies at median 5.093 s,
excluding silent attempts and waits before interrupted/repeated requests.

**Fast routine tools worked in about two seconds, but this was not a reliable
end-to-end pass.** Five speech-detection segments had no final transcript or
reply. The user confirmed having to repeat commands after silence. Successful
replies also had substantial GLM and external-weather tails.

## Response latency and coverage

| Group | Timed replies | Median | Range |
|---|---:|---:|---:|
| All user replies with finite timing | **14** | **4.761 s** | **1.842–14.465 s** |
| Fast tools, excluding external weather | **4** | **2.049 s** | **1.842–2.233 s** |
| GLM-routed replies | **9** | **5.139 s** | **3.608–14.465 s** |
| Weather fast route, failed provider request | **1** | **9.597 s** | — |

The historical Llama-only median was **5.468 s** over 22 replies. This run's
completed-reply median is descriptively 12.9% lower, but the utterances differ
and the silent attempts have no finite response latency. It is **not a
controlled speedup or an improvement in overall command completion**. No
explicit second-pass boundary or repeated complete script was logged.

Latency begins at the VAD estimate of final speech end and ends at first
software bot speech/playback. First playback writes agree with native latency
within 8 ms for all 14 replies. Physical acoustic onset was not independently
measured. Repeat playback writes for later sentences are not new replies.
Nearest-rank p95 on only 14 samples is the maximum, 14.465 s; treat it as a
small-sample tail, not a stable production percentile.

There were **20 speech-start IDs**: one startup self-hearing segment, fourteen
transcribed user contexts with replies, and five segments without final ASR.
Some VAD starts could be noise, so these IDs do not establish a formal command
count or failure percentage. The user's confirmation establishes that actual
spoken commands were missed, but cannot identify the content of every silent
segment from these logs.

## The no-reply issue is before routing

| Turn ID | Speech detection began | Last VAD stop | Empty turn closed |
|---|---|---|---|
| 5 | 22:07:23 | 22:07:25.637 | 22:07:30.640 |
| 9 | 22:08:30 | 22:08:31.298 | 22:08:36.302 |
| 11 | 22:09:05 | 22:09:08.095 | 22:09:13.097 |
| 16 | 22:11:22 | 22:11:23.386 | 22:11:28.389 |
| 17 | 22:11:46 | 22:11:46.850 | 22:11:51.853 |

Each had VAD start/stop and **COMPLETE** Smart Turn analysis, but **no final
ASR transcript, routing context, Jev request, GLM request or TTS reply**.
The aggregator logged an empty stop with `strategy: None` roughly **five
seconds after the last VAD stop**. These were not Jev deadline failures or
slow cloud responses: the requests never reached either model.

This localizes the observed gap to the audio/ASR-result path before routing.
It does **not** distinguish bad/attenuated captured audio, ASR decoding or
finalization, streaming transport, or client handling. Interim ASR results and
per-segment input signal measurements were not captured. Jetson ASR Docker
logs returned no entries for this interval, so they did not resolve the gap.
No ASR transport error or reconnection was logged on Pi during the test.

Changing Jev confidence thresholds, replacing it with Laya, or increasing the
GLM budget cannot recover a command for which no transcript reaches routing.
The next diagnosis should capture per-segment audio frame counts/signal levels,
ASR interim/final response status and stream lifecycle, then compare the same
spoken phrase against a direct ASR probe. Keep the current routing benchmark
separate from that investigation. An explicit no-transcript recovery response
would also make this failure visible instead of leaving the user waiting.

## Jev and normal pipeline costs

- **14** Jev classifications including startup self-hearing; **13** were for
  user contexts. Median client wait **0.310 s**, range **0.268–0.399 s**.
  **No Jev timeouts** or router exceptions occurred.
- The reminder fast path bypassed Jev. All five fast tool routes used direct
  argument extraction; **no Llama argument extraction or small-talk completion
  occurred**. Thus this run does not measure ThinkPad Llama generation cost.
- Nine user contexts reached GLM: six non-`other` choices below the 0.90
  confidence gate and three `other` choices. Poorly transcribed speech is a
  visible contributor. Jev rejection is not evidence that GLM's subsequent
  interpretation was correct.
- Seven GLM tool contexts needed **two cloud calls each**—tool selection and
  post-tool response. Two hearing checks each needed one cloud call. Across
  these **16** calls, median first token was **1.113 s**, median complete call
  **1.295 s**; the latter ranged **1.037–11.053 s**. These timings include
  provider and network waiting and do not isolate model compute.
- Completed-turn endpoint/context readiness: median **834 ms**, range
  **702–879 ms**. First TTS byte: median **1.017 s**, range **0.903–1.182 s**.
  Nested/streaming stages must not be added as independent exact components.

## Where the longest waits went

| Turn | Path / task | First speech | Observed main cost |
|---|---|---:|---|
| 14 | Ambiguous music-volume transcript → GLM | **14.465 s** | First GLM call **11.053 s**, second **1.172 s**; MCP **36 ms** |
| 15 | Current weather → direct tool | **9.597 s** | Weather HTTP **7.441 s**, ending in `URLError`; no GLM call |
| 13 | Noisy light-color transcript → GLM | **8.607 s** | GLM calls **5.140 s + 1.276 s**; MCP **28 ms** |
| 10 | Noisy music request → GLM/catalog | **5.858 s** | Two GLM calls plus **1.111 s** catalog HTTP |

On turn 14, first token arrived at **1.667 s**, but that cloud call took
**11.053 s** to finish despite only **24 completion tokens**, including eleven
reasoning tokens. The logs support a long cloud-completion wait, not a claim
that large reasoning output or SQLite caused it. Provider versus network delay
cannot be separated here. Turn 13 similarly took 5.140 s for 27 completion tokens.

The weather MCP client reported a mechanically completed tool call because
the tool caught the provider error and returned a spoken failure. That is
**not successful weather retrieval**. The HTTP span identifies the failure.

## Storage and tracing stayed healthy

There were **12 MCP calls**: nine state-writing operations, one unconfigured
messaging request, one failed weather request and one time lookup. Non-HTTP
MCP calls had median **22.559 ms**. Nine writing-call commit totals had median
**3.444 ms**, maximum **4.171 ms**. All SQL spans were on Jetson's `state`
component; Pi retained the MCP server and tool logic.

The saved 1,239-event snapshot has no incomplete lines or unfinished spans and
reports no dropped events/write errors. One Pi event-loop lag of **135 ms**
occurred at startup/self-hearing, outside the user test; none was reported
during the measured user replies. There were no MCP transport or worker
exceptions. The weather HTTP `URLError` was caught inside its tool.

## Correctness and startup observations

- The startup greeting was transcribed back into the pipeline and generated
  an extra GLM response. Greeting turn 0 and self-hearing turn 1 are excluded
  from user latency statistics. This confirms startup echo remains unresolved.
- GLM executed a light color after a badly garbled transcript; the intended
  color cannot be verified from ASR text alone. Another noisy color request
  was interpreted as red. Do not count a schema-valid receipt as intent accuracy.
- A music-volume transcript lacked a direction; GLM nevertheless selected
  `volume_up`. The user’s intended direction is not established by that transcript.
- A messaging request with no stated message body produced model-invented
  message text and a `send_message` call. The tool returned **not configured**,
  so **no message was sent**. This exposes missing argument grounding on the
  GLM path; Jev's confidence gate does not validate cloud-selected arguments.
- A badly recognized music request produced an unrelated catalog result.
  Replies claimed playback/skip/volume changes although real music playback
  remains unimplemented; only catalog metadata/device state was updated.

There is no defensible overall intent-accuracy percentage without a labeled
reference for the actual intended speech, particularly the missing segments.
Preserve the no-reply cases and ambiguous actions in the assessment rather
than scoring only successful tool receipts.

## Evidence and current state

Sources: Pi run-specific main-log slice inspected locally, metadata snapshots
from Pi/MCP/Jetson, and the user's report of having to repeat commands. Raw
transcripts and full conversational prompts remain outside Git.

- [Per-turn metadata and latency summary](../profiling/jev-glm-live-20261101/voice-summary.json)
- [MCP/worker/HTTP trace summary](../profiling/jev-glm-live-20261101/stall-summary.json)
- [Saved trace snapshot](../profiling/jev-glm-live-20261101/capture/)
- [Activation and rollback](jev-glm-live-trial-20261101.md)

Jev + GLM remains selected, with the existing Pi MCP/Jetson state split and
speakerphone settings. No model, threshold, audio setting, database or service
was changed while inspecting this trial. All local review changes are uncommitted.
