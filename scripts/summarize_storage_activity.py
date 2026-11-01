"""Correlate read-only storage samples with disposable SQLite probe traces."""

from collections import Counter, defaultdict
import argparse
import gzip
import json
from pathlib import Path
import re
import statistics


def stats(values):
    return {"count": len(values), "min": min(values), "median": statistics.median(values),
            "max": max(values)} if values else None


def summarize(folder):
    activity_path = folder / "activity.jsonl"
    raw_activity = (activity_path.read_bytes() if activity_path.exists() else
                    gzip.decompress((folder / "activity.jsonl.gz").read_bytes()))
    activity = [json.loads(x) for x in raw_activity.splitlines()]
    assert activity[-1]["event"] == "capture_completed" and activity[-1]["probe_exit_code"] == 0
    samples = [x for x in activity if x["event"] == "sample"]
    events = [json.loads(x) for x in (folder / "events.jsonl").read_text().splitlines()]
    assert events[-1]["event"] == "probe_completed"
    begin = next(x for x in activity if x["event"] == "probe_started")
    end = next(x for x in activity if x["event"] == "probe_finished")
    full = [s for s in samples if s.get("process_scan", "full") == "full"]

    def window(lo, hi):
        # Include bracketing samples to account for requests completed just
        # after a traced call returns. Return actual bounds, not false precision.
        first = max((i for i, s in enumerate(samples) if s["at"] <= lo), default=0)
        last = next((i for i, s in enumerate(samples) if s["at"] >= hi), len(samples) - 1)
        selected = samples[first:last + 1]
        a, b = selected[0], selected[-1]
        seconds = (b["mono_ns"] - a["mono_ns"]) / 1e9
        delta = [y - x for x, y in zip(a["disk"], b["disk"])]
        assert all(v >= 0 for i, v in enumerate(delta) if i != 8), "Device counters reset"
        cpu = [y - x for x, y in zip(a["cpu"][:8], b["cpu"][:8])]
        cpu_total = sum(cpu)
        blocked, writers, seen = Counter(), defaultdict(int), {}
        for sample in selected:
            for pid, info in sample["processes"].items():
                threads = info.get("blocked_threads", [])
                if not threads and info["state"] == "D":
                    threads = [{"comm": info["comm"], "wchan": info.get("wchan")}]
                for thread in threads:
                    blocked[(pid, thread["comm"], str(thread.get("wchan")))] += 1
                io = info.get("io", {})
                if "write_bytes" not in io:
                    continue
                key = (pid, info["starttime"], info["comm"])
                if key in seen:
                    writers[key] += max(0, io["write_bytes"] - seen[key])
                seen[key] = io["write_bytes"]
        pending = [int(s["scsi"]["iorequest_cnt"], 16) - int(s["scsi"]["iodone_cnt"], 16)
                   for s in selected if isinstance(s["scsi"]["iorequest_cnt"], str)
                   and isinstance(s["scsi"]["iodone_cnt"], str)]
        return {"sample_start_at": a["at"], "sample_end_at": b["at"], "sample_seconds": seconds,
                "read_ios": delta[0], "write_ios": delta[4], "written_kib": delta[6] / 2,
                "write_ms": delta[7], "write_await_ms": delta[7] / delta[4] if delta[4] else None,
                "io_ticks_ms": delta[9], "weighted_io_ms": delta[10],
                "sampled_block_inflight_max": max(s["disk"][8] for s in selected),
                "scsi_pending_requests": stats(pending),
                "scsi_pending_sample_count": sum(x > 0 for x in pending),
                "dirty_kib_max": max(s["mem_kb"]["Dirty"] for s in selected),
                "writeback_kib_max": max(s["mem_kb"]["Writeback"] for s in selected),
                "mem_available_kib_min": min(s["mem_kb"]["MemAvailable"] for s in selected),
                "dirty_background_threshold_kib_min": min(s["vm"]["nr_dirty_background_threshold"]
                    * activity[0]["page_size"] / 1024 for s in selected),
                "swap_in_pages": b["vm"]["pswpin"] - a["vm"]["pswpin"],
                "swap_out_pages": b["vm"]["pswpout"] - a["vm"]["pswpout"],
                "cpu_iowait_percent": 100 * cpu[4] / cpu_total if cpu_total else None,
                "cpu_busy_percent": 100 * (cpu_total - cpu[3] - cpu[4]) / cpu_total if cpu_total else None,
                "blocked_samples": [{"pid": p, "comm": c, "wchan": w, "count": count}
                                    for (p, c, w), count in blocked.most_common()],
                "readable_process_write_byte_deltas": [{"pid": p, "comm": c, "write_bytes": n}
                    for (p, _, c), n in sorted(writers.items(), key=lambda x: x[1], reverse=True) if n]}

    phases, pending = [], {}
    for event in events:
        key = tuple(event.get(k) for k in ["case", "phase", "iteration"])
        if event["event"] == "phase_start":
            pending[key] = event
        elif event["event"] == "phase_end":
            start = pending.pop(key)
            assert event["error"] is None
            phases.append({**event, "start_at": start["at"]})
    assert not pending
    slow, descriptors = [], {}
    for line in (folder / "syscalls.log").read_text().splitlines():
        opened = re.match(r"\s*(\d+)\s+[0-9.]+\s+openat\(.*\) = (\d+)<([^>]+)>", line)
        if opened:
            descriptors[(opened[1], int(opened[2]))] = opened[3]
        call = re.match(r"\s*(\d+)\s+(\d+\.\d+)\s+(\w+)\(.* <([0-9.]+)>$", line)
        if call and call[3] != "clock_nanosleep" and float(call[4]) > .1:
            lo, seconds = float(call[2]), float(call[4])
            enclosing = [p for p in phases if p["start_at"] <= lo <= p["at"]]
            phase = min(enclosing, key=lambda p: p["elapsed_ms"]) if enclosing else {}
            raw = re.search(r"\w+\((0x[0-9a-f]+),", line)
            decoded = re.search(r"\w+\(\d+<([^>]+)>", line)
            target = opened[3] if opened else decoded[1] if decoded else (
                descriptors.get((call[1], int(raw[1], 16))) if raw else None)
            slow.append({"at": lo, "elapsed_ms": seconds * 1000, "syscall": call[3],
                         "case": phase.get("case"), "phase": phase.get("phase"),
                         "iteration": phase.get("iteration"), "target": target,
                         "line": line, "activity": window(lo, lo + seconds)})
        closed = re.match(r"\s*(\d+)\s+[0-9.]+\s+close\((\d+)(?:<.*?>)?\) = 0", line)
        if closed:
            descriptors.pop((closed[1], int(closed[2])), None)
    return {"capture": activity[0], "completed": activity[-1], "sample_count": len(samples),
            "sample_cost_ms": stats([s["sample_cost_ms"] for s in samples]),
            "full_scan_cost_ms": stats([s["sample_cost_ms"] for s in full]),
            "watched_scan_cost_ms": stats([s["sample_cost_ms"] for s in samples if s.get("process_scan") == "watched"]),
            "process_io_coverage": {"readable": stats([sum("write_bytes" in p.get("io", {})
                for p in s["processes"].values()) for s in full]), "total": stats([len(s["processes"]) for s in full])},
            "baseline": window(samples[0]["at"], begin["at"]),
            "probe": window(begin["at"], end["at"]),
            "tail": window(end["at"], samples[-1]["at"]),
            "slow_syscalls_over_100ms": slow, "probe_phase_summary": events[-1]["summary"],
            "scsi_error_counter_before": samples[0]["scsi"]["ioerr_cnt"],
            "scsi_error_counter_after": samples[-1]["scsi"]["ioerr_cnt"],
            "limits": ["Window boundaries are bracketed by samples; short I/O can be missed.",
                       "Most root-owned process I/O and wait channels are not readable.",
                       "Per-process counters can include waited children; do not sum parent/child write bytes.",
                       "Block inflight may read zero even while SCSI request/done counters show an outstanding command."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.folder), indent=2))
