# Jev + DGX Qwen Ryan voice trial — 2026-11-02

User requested Ryan in place of Aiden for another end-to-end latency and
performance test on the current `laya-integration` branch. Switched at
**11:03:13 Asia/Manila**. Human trial completed, approximately
**11:04–11:09 Manila**; results below.
Run **`9576b0bcb6`**; pipeline ready **11:03:27**, greeting first playback
**11:03:42**. Greeting first PCM **0.337 s**, full request **2.075 s**;
startup validation found no errors. These startup metrics are excluded from
the human trial statistics.

## Completed latency and performance results

There were **23 timed replies** across 24 speech-start events. Turn **6**,
between the message request and message-status follow-up, had no final ASR
and produced no reply. Its intended content cannot be recovered from timing
metadata. All other turns have native latency and same-turn earliest playback
timing, differing by only a few milliseconds. Greeting is excluded.

Direct set **1–15** has 14 replies; hearing check **16** is separated as a
transition; contextual set **17–24** has eight replies. Set boundaries are
inferred from command content. The direct set includes an additional compound
color/volume command and message-status follow-up relative to the Aiden test.

| Measurement | Ryan median | Aiden median | Ryan P95, nearest rank |
|---|---:|---:|---:|
| Direct speech end to software bot start | **2.668 s** | 1.477 s | 8.136 s |
| Context speech end to software bot start | **4.975 s** | 4.960 s | 6.567 s |
| All human speech end to software bot start | **3.188 s** | 2.559 s | 6.567 s |
| Fast tool route, speech end to bot start | **1.317 s** | 1.313 s | 2.357 s |
| GLM route, speech end to bot start | **4.419 s** | 4.428 s | 8.136 s |
| Successful Jev client classification | **0.285 s** | 0.283 s | 0.303 s |
| Qwen first PCM, all successful human requests | **0.170 s** | 0.165 s | 0.300 s |
| Qwen full request, all successful human requests | **0.624 s** | 0.616 s | 0.971 s |

Ryan fast-tool and GLM-path medians were nearly identical to Aiden's. Ryan
had **15/23 GLM replies**, compared with **12/23** for Aiden; eight fast-tool
replies and no local-small-talk replies, versus Aiden's nine and two.
The higher aggregate median is consistent with that changed route mix and
command wording. These runs do not establish an intrinsic voice-speed
difference. Router and source code were unchanged; persistent state, model
generation and remote server/network conditions are additional variables.

The **31 human Qwen requests all completed**, with first PCM **0.097–0.362 s**
and complete requests **0.247–1.045 s**. There were **no captured TTS errors,
cancellations or late-context recreation warnings**. Aiden's observed first
PCM maximum was 3.719 s, including an empty-context warning; its P95 was
1.409 s. Ryan's TTS timing had a smaller tail in this sample. This does not
show that voice choice caused the difference in server/network stalls.

All **20 Jev classifications completed**, with **no timeouts or failures**.
The reminder bypassed classification; two explicit compound stop/lights-off
requests bypassed it for GLM. The color/volume compound reached Jev as `other`
and then GLM. No tool-call errors appeared in the captured Pi/MCP spans.

### Representative replies and remaining delays

- Reminder **1.056 s**, red lights **1.237 s**, thermostat twenty-five
  **1.284 s**, direct time **1.315 s**, lights on **1.318 s**, contextual green
  preference **1.346 s**, volume up **1.560 s**, and current weather **2.357 s**.
- Longest turn **12**, compound green lights plus lower volume: **8.136 s**.
  Smart Turn judged both speech stops incomplete, delaying routing. GLM
  generations took **2.970 / 1.305 s** around the two tool calls, which took
  about **36 / 43 ms**. Qwen first PCM was **0.200 s**. Native latency uses
  the final estimated speech stop when a turn contains multiple stops.
- Dark-room turn **17**: **6.567 s**. Smart Turn initially judged it incomplete;
  Jev's lights choice was below the confidence gate and GLM turned lights on.
  First Qwen PCM was **0.183 s**. Endpointing and GLM remain the larger waits.
- Pronoun-based green follow-up **3** reached GLM at confidence 0.78 and took
  **3.759 s**; contextual green preference **21** was accepted at 0.91 and
  completed directly in **1.346 s**. Wording changes both route and latency.
- Manila time **23** reached GLM because Jev confidence was 0.77; reply
  **4.933 s**, first Qwen PCM **0.176 s**. The time tool was invoked.
- No message was sent after missing-ASR turn 6. The subsequent status reply
  correctly reported that it was still waiting for message content. These
  logs do not establish intended content or overall accuracy against audio.

Timings measure estimated speech end to software onset, not acoustic onset.
Silent ASR failure is kept outside reply percentiles. Voice quality and
identity consistency remain unmeasured without recorded audio or user ratings.
Jev + Ryan remains active; analysis made no runtime/source changes and required
no test-suite rerun.

Saved [summary](../profiling/jev-ryan-trial-20261102/benchmark-summary.json),
[per-turn timings](../profiling/jev-ryan-trial-20261102/per-turn-timings.md),
and metadata-only `timing-events.jsonl` alongside them. Raw log and Pi/MCP
capture remain outside the repository at `/tmp/jev-ryan-live-9576b0bcb6.log`
and `/tmp/jev-ryan-live-9576b0bcb6-traces.tar.gz`.

Only private settings `DGX_TTS_VOICE=ryan` and
`VAD_EXPERIMENT=jev-glm-qwen-ryan-20261102` changed. Jev **1.14.0** keeps its
**1,200 ms** deadline and confidence gate. GLM, ThinkPad Llama, Jetson Nemotron
ASR, Pi MCP, Jetson SQLite/NVMe state, speakerphone/AEC, volume, VAD 0.3 s,
Smart Turn two threads, pacat 150 ms and queued diagnostics are unchanged.
Conversation resets on restart; durable state is retained. No source code
changed or deployed for this selection.

Qwen **`Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`** remains on DGX port **8001**
via the temporary ThinkPad SSH reverse forward to Pi **127.0.0.1:18001**.
Requests use Ryan, English, streaming mono PCM16 at 24 kHz. The synthetic
preflight produced 165,120 bytes (3.44 seconds audio), first PCM **0.232 s**,
complete request **0.718 s**, without speaker playback. This is a readiness
check rather than end-to-end voice performance. The unchanged adapter's prior
92-test validation stands; no new test-suite run was needed for this switch.

## Capture and comparison

Main Pi log: `/home/aldwinrpi4/voice-agent/me3-local-audio.log`; new startup
begins at byte **5648153**. Select run **`9576b0bcb6`** `TURN_TIMING` records.
Matching Pi/MCP RAM traces are under `/dev/shm/voice-agent-diagnostics/9576b0bcb6/`;
the Jetson worker emits matching state traces. Exclude greeting turn 0.

Repeat direct and context-based command sets. Measure earliest speech-end to
playback/native response, Jev client wait, accepted routes/argument extraction,
GLM/tool waits, Qwen first PCM and full requests. Include missing ASR, repeated
commands, interruptions, late audio contexts and failures separately from
successful reply percentiles. Native timing is software onset, not a physical
acoustic measurement; Jev client wait includes network time.

Reference Aiden run **`f0c87b3a33`**: direct **1.477 s**, context **4.960 s**,
overall **2.559 s**, Jev successful client wait **0.283 s**, Qwen first PCM
**0.165 s**. Keeping Jev fixed makes this a better speaker comparison, but
utterances, GLM generation, server load and persistent state must still be
considered before claiming a causal difference. Evaluate response correctness
and user-reported voice consistency alongside latency. No acoustic recording
was enabled.

## Rollback

Private backup (mode 600):
`/home/aldwinrpi4/voice-agent-backups/jev-ryan-20261102-110313/voice-agent-env.before`.
Restore it to `~/.voice-agent-env` and restart `me3-local-audio.service` to return
to Jev + Aiden. Tool-state changes are not undone by configuration rollback.
The temporary SSH reverse forward needs verification after reboot.

[Sanitized activation metadata](../profiling/jev-ryan-trial-20261102/activation.json)
contains no key values. Implementation and trial documentation remain
uncommitted for review.
