"""Summarize a run's Pi/MCP JSONL traces; paths may be copied from Pi RAM."""

import argparse
import collections
import json
from pathlib import Path
import statistics


def summarize(folder):
    events = []
    incomplete_lines = 0
    for path in Path(folder).glob("*.jsonl"):
        for line in path.read_text().splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                incomplete_lines += 1
    ends = [e for e in events if e["event"] == "span_end"]
    starts = {e["span_id"]: e for e in events if e["event"] == "span_start"}
    finished = {e["span_id"] for e in ends}
    grouped = collections.defaultdict(list)
    for e in ends:
        if e.get("call_id"):
            grouped[e["call_id"]].append(e)
    calls = []
    for call_id, spans in grouped.items():
        phases = collections.defaultdict(list)
        for e in spans:
            phases[e["phase"]].append(e)
        if not phases["mcp_client_total"]:
            continue
        total = phases["mcp_client_total"][0]
        row = {"call_id": call_id, "tool": total["tool"], "error": total.get("error")}
        for phase in ["mcp_client_total", "mcp_open_session", "mcp_rpc", "mcp_server_call",
                      "tool_execute", "sqlite_connect", "sqlite_execute", "sqlite_fetchone",
                      "sqlite_fetchall", "sqlite_commit", "sqlite_close", "http_request"]:
            row[phase + "_ms"] = round(sum(e["elapsed_ms"] for e in phases[phase]), 3) if phases[phase] else None
        if phases["state_rpc"] or phases["state_worker_call"]:
            for phase in ["state_rpc", "state_worker_call"]:
                row[phase + "_ms"] = round(sum(e["elapsed_ms"] for e in phases[phase]), 3) if phases[phase] else None
            row["state_request_count"] = len(phases["state_rpc"])
            row["sqlite_components"] = sorted({e["component"] for e in spans if e["phase"].startswith("sqlite_")})
            if phases["state_rpc"] and phases["state_worker_call"]:
                row["state_rpc_outside_worker_ms"] = round(sum(e["elapsed_ms"] for e in phases["state_rpc"])
                    - sum(e["elapsed_ms"] for e in phases["state_worker_call"]), 3)
        if phases["mcp_rpc"]:
            rpc = phases["mcp_rpc"][0]
            total_start, rpc_start = starts.get(total["span_id"]), starts.get(rpc["span_id"])
            if total_start and rpc_start:
                row["client_before_rpc_ms"] = round((rpc_start["mono_ns"] - total_start["mono_ns"]) / 1e6, 3)
            row["client_after_rpc_ms"] = round((total["mono_ns"] - rpc["mono_ns"]) / 1e6, 3)
            if phases["mcp_server_call"]:
                server = phases["mcp_server_call"][0]
                server_start = starts.get(server["span_id"])
                same_clock = rpc.get("clock_domain") == server.get("clock_domain")
                if rpc_start and server_start and same_clock:
                    row["rpc_to_server_entry_ms"] = round((server_start["mono_ns"] - rpc_start["mono_ns"]) / 1e6, 3)
                if same_clock:
                    row["server_exit_to_rpc_return_ms"] = round((rpc["mono_ns"] - server["mono_ns"]) / 1e6, 3)
                if "clock_domain" in rpc or "clock_domain" in server:
                    row["same_clock_domain"] = same_clock
                    row["rpc_outside_server_ms"] = round(rpc["elapsed_ms"] - server["elapsed_ms"], 3)
        calls.append(row)
    loops = {}
    for component in {e["component"] for e in events}:
        lags = [e["lag_ms"] for e in events if e["event"] == "event_loop_lag" and e["component"] == component]
        loops[component] = {"count_over_50ms": len(lags), "max_lag_ms": round(max(lags), 3) if lags else 0}
    logging = sorted((e for e in ends if e["phase"] in {"timing_log", "route_log"}),
                     key=lambda e: e["elapsed_ms"], reverse=True)[:10]
    model = [e["elapsed_ms"] for e in ends if e["phase"] == "model_client"]
    return {"run_ids": sorted({e["run"] for e in events}), "event_count": len(events),
            "incomplete_lines": incomplete_lines,
            "unfinished_spans": [e for key, e in starts.items() if key not in finished],
            "max_reported_dropped": max((e.get("dropped", 0) for e in events), default=0),
            "max_reported_write_errors": max((e.get("write_errors", 0) for e in events), default=0),
            "model_ms": {"count": len(model), "median": statistics.median(model) if model else None},
            "event_loop": loops, "slowest_normal_logs": logging, "calls": calls}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", help="One run directory containing Pi and MCP JSONL files")
    args = parser.parse_args()
    print(json.dumps(summarize(args.folder), indent=2))
