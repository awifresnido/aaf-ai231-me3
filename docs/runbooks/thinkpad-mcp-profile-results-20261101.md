# Pi/MCP stall profiling results

Voice test: 2026-11-01 15:33–15:35 Asia/Manila. Run `52be8da4d9`,
experiment `vcm-thinkpad-mcp-profile-20261101`. ThinkPad was the only model
host; Jev, GLM, and VPS fallback stayed disabled. Prompt, tool behavior,
deadlines, VAD 0.3 s, Smart Turn two threads, and audio configuration stayed
fixed. No runtime changes were made during this assessment.

The RAM trace snapshot was copied into
[`docs/profiling/mcp-stall-52be8da4d9`](../profiling/mcp-stall-52be8da4d9/)
before a Pi reboot could lose it. It contains both metadata-only JSONL
files, a reproducible summary, and capture hashes; the ordinary speech log
was not added. There were 991 records, zero incomplete lines, no unfinished
spans, no reported queue drops/write errors, and nine matched client/server
tool calls. Normal main logs and ThinkPad journal were also inspected.

## Result

Two separate sources of intermittent delay were captured:

1. **Synchronous normal logging stalls the Pi event loop.** Three calls took
   0.937 s, 0.416 s, and 1.807 s. Independent loop-lag events align with them.
2. **A SQLite commit stalls an otherwise simple state update.** Final
   lights-off took 2.006 s in MCP, of which one commit consumed 1.978 s.

The recurring MCP session and stdio transport were fast in this sample.
The traces do not prove that every earlier 8–12 s tool wait had the same
cause; those older runs lacked this instrumentation.

## Overall voice timing

Twelve observed user turns produced twelve measured replies: nine completed
tool calls, two unsupported-capability replies, and one validation failure.
Some tool calls were semantically incorrect, so this is a reply-latency
summary, not twelve successful commands. All twelve replies retained their
speech-end timing reference, unlike the earlier split-turn trials.

| Measurement | Result |
|---|---:|
| Speech end to first bot speech | Median 5.497 s; range 3.784–7.803 s; 12 replies |
| ThinkPad model call | Median 3.515 s; range 1.768–5.208 s |
| Speech end to first routing-context event | Median 784 ms; range 712–1,000 ms |
| Smart Turn processing | Median 430 ms; range 392–470 ms; 15 evaluations |
| TTS first byte, including greeting | Median 1.047 s; range 0.852–1.304 s; 13 values |

These are software timing proxies, excluding hardware playback delay. A
context-event timestamp is taken before its normal logging call; a blocked
log can therefore delay actual model dispatch beyond that event's timestamp.
Component medians cannot be added to reconstruct the reply median.

The earlier ThinkPad trial's native median was 6.368 s and VPS 9.442 s, but
the requests and timing integrity differ. This sample has smaller tool
spikes, while its model-call median is higher than the earlier ThinkPad's
2.874 s. Instrumentation is diagnostic, not an established latency fix.

| Request | First speech delay | Model | MCP |
|---|---:|---:|---:|
| First hearing check | 3.78 s | 2.05 s | 0.012 s; incorrectly called time |
| Repeated hearing check | 4.32 s | 1.77 s | 0.007 s; incorrectly called time |
| Lights on | 4.68 s | 2.76 s | 0.070 s |
| Lights green | 4.80 s | 3.05 s | 0.045 s |
| Thermostat 26 C | 5.58 s | 3.71 s | 0.037 s |
| Messaging | 6.14 s | 4.19 s | Unavailable; no tool |
| Calling | 7.80 s | 5.21 s | Unavailable; no tool |
| Play a love song | 4.93 s | 3.13 s | Validation rejected; no tool issued |
| Lights blue and increase music volume | 5.55 s | 3.56 s | 0.067 s; lights only |
| Current weather | 6.74 s | 3.54 s | 1.380 s |
| Current time | 5.45 s | 3.49 s | 0.008 s |
| Lights off | 7.80 s | 3.75 s | 2.006 s |

## Logging stalls

RAM trace spans surround the existing timing log and route log calls without
using the normal log sink. Of 181 measured logging spans, median time was
0.669 ms, but three exceeded 50 ms and together occupied 3.161 s. This is
time spent in those calls, not an additive estimate of total reply savings.

| Location | Blocked time | Independent Pi loop lag |
|---|---:|---:|
| Repeated hearing check: routing-context log | 937 ms | 851 ms |
| Calling reply: model-decision log | 416 ms | 329 ms |
| Final lights-off: user-turn-start log | 1,807 ms | 1,754 ms |

For the longest span, process CPU increased only about 71 ms during 1.807 s
elapsed, with no major faults or block-I/O increments in its process-wide
counters. That supports waiting rather than CPU-heavy formatting; it does
not distinguish logger-lock contention from a blocked sink or process
scheduling. The other process/thread work is included in these counters.

The final user-start log span ended around 15:35:18.577; loop lag was
reported at 15:35:18.592, followed by “no audio received while speaking” at
15:35:18.606. This directly correlates the logging-path stall with disrupted
audio scheduling. It does not establish the exact lost audio samples or
recognized-word error. An additional 163 ms loop-lag event occurred during
the thermostat turn without a matching slow measured log. A separate
1.516 s lag event occurred during startup and is excluded from user-turn
stall counts. No MCP server-loop lag above 50 ms was reported.

## SQLite and MCP breakdown

The final lights-off request has call ID
`76b51b91fb4549438aa71b0f48484ec5` in both processes:

| Phase | Duration |
|---|---:|
| Entire installed MCP client call | 2,005.680 ms |
| Session acquisition | 0.096 ms |
| RPC request through response | 2,002.897 ms |
| Server handler, including conversion | 1,994.496 ms |
| Tool body | 1,991.746 ms |
| SQLite commit phases, summed | 1,978.328 ms |
| SQL execute phases, summed | 7.416 ms |
| Client logs/result work after RPC | 1.848 ms |

The single slow commit was 1,978.232 ms, with only about 6.958 ms process
CPU, 32 output blocks, and no major faults. It accounts for approximately
98.6% of that MCP client call. Other local write commands had total MCP
times of 36.9–70.2 ms and summed commit times of 25.1–51.5 ms. Time queries
had 7.1–11.9 ms total MCP time. This points to the commit path for this
specific spike, not session setup or request transport.

Recurring session acquisition was 0.042–0.096 ms across tool calls; the
initial owner connection took 2.397 s before the voice test. For lights-off,
RPC-to-server entry was 4.107 ms and server-exit-to-client return 4.298 ms.
These boundaries include scheduling/protocol handling and are not pure wire
latency. Server-loop responsiveness during the slow commit indicates that
the tool worker can wait while its asyncio loop remains responsive.

Read-only inspection confirmed the actual database journal mode is `delete`
with 4096-byte pages. Its filesystem is `/dev/sda2`, ext4 `rw,noatime`, on
a USB device reported as “Storage Media.” No kernel journal entries were
available for the test interval. A slow durability flush and commit-lock
waiting remain hypotheses; the trace does not diagnose a bad disk or prove
which SQLite syscall waited. No database settings were changed.

Weather's 1.379 s client time was almost entirely the existing HTTP request:
1.370 s in HTTP versus 1.372 s in the server handler. The client and local
transport contributed only milliseconds. This is a separate network-tool
cost from the intermittent local database wait.

## Model and correctness

The model remains the largest ordinary stage: median 3.515 s. ThinkPad
server timings corroborate actual inference, for example 3.473 s server
total for the time query versus 3.495 s at the Pi client, and 3.729 s for
lights-off versus 3.753 s at the client. Typical prompt processing still
re-evaluates roughly 90–118 tokens; generated JSON adds further latency.
Address repeated context/output cost after isolating the intermittent stalls.

Both hearing checks were transcribed correctly enough to identify their
intent, but called get_time. This is an intent-selection failure, not
evidence of an actual clock request. Messaging and calling were rejected
as unavailable. Music was rejected by argument validation before execution.
The blue-lights/volume request only changed lights, so compound handling
still needs correction. No model deadline or tool deadline failure occurred.
No startup greeting echo or repeating self-conversation was observed in
this sample; previous evidence means echo control is not proven universally.

## Next diagnostic trial

1. Move normal logging output off the audio/event-loop thread with queued
   logging. Keep log levels, model/prompt, tools, audio, and SQLite policy
   fixed initially so the scheduling effect can be assessed separately.
2. Keep the current commit traces and investigate fsync/durability versus
   lock waits if commit spikes recur. Do not attribute every tool delay to
   the client or change multiple database settings before measuring them.
3. Repeat the same local light/thermostat/time script; include weather as
   the separate network case. Check loop lag, slow-log spans, per-call commit
   duration, correctness, and first playback—not only overall median.

The bot remains on ThinkPad-only with diagnostics enabled. This assessment
does not apply queued logging or change database behavior.

Related: [profiling setup](thinkpad-mcp-profile-20261101.md),
[saved summary](../profiling/mcp-stall-52be8da4d9/summary.json).
