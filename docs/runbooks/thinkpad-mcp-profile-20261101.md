# ThinkPad retest with Pi/MCP stall tracing

The completed test is assessed in
[Profiling results](thinkpad-mcp-profile-results-20261101.md): logging
blocked the Pi loop for up to 1.807 s, and a SQLite commit took 1.978 s.
Raw metadata traces and their summary are preserved in the workspace.
The subsequent [queued logging trial](queued-logging-trial-20261101.md)
keeps the same traces and voice latency measurements while changing logging
delivery only.

Requested after the VPS comparison on 2026-11-01. Select ThinkPad as the
only model host, with Jev, GLM, and VPS fallback disabled. This diagnostic
trial retains the Voice of Pi prompt/greeting, structured schema, VCM tools,
model deadlines (12 s), tool deadline (20 s), context window, and validation.
VAD remains 0.3 s, Smart Turn two threads, echo cancellation paired over the
JV801P, PCM 100%, and pacat target buffer 150 ms. No SQLite timeout, journal,
cache, or synchronization settings are changed.

Private environment selections:

```text
ORCHESTRATION_MODE=local_vcm
LOCAL_VCM_MODEL_HOST=thinkpad
VAD_EXPERIMENT=vcm-thinkpad-mcp-profile-20261101
VOICE_DIAGNOSTICS=1
VOICE_DIAGNOSTICS_DIR=/dev/shm/voice-agent-diagnostics
```

## What the trace measures

The normal Pi log stays enabled with its existing levels and destination.
The trial adds metadata-only JSONL traces to a separate RAM-backed directory
through a bounded queue and daemon writer thread. Trace producers do not
wait for file writes or route through Loguru. This lets an independent
timestamp/span surround a slow normal logging call. Instrumentation has
nonzero overhead and is diagnostic, not a claim of unchanged latency.

Each run has separate Pi and MCP files under
`/dev/shm/voice-agent-diagnostics/RUN_ID/`. Files are mode 600, directories
mode 700, and use Pi monotonic timestamps for cross-process comparison.
Queue drops and writer errors are counted in five-second heartbeats. These
RAM files are volatile: collect them before Pi reboot. Trial configuration
and the usual main log persist; a reboot starts a new run directory.

Measurements:

- `model_client`: local model request duration, separate from route logging.
- `timing_log` / `route_log`: synchronous time inside existing logging calls.
- `mcp_client_total`: the installed client's complete tool call, including
  its existing logging and result handling.
- `mcp_open_session`: session/lifecycle-lock acquisition and connection setup.
- `mcp_rpc`: session call_tool request through response return.
- `mcp_server_call`: MCP server entry through argument validation, tool
  execution, and result conversion.
- `tool_execute`: the actual tool function body.
- `sqlite_connect`, `sqlite_execute`, `sqlite_fetchone/fetchall`,
  `sqlite_commit`, `sqlite_close`: database work, with only SQL verbs logged.
- `http_request`: the existing weather/music HTTP helper, host only.
- `event_loop_lag`: scheduling delays above 50 ms, sampled every 100 ms on
  both the Pi pipeline and MCP server loops. Five-second heartbeats record
  maximum observed lag, process CPU, block-I/O counters, faults, and peak RSS.

Spans include elapsed and process CPU time, context-switch deltas, block-I/O
counters, and exception class. CPU and OS counters are process-wide and can
include concurrent/background work; they are not exclusive function costs.

The client assigns a random call ID in MCP request `_meta`. The server uses
the same ID for its tool/SQLite/HTTP spans. Tool arguments, tool schemas,
and returned payloads remain unchanged. Traces contain no raw utterances,
reminder text, tool arguments/results, SQL statements/parameters, URLs with
queries, or credentials. Existing normal logs retain their previous behavior.

The client instrumentation subclasses the installed MCP client and delegates
to its existing tool-call implementation. This intentionally measures normal
client response logging instead of bypassing it. When profiling is disabled,
the bot uses the original client and SQLite connection types.

## Retest script

Wait for each result; use single commands so intent errors and split turns
do not obscure the timing. Repeat the light commands two or three times to
capture variable waits:

1. “What time is it now?”
2. “Turn on the lights.”
3. “Set the lights to green.”
4. “Set the temperature to twenty-seven degrees.”
5. “Set the lights to blue.”
6. “Turn off the lights.”
7. “List my reminders.”
8. “What is the weather today?”

The first six plus reminder listing exercise local operations; weather adds
an external network comparison. Ordinary device commands retain their state
effects. Deletion, date lookup, messaging, and mixed plans are still outside
this narrow trial. Echo and ASR issues from earlier sessions are not fixed
by this instrumentation and remain part of the assessment.

## Validation and collection

All 35 regression tests passed in the Pi environment. New tests exercise an
actual MCP stdio connection with a temporary SQLite database, proving matching
call IDs across client/server/database and one tool invocation with unchanged
result shape. Other checks exercise SQLite lock errors and intentional loop
blocking. No live reminders/device state were changed by those tests.

Main log: `/home/aldwinrpi4/voice-agent/me3-local-audio.log`.
Deployment metadata:
`/home/aldwinrpi4/voice-agent/thinkpad-mcp-profile-trial.json` records the
log offset, settings, backup paths, and diagnostic root. The `configuration`
event records the actual per-run directory. Previous trial metadata is kept.

Deployment verified at 15:28 Asia/Manila: run `52be8da4d9`, ThinkPad host,
ten advertised VCM tools, pipeline ready, and Voice of Pi greeting at
software playback. Both Pi and MCP trace files have active heartbeats with
zero dropped records/write errors. Metadata log offset is 2,596,141 bytes;
backup suffix is `.bak-mcp-profile-20261101-152810`. A startup-only trace
snapshot was parsed successfully by the summary script before user testing.

After the user says done, collect both JSONL files and the relevant main-log
slice. A local summary can be generated with:

```bash
python3 scripts/summarize_stall_diagnostics.py /path/to/collected/run
```

Compare client total, RPC, server, body, and DB times per call ID. Pre-server
and post-server residuals include protocol processing and scheduling; they
are not pure network latency. Large normal-log spans implicate logging or
process scheduling around that call. Long SQLite commits with low process
CPU suggest waiting, but do not by themselves diagnose a physical disk fault.
Check queue/error counters and unfinished spans before drawing conclusions.

## Rollback

Backups use `.bak-mcp-profile-TIMESTAMP` for existing live Python files and
the private environment; new helper files are listed separately in metadata.
Restore the saved environment/files to reproduce the VPS comparison exactly.
For a ThinkPad run with compatible new code and profiling disabled, set
`VOICE_DIAGNOSTICS=0`, retain `LOCAL_VCM_MODEL_HOST=thinkpad`, restore the
desired experiment label, and restart `me3-local-audio.service`.

Related: [ThinkPad baseline](local-vcm-results-20261101.md),
[VPS comparison](vps-vcm-results-20261101.md).
