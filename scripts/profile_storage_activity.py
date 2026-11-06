"""Sample read-only Linux I/O metadata around a separately supplied probe.

Captures counters, process names/states and blocked thread wait channels, not
command lines, environments, file contents, or audio. Store output in RAM.
Never changes sysctls, service state, caches, or live database configuration.
"""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError as exc:
        return {"error": type(exc).__name__}


def counters(path, selected=None):
    raw = read(path)
    if not isinstance(raw, str):
        return raw
    result = {}
    for line in raw.splitlines():
        fields = line.replace(":", "").split()
        if len(fields) >= 2 and (selected is None or fields[0] in selected):
            try:
                result[fields[0]] = int(fields[1])
            except ValueError:
                pass
    return result


def process_stat(path):
    raw = path.read_text()
    fields = raw[raw.rfind(")") + 2:].split()
    return {"comm": raw[raw.find("(") + 1:raw.rfind(")")], "state": fields[0],
            "ppid": int(fields[1]), "utime": int(fields[11]), "stime": int(fields[12]),
            "starttime": int(fields[19]), "blkio_ticks": int(fields[39])}


def snapshot(device, full_processes=True, watch_pids=()):
    started = time.monotonic_ns()
    processes = {}
    folders = Path("/proc").iterdir() if full_processes else (Path("/proc") / str(pid) for pid in watch_pids)
    for folder in folders:
        if not folder.name.isdigit():
            continue
        try:
            info = process_stat(folder / "stat")
            if full_processes:
                info["io"] = counters(folder / "io")
            if info["state"] == "D":
                info["wchan"] = read(folder / "wchan")
            # Root-owned threads' names/states can be visible even when their
            # I/O counters or wait channels are protected. Record that limit.
            blocked = []
            tasks = (folder / "task").iterdir() if not full_processes or "error" not in info["io"] else []
            for task in tasks:
                try:
                    state = process_stat(task / "stat")
                    if state["state"] == "D":
                        blocked.append({"tid": int(task.name), "comm": state["comm"],
                                        "wchan": read(task / "wchan")})
                except (OSError, ValueError, IndexError):
                    pass
            if blocked:
                info["blocked_threads"] = blocked
            processes[folder.name] = info
        except (OSError, ValueError, IndexError):
            pass
    disk = read(f"/sys/block/{device}/stat")
    cpu = read("/proc/stat")
    return {"event": "sample", "at": time.time(), "mono_ns": time.monotonic_ns(),
            "disk": [int(x) for x in disk.split()] if isinstance(disk, str) else disk,
            "scsi": {key: read(f"/sys/block/{device}/device/{key}")
                     for key in ["iorequest_cnt", "iodone_cnt", "ioerr_cnt"]},
            "cpu": [int(x) for x in cpu.splitlines()[0].split()[1:]] if isinstance(cpu, str) else cpu,
            "mem_kb": counters("/proc/meminfo", {"Dirty", "Writeback", "MemAvailable", "SwapFree", "SwapTotal"}),
            "vm": counters("/proc/vmstat", {"nr_dirty", "nr_writeback", "nr_dirtied", "nr_written",
                                           "nr_dirty_threshold", "nr_dirty_background_threshold",
                                           "pgpgin", "pgpgout", "pswpin", "pswpout"}),
            "process_scan": "full" if full_processes else "watched",
            "processes": processes, "sample_cost_ms": (time.monotonic_ns() - started) / 1e6}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", default="sda")
    parser.add_argument("--baseline-secs", type=float, default=10)
    parser.add_argument("--tail-secs", type=float, default=10)
    parser.add_argument("--period-secs", type=float, default=0.2)
    parser.add_argument("--process-period-secs", type=float, default=1)
    parser.add_argument("--timeout-secs", type=float, default=180)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.device.isalnum() or not Path(f"/sys/block/{args.device}/stat").exists():
        parser.error("Device must name an existing block device")
    if not (0 <= args.baseline_secs <= 30 and 0 <= args.tail_secs <= 30 and
            0.1 <= args.period_secs <= 2 and 0.5 <= args.process_period_secs <= 5 and
            1 <= args.timeout_secs <= 300):
        parser.error("Invalid sampling/timing bound")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("A probe command is required after --")
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    child = None
    exit_code = None
    try:
        with (args.output_dir / "activity.jsonl").open("x", buffering=1) as output, \
                (args.output_dir / "probe-output.log").open("x") as log:
            def emit(event, **fields):
                output.write(json.dumps({"event": event, "at": time.time(),
                                         "mono_ns": time.monotonic_ns(), **fields}, separators=(",", ":")) + "\n")

            settings = {name: read("/proc/sys/vm/" + name) for name in [
                "dirty_background_ratio", "dirty_ratio", "dirty_background_bytes", "dirty_bytes",
                "dirty_expire_centisecs", "dirty_writeback_centisecs"]}
            emit("capture_started", device=args.device, period_secs=args.period_secs,
                 process_period_secs=args.process_period_secs,
                 clock_ticks=os.sysconf("SC_CLK_TCK"), page_size=os.sysconf("SC_PAGE_SIZE"),
                 baseline_secs=args.baseline_secs, tail_secs=args.tail_secs, vm_settings=settings,
                 queue={key: read(f"/sys/block/{args.device}/queue/{key}") for key in [
                     "scheduler", "write_cache", "nr_requests", "rotational"]},
                 journal_before=read(f"/proc/fs/jbd2/{args.device}2-8/info"))
            started = time.monotonic()
            next_sample = started
            child_started = None
            finished = None
            next_process_scan = started
            watch_pids = set()
            while True:
                now = time.monotonic()
                if child is None and now - started >= args.baseline_secs:
                    child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                    child_started = time.monotonic()
                    emit("probe_started", pid=child.pid)
                    print(json.dumps({"probe_started": child.pid}), flush=True)
                if child is not None and finished is None:
                    exit_code = child.poll()
                    if exit_code is not None:
                        finished = time.monotonic()
                        emit("probe_finished", exit_code=exit_code)
                    elif now - child_started > args.timeout_secs:
                        os.killpg(child.pid, signal.SIGTERM)
                        try:
                            child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL)
                            child.wait()
                        raise TimeoutError("Probe exceeded configured bound")
                full_scan = now >= next_process_scan
                if child is not None:
                    watch_pids.add(child.pid)
                    children = read(f"/proc/{child.pid}/task/{child.pid}/children")
                    if isinstance(children, str):
                        watch_pids.update(int(pid) for pid in children.split())
                sample = snapshot(args.device, full_scan, watch_pids)
                if full_scan:
                    next_process_scan = time.monotonic() + args.process_period_secs
                    watch_pids.update(int(pid) for pid, info in sample["processes"].items()
                                      if info["comm"].startswith(("jbd2/", "usb-storage")))
                output.write(json.dumps(sample, separators=(",", ":")) + "\n")
                if finished is not None and time.monotonic() - finished >= args.tail_secs:
                    break
                next_sample += args.period_secs
                # Skip missed sample deadlines instead of creating a burst.
                if next_sample < time.monotonic():
                    next_sample = time.monotonic() + args.period_secs
                time.sleep(max(0, next_sample - time.monotonic()))
            emit("capture_completed", probe_exit_code=exit_code,
                 journal_after=read(f"/proc/fs/jbd2/{args.device}2-8/info"))
            print(json.dumps({"completed": True, "probe_exit_code": exit_code}), flush=True)
    finally:
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
