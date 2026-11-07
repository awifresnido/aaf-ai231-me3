# SQLite flush-versus-lock diagnosis

Tests performed 2026-11-01, approximately 17:03–17:15 Asia/Manila, after
checkpoint `81cbbb8`. The live ThinkPad-only bot, queued logging, VAD/audio,
model settings, and SQLite durability were unchanged. All synthetic writes
used exclusively created temporary databases/files; no live database rows
were changed or copied by the probes. Temporary data directories were
removed automatically after completion.

## Finding

**A real MCP state update stalled inside the operating system's journal
flush.** The synthetic lights-off call took 3.160 s; SQLite commit phases
totalled 3.119 s, including this single syscall:

```text
fdatasync(.../voice-mcp-storage-probe-.../state.db-journal) = 0 <3.099516>
```

This was the actual tool server and profiled MCP client operating on a
disposable database on the same USB-backed filesystem. No model, TTS, real
device action, live reminder data, or competing database connection was
involved. There were no failed kernel lock requests in this MCP probe.
The flush alone accounts for about 98.1% of the entire MCP call.

The earlier voice runs located 7–15 s waits inside commit without measuring
its syscalls. This new test directly establishes a multi-second storage-sync
stall in the same implementation/path. It does not retrospectively prove
that every previous delay had the same cause or diagnose a physical drive
failure. The underlying filesystem/USB/device/writeback cause remains open.

## Inspected configuration

The actual database is 28,672 bytes on `/dev/sda2`, ext4 `rw,noatime`, USB
device reported as “Storage Media.” A fresh read-only SQLite connection
reported DELETE journal, synchronous 2/FULL, busy timeout 5000 ms, normal
locking, and page size 4096. The application creates fresh connections and
does not override those settings. Python is 3.13.5; SQLite 3.46.1; strace
6.13 on aarch64. `fuser` found no open live-database handles at inspection
time; that is not evidence about earlier concurrent readers.

The USB device and disk were runtime-active with power control `on` and
zero recorded runtime-suspended time for the disk/device. No power setting
was changed. No kernel journal entries were available in the inspected
interval. These observations do not rule out firmware/storage problems.

## Controlled tests

Every synthetic SQLite test used a 28 KiB database with the same four-table
schema and a changing dummy device_state value, DELETE journaling, FULL
synchronization, 4096-byte pages, and no competing connection during the
ordinary write tests. Data and probe traces contain no user reminder text.

| Test | USB/disk | RAM diagnostic control |
|---|---:|---:|
| Four back-to-back commits | Median 23.329 ms; max 27.044 ms | Median 1.494 ms |
| Four commits, ten seconds apart | Median 26.100 ms; max 28.904 ms | Median 2.460 ms |
| Spaced raw fsync, three samples | Median 9.769 ms; **max 1,117.662 ms** | Median 0.479 ms |
| Later initial database-file fsync | **1,742.539 ms** | 0.575 ms |

The long raw USB fsyncs happened on private files outside SQLite. Their
syscalls were directly timed at 1.117201 s and 1.742052 s. Thus a database
lock cannot explain those particular storage-flush stalls. Most samples
were fast, demonstrating why a short average or burst-only benchmark can
miss this intermittent problem. Strace adds overhead, especially to the
sub-millisecond RAM controls; these are diagnostic samples, not throughput
benchmarks. RAM is not proposed as a replacement for persistent data.

The scripts alternate disk/RAM cases. Optional ten-second spacing mimics
gaps between spoken commands. Seed fsyncs, SQL execution, commits, direct
fdatasync/fsync calls, and intentional idle intervals are labelled separately
so the ten-second test sleeps are not mistaken for database waiting.

## Real MCP tool path, disposable database

`scripts/probe_mcp_sqlite_storage.py` starts the existing MCP server with
VOICE_TOOLS_DATA pointing to a fresh temporary directory and calls four
state tools ten seconds apart. It uses queued DEBUG logging to a separate
RAM capture, plus the existing correlation-ID diagnostics. The live bot
remained running. The test did not execute physical device operations.

| Synthetic tool | Entire client call | Summed SQLite commits |
|---|---:|---:|
| Lights on, first-call schema creation | 209.808 ms | 24.795 ms |
| Green lights | 70.795 ms | 25.507 ms |
| Thermostat | 96.576 ms | 45.824 ms |
| Lights off | **3,160.372 ms** | **3,118.905 ms** |

The first call also creates the fresh schema, so its SQL execution time
includes initialization and should not be treated as steady-state cost.
For the slow final call, server handler time was 3,144.199 ms, tool body
3,141.011 ms, session acquisition 0.125 ms, and client handling after RPC
3.627 ms. The journal fdatasync consumed 3,099.516 ms. This cleanly separates
the observed storage wait from model, connection, and response handling.

## Positive lock controls

A held reader on a temporary RAM database delays writer commit even when
storage flush is fast. The initial same-process/thread reader controls held
the read transaction for 250 ms and caused approximately 333 ms commits.
SQLite can track same-process conflicts internally, so these controls did
not show failed kernel fcntl calls.

A separate-process reader control then held the same kind of read lock for
250 ms. Writer commit took 337.183 ms and produced twelve failed F_SETLK
requests with EAGAIN, plus SQLite retry sleeps. This validates a distinct
external-lock signature. In the reproduced MCP storage stall, no such lock
failures occurred and a single successful fdatasync occupied 3.10 s.
Absence of failed fcntl alone would not rule out every internal SQLite wait;
the long timed flush syscall is the decisive evidence here.

## Evidence and reproduction

[`docs/profiling/sqlite-storage-20261101`](../profiling/sqlite-storage-20261101/)
contains phase events, filtered syscall traces, MCP metadata traces, a
combined summary, and hashes. The syscall filter includes only fsync,
fdatasync, fcntl, unlink, and clock_nanosleep—not SQL values or write payloads.
The live database was inspected read-only; no private data copy was used.

Rerunnable harnesses:

- `scripts/diagnose_sqlite_storage.py`: standalone disk/RAM transactions,
  raw flushes, spacing, and optional separate-process reader lock.
- `scripts/probe_mcp_sqlite_storage.py`: actual MCP tools against an
  exclusively created disposable database, with no model or spoken audio.

Run them as children of `strace -f -ttt -T -yy` with the above syscall filter
and traces directed to RAM. Both scripts were compiled and executed on the
Pi. The existing application's 37-test checkpoint was not modified by these
test harnesses. No new end-to-end voice latency is claimed from these probes.

## Next investigation

Keep queued logging and the existing persistent-data policy. The next
controlled comparison can evaluate fewer durable flushes, such as WAL with
FULL synchronization, on temporary data before changing the live database,
and inspect shared-storage/writeback contention. A faster persistent-storage
comparison would further separate application behavior from the USB medium.
Do not disable synchronization or move the live database into volatile RAM
as a performance fix based on this test.

SQLite's [atomic-commit documentation](https://www.sqlite.org/atomiccommit.html)
describes the journal/data flush stages; its
[WAL documentation](https://www.sqlite.org/wal.html) describes a different
commit mechanism with fewer synchronization operations. Neither establishes
that a journal-mode change will eliminate this device's long flush tail.

The live bot remains ThinkPad-only, queued logging and diagnostics enabled,
Jev/GLM/VPS fallback disabled. The new diagnostic scripts and report remain
uncommitted after the prior checkpoint.
