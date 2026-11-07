"""Compare DELETE/FULL and WAL/FULL on disposable, synthetic databases only.

Fresh connections include last-close checkpoint costs; persistent connections
include explicit checkpoints and final close. All operations are serial. Run
under strace and put --output in RAM to avoid tracing-induced storage writes.
"""

import argparse
from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import resource
import sqlite3
import statistics
import tempfile
import time

from diagnose_sqlite_storage import SCHEMA


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disk-root", type=Path, required=True)
    parser.add_argument("--ram-root", type=Path, default=Path("/dev/shm"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--transactions", type=int, default=12)
    parser.add_argument("--interval-secs", type=float, default=5)
    parser.add_argument("--checkpoint-every", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.transactions <= 40 or not 1 <= args.checkpoint_every <= 40:
        parser.error("Use 1–40 transactions/checkpoint interval")
    if not 0 <= args.interval_secs <= 15:
        parser.error("Use a 0–15 second interval")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    records = []
    with args.output.open("x", buffering=1) as output, ExitStack() as cleanup:
        def emit(event, **fields):
            item = {"event": event, "at": time.time(), "mono_ns": time.monotonic_ns(),
                    "pid": os.getpid(), **fields}
            records.append(item)
            output.write(json.dumps(item, separators=(",", ":")) + "\n")

        @contextmanager
        def span(phase, case, **fields):
            started = time.monotonic_ns()
            before = resource.getrusage(resource.RUSAGE_SELF)
            emit("phase_start", phase=phase, case=case, **fields)
            error = None
            try:
                yield
            except BaseException as exc:
                error = type(exc).__name__
                raise
            finally:
                after = resource.getrusage(resource.RUSAGE_SELF)
                emit("phase_end", phase=phase, case=case,
                     elapsed_ms=(time.monotonic_ns() - started) / 1e6,
                     cpu_ms=((after.ru_utime + after.ru_stime) -
                             (before.ru_utime + before.ru_stime)) * 1000,
                     output_blocks=after.ru_oublock - before.ru_oublock,
                     error=error, **fields)

        emit("probe_started", sqlite_version=sqlite3.sqlite_version,
             transactions=args.transactions, interval_secs=args.interval_secs,
             checkpoint_every=args.checkpoint_every, serial_single_connection_per_database=True)
        template = sqlite3.connect(":memory:")
        for sql in SCHEMA:
            template.execute(sql)
        template.commit()
        image = template.serialize()
        template.close()
        cases = []
        for medium, root in [("disk", args.disk_root), ("ram", args.ram_root)]:
            folder = Path(cleanup.enter_context(tempfile.TemporaryDirectory(
                prefix="voice-wal-compare-", dir=root)))
            for lifecycle in ["fresh", "persistent"]:
                for mode in ["delete", "wal"]:
                    name = f"{medium}:{lifecycle}:{mode}"
                    path = folder / f"{lifecycle}-{mode}.sqlite"
                    with span("setup", name):
                        with path.open("xb") as seed:
                            seed.write(image)
                            seed.flush()
                            with span("seed_fsync", name):
                                os.fsync(seed.fileno())
                        db = sqlite3.connect(path)
                        try:
                            db.execute("PRAGMA synchronous=FULL")
                            actual_mode = db.execute("PRAGMA journal_mode=" + mode).fetchone()[0]
                            assert actual_mode == mode
                        finally:
                            db.close()
                    cases.append({"name": name, "path": path, "mode": mode,
                                  "lifecycle": lifecycle, "db": None})
                    emit("case_settings", case=name, database=str(path), seed_bytes=len(image),
                         journal_mode=mode, synchronous=2, wal_autocheckpoint=1000)
        try:
            for case in cases:
                if case["lifecycle"] == "persistent":
                    with span("persistent_open", case["name"]):
                        case["db"] = sqlite3.connect(case["path"])

            for iteration in range(args.transactions):
                if iteration and args.interval_secs:
                    time.sleep(args.interval_secs)
                # Reverse each round, rotate each pair: vary ordering without
                # overlapping writes or changing the databases/workload.
                offset = (iteration // 2) % len(cases)
                ordered = cases[offset:] + cases[:offset]
                if iteration % 2:
                    ordered = list(reversed(ordered))
                for case in ordered:
                    name = case["name"]
                    with span("cycle", name, iteration=iteration):
                        db = case["db"]
                        if db is None:
                            with span("open", name, iteration=iteration):
                                db = sqlite3.connect(case["path"])
                        try:
                            with span("prepare", name, iteration=iteration):
                                db.execute("PRAGMA synchronous=FULL")
                                settings = {p: db.execute("PRAGMA " + p).fetchone()[0]
                                            for p in ["journal_mode", "synchronous", "wal_autocheckpoint"]}
                                assert settings == {"journal_mode": case["mode"],
                                                    "synchronous": 2, "wal_autocheckpoint": 1000}
                                for sql in SCHEMA:
                                    db.execute(sql)
                                db.commit()
                            with span("execute", name, iteration=iteration):
                                db.execute("INSERT INTO device_state(key,value) VALUES (?,?) "
                                           "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                           ("synthetic", json.dumps({"iteration": iteration})))
                            with span("commit", name, iteration=iteration):
                                db.commit()
                        finally:
                            if case["db"] is None:
                                with span("close", name, iteration=iteration):
                                    db.close()
                        wal_path = Path(str(case["path"]) + "-wal")
                        emit("cycle_state", case=name, iteration=iteration,
                             wal_bytes=wal_path.stat().st_size if wal_path.exists() else 0)
                    if (case["mode"] == "wal" and case["lifecycle"] == "persistent" and
                            (iteration + 1) % args.checkpoint_every == 0):
                        with span("checkpoint_full", name, iteration=iteration):
                            result = db.execute("PRAGMA wal_checkpoint(FULL)").fetchone()
                        emit("checkpoint_result", case=name, iteration=iteration, kind="FULL",
                             busy=result[0], log_frames=result[1], checkpointed_frames=result[2])
                        assert result[0] == 0 and result[1] == result[2]
                print(json.dumps({"iteration_completed": iteration + 1}), flush=True)

            for case in cases:
                db, name = case["db"], case["name"]
                if db is not None:
                    if case["mode"] == "wal":
                        with span("checkpoint_truncate", name):
                            result = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                        emit("checkpoint_result", case=name, kind="TRUNCATE", busy=result[0],
                             log_frames=result[1], checkpointed_frames=result[2])
                        assert tuple(result) == (0, 0, 0)
                    with span("persistent_close", name):
                        db.close()
                    case["db"] = None
                with span("verify", name):
                    db = sqlite3.connect(case["path"])
                    try:
                        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                        value = db.execute("SELECT value FROM device_state WHERE key='synthetic'").fetchone()
                        assert json.loads(value[0]) == {"iteration": args.transactions - 1}
                        assert db.execute("SELECT count(*) FROM device_state").fetchone() == (1,)
                    finally:
                        db.close()
                emit("verified", case=name, integrity_check="ok", final_iteration=args.transactions - 1)
        finally:
            for case in cases:
                if case["db"] is not None:
                    case["db"].close()

        groups = {}
        for row in records:
            if row["event"] == "phase_end":
                groups.setdefault(row["case"] + ":" + row["phase"], []).append(row["elapsed_ms"])
        summary = {key: {"count": len(values), "median_ms": statistics.median(values),
                         "min_ms": min(values), "max_ms": max(values), "sum_ms": sum(values)}
                   for key, values in groups.items()}
        emit("probe_completed", summary=summary)
        print(json.dumps({"completed": True, "cases": len(cases), "cycles": len(cases) * args.transactions}),
              flush=True)


if __name__ == "__main__":
    main()
