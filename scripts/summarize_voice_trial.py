"""Summarize a voice capture using explicit/inferred turn-number pass bounds.

Only metadata is read. Optional tts-metadata.json/model-metadata.json contain
filtered runtime measurements, never transcripts or prompt contents.
"""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics


def stats(values):
    return {"count": len(values), "median": statistics.median(values), "min": min(values),
            "max": max(values)} if values else {"count": 0, "median": None, "min": None, "max": None}


def summarize(folder, bounds):
    events = [json.loads(line) for path in folder.glob("*.jsonl") for line in path.read_text().splitlines()]
    turns = defaultdict(list)
    for event in events:
        if event["component"] == "pi" and event["event"] == "turn_event":
            turns[event["turn"]].append(event)
    optional = {}
    for kind in ["tts", "model"]:
        path = folder / f"{kind}-metadata.json"
        optional[kind] = {r["turn"]: r for r in json.loads(path.read_text())["measurements"]} if path.exists() else {}
    rows = []
    for turn, items in sorted(turns.items()):
        def matching(name):
            return sorted((e for e in items if e["timing_event"] == name), key=lambda e: e["mono_ns"])
        native = matching("native_user_bot_latency")
        playback = matching("first_playback_write")
        decision = matching("local_decision")
        ready = [e for e in matching("routing_context_ready") if e["fields"].get("since_speech_end_ms") is not None]
        complete = [e for e in matching("turn_analysis") if e["fields"]["is_complete"]
                    and decision and e["at"] < decision[0]["at"]]
        outcomes = [e for e in items if e["timing_event"] in {"route_local_tool", "route_local_reply", "route_local_failure"}]
        assert len(native) <= 1 and len(decision) <= 1 and len(outcomes) <= 1
        row = {"turn": turn, "start_at": min(e["at"] for e in items),
               "transcript_frames": len(matching("asr_transcript")),
               "native_latency_s": native[0]["fields"]["seconds"] if native else None,
               "first_playback_ms": playback[0]["fields"].get("since_speech_end_ms") if playback else None,
               "model_s": decision[0]["fields"]["model_s"] if decision else None,
               "tool_decision": decision[0]["fields"]["tool"] if decision else None,
               "endpoint_context_ms": ready[0]["fields"]["since_speech_end_ms"] if ready else None,
               "smart_turn_ms": complete[-1]["fields"]["e2e_processing_time_ms"] if complete else None,
               "outcome": outcomes[0]["timing_event"] if outcomes else None,
               "outcome_metadata": outcomes[0]["fields"] if outcomes else None,
               "tts_ttfb_s": optional["tts"].get(turn, {}).get("ttfb_s"),
               "model_server": optional["model"].get(turn)}
        rows.append(row)

    def group(selected):
        measured = [row for row in selected if row["native_latency_s"] is not None]
        stages = {field: stats([row[field] for row in measured if row[field] is not None])
                  for field in ["native_latency_s", "first_playback_ms", "model_s", "endpoint_context_ms",
                                "smart_turn_ms", "tts_ttfb_s"]}
        stages["outcomes"] = dict(Counter(row["outcome"] for row in selected if row["outcome"]))
        stages["unmeasured_turns"] = [row["turn"] for row in selected if row["native_latency_s"] is None]
        stages["model_server"] = {field: stats([row["model_server"][field] for row in measured if row["model_server"]])
            for field in ["prompt_ms", "generation_ms", "server_total_ms", "pi_minus_server_ms",
                          "prompt_evaluated_tokens", "generation_tokens"]}
        return stages

    selected = [row for row in rows if any(lo <= row["turn"] <= hi for lo, hi in bounds)]
    return {"pass_bounds": bounds, "passes": [group([row for row in rows if lo <= row["turn"] <= hi])
                                             for lo, hi in bounds], "combined": group(selected),
            "excluded_turns": [row["turn"] for row in rows if row not in selected], "turns": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--pass-turns", action="append", required=True, help="Inclusive first:last turn, repeat per pass")
    args = parser.parse_args()
    bounds = []
    for value in args.pass_turns:
        try:
            lo, hi = map(int, value.split(":"))
            assert 0 <= lo <= hi
        except (ValueError, AssertionError):
            parser.error("Pass bounds must be nonnegative first:last pairs")
        if bounds and lo <= bounds[-1][1]:
            parser.error("Pass bounds must be ordered and non-overlapping")
        bounds.append((lo, hi))
    print(json.dumps(summarize(args.folder, bounds), indent=2))
