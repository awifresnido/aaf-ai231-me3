# Pi MCP with Jetson SQLite worker: two voice tests

Run `afe7b8b933`, experiment `vcm-pi-mcp-nvme-worker-20261101`,
2026-11-01 Asia/Manila. This configuration keeps the VCM MCP server and
tool logic on Pi and moves only persistence to the non-MCP Jetson worker.
The storage benefit was retained: median commit time was **2.651 ms**,
without any second-long database stalls, and the original Pi database's
byte hash and modification time remained unchanged after testing.

Median measured response latency was **5.468 s** across 22 replies. This
is slightly higher than **5.185 s** with the complete VCM server on Jetson,
and lower than **6.931 s** with Pi-local storage. The split's non-HTTP MCP
calls were only about three milliseconds slower than the full-Jetson run.
The overall change should not be attributed to that overhead: model
timings and the mix of external API calls also changed.

No runtime settings were changed during log assessment. ThinkPad Llama
3.2 3B, ASR/TTS endpoints, VAD 0.3 s, Smart Turn two threads, Pi speakerphone
AEC, queued logging, and pacat 150 ms remained selected. Jev, GLM, and VPS
fallback stayed disabled. The service remained active with the same PID.

## Test boundaries and response latency

Pass 1 is inferred as turns 1–11, approximately 20:37–20:39. Pass 2 is
turns 12–22, approximately 20:39–20:42, starting with the repeated lights-on/
color/thermostat sequence. No explicit pass marker was recorded. Both passes
share the same process, conversation, state, and model service.

| Metric | Pi MCP + local SQLite baseline | Full Jetson VCM | Pi MCP + Jetson state worker |
|---|---:|---:|---:|
| Timed replies, both passes | 24 | 25 | **22** |
| Median response latency | 6.931 s | 5.185 s | **5.468 s** |
| Range | 4.677–20.992 s | 3.376–6.880 s | **4.295–8.452 s** |
| Median writing-call commit time | 2,100 ms | 2.456 ms | **2.651 ms** |
| Maximum writing-call commit time | 14,714 ms | 3.907 ms | **3.798 ms** |

The current aggregate median is 21.1% below the Pi-local-storage run and
5.5% above the full-Jetson run. These are descriptive comparisons from
different request mixes, not controlled causal speedup/regression estimates.

| Current measurement | Pass 1 | Pass 2 |
|---|---:|---:|
| Timed replies | 11 | 11 |
| Median response latency | **5.309 s** | **5.691 s** |
| Range | 4.295–8.079 s | 4.756–8.452 s |
| Median completed model call | 3.514 s | 3.637 s |
| Median final speech-end to context readiness | 787 ms | 797 ms |
| Smart Turn processing median | 426 ms | 409 ms |
| TTS first-byte median | 1.010 s | 1.051 s |

Every detected user turn has a transcript, completed decision, spoken reply,
native latency value, and first-playback reference. The greeting is turn 0
and excluded. Eighteen replies were tool receipts, two were unsupported-task
replies, and two were validation errors. The receipt count includes an
incorrect time decision for a hearing-check question, so it is not an intent
accuracy score. No extra detected starts were silently omitted.

Combined native latency was 5.468 s and first-playback-write latency 5.464 s.
Neither is a separate physical acoustic measurement; speaker buffering and
hardware sound onset were not independently measured.

## The persistence split stayed fast

All eighteen MCP calls have completed Pi client/server spans. Thirteen
performed state writes; each had exactly one storage RPC, one matched
worker operation, and SQL spans only in the Jetson `state` component.
The worker's durable receipt table held thirteen entries after the test,
matching those thirteen writes. Database integrity remained `ok` and journal
mode remained DELETE. Worker startup and per-connection code retain FULL
synchronization.

| Current storage-path measurement | Median | Range |
|---|---:|---:|
| Commit spans per writing call, 13 writes | **2.651 ms** | 2.431–3.798 ms |
| Storage RPC, 13 requests | **10.590 ms** | 8.193–11.820 ms |
| Worker handling, within the storage RPC | 8.498 ms | 5.923–10.034 ms |
| RPC duration outside worker handling | 2.184 ms | 1.691–2.572 ms |
| Complete MCP call, 12 non-HTTP writing tools | **20.960 ms** | 18.590–30.157 ms |
| Complete MCP call, all 15 non-HTTP tools | **20.760 ms** | 9.629–30.157 ms |

The thirteen commits together occupied 36.646 ms. Music's successful catalog
request also wrote state, but its complete MCP duration includes an external
HTTP wait, so it is excluded from the non-HTTP writing-tool row.

For comparison, full-Jetson VCM had median non-HTTP MCP duration 17.669 ms
and non-HTTP writing-tool duration 17.735 ms. The measured split adds about
3.1–3.2 ms at those medians, while meeting the Pi-hosted MCP requirement.

Client/MCP spans share Pi's monotonic clock domain; SQL/worker spans use
Jetson's. Worker transport comparisons subtract elapsed durations only.
The three matching trace files demonstrate that SQLite ran on Jetson,
while the MCP server ran on Pi. No NFS/SSHFS database file was involved.

## The longest replies came from external APIs

| Current request | Model | Full MCP | External HTTP | Response latency |
|---|---:|---:|---:|---:|
| Weather, pass 1 | 3.421 s | 2.822 s | 2.806 s | **8.079 s** |
| Music catalog, pass 2 | 3.294 s | 3.248 s | 3.218 s | **8.452 s** |
| Weather, pass 2 | 4.141 s | 1.423 s | 1.411 s | **7.278 s** |

The music call's state commit took just 2.638 ms. Its spoken response
correctly said a catalog match was found and that music playback is not
connected. This was a catalog lookup, not working speaker music playback.
The previous full-Jetson trial had no successful music lookup and weather
HTTP spans of 1.467 s and 1.313 s. These changed network workloads affect
the tail comparison independently of persistence.

## Remaining model and endpoint costs

Across all twenty-two replies, the ThinkPad model's median Pi-observed
duration was **3.517 s**, versus 3.355 s in the preceding full-Jetson run.
Its maximum was 4.410 s. Median endpoint/context wait was **793 ms**,
Smart Turn processing **416 ms**, and TTS first byte **1.014 s**. Smart Turn
is inside endpointing; these overlapping distributions must not be added
as an exact latency decomposition.

The ThinkPad journal independently matched all twenty-two completed tasks
to the Pi decisions in chronological order, with every duration difference
under 100 ms. Median server prompt evaluation was **1.956 s**, generation
**1.470 s**, and total **3.495 s**. Median Pi-minus-server model time was
**22.68 ms**, including the connection/client overhead. Prompt processing
and generation, not persistence transport, remain the largest target.

For a narrower comparison, both trials contain twelve non-HTTP state-tool
receipts (lights, thermostat, reminders). Their median response latency
changed from 4.859 s to 5.365 s, while model duration changed from 2.995 s
to 3.575 s and complete MCP time changed by only about 3 ms. Utterances and
arguments still differ, so this does not establish a model slowdown caused
by the split; it demonstrates why overall response differences cannot be
assigned to the worker hop.

Every final-marker-to-context interval was below 0.86 s. One INCOMPLETE
Smart Turn analysis appeared during the first music request, followed by
completion; there was no several-second final-marker endpoint tail among
the measured replies.

## Correctness and runtime observations

- The initial hearing-check question was transcribed as a hearing check
  but classified as `get_time`, producing a time response. This is an intent
  error despite a mechanically successful tool call.
- Two decisions failed validation before any MCP operation: a music request
  proposed as playback control and a reminder attempt with a garbled extra
  article. Rephrasing the reminder succeeded. The generic ValueError event
  does not retain the exact rejecting rule.
- Message/call requests returned the expected unavailable-in-this-trial
  replies. These were not calls to the large model or messaging backends.
- No startup transcription repeated the greeting in this capture. That
  absence does not establish that the earlier self-hearing issue is fixed;
  the echo settings were unchanged. No complete compound-command utterance
  was logged here, so the known partial-execution issue was not resolved
  or meaningfully retested by this workload.

No transport/server/worker exception, incomplete JSONL line, unfinished span,
dropped diagnostic event, or diagnostic write error occurred in the
1,802-event capture. Pi and MCP heartbeat loop-lag maxima were 16.524 ms
and 8.370 ms, with no events over 50 ms. The synchronous worker has no
asyncio-loop monitor. Of 293 measured normal log calls, median caller time
was 0.759 ms and maximum 2.661 ms.

## Recommendation and evidence

Keep the **Pi MCP + Jetson state worker** option as the current checkpoint.
It satisfies the MCP location requirement and preserves millisecond durable
storage. Next isolate ThinkPad prompt/history/cache and generation costs
with a fixed command sequence, while checking intent/argument correctness.
Weather caching can be tested separately for the external-API path.

[Saved traces, pass statistics, filtered model/TTS measurements, and hashes](../profiling/pi-mcp-worker-afe7b8b933/)
contain metadata only. Speech/main logs and database contents were inspected
privately and were not added. The [implementation/preflight runbook](pi-mcp-jetson-state-trial-20261101.md)
records the 57 passing tests, backup, configuration, and rollback options.

Reproduce:

```bash
python3 -B scripts/summarize_stall_diagnostics.py docs/profiling/pi-mcp-worker-afe7b8b933
python3 -B scripts/summarize_voice_trial.py docs/profiling/pi-mcp-worker-afe7b8b933 \
  --pass-turns 1:11 --pass-turns 12:22
```

The bot remains active in this configuration. Code, tests, and results are
saved in checkpoint `feat(pi): keep MCP on Pi with Jetson SQLite persistence`
on `two-brain-plusjev`, following `81cbbb8`. Publication to GitHub is separate.
