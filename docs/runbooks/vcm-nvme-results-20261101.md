# Jetson/NVMe VCM: two voice tests — 2026-11-01

The NVMe option removed the reproduced second-long SQLite stalls during
these tests. Median response latency was **5.185 seconds**, compared with
**6.931 seconds** in the preceding Pi-hosted queued-logging trial. The
observed median is about 25.2% lower, and the longest measured response fell
from 20.992 to 6.880 seconds. The request mix and model timings differ, so
this is an observed run comparison, not a controlled estimate of savings
from storage alone.

Run `625b1e52a7`, experiment `vcm-jetson-nvme-20261101`. The Pi retained
speakerphone audio, VAD 0.3 seconds, Smart Turn two threads, queued logging,
and orchestration. The model remained ThinkPad Llama 3.2 3B, with Jev, GLM,
and VPS fallback disabled. Only the explicitly selected VCM server/state
location changed to Jetson NVMe over SSH stdio. Pi hosting remains the
implementation default; this run uses the documented experimental exception
to the all-MCP-on-Pi requirement.

## Pass boundaries and measured replies

The two passes are inferred from the repeated hearing-check/command
sequence: pass 1, turns 3–17, approximately 18:29:58–18:33:22; pass 2,
turns 18–30, approximately 18:33:30–18:36:18, Asia/Manila. No explicit
test-start marker exists. Both passes used the same running process,
conversation, model service, and state; pass 2 was not a fresh-context run.

| Measurement | Previous Pi pass 1 | Previous Pi pass 2 | NVMe pass 1 | NVMe pass 2 |
|---|---:|---:|---:|---:|
| Measured replies | 12 | 12 | 13 | 12 |
| Median response latency | 7.014 s | 6.931 s | **5.185 s** | **5.192 s** |
| Range | 4.781–15.320 s | 4.677–20.992 s | 3.376–6.880 s | 4.524–6.634 s |
| Median completed model call | 4.157 s | 3.333 s | 3.372 s | 2.995 s |
| Median final speech-end to context readiness | 821 ms | 804 ms | 845 ms | 792 ms |
| Smart Turn processing median | 425 ms | 413 ms | 439 ms | 433 ms |

The twenty-five native response measurements include sixteen tool receipts,
six text replies, and three validation-error replies. They are not all
successful command executions. Tool-receipt-only native medians were
4.975 s and 4.859 s, eight receipts per pass.

The combined native median is 5.185 s, range 3.376–6.880 s. All twenty-five
have matching first-playback timing references; that median is 5.179 s.
These are pipeline speech-start/first-playback-write measurements, not a
physical microphone-to-speaker acoustic measurement. Output buffering and
hardware sound onset were not independently recorded.

Startup turns 1–2 had replies but no valid speech-end timing reference and
are excluded from end-to-end aggregates. Turn 0 is the greeting. Turns
13, 14, and 28 were detected starts without an ASR transcript, model
decision, or reply. They remain in the evidence, but have no finite reply
latency to aggregate. A latency summary alone must not hide these misses.

## The storage delay disappeared in the captured calls

Seventeen actual MCP calls, including one startup time call, have matching
Pi-client and Jetson-server IDs. None has a recorded transport/server
exception or an unfinished span.

| Diagnostic | Previous Pi-hosted voice trial | NVMe voice trial |
|---|---:|---:|
| Database-writing tool calls | 13 | 12 |
| Median summed commit time per writing call | 2,100 ms | **2.456 ms** |
| Commit range | 19–14,714 ms | **2.352–3.907 ms** |
| Writes with commits above one second | 11 | **0** |
| Median complete MCP call for writing tools | Commit dominated the multi-second calls | **17.735 ms** |

All twelve NVMe write calls together spent 32.490 ms in commit spans.
Their complete MCP calls ranged from 14.740 to 22.556 ms. Across all fifteen
non-weather calls, including time calls, median MCP duration was 17.669 ms.
RPC duration outside the remote handler was median 6.904 ms, range
5.564–12.729 ms; this includes protocol/client overhead and is not a pure
network round-trip measurement.

The two weather calls remain separate external-network waits: HTTP spans
1.467 s and 1.313 s, versus full MCP calls 1.480 s and 1.324 s. Faster
SQLite storage cannot remove those HTTP waits.

The cross-host clock guard worked: remote/server spans use a different
boot-specific monotonic clock domain. Transport comparisons use elapsed
durations; unrelated monotonic timestamps are never subtracted.

## Per-command comparison

These rows compare request types, with differences preserved rather than
treated as identical inputs. Values are native response latency in seconds.

| Request | Previous Pi pass 1 / 2 | NVMe pass 1 | NVMe pass 2 |
|---|---:|---:|---:|
| Lights on | 6.71 / 6.81 | 4.23 | 4.92 |
| Set light color | 8.55 / 7.88, green | 4.80, green | 6.61, red |
| Thermostat | 13.62 / 7.84, 20/18 C | 5.53, 23 C | 6.45, 17 C |
| Reminder that executed | 13.21 / 12.75 | 5.19, study | 4.67, drink water |
| Blue lights plus volume | 7.76 / 20.99 | 5.15, lights only | 4.80, lights only |
| Weather | 7.32 / 6.21 | 6.67 | 5.79 |
| Time | 6.66 / 4.68 | 4.55 | 4.55 |
| Lights off | 15.32 / 7.26 | 4.57 | 4.52 |

The failed reminder attempt in NVMe pass 1 is also retained in the overall
latency statistics; the successful-reminder row does not replace it.

## What now dominates the remaining five seconds

Across the twenty-five measured replies:

| Stage | Median | Observed range |
|---|---:|---:|
| ThinkPad structured model decision | **3.355 s** | 1.500–5.052 s |
| Endpoint/context readiness after final recorded speech end | **837 ms** | 697–942 ms |
| Smart Turn processing, within endpointing | 436 ms | 388–475 ms |
| TTS time to first byte | **972 ms** | 886–1,093 ms |
| Writing-tool MCP call, twelve calls | 17.735 ms | 14.740–22.556 ms |

These are separate distributions; their medians should not be added as an
exact latency decomposition. Smart Turn is already part of the endpointing
interval, and weather has an additional network wait.

The ThinkPad's llama-server journal independently confirms the model cost.
Twenty-seven completed server tasks align chronologically with twenty-seven
Pi model decisions; every paired duration differs by less than 100 ms.
For the twenty-five measured replies, prompt evaluation had median
**1.846 s**, generation **1.352 s**, and server total **3.336 s**.
Pi-observed model time exceeded server total by median **22.49 ms**,
range 17.30–29.18 ms. This locates the main cost inside inference rather
than the Pi-to-ThinkPad connection.

The server reported median 91 newly evaluated prompt tokens and 17 generated
tokens. These are runtime processed-token counts, not full request lengths.
Prompt evaluation accounted for about 58.2% of summed server time over
these twenty-five calls. The next latency trial should focus on prompt/
history processing and cache reuse, as well as CPU generation throughput;
reducing transport overhead by a few milliseconds is now a smaller target.

No final-marker-to-context interval exceeded 0.95 seconds in these replies.
Turn 24 did have an INCOMPLETE Smart Turn decision followed by a new VAD
stop marker about 3.10 seconds later and then COMPLETE. Its reported reply
latency starts at the final recorded speech end. Without recorded audio,
that gap cannot be classified solely as inference delay or a speech pause.

## Correctness, echo, and runtime health

- Three model decisions failed validation before any MCP tool was issued:
  the first reminder attempt, a music request proposed as playback control,
  and a garbled lights-on request. A clearer lights-on retry succeeded.
  These are separate from storage or SSH failures. The generic ValueError
  event does not preserve the exact rejecting validation rule.
- Both compound blue-lights/volume requests still executed only the lights
  change. Compound-command handling remains an unresolved correctness issue.
- Message/call requests produced the expected unavailable-in-this-trial
  replies. One music reply also reported playback unavailable. These replies
  should not be counted as working implementations of those actions.
- Startup ASR captured the greeting's own phrase about helping with time
  and triggered a time tool call, followed by a short garbled fragment.
  This is strong evidence of startup self-hearing despite the paired echo
  canceller. Raw audio was not recorded, so acoustic origin is inferred.
  These two startup responses were outside the measured test aggregates.

There were no event-loop lag events above 50 ms. Heartbeat maxima were
18.628 ms on the Pi and 1.786 ms in the remote MCP process. The longest
of 374 measured normal logging calls was 6.872 ms, median 0.686 ms.
No incomplete JSONL lines, unfinished spans, dropped events, or diagnostic
write errors were reported in the 1,918-event capture. The Pi service and
ThinkPad endpoint remained healthy; no runtime settings or services were
changed during this assessment.

## Saved evidence and next trial

[Metadata capture, pass statistics, model/TTS measurements, and hashes](../profiling/vcm-nvme-625b1e52a7/)
are saved locally. Main logs/transcripts were inspected privately and were
not added to the artifact. The existing application's 46-test validation
from deployment remains applicable; this assessment changed analysis and
documentation only. Results remain uncommitted.

Reproduce the summaries:

```bash
python3 -B scripts/summarize_stall_diagnostics.py docs/profiling/vcm-nvme-625b1e52a7
python3 -B scripts/summarize_voice_trial.py docs/profiling/vcm-nvme-625b1e52a7 \
  --pass-turns 3:17 --pass-turns 18:30
```

Keep the NVMe option selected for a controlled model-latency trial, with
the same command script and host/settings. Test prompt/history changes
independently while checking reminder grounding, colors, compound commands,
and clarification behavior. Startup echo also deserves a separate targeted
trial. For a permanent design requiring every MCP server on the Pi, this
NVMe result motivates testing faster durable storage attached to the Pi;
the experimental Jetson placement does not itself meet that strict location
requirement. No permanent state migration or host-policy change is implied.
