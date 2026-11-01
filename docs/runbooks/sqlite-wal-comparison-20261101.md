# SQLite DELETE/FULL versus WAL/FULL — 2026-11-01

WAL is not a reliable fix for the long pauses on the Pi's current storage.
Keeping a connection open reduces typical commit cost, but durable WAL
flushes still stalled for 1.1–1.8 seconds. With the bot's existing
open/commit/close pattern, WAL increased total synchronization calls and
slightly increased median complete-write time. No live database policy,
application code, audio setting, model, or running service was changed.

This follows the [storage diagnosis](sqlite-storage-diagnosis-20261101.md),
which reproduced a 3.10-second journal flush through an actual MCP tool.
These new measurements are synthetic database tests, not voice latency tests.

## Workload and controls

The Pi ran two serial comparisons: 12 writes per case, then 8 per case with
expanded syscall tracing. Each comparison covered DELETE and WAL, fresh and
reusable connections, USB/ext4 and a RAM control: 160 writes across 16
disposable databases in total. No private database contents were copied.

Every database began with the same synthetic 28,672-byte, four-table schema.
Every write repeated the bot's schema checks and upserted a changing JSON
value. FULL synchronization was set and verified on each cycle; journal
mode and the default 1,000-page automatic-checkpoint threshold were also
verified. Cases alternated order, with five-second gaps between rounds.
All database operations were serial, with only one connection per database.

Fresh-connection cycles include open, preparation, update, commit, and close.
Reusable connections stayed open across writes. Their WAL databases received
an explicit FULL checkpoint every four writes, a final TRUNCATE checkpoint,
and a timed final close. Setup, verification, and deliberate sleeps are
reported separately. The checkpoint-inclusive average includes all runtime
cycles, explicit checkpoints, reusable open, and reusable close, without
double-counting nested spans.

## First comparison: USB storage, 12 writes per case

All times below are milliseconds under syscall tracing.

| Connection / journal | Median commit | Median complete write | Maximum complete write | Checkpoint-inclusive average per write |
|---|---:|---:|---:|---:|
| Fresh / DELETE | 25.09 | 40.76 | 1,716.93 | 369.97 |
| Fresh / WAL | 22.39 | 46.15 | 1,196.00 | 229.76 |
| Reusable / DELETE | 25.77 | 35.88 | 1,090.87 | 130.23 |
| Reusable / WAL | 10.96 | 16.99 | 1,799.18 | 258.19 |

The averages are dominated by a few stalls; their ordering should not be
treated as a stable ranking from this small sample. In particular, the
follow-up reversed the fresh DELETE/WAL average ranking.

Fresh DELETE issued 48 synchronization calls over 12 writes. Fresh WAL
issued 60: 36 during commits and 24 during closes. Median close time rose
from 0.71 ms to 8.03 ms. Closing the last WAL connection performs checkpoint
work, so measuring only commit would hide part of its cost.

Reusable WAL reduced synchronization calls to 22, including six during
explicit FULL checkpoints, compared with 48 for reusable DELETE. Its three
FULL checkpoints took 6.44–8.30 ms; checkpoint results were respectively
`(busy=0, frames=5, checkpointed=5)`, `(0,4,4)`, `(0,4,4)`.
Final TRUNCATE returned `(0,0,0)` in 2.00 ms; final close took 2.14 ms.
This accounts for the deferred work in this sample.

Despite fewer synchronization calls, reusable WAL hit two long `fdatasync`
calls on its WAL file: **1,790.368 ms and 1,107.603 ms**. Both occurred inside
commit. The RAM control's median commits ranged from 1.08 to 2.56 ms, and
its maximum complete-write cycle was 20.76 ms across the four cases.

## Follow-up: locate delays outside commit

The first trace also showed long preparation/update phases with fast
commits. The second comparison added open, close, truncate, mapped-file,
and positional read/write syscalls. Read/write buffers were rendered as raw
addresses, so the retained traces contain no buffer payloads.

| Connection / journal | Median commit | Median complete write | Maximum complete write | Checkpoint-inclusive average per write |
|---|---:|---:|---:|---:|
| Fresh / DELETE | 25.26 | 40.18 | 1,093.50 | 169.89 |
| Fresh / WAL | 24.07 | 48.75 | 3,047.07 | 559.97 |
| Reusable / DELETE | 26.86 | 39.40 | 1,191.89 | 181.30 |
| Reusable / WAL | 15.21 | 20.68 | 1,247.33 | 286.39 |

Timed kernel calls identified:

- Initial 512-byte journal `pwrite64`: **1,046.362 ms** with fresh DELETE and
  **1,153.354 ms** with reusable DELETE, both before commit.
- Creating/opening the fresh WAL shared-memory file with `openat`:
  **1,111.200 ms and 1,833.607 ms**, during connection preparation.
- WAL `fdatasync`: **901.740 ms and 1,240.448 ms** with reusable WAL, plus
  **1,168.749 ms** with fresh WAL.

The 3.047-second fresh WAL cycle contained both the 1.834-second shared-memory
file creation and the 1.169-second WAL flush. No failed kernel lock requests
were observed in either comparison. All explicit checkpoints completed,
all 16 databases passed integrity checks, and every final value matched its
last intended write. All temporary database directories were removed.

## Interpretation and next step

These traces establish waits within the storage/filesystem syscall path,
including file creation and tiny writes as well as durable flushes. They
do not isolate the physical USB device from ext4 metadata, Linux writeback,
scheduling, or other host I/O. They do not prove that every earlier voice
stall has the same cause. Syscall tracing and extra settings assertions
also add overhead; these results must not be substituted for end-to-end
spoken-response measurements.

Keep the live database in DELETE/FULL for now. The next useful investigation
is to correlate these waits with device I/O, writeback, and competing
processes, then compare the same workload on another durable storage device
if one is available. Reusable WAL remains a possible reduction in typical
write overhead, but this test does not justify it as the cure for the long
pauses. Retain FULL durability while investigating persistent storage.

SQLite documents both [last-close checkpoints and WAL synchronization
behavior](https://sqlite.org/wal.html). Its current documentation also
describes a rare WAL-reset race affecting the Pi's SQLite 3.46.1, fixed in
3.51.3 and certain backports. A future concurrent WAL writer/checkpointer
design should use a build with that fix. These probes used serial operations
and a single connection per database, outside that concurrent usage pattern.

## Evidence and reproduction

Saved [events, syscall traces, summaries, and hashes](../profiling/sqlite-wal-comparison-20261101/)
include the initial comparison and the expanded `followup/` capture.
The bot remained active with the same PID, 29743, before and after. A final
read-only live-database inspection still reported DELETE, synchronous=2,
4,096-byte pages, and busy_timeout=5,000 ms. No voice test was requested.

Harness: `scripts/compare_sqlite_journals.py`, with sibling
`scripts/diagnose_sqlite_storage.py` providing only the schema constants.
Run the harness with the Pi virtual environment's Python under:

```text
strace -f -ttt -T -yy \
  -e trace=fsync,fdatasync,fcntl,unlink,clock_nanosleep \
  -o <new-RAM-directory>/syscalls.log \
  python -B compare_sqlite_journals.py \
  --disk-root /home/aldwinrpi4/voice-agent-tools \
  --output <new-RAM-directory>/events.jsonl \
  --transactions 12 --interval-secs 5 --checkpoint-every 4
```

For the follow-up, use eight transactions, add
`openat,close,ftruncate,pwrite64,pread64,mmap,msync` to the trace filter, and
add `-e raw=pwrite64,pread64`. Create a fresh output directory for each run.
Generate each summary with `python -B scripts/summarize_sqlite_journals.py
<capture-directory>`. Both Pi runs exited successfully; a local two-write
smoke run also exercised checkpointing and verification for all eight cases.
The application itself remains at checkpoint `81cbbb8`; these harnesses and
results are uncommitted.
