"""Trace synthetic SQLite commits/flushes on disk and RAM; never opens live DBs.

Run as a child of strace with fsync,fdatasync,fcntl,clock_nanosleep selected.
All databases/files are exclusively created in temporary subdirectories.
"""

import argparse
import json
import multiprocessing
import os
from pathlib import Path
import resource
import sqlite3
import statistics
import tempfile
import threading
import time


SCHEMA = [
    "CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, created_ms REAL NOT NULL, done INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS device_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS timers (id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT NOT NULL, ends_at REAL NOT NULL, fired INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS alarms (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1)",
]


def hold_reader(path, ready, release):
    connection = sqlite3.connect(path)
    try:
        connection.execute("BEGIN")
        connection.execute("SELECT * FROM device_state").fetchall()
        ready.set()
        release.wait(timeout=5)
        connection.rollback()
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disk-root", required=True, type=Path)
    parser.add_argument("--ram-root", default=Path("/dev/shm"), type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--transactions", type=int, default=4)
    parser.add_argument("--flushes", type=int, default=3)
    parser.add_argument("--interval-secs", type=float, default=0)
    parser.add_argument("--cross-process-lock", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.transactions <= 20 or not 1 <= args.flushes <= 10:
        parser.error("Use 1–20 transactions and 1–10 raw flush pairs")
    if not 0 <= args.interval_secs <= 15:
        parser.error("Interval must be between 0 and 15 seconds")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    records = []
    with args.output.open("x", buffering=1) as output:
        def emit(event, **fields):
            record = {"event": event, "at": time.time(), "mono_ns": time.monotonic_ns(),
                      "pid": os.getpid(), **fields}
            records.append(record)
            output.write(json.dumps(record, separators=(",", ":")) + "\n")
            if event in {"phase_end", "case_settings"}:
                print(json.dumps(record), flush=True)

        def measure(phase, fn, **fields):
            started = time.monotonic_ns()
            usage = resource.getrusage(resource.RUSAGE_SELF)
            emit("phase_start", phase=phase, **fields)
            error = None
            try:
                return fn()
            except BaseException as exc:
                error = type(exc).__name__
                raise
            finally:
                after = resource.getrusage(resource.RUSAGE_SELF)
                emit("phase_end", phase=phase, elapsed_ms=(time.monotonic_ns() - started) / 1e6,
                     cpu_ms=((after.ru_utime + after.ru_stime) - (usage.ru_utime + usage.ru_stime)) * 1000,
                     output_blocks=after.ru_oublock - usage.ru_oublock, error=error, **fields)

        emit("probe_started", sqlite_version=sqlite3.sqlite_version,
             disk_root=str(args.disk_root), ram_root=str(args.ram_root),
             transactions=args.transactions, flushes=args.flushes, interval_secs=args.interval_secs,
             cross_process_lock=args.cross_process_lock)
        template = sqlite3.connect(":memory:")
        for sql in SCHEMA:
            template.execute(sql)
        template.commit()
        image = template.serialize()
        template.close()

        with tempfile.TemporaryDirectory(prefix="voice-sqlite-probe-", dir=args.disk_root) as disk_dir, \
                tempfile.TemporaryDirectory(prefix="voice-sqlite-probe-", dir=args.ram_root) as ram_dir:
            paths = {"disk": Path(disk_dir), "ram": Path(ram_dir)}
            emit("temporary_paths", paths={k: str(v) for k, v in paths.items()})

            def seed(path, case):
                with path.open("xb") as f:
                    f.write(image)
                    f.flush()
                    measure("seed_fsync", lambda: os.fsync(f.fileno()), case=case)

            for case, folder in paths.items():
                path = folder / "synthetic.sqlite"
                seed(path, case)
                c = sqlite3.connect(path)
                c.execute("PRAGMA synchronous=FULL")
                settings = {k: c.execute("PRAGMA " + k).fetchone()[0]
                            for k in ["journal_mode", "synchronous", "busy_timeout", "page_size"]}
                assert settings["journal_mode"] == "delete" and settings["synchronous"] == 2
                c.close()
                emit("case_settings", case=case, database=str(path), bytes=len(image), settings=settings,
                     no_other_connections=True)

            # Alternate media to reduce ordering effects. Each connection mirrors
            # the bot's schema checks, upsert, commit, close, with synthetic values.
            for iteration in range(args.transactions):
                if iteration and args.interval_secs:
                    time.sleep(args.interval_secs)
                for case, folder in paths.items():
                    c = sqlite3.connect(folder / "synthetic.sqlite")
                    c.execute("PRAGMA synchronous=FULL")
                    for sql in SCHEMA:
                        c.execute(sql)
                    c.commit()
                    measure("sqlite_execute", lambda: c.execute(
                        "INSERT INTO device_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        ("synthetic", json.dumps({"iteration": iteration}))), case=case, iteration=iteration)
                    measure("sqlite_commit", c.commit, case=case, iteration=iteration)
                    c.close()

            for iteration in range(args.flushes):
                if iteration and args.interval_secs:
                    time.sleep(args.interval_secs)
                for case, folder in paths.items():
                    path = folder / "raw-flush.bin"
                    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
                    try:
                        for kind in ["fdatasync", "fsync"]:
                            os.lseek(fd, 0, os.SEEK_SET)
                            os.write(fd, bytes([(iteration * 2 + (kind == "fsync")) % 256]) * 4096)
                            measure("raw_" + kind, lambda k=kind: getattr(os, k)(fd),
                                    case=case, iteration=iteration)
                    finally:
                        os.close(fd)

            # Positive control: a known reader holds a shared lock for 250 ms.
            locked_path = paths["ram"] / "lock-control.sqlite"
            seed(locked_path, "lock_control")
            reader = None
            process = None
            if args.cross_process_lock:
                ctx = multiprocessing.get_context("spawn")
                ready, released = ctx.Event(), ctx.Event()
                process = ctx.Process(target=hold_reader, args=(str(locked_path), ready, released))
                process.start()
                if not ready.wait(timeout=3):
                    released.set()
                    process.join(timeout=2)
                    raise RuntimeError("Reader process did not start")
                unlock = released.set
            else:
                reader = sqlite3.connect(locked_path, check_same_thread=False)
                reader.execute("BEGIN")
                reader.execute("SELECT * FROM device_state").fetchall()
                unlock = reader.rollback
            writer = sqlite3.connect(locked_path, timeout=2)
            writer.execute("PRAGMA synchronous=FULL")
            writer.execute("INSERT INTO device_state VALUES (?,?)", ("synthetic", "control"))
            release = threading.Timer(0.25, unlock)
            release.start()
            try:
                measure("sqlite_commit", writer.commit, case="lock_control", held_reader_ms=250,
                        cross_process_lock=args.cross_process_lock)
            finally:
                release.join(timeout=2)
                writer.close()
                if reader:
                    reader.close()
                if process:
                    process.join(timeout=2)

        groups = {}
        for record in records:
            if record["event"] == "phase_end":
                key = record["case"] + ":" + record["phase"]
                groups.setdefault(key, []).append(record["elapsed_ms"])
        emit("probe_completed", summary={k: {"count": len(v), "median_ms": statistics.median(v),
                                             "min_ms": min(v), "max_ms": max(v)} for k, v in groups.items()})
        print(json.dumps(records[-1]), flush=True)


if __name__ == "__main__":
    main()
