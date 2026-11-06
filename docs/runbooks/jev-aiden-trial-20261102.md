# Jev + DGX Qwen Aiden voice trial — 2026-11-02

The user requested a new live test using **Aiden** and **Jev** on the current
`laya-integration` branch. Run **`f0c87b3a33`**, experiment
**`jev-glm-qwen-aiden-20261102`**. Configuration changed at **10:46:24 Manila**.
Pi service PID **12850** is active; pipeline ready **10:46:37**, greeting first
playback **10:46:52**. Startup has no errors. Greeting first PCM **0.160 s**,
complete request **0.957 s**. Human trial completed, approximately
**10:47–10:52 Manila**. The user reported that this run felt very responsive.

## Completed latency results

There were **23 timed replies** across 26 speech-start events. All 23 have
both native latency and same-turn earliest playback timing; these differ by
only a few milliseconds. The greeting is excluded. Turns **1–13** form the
direct set (13 replies), **14** is a transition hearing check, and **15–26**
form the contextual set (nine timed replies). Boundaries are inferred from
command content. Two contextual segments (**22, 23**) lacked final ASR; turn
**25** executed a pause tool but was interrupted before spoken acknowledgement.
Those three segments are excluded from successful-reply latency statistics.

| Measurement | Median | P95, nearest rank | Sample |
|---|---:|---:|---:|
| Direct speech end to software bot start | **1.477 s** | 4.324 s | 13 replies |
| Context speech end to software bot start | **4.960 s** | 12.086 s | 9 replies |
| All human speech end to software bot start | **2.559 s** | 7.278 s | 23 replies |
| All human speech end to earliest playback write | **2.557 s** | 7.275 s | 23 replies |
| Fast tool route, speech end to bot start | **1.313 s** | 2.406 s | 9 replies |
| GLM route, speech end to bot start | **4.428 s** | 12.086 s | 12 replies |
| Successful Jev client classification | **0.283 s** | 0.414 s | 20 calls |
| Qwen first PCM, all successful human requests | **0.165 s** | 1.409 s | 30 requests |
| Qwen full request, all successful human requests | **0.616 s** | 1.758 s | 30 requests |

Fast tool examples: reminder **1.073 s** (explicit-reminder classifier bypass),
thermostat seventeen **1.196 s**, green lights **1.229 s**, volume up
**1.274 s**, time **1.313 s**, blue lights **1.323 s**, lights on **1.477 s**,
and weather **2.094 s**. Software onset is measured, not physical acoustic onset.

Against the immediately preceding Laya/Vivian run `147f31abef`, direct median
fell **3.809 → 1.477 s**, about **61% lower**. Overall reply median fell
**4.321 → 2.559 s**. Context median **4.668 → 4.960 s** did not improve.
Successful classifier client wait fell **0.766 → 0.283 s**; typical Qwen
first PCM stayed essentially unchanged (**0.163 → 0.165 s**).

Jev accepted explicit light colors and thermostat settings into the direct
path where the prior Laya run used GLM. For example, blue lights changed
**3.899 → 1.323 s**, and green lights **4.114 → 1.229 s**. The evidence supports
faster classification and avoidance of GLM on those commands as contributors.
Router, speaker, wording, tool state and route mix changed, so this is an
observational comparison, not an isolated causal model or speaker benchmark.

### Remaining delays and correctness limits

- Jev completed 20 classifications and hit **two 1.201 s timeouts**, on the
  message request (5) and green preference (20). Both fell through to GLM and
  eventually produced replies. These timeouts are separate from successful
  classifier percentiles. One reminder bypassed classification, and the
  compound stop/lights-off command bypassed it for GLM.
- Too-bright turn **16** took **7.231 s**. Qwen first PCM took **3.719 s**,
  with **3.668 s before HTTP headers**. Pipecat declared the audio context
  empty at about three seconds, then recreated it when late audio arrived.
  The reply played. The existing late-context lifecycle problem remains.
- Loud-music turn **24** took **12.086 s**. GLM generations took **8.172 s**
  before and **2.028 s** after the volume tool; MCP itself took about **39 ms**,
  and first Qwen PCM **0.495 s**. This tail was predominantly in the GLM path.
- Rephrased direct volume-down turn **26** took **2.406 s**, including a
  slower Qwen first PCM **1.409 s**. All **30 human Qwen requests completed**;
  there were no captured HTTP synthesis failures or Qwen cancellation events.
- Two segments had no final ASR (22, 23). Turn 25's GLM pause action completed
  before the next utterance interrupted its spoken acknowledgement; no
  independent reply is counted for it.
- Responsiveness does not establish conversational correctness. The
  message-body follow-up (6) became a small-talk greeting rather than a
  `send_message` call. The heat complaint (17) also went to small talk; the
  next room-specific follow-up reached GLM and changed the thermostat.
  Contextual brightness and alarm choices were below Jev's acceptance gate
  and were correctly escalated for GLM interpretation.

No audio recording was captured, so voice consistency is not objectively
assessed here. Runtime settings and model selection were unchanged during
analysis; Jev + Aiden remains active. No source tests were rerun for log analysis.

Saved [summary](../profiling/jev-aiden-trial-20261102/benchmark-summary.json),
[per-turn timings](../profiling/jev-aiden-trial-20261102/per-turn-timings.md),
and metadata-only `timing-events.jsonl` alongside them. Raw log and Pi/MCP
capture remain outside the repo as `/tmp/jev-aiden-live-f0c87b3a33.log` and
`/tmp/jev-aiden-live-f0c87b3a33-traces.tar.gz`.

Only three private settings changed from the previous Laya/Vivian run:

```text
DGX_TTS_VOICE=aiden
ROUTER_MODEL=jev
VAD_EXPERIMENT=jev-glm-qwen-aiden-20261102
```

Jev uses existing **`jev-1.14.0`**, **1,200 ms** deadline and **0.90/0.20**
acceptance gate. Laya is not invoked by this selection. Existing deterministic
argument parsing, bounded ThinkPad Llama extraction/small talk and GLM fallback
are retained. GLM is `z-ai/glm-5.3-flash`; the secondary small-model URL remains
blank. No cloud-escalation policy or routing prompt was changed.

TTS remains **`Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`** on DGX port **8001**,
accessed through Pi loopback **18001** and the temporary ThinkPad reverse SSH
tunnel. Aiden is explicitly requested with English and streaming mono PCM16
at 24 kHz. Jetson Nemotron ASR, Pi MCP, Jetson SQLite/NVMe state, speakerphone,
AEC, PCM volume, VAD 0.3 seconds, Smart Turn two threads, pacat 150 ms and
diagnostics remain unchanged. Conversation resets on restart; durable state
is retained. No source code was deployed or changed for this switch.

## Preflight and capture

A synthetic Aiden request produced 119,040 PCM bytes (2.48 seconds of audio),
first PCM **0.222 s**, full request **0.660 s**, without physical playback.
Jev classified a synthetic time question as `get_time` with probability 1.0 in
**0.472 s**; no tool executed. These are readiness checks, not live E2E results.
The unchanged Qwen implementation previously passed the 92-test suite; this
configuration switch does not constitute a new test-suite run.

Main Pi log: `/home/aldwinrpi4/voice-agent/me3-local-audio.log`, startup byte
**5145111**. Select `TURN_TIMING` records matching run **`f0c87b3a33`**.
Pi and MCP traces: `/dev/shm/voice-agent-diagnostics/f0c87b3a33/`; the Jetson
worker emits matching `state-*.jsonl` under its own diagnostics directory.
Greeting turn 0 is excluded from live command statistics.

Record Jev client classification duration, confidence/gate decisions, extraction
and tools, GLM waits, Qwen first PCM/full request/failure, and speech-end-to-first
playback/native bot-start latency. Jev does not expose the Laya-specific server
classification timing; client wait must not be labeled isolated model inference.
Count only the earliest playback per reply; retain missing-ASR segments,
fragment continuations, cancellations and partial speech separately.

Repeat direct and contextual command sets. Assess the user's reported voice
variation separately from route/tool correctness. This run changes both router
and speaker relative to `147f31abef`, so differences cannot independently
identify the causal contribution of either change. No trial audio recording
was enabled. Native timing does not measure independent acoustic onset.

## Rollback

Private configuration backup, mode 600:
`/home/aldwinrpi4/voice-agent-backups/jev-aiden-20261102-104624/voice-agent-env.before`.
Restore it to `~/.voice-agent-env` and restart `me3-local-audio.service` to return
to Laya + Vivian. Durable tool state is not rolled back by restoring settings.
The temporary DGX/Laya SSH forwards must be checked after a reboot.

[Sanitized activation metadata](../profiling/jev-aiden-trial-20261102/activation.json)
records configuration, preflight, source hashes and capture offset without keys.
New Qwen integration and trial documentation remain uncommitted for review.
