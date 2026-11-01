"""Summarize compare_sqlite_journals events and filtered strace output."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import statistics


def stats(values):
    return {"count": len(values), "median_ms": statistics.median(values),
            "min_ms": min(values), "max_ms": max(values), "sum_ms": sum(values)} if values else None


def summarize(folder):
    events = [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines()]
    assert events[-1]["event"] == "probe_completed", "Incomplete probe"
    pending, phases, cases = [], [], {}
    for event in events:
        if event["event"] == "phase_start":
            pending.append(event)
        elif event["event"] == "phase_end":
            started = pending.pop()
            assert all(event.get(k) == started.get(k) for k in ["phase", "case", "iteration"])
            assert event["error"] is None, event
            phases.append({**event, "start_at": started["at"]})
        elif event["event"] == "case_settings":
            cases[event["case"]] = {"settings": event}
    assert not pending
    flushes, failures, slow_other, descriptors = [], [], [], {}
    for line in (folder / "syscalls.log").read_text().splitlines():
        opened = re.match(r"\s*(\d+)\s+[0-9.]+\s+openat\(.*\) = (\d+)<([^>]+)>", line)
        if opened:
            descriptors[(opened[1], int(opened[2]))] = opened[3]
        if "fcntl(" in line and "= -1" in line:
            failures.append(line)
        other = re.match(r"\s*(\d+)\s+(\d+\.\d+)\s+(\w+)\(.* <([0-9.]+)>$", line)
        if other and other[3] not in {"fsync", "fdatasync", "clock_nanosleep"} and float(other[4]) > 0.1:
            enclosing = [p for p in phases if p["start_at"] <= float(other[2]) <= p["at"]]
            phase = min(enclosing, key=lambda p: p["elapsed_ms"]) if enclosing else {}
            raw_fd = re.search(r"\w+\((0x[0-9a-f]+),", line)
            target = (opened[3] if opened else
                      descriptors.get((other[1], int(raw_fd[1], 16))) if raw_fd else None)
            slow_other.append({"at": float(other[2]), "syscall": other[3],
                               "elapsed_ms": float(other[4]) * 1000, "case": phase.get("case"),
                               "phase": phase.get("phase"), "iteration": phase.get("iteration"),
                               "target": target, "line": line})
        closed = re.match(r"\s*(\d+)\s+[0-9.]+\s+close\((\d+)(?:<.*?>)?\) = 0", line)
        if closed:
            descriptors.pop((closed[1], int(closed[2])), None)
        match = re.match(r"\s*(\d+)\s+(\d+\.\d+)\s+(fsync|fdatasync)\(.*= 0 <([0-9.]+)>$", line)
        if not match:
            continue
        _, timestamp, syscall, duration = match.groups()
        timestamp = float(timestamp)
        enclosing = [p for p in phases if p["start_at"] <= timestamp <= p["at"]]
        assert enclosing, line
        phase = min(enclosing, key=lambda p: p["elapsed_ms"])
        flushes.append({"at": timestamp, "syscall": syscall, "elapsed_ms": float(duration) * 1000,
                        "case": phase["case"], "phase": phase["phase"],
                        "iteration": phase.get("iteration"), "line": line})
    runtime_phases = {"cycle", "persistent_open", "persistent_close", "checkpoint_full", "checkpoint_truncate"}
    setup_phases = {"setup", "seed_fsync", "verify"}
    for name, result in cases.items():
        own = [p for p in phases if p["case"] == name]
        grouped = defaultdict(list)
        for p in own:
            grouped[p["phase"]].append(p["elapsed_ms"])
        result["phases"] = {k: stats(v) for k, v in sorted(grouped.items())}
        total = sum(p["elapsed_ms"] for p in own if p["phase"] in runtime_phases)
        result["runtime_total_ms"] = total
        result["runtime_amortized_ms_per_write"] = total / len(grouped["cycle"])
        result["checkpoints"] = [e for e in events if e["event"] == "checkpoint_result" and e["case"] == name]
        own_flush = [f for f in flushes if f["case"] == name and f["phase"] not in setup_phases]
        result["runtime_flushes"] = stats([f["elapsed_ms"] for f in own_flush])
        result["runtime_flush_count_by_phase"] = dict(Counter(f["phase"] for f in own_flush))
        result["slow_runtime_flushes_over_100ms"] = [f for f in own_flush if f["elapsed_ms"] > 100]
        result["verified"] = any(e["event"] == "verified" and e["case"] == name for e in events)
        assert result["verified"]
    return {"probe": events[0], "cases": cases, "failed_kernel_lock_requests": failures,
            "all_flush_count": len(flushes),
            "slow_other_syscalls_over_100ms": slow_other,
            "slow_flushes_over_100ms_including_setup": [f for f in flushes if f["elapsed_ms"] > 100],
            "runtime_definition": "sum(cycle + persistent_open + checkpoints + persistent_close); excludes setup, verify, deliberate sleeps; nested spans are not added twice"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.folder), indent=2))
