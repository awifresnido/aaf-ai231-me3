"""Analyze decoded tones and RTP timing from a selected lab results directory."""

import argparse
import json
from pathlib import Path
import wave

import numpy as np

from lab import stats, tone_label


def analyze(root):
    summary = json.loads((root / "summary.json").read_text())
    timing = json.loads((root / "guarded_handoffs/timing.json").read_text())
    events = json.loads((root / "guarded_handoffs/events.json").read_text())
    if not summary.get("run_id") or timing.get("run_id") != summary["run_id"]:
        raise ValueError("Summary and timing must belong to the same current lab run")
    with wave.open(str(root / "guarded_handoffs/receiver.wav")) as audio:
        rate = audio.getframerate()
        pcm = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
    frames, offset = [], 0
    for frame in timing["receiver_timing"]:
        count = frame["samples"]
        frames.append(
            {**frame, "label": tone_label(pcm[offset : offset + count], rate)}
        )
        offset += count
    if offset != len(pcm):
        raise ValueError("Receiver WAV length does not match its timing records")
    changes, last_source = [], None
    for frame in frames:
        # Silence is measured separately; it does not create a new source.
        if frame["label"] != "silence" and frame["label"] != last_source:
            changes.append(frame)
            last_source = frame["label"]
    transitions = summary["guarded"]["transitions"]
    expected = ["pp"] + [item["to"] for item in transitions] + ["cascade"]
    aligned = [item["label"] for item in changes] == expected
    checks = [
        {
            "name": "all_60_source_changes_reached_decoded_peer_in_order",
            "passed": aligned,
            "expected_count": len(expected),
            "observed_count": len(changes),
        }
    ]
    metrics = {}
    if aligned:
        # Exclude the final stale-frame test's intentional pause from handoff gaps.
        handoffs = changes[1 : len(transitions) + 1]
        delays = [
            (received["t"] - command["requested"]) * 1000
            for received, command in zip(handoffs, transitions)
        ]
        metrics["handoff_request_to_receiver_delivery_ms"] = stats(delays)
        checks.append(
            {
                "name": "decoded_peer_transition_p95_under_300ms",
                "passed": bool(np.percentile(delays, 95) < 300),
                "metrics_ms": stats(delays),
            }
        )
        silence = []
        for prior, current in zip(changes[: len(transitions)], handoffs):
            selected = [
                frame
                for frame in frames
                if prior["pts"] <= frame["pts"] < current["pts"]
            ]
            trailing = 0.0
            for frame in reversed(selected):
                if frame["label"] != "silence":
                    break
                trailing += frame["samples"] / frame["rate"] * 1000
            silence.append(trailing)
        metrics["classified_silence_between_sources_ms"] = stats(silence)
        checks.append(
            {
                "name": "no_decoded_silence_gap_over_300ms",
                "passed": max(silence) < 300,
                "metrics_ms": stats(silence),
            }
        )
    else:
        for name in (
            "decoded_peer_transition_p95_under_300ms",
            "no_decoded_silence_gap_over_300ms",
        ):
            checks.append(
                {
                    "name": name,
                    "passed": False,
                    "status": "unrun",
                    "reason": "Source sequence did not align",
                }
            )
    violations = 0
    for command in transitions:
        next_handoffs = [
            event["t"]
            for event in events
            if event["event"] == "handoff_requested" and event["t"] > command["first"]
        ]
        end = (
            min(next_handoffs)
            if next_handoffs
            else timing["sender_timing"][-1]["t"] + 0.01
        )
        violations += sum(
            frame["label"] == command["from"]
            for frame in timing["sender_timing"]
            if command["first"] <= frame["t"] < end
        )
    checks.append(
        {
            "name": "no_revoked_sender_audio_reappeared_after_switch",
            "passed": violations == 0,
            "violations": violations,
        }
    )
    names = {check["name"] for check in checks}
    summary["checks"] = [
        check for check in summary["checks"] if check["name"] not in names
    ] + checks
    summary["receiver_analysis"] = metrics
    summary["all_passed"] = all(check["passed"] for check in summary["checks"])
    (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    for check in checks:
        print(json.dumps(check))
    print(
        "TOTAL",
        sum(check["passed"] for check in summary["checks"]),
        "/",
        len(summary["checks"]),
    )
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_dir", type=Path)
    args = parser.parse_args()
    raise SystemExit(analyze(args.results_dir.resolve()))
