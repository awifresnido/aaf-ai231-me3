# Pi storage activity and durable-storage comparison — 2026-11-01

The Pi's USB storage path is the leading explanation for the reproduced
second-long database pauses. During tiny journal writes, the probe slept
inside ext4/JBD2 write access while the USB/SCSI command remained unfinished.
Dirty memory was small, and the readable bot/MCP counters showed no disk
writes. The same six-write probe without tracing measured median commits
of **792.73 ms on the Pi** and **2.43 ms on the Jetson's NVMe**.

This narrows the problem beyond the earlier
[WAL comparison](sqlite-wal-comparison-20261101.md). It does not prove a
physical drive defect or isolate the device from the Pi's driver/kernel.
No live database, service, audio, model, synchronization policy, or sysctl
was changed. These are storage tests, not new end-to-end voice tests.

## Correlation tests

Two probes used synthetic DELETE/FULL databases on the Pi's existing
`/dev/sda2` ext4 filesystem, plus RAM controls and raw 4 KiB flushes.
An observer sampled disk/SCSI counters, dirty/writeback memory, CPU,
process I/O, and blocked thread names/wait channels. All captures went to
RAM. Only the probe was traced; no live bot process was attached.

The first run sampled every 200 ms, including a full process scan each
time. Its median scan took 75.18 ms, so it was followed by a lighter run:
100 ms device sampling, full process scans about once a second, and fast
checks of the probe and journal/USB threads between those scans. Median
light-run sampling cost was 2.46 ms; full scans had a 44.21 ms median.
The first capture is retained, but conclusions below emphasize the lighter
confirmation and the subsequent untraced comparison.

The lighter run recorded:

- Four 512-byte journal writes taking **343, 1,207, 1,222, and 1,897 ms**.
  The writer was sampled in `do_get_write_access`, with `jbd2/sda2-8` and
  `usb-storage` also blocked and a SCSI request awaiting completion.
- Raw-file `fdatasync` of **1,242 ms** and `fsync` of **880 ms**. The writer
  waited in `folio_wait_bit_common` and `blk_mq_get_tag`; a pending device
  command was again visible. This reproduces delays outside SQLite.
- At most **52 KiB dirty** and **12 KiB in writeback** during the probe,
  versus a sampled background dirty threshold of at least **328,984 KiB**.
  Available memory stayed above 3.14 GiB; no swap pages moved.
- **66 completed block writes / 644 KiB** over the approximately 37.86-second
  bracketed probe window. Aggregate write time divided by completed writes
  was **122.79 ms**. CPU busy time was about 13.5% across the machine;
  sampled CPU iowait was 7.3%.
- Before the probe, the disk completed just one 4 KiB write during the
  approximately ten-second baseline, but its accumulated write time was
  **1,562 ms**. High write throughput was not required for a long wait.

Linux's [JBD2 implementation](https://raw.githubusercontent.com/torvalds/linux/v6.18/fs/jbd2/transaction.c)
obtains buffer write access in `do_get_write_access` and can wait for
outstanding buffer I/O. The observed wait channel supports filesystem
metadata/journal involvement; it is not a complete kernel stack trace.

Disk deltas use the [kernel's documented counter definitions](https://www.kernel.org/doc/html/latest/admin-guide/iostats.html).
In these captures, the block `inflight` gauge remained zero even while SCSI
request/done counters differed. We therefore retain both and use the
sustained SCSI difference as evidence of an unfinished command. Counters
are sampled separately and window boundaries are bracketed by samples.

## Competing work and hardware observations

The live bot PID 29743 and MCP PID 29783 accumulated zero `read_bytes`,
`write_bytes`, and `cancelled_write_bytes` in both observer captures.
In the lighter probe window, readable process counters attributed 139,264
write bytes to the probe and 4,096 to a shell. Parent/child counters must not
be added together because waited-child I/O can be incorporated into a
parent's accounting.

Only 15–20 processes' I/O counters were readable out of 165–170 processes
in full scans. Root-owned counters and kernel wait channels were mostly
restricted, and passwordless sudo was unavailable. Consequently, this is
evidence against heavy *observed* competing application writes, not proof
that every competing writer was absent. No service was stopped to create
an artificial quiet machine.

The root drive identifies as Sony USB storage, 57.7 GiB, on a 5,000 Mbit/s
USB link using `usb-storage`. The speakerphone is on the separate USB2 bus.
The device reports write-through caching, no FUA support, and a request
setting of two. These settings were inspected only. The reported rotational
flag does not establish the physical medium type.

`vcgencmd get_throttled` stayed `0x0`; observed temperatures were about
50–54 C. The SCSI error counter remained `0x1` throughout both captures,
so there was no counter increase. The readable boot kernel log contained
no matching storage I/O errors, USB resets, or undervoltage messages in
the final check. These observations do not establish that the device is
healthy or explain the existing counter value.

## Untraced durable-storage comparison

Both hosts ran the identical, hash-verified `diagnose_sqlite_storage.py`
with six writes, two raw-flush pairs, and five-second gaps. Neither run
used strace or the observer. Fresh connections, the synthetic 28 KiB schema,
DELETE journal mode, and FULL synchronization were retained on both hosts.

| Measurement, milliseconds | Pi USB/ext4 | Jetson NVMe/ext4 |
|---|---:|---:|
| Median SQLite commit, six writes | 792.73 | 2.43 |
| Maximum SQLite commit | 1,937.25 | 3.18 |
| Median SQLite update before commit | 0.82 | 0.62 |
| Maximum raw fdatasync, two calls | 9.03 | 1.05 |
| Maximum raw fsync, two calls | 9.32 | 1.06 |
| Median RAM SQLite commit | 0.38 | 0.20 |

The Jetson's root/models filesystem is a Kingston SNV3S500G NVMe, with
364 GiB free at inspection. The probes used disposable directories under
the owning user's home, outside model files. ASR/TTS containers remained up.

This small comparison demonstrates a practical faster durable-storage
candidate and confirms the Pi pauses persist without the monitor. It
changes host/kernel and SQLite version as well as storage: Pi SQLite
3.46.1 versus Jetson 3.45.1. It cannot establish a drive-only speed ratio,
predict future percentiles, or estimate total spoken-response improvement.
The position of stalls moved between update and commit across runs, so
timing only commit is insufficient.

## Recommended application trial

Retain the live Pi's DELETE/FULL policy. Do not adjust dirty-memory limits
based on a backlog that these captures did not show. The kernel documents
those limits as [writeback controls](https://www.kernel.org/doc/html/latest/admin-guide/sysctl/vm.html),
not a remedy for slow completion of a few small durable writes.

The next bounded application trial can run the existing VCM MCP tool server
on the Jetson against disposable state on NVMe and connect from the Pi over
SSH stdio. Keep Pi audio, ThinkPad inference, and Jetson ASR/TTS unchanged.
Measure MCP transport, database phases, and spoken-response timing before
choosing a permanent migration. That trial has not been deployed here.
If a different durable drive is attached to the Pi, repeating the same
probe there would provide a cleaner same-host comparison and could preserve
the current local tool-server architecture.

Before any permanent move, preserve existing reminder/timer/alarm/device
state, maintain a single authoritative writer, and verify reboot behavior
and rollback. Storage work can address the long tool pauses; existing
model, endpointing, and speech-generation delays remain separate timings.

## Evidence and resumption

[Saved captures and summaries](../profiling/storage-activity-20261101/)
contain the first observer run, lighter `light/` confirmation, and untraced
`durable-pi/` and `durable-jetson/` runs. Activity JSONL files are compressed
losslessly; syscall traces suppress positional read/write buffer contents.
Captures contain process names/counters, not command lines or environments.

`scripts/profile_storage_activity.py` wraps a separately supplied probe with
read-only sampling; `scripts/summarize_storage_activity.py` regenerates each
observer summary from its capture directory. `capture.json` records hashes,
commands, coverage, and the initial sampler revision. All four probes exited
successfully and temporary databases were removed. Live Pi PID 29743 and
DELETE/FULL settings were verified again after testing. Changes remain
uncommitted after checkpoint `81cbbb8` on `two-brain-plusjev`.
