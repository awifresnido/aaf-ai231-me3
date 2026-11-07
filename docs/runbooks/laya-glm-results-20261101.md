# Laya live benchmark: direct and contextual sets

Run `26c376b1c3`, 2026-11-01 Asia/Manila. User completed both a direct-command
set and a contextual set. Laya remained on ThinkPad CPU; GLM, Pi MCP, Jetson
SQLite, speakerphone/AEC and endpointing settings were unchanged while logs
were assessed. No settings were adjusted during this benchmark assessment.

**Laya classification was consistent at roughly 0.7 seconds, but the complete
agent did not demonstrate an end-to-end speed advantage.** Only time and
weather used direct MCP execution. Guard coverage, number-word routing, ASR
losses and context-blind small talk prevented broader fast execution.

## Measured layers and end-to-end latency

Sets are inferred from the utterance sequence: direct turns **3–15**, ending
with the compound stop/lights-off request; contextual turns **16–26**, beginning
with the dark-room statement. Startup greeting/echo turns **0–2** are excluded.

| Measurement | Direct set | Contextual set |
|---|---:|---:|
| Timed replies | **11** | **10** |
| Completed Laya classifications | **10** | **10** |
| Laya server inference p50 | **0.693 s** | **0.719 s** |
| Laya server inference p95 | **0.744 s** | **0.748 s** |
| Pi wait for Laya p50 | **0.716 s** | **0.739 s** |
| Pi wait for Laya p95 | **0.762 s** | **0.772 s** |
| End-to-end first-response p50 | **4.807 s** | **6.131 s** |
| First-response range | **2.460–34.543 s** | **3.306–9.024 s** |
| First-response p95, nearest rank | **34.543 s** | **9.024 s** |
| GLM / Llama / direct-MCP replies | **8 / 1 / 2** | **9 / 1 / 0** |

Across the **20 completed user classifications**, server inference p50/p95 was
**0.704/0.744 s**; Pi wait **0.723/0.762 s**. Median elapsed time outside the
server was **17.3 ms**. There were **no live classifier timeouts or response
validation failures**. One classification was interrupted after **0.192 s**
when the next speech fragment arrived; it has no completed server-time sample.
The explicit compound command bypassed classification and must not count as
a zero-latency Laya inference.

Overall first-response median was **5.497 s** over 21 replies. All first
playback writes agree with native latency within 40 ms. End-to-end means final
estimated speech-end to first software speech/playback, not physical acoustic
onset or completion of the whole spoken answer. P95 values use nearest rank
and very small samples. No-reply attempts have no finite latency and are
retained separately below.

The earlier Jev contextual set had eleven finite replies at median **5.501 s**
and successful classifier waits around **0.31 s** in its initial window.
This is descriptive, not a matched causal estimate: ASR text, state/history,
model-selected actions, question/gate and argument policy differ. The current
CPU classifier is slower than those successful Jev calls. It is not the DGX
30 ms GPU result described in the training README.

## Direct-command findings

- Time executed directly in **2.460 s**, including **0.694 s** Pi wait for Laya.
  Weather executed directly in **3.827 s**, including **0.726 s** classification
  and **1.275 s** MCP/API work.
- Laya correctly selected lights for the noisy lights-on request, but its
  recognized noun was corrupted. The grounding guard rejected it; GLM
  recovered the action. First response **6.309 s**.
- The standard light-color command was classified correctly but rejected by
  the stricter argument grammar. The existing direct parser recognizes the
  color; the grammar lacks that phrasing, even after whitespace normalization.
  GLM performed the action; first response **4.807 s**. This is an integration
  coverage defect in the added guard, not a wrong Laya class.
- The reminder was also classified correctly but ASR-fragment spacing prevented
  the existing reminder bypass/parser and stricter guard from matching. A
  read-only probe confirmed whitespace normalization makes it match. GLM
  added the reminder in **5.434 s**. No live parser fix was applied mid-test.
- The explicit twenty-degree thermostat request was classified as `other`
  with probability **0.86**, despite valid temperature wording. GLM executed
  it in **5.027 s**. This reproduces the number-word generalization weakness
  found in the earlier text benchmark.
- The message request correctly reached GLM, which asked for message text.
  No message was sent. This was better clarification behavior than the earlier
  Jev-run GLM attempt, but GLM output/history changed, so do not attribute the
  difference solely to the classifier.

Six tool-class candidates across both sets were rejected by the independent
argument guard. Some were appropriate fall-throughs for contextual/noisy
requests; the light-color wording and reminder spacing are identifiable
avoidable fallbacks. No fast-path setter was executed in this live sample,
so it does not independently validate fast setter execution accuracy.

## Longest wait: catalog retries, not classification

The music request took **34.543 s** to first speech. Laya consumed **0.762 s**.
GLM issued **five catalog searches**: the first HTTP request failed, the next
three timed out, and the final search succeeded. Catalog HTTP waits totaled
**22.988 s**; six GLM calls totaled **8.692 s** of generation/client wait.
This was not a long Laya inference. Returned audio playback remains unconnected;
the eventual spoken playback claim exceeded the actual catalog capability.

The contextual rain question took **9.024 s**. Its first endpoint/context wait
was **3.301 s**, after Smart Turn initially judged the turn incomplete. Laya
then took **0.756 s**; GLM and weather/TTS explain the rest. The endpoint tail
must not be attributed to the classifier.

## Contextual correctness

Useful inference was preserved through GLM: darkness led to lights on and
brightness 70%; excessive brightness led to 35%; a blue-light preference led
to blue; waking at six the next morning led to an alarm; loud music led to
`volume_down`; the lights-off idiom led to off. The brightness settings were
chosen by GLM rather than explicitly specified. Alarm delivery and real media
control remain unimplemented; state updates are not physical execution proof.

Two material failures:

1. **Pending consent lost.** GLM answered the heat complaint using weather and
   offered to lower the thermostat. The affirmative follow-up was classified
   `small_talk` and sent to Llama, which returned a generic instruction-like
   sentence. **No thermostat operation followed.** Laya and the small-talk
   adapter see only the latest utterance, so the pending question was lost at
   routing. A fast response of **3.306 s** is still an incorrect workflow outcome.
2. **Manila intent lost.** The user explicitly confirmed this was a question
   about **time in Manila**. ASR retained an ambiguous location fragment.
   Laya sent it to GLM as `other`; GLM continued the preceding weather topic and
   answered Manila weather instead. It replied in **6.557 s**, but performed
   the wrong intended task. Clarification was needed instead of assuming the
   prior topic supplied the missing intent.

No overall intent-accuracy percentage is claimed: there is no complete labeled
reference for all intended speech. Mechanical receipts, sensible tool choices,
exact argument preferences and actual task completion must be scored separately.

## No-reply and capture quality

Turns **8** (direct) and **18** (context) had VAD start/stop and complete Smart
Turn analysis but **no final ASR transcript, classifier call, route or reply**.
They exhibit the same upstream no-transcript symptom as the earlier run. Their
spoken content cannot be reconstructed from these logs.

Turn **11** was a transcribed color fragment whose classification was
interrupted by the subsequent volume fragment. GLM handled both actions in
turn 12. It is not another silent-ASR case or a classifier timeout. Startup
self-hearing produced two extra cloud contexts; both are excluded from user
timing and correctness.

The 2,122-event snapshot has no incomplete lines or unfinished spans and reports
no drops/write errors. All **25 MCP calls** are correlated. Non-HTTP MCP median
was **28.713 ms**; **16 writing-call commit totals** had median **2.856 ms**,
maximum **3.767 ms**. SQL remained on Jetson. Three Pi loop-lag samples were
50–77 ms, insufficient to explain the multi-second tails. The four catalog
failures were caught by their tools and are not successful business outcomes.

## Saved results and next work

- [Per-command layer and end-to-end timings](../profiling/laya-glm-live-20261101/per-turn-timings.md)
- [Machine-readable groups and per-turn outcomes](../profiling/laya-glm-live-20261101/benchmark-summary.json)
- [MCP/worker/HTTP summary](../profiling/laya-glm-live-20261101/stall-summary.json)
- [Capture](../profiling/laya-glm-live-20261101/capture/)

Priorities are to repair argument-guard phrasing/spacing coverage without
altering exact reminder payloads, route pending confirmations with their
conversation, investigate absent ASR results, and bound catalog retry plans.
GPU placement is assessed separately in
[Jetson capacity](jetson-laya-capacity-20261101.md). Model placement and live
configuration remain unchanged during these assessments. The user requested
committing this implementation and assessment progress on `laya-integration`.
