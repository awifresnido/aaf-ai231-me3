# Queued logging: two consecutive voice tests

Run `597aabcb5a`, experiment `vcm-thinkpad-queued-log-20261101`,
2026-11-01 Asia/Manila. ThinkPad-only; Jev, GLM, and VPS fallback disabled.
Queued DEBUG logging was enabled with the same destination. Prompt, model,
audio, tools, timeouts, and database policy were unchanged. No runtime
changes were made during this assessment; the service/model remained healthy.

The two passes are separated at the pause and repeated hearing-check/command
sequence: first roughly 15:51–15:54, second 15:55–15:58. This boundary is
inferred, since no explicit test marker was recorded. Both used the same
process and conversation; the second was not a fresh context/model start.

Metadata-only traces, hashes, per-pass statistics and reproducible summary:
[`docs/profiling/queued-log-597aabcb5a`](../profiling/queued-log-597aabcb5a/).
The capture has 1,875 events, seventeen correlated client/server tool calls,
no incomplete lines or unfinished spans, and zero reported drops/write
errors. Raw speech/main logs were inspected but not added to this artifact.

## End-to-end latency

| Measurement | Previous synchronous-log profiling run | Queued pass 1 | Queued pass 2 |
|---|---:|---:|---:|
| Measured replies | 12 | 12 | 12 |
| Median speech-end to first speech | 5.497 s | 7.014 s | 6.931 s |
| Range | 3.784–7.803 s | 4.781–15.320 s | 4.677–20.992 s |
| Median completed model call for these replies | 3.515 s | 4.157 s | 3.333 s |
| Median endpoint/context event wait | 784 ms | 821 ms | 804 ms |
| Smart Turn median processing | 430 ms | 425 ms | 413 ms |

The combined native reply median is **6.931 s**, range **4.677–20.992 s**,
across twenty-four values. Thirteen starts were in pass 1, including an
initial “I think” fragment/reply without a usable speech-end reference.
Pass 2 had fourteen starts; one model call was cancelled and another start
had no transcript/outcome. Its drink-water reminder reply lost the timing
observer's speech-end reference, but its native 12.747 s value is retained
in the aggregate rather than selectively dropping the slow case. The other
twenty-three timing-ID-matched replies have median 6.809 s.

There were twenty-five completed outcomes including the initial fragment:
seventeen tool results, five text replies, and three validation failures.
Mechanical tool completion does not establish that the action matched the
request. Reply summaries include unsupported/error replies and wrong actions.
The request mixes differ from the previous test, so the higher median cannot
be attributed to queued logging alone. Physical speaker delay is unmeasured.

## Logging change worked for loop responsiveness

| Diagnostic | Previous run | Queued run, both passes |
|---|---:|---:|
| Longest measured normal log call | 1,807 ms | 10.963 ms |
| Median log-call time | 0.669 ms | 0.788 ms |
| User-turn loop-lag events above 50 ms | 4 | 0 |
| Largest sampled Pi loop lag | 1,754 ms during user turns | 19.423 ms from heartbeats |
| Largest sampled MCP loop lag | No event above 50 ms | 5.987 ms from heartbeats |

All 346 queued logging spans together occupied 304 ms on their calling
threads. This includes formatting/enqueue work, not the background writer's
file-write duration. The previous 181 spans included three slow log calls
totalling 3.161 s. Different record counts prevent a like-for-like aggregate
savings claim; the disappearance of large caller/loop stalls is the useful
observation. No audio-idle forced-stop warning appeared in this queued run.

The lack of threshold events does not mean zero loop lag: the heartbeat
maxima above preserve the actual sub-50-ms samples.

## SQLite commit now clearly dominates the long replies

Thirteen tools wrote database state. Eleven of those thirteen had commit
times above one second. Summed commit time per writing call had median
**2.100 s**, range **0.019–14.714 s**, and total **54.527 s** across the two
passes. The eleven slow commits account for more than 99% of their complete
MCP client call times. SQL execution itself took only milliseconds.

| Writing command | Pass 1 commit | Pass 2 commit |
|---|---:|---:|
| Lights on | 2.835 s | 2.064 s |
| Lights green | 2.100 s | 0.037 s |
| Thermostat | 7.091 s at 20 C | 1.726 s at 18 C |
| Add reminder | 7.839 s, study | 2.853 s, drink water |
| Blue lights in compound request | 0.019 s | 14.714 s |
| Lights off | 9.260 s | 2.016 s |

Pass 2 also performed an unintended thermostat update with a 1.974 s commit.
The recognized text was “a thera today,” with no temperature value; the
model nevertheless supplied 26 C. This was not a successful weather request.

The longest request, pass 2 blue lights, took **20.992 s** to first speech:
model 4.448 s, entire MCP call 14.730 s, and commit phases 14.714 s. Its
single slow commit consumed 14.714 s elapsed but only about 37 ms of process
CPU, with 32 output blocks and no major faults. A server/model deadline did
not fire: the tool's 14.7 s wait stayed below the existing 20 s deadline.

For this request, session acquisition was 0.045 ms and client response
handling after RPC about 1.218 ms. Thus session setup, model handoffs, and
RPC response logging cannot explain its fourteen-second MCP delay. The
matched server and commit spans locate the wait inside commit. This still
does not distinguish storage durability flush from commit-lock waiting.

Both weather calls were separate external-network waits: HTTP 1.487 s and
1.871 s, versus total MCP 1.501 s and 1.880 s. Current-time MCP calls were
about 20 ms and 16 ms, demonstrating that read-only/local responses remain
fast when no database write is involved.

The database remains on the USB-backed ext4 root filesystem. No kernel
journal entries were available for this interval. Queued logging still writes
to the same storage in its background worker, so it does not remove storage
traffic; altered write timing could interact with commit waits. The logs do
not establish whether that interaction or independent storage variation
explains the increased frequency of slow commits. No SQLite settings or
storage paths were changed, and a physical-device fault is not diagnosed.

## Per-command voice comparison

| Request type | Prior profiling run | Queued pass 1 | Queued pass 2 |
|---|---:|---:|---:|
| Lights on | 4.68 s | 6.71 s | 6.81 s |
| Green lights | 4.80 s | 8.55 s | 7.88 s |
| Thermostat | 5.58 s, 26 C | 13.62 s, 20 C | 7.84 s, 18 C |
| Add reminder | Not sampled | 13.21 s | 12.75 s, split timing |
| Blue lights + volume | 5.55 s, lights only | 7.76 s, lights only | 20.99 s, lights only |
| Current weather | 6.74 s | 7.32 s | 6.21 s, repeated after wrong action |
| Current time | 5.45 s | 6.66 s | 4.68 s |
| Lights off | 7.80 s | 15.32 s | 7.26 s |

Three endpoint waits reached roughly 3.3 s: pass 1 compound blue lights,
pass 2 green lights, and pass 2 music. Smart Turn's three-second silence
completion was logged, despite the Pi loops remaining responsive. This is
a turn-completion decision tail, distinct from logging or database waiting.

TTS first byte stayed stable: median 1.000 s, range 0.907–1.149 s, twenty-six
measurements including the greeting and initial fragment reply. ThinkPad
journal confirms the model-call durations, e.g. pass 1 thermostat server
4.666 s vs Pi 4.692 s, and pass 2 final time server 2.812 s vs Pi 2.833 s.
The successful-decision median excluding the initial fragment is 3.788 s
across twenty-four calls. The raw span summary also includes a cancelled
357 ms attempt and the initial fragment; its different model count/median
must not be substituted for completed voice-request statistics.

## Correctness and next step

Three proposals failed validation across the two passes: first pass music,
first pass compound stop/music/lights, and second pass music. No tool was
issued for those failures.
Both blue-lights/volume requests executed only lights. The unintended 26 C
thermostat update on garbled ASR is a concrete need for stronger intent and
argument grounding: clarify missing values rather than taking examples or
unrelated history as authorization for a setter. The hearing-check replies
also incorrectly described the voice agent as text-only.

Keep queued logging: it removed the observed main-loop logging stalls.
The next latency investigation should isolate the database commit's flush
and lock waits while retaining current durability. Measure syscall/commit
boundaries and shared-storage contention before choosing a database/storage
change. Model context and turn-completion tuning remain additional targets,
but neither explains the 7–15 s commit waits captured here.

No service restart, database change, or tool/routing fix was made during
this assessment. ThinkPad-only with queued logging and diagnostics remains
active. Related: [trial setup](queued-logging-trial-20261101.md),
[previous profiling diagnosis](thinkpad-mcp-profile-results-20261101.md).
