# Pi-hosted VCM MCP with Jetson/NVMe persistence

The Pi option now runs the VCM MCP server and all tool validation, business
logic, and spoken-receipt construction on the Pi. A separate Jetson worker
owns SQLite reads, transactions, and durable commits on local NVMe. The
worker is a private storage protocol endpoint, **not an MCP server**.

The active voice trial is run **`afe7b8b933`**, experiment
`vcm-pi-mcp-nvme-worker-20261101`. The
[completed two-test results](pi-mcp-worker-results-20261101.md) measured
median response latency 5.468 s over 22 replies and commits 2.651 ms.
All MCP remained on Pi, and its original database stayed unchanged. The preceding
[full-VCM-on-Jetson trial](vcm-nvme-results-20261101.md) measured a 5.185 s
median across 25 replies. That is a comparison baseline, not a measurement
of this new split; see the completed results for the measured comparison.

```mermaid
flowchart LR
    B[Pi bot / ThinkPad model] --> M[Pi VCM MCP server]
    M <-->|Persistent SSH storage requests| W[Jetson SQLite worker]
    W --> D[SQLite on local NVMe]
```

## Configuration and placement

The Pi private environment now selects:

```ini
VCM_TOOL_SERVER_HOST=pi
VCM_STATE_BACKEND=jetson_sqlite
VCM_JETSON_DATA_DIR=/home/aldwin/voice-agent-vcm/state/trials/nvme-20261101
VAD_EXPERIMENT=vcm-pi-mcp-nvme-worker-20261101
```

`VCM_STATE_TIMEOUT_SECS` defaults to eight seconds. The existing target,
key, and pinned known-hosts settings remain `VCM_JETSON_SSH_TARGET`,
`VCM_JETSON_SSH_KEY`, and `VCM_JETSON_KNOWN_HOSTS`. Pi mode defaults to
`jetson_sqlite` even when `VCM_STATE_BACKEND` is omitted. Setting
`VCM_STATE_BACKEND=local_sqlite` explicitly retains the original Pi-local
storage path as a benchmark/rollback option.

The existing `VCM_TOOL_SERVER_HOST=jetson` option still runs the entire VCM
MCP server on Jetson and forces local SQLite there, preventing a recursive
storage hop. It remains available for comparison, but the active Pi option
satisfies the Pi-hosted-MCP requirement.

Changing MCP location between Pi and Jetson now uses the same NVMe state
when Pi's storage backend is `jetson_sqlite`. Changing the **storage backend**
to `local_sqlite` selects the separate original Pi database. There is no
automatic state synchronization between those two database files.

Startup verification found bot PID 50252 and VCM MCP PID 50276 on Pi, and
only `vcm_state_worker.py` PID 1297656 on Jetson. No VCM MCP server process
remained on Jetson. These PIDs are capture-time observations, not settings.
The worker starts when the Pi MCP server starts and exits with its SSH
connection. The existing enabled Pi systemd service handles reboot startup;
no separate worker service or public storage port is required.

## Storage contract and durability

`pi/vcm_state.py` exposes a small state adapter. Allowed operations are
device-state get/set/patch, reminder add/list, timer insertion, and alarm
insertion. The worker accepts operation arguments, not arbitrary SQL,
executable names, or database paths supplied with each operation. Existing
tool calculations—including weather/music access, timezone handling,
timer end times, and alarm validation—remain on Pi.

The existing restricted SSH key's forced entry point now recognizes two
validated request kinds: `voice-agent-vcm` for the old full-server option
and `voice-agent-state` for storage only. Both retain the bounded request
and state-directory confinement. The storage worker uses standard-library
Python plus the shared metadata profiler; it imports no MCP server SDK.

One persistent SSH child is reused by the Pi MCP process. Requests are
serialized with bounded lock, write, and read waits. Lighting and playback
state changes use one atomic read/modify/write storage operation rather
than separate network reads and writes. Worker transactions use
`BEGIN IMMEDIATE`; every connection sets `PRAGMA synchronous=FULL`.
The existing DELETE journal mode remains unchanged.

Writes carry a unique request ID. A small `state_requests` receipt table
stores a request fingerprint and result in the **same transaction** as the
state change. Replaying the identical ID/arguments returns the prior result;
reusing that ID with different arguments fails. This protects explicit
request replay after a lost reply, including across worker restarts. A new
spoken request has a new ID, so this does not deduplicate the user's manual
repetition of an uncertain action.

The worker returns success only after commit and connection cleanup return.
It never acknowledges a queued/background write. On disconnect or timeout,
the Pi raises an unconfirmed-outcome error without automatic write retry or
local-file fallback. The existing voice controller then reports that it
could not confirm the outcome. A timed-out write might already be committed;
read its state before repeating it as a new action.

## State preservation and backup

The active database is the same NVMe trial database used in the preceding
two voice tests. No fresh copy of the older Pi state replaced it. A
consistent SQLite backup, opened with a read-only source connection, is at:

`/home/aldwin/voice-agent-vcm/backups/pi-worker-20261101/state-before.db`

The backup and directory are private and outside this repository. Startup
verified that all existing rows in device state, reminders, timers, and
alarms matched the backup, the database passed integrity checking, and the
new receipt table contained zero operations before handoff to voice testing.

The Pi's original `voice-agent-tools/state.db` had the same byte hash and
modification time before and after deployment. Prior Pi source and private
environment are preserved under
`/home/aldwinrpi4/voice-agent-backups/pi-worker-20261101/`.

## Validation and measured preflights

All **57 regression tests passed on the Pi**. They include the previous
46, two additional placement checks, and nine state/transport checks:
existing-schema preservation, all persisted entities, atomic patches,
durable replay protection, commit-failure rollback, rejected SQL-like
requests, persistent worker reuse, reply loss after commit, timeout behavior,
and rejection of a non-FULL handshake. No production fault was injected.

The actual SSH split was then exercised on disposable state:

| Preflight | Calls | Median complete MCP call | Maximum |
|---|---:|---:|---:|
| Pi MCP + Jetson worker, lights/thermostat, five-second gaps | 4 | **25.044 ms** | 26.870 ms |
| Same split, extended reminder/timer/alarm contract, one-second gaps | 8 | **23.487 ms** | 28.027 ms |
| Full Jetson MCP compatibility check, no gaps | 4 | 16.391 ms | 31.064 ms |

In the four-call spaced split, median summed SQLite commit time was
**2.192 ms** (2.028–2.303 ms), and each tool used exactly one storage RPC.
Worker RPC time was 9.764–10.454 ms; the complete MCP measurement includes
the Pi client/server overhead as well. This is a small functional preflight,
not a controlled performance ranking or an end-to-end voice measurement.

All twelve split calls had their SQL spans exclusively in component
`state`, on Jetson's clock domain. Their MCP client and server spans shared
the Pi clock domain. The readback test confirmed the synthetic reminder,
and timer/alarm calls returned valid receipts. No incomplete spans,
diagnostic drops/write errors, or tool-call exceptions were reported.

[Saved metadata, summaries, and regression output](../profiling/pi-mcp-state-preflight-20261101/)
exclude raw speech, private databases, and environment contents.
`scripts/probe_vcm_location.py --exercise-state` reproduces the extended
contract using disposable state. The summarizer now reports `state_rpc`,
`state_worker_call`, storage request count, and SQLite execution component.
Worker transport overhead uses elapsed durations, without subtracting
monotonic timestamps from different hosts.

## Voice test and collection

Startup verified greeting playback, the speakerphone's paired AEC paths,
PCM 100%, healthy ThinkPad model, and no startup errors. Model/routing,
ASR/TTS services, VAD 0.3 s, Smart Turn two threads, queued logging, and
pacat 150 ms remain unchanged. Startup echo/recognition and compound-command
issues from the earlier test have not been changed in this storage trial.

Repeat the prior command sequence twice, waiting for each response. Include
lights, thermostat, reminder, time, and weather; report completion and any
speech while silent. Collect the matching run's three metadata files:

```text
Pi:     /dev/shm/voice-agent-diagnostics/<run>/pi-*.jsonl
Pi:     /dev/shm/voice-agent-diagnostics/<run>/mcp-*.jsonl
Jetson: /dev/shm/voice-agent-diagnostics/<run>/state-*.jsonl
```

Combine the files and use `scripts/summarize_stall_diagnostics.py`; extract
the final speech-end/first-playback measurements and match model, MCP,
storage RPC, worker, SQLite, and TTS timings. Keep overlaps between nested
stages separate. The synchronous storage worker has no asyncio loop-lag
monitor; its request spans measure blocking work directly.

## Rollback and current status

For a comparison with the previous full-Jetson mode, select
`VCM_TOOL_SERVER_HOST=jetson` and restart the Pi service. It keeps using the
same NVMe database with local persistence on Jetson. To use the original Pi
database, select both `VCM_TOOL_SERVER_HOST=pi` and
`VCM_STATE_BACKEND=local_sqlite`; this changes state history and should be
an explicit choice. Preserve the NVMe file rather than copying over it.

Code, tests, and captures are saved in the configuration checkpoint
`feat(pi): keep MCP on Pi with Jetson SQLite persistence` on
`two-brain-plusjev`, following `81cbbb8`. Both voice passes are assessed,
and this configuration remains active. Publication to GitHub is separate.
