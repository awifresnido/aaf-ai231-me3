#!/usr/bin/env python3
"""GATE 5: head-to-head Jev-1.14.0 vs fine-tuned Laya v4 on identical transcripts.

Jev probe: POST https://api.typesafe.ai/v1/systemone, Bearer auth (matches
pipecat JevClient). Key passed via TYPESAFE_API_KEY env var only -- never
written to disk. Same 12-option question format as the Laya router (play_radio
dropped per user decision). Measures: accuracy, wrong-tool, safe-other,
latency p50/p95, at the Jev gate (0.90/0.20) and the Laya gate (0.50/0.05).

Usage: TYPESAFE_API_KEY=... python3 gate5_jev_baseline.py [--slices a,b,c]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import time
import urllib.request
from pathlib import Path

DATA = Path.home() / "projects/laya-router/data"
OUT = Path.home() / "projects/laya-router/laya-router-v4-softce"
MODEL = "jev-1.14.0"
BASE = "https://api.typesafe.ai"

# Same options the Laya router was trained on (order = criteria order).
OPTIONS = {
    "get_time": "Ask for the current local clock time",
    "get_weather": "Ask for current weather, including for a stated location",
    "list_reminders": "Ask to list existing reminders",
    "add_reminder": "Create one reminder with stated note text, such as 'remind me to study'",
    "set_thermostat": "Set the thermostat to one explicit Celsius temperature",
    "control_lights": "Turn lights on or off, set one light color, or set light brightness",
    "set_timer": "Start one countdown with an explicit duration",
    "set_alarm": "Set one alarm with an explicit clock time and AM or PM",
    "playback_control": "Pause, stop, resume, skip, or change volume of current music",
    "play_music": "Start playing music using a stated genre, mood, artist, or title",
    "small_talk": "A brief greeting, thanks, or simple conversational reply that needs no tool",
    "other": "Complex or multiple actions, forecasts, ambiguous follow-ups, factual questions, messaging, or calls",
}
QUESTION = {
    "type": "choice",
    "instructions": "Which single route should handle this utterance?",
    "criteria": OPTIONS,
}


def ask_jev(api_key: str, text: str, timeout: float = 20.0):
    body = json.dumps({"model": MODEL, "state": text,
                       "questions": {"route": QUESTION}}).encode()
    req = urllib.request.Request(
        f"{BASE}/v1/systemone", data=body, method="POST",
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read())
    dt = time.perf_counter() - t0
    ans = payload.get("answers", {}).get("route", {})
    return ans, dt


def load_slice(name: str, n: int | None) -> list[dict]:
    with (DATA / f"routes_{name}.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if n and len(rows) > n:
        import random
        random.seed(20261101)
        rows = random.sample(rows, n)
    return rows


def analyse(rows_results: list[tuple], gate: tuple[float, float]) -> dict:
    tau, gmin = gate
    n = len(rows_results)
    accepted = [x for x in rows_results if x[2] >= tau and x[3] >= gmin]
    correct = sum(1 for t, p, _, _ in accepted if t == p)
    safe = sum(1 for t, p, _, _ in accepted if t != p and p == "other")
    unsafe = sum(1 for t, p, _, _ in accepted if t != p and p != "other")
    return {
        "accept_rate": round(len(accepted) / n, 4),
        "correct_fastpath": round(correct / n, 4),
        "safe_other": round(safe / n, 4),
        "unsafe_of_accepted": round(unsafe / max(len(accepted), 1), 6),
        "unsafe_rate": round(unsafe / n, 6),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slices", default="paraphrase_holdout,test,personal_awi")
    ap.add_argument("--n", type=int, default=200, help="cap per slice (cost control)")
    ap.add_argument("--gates", default="0.90:0.20,0.50:0.05")
    args = ap.parse_args()

    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise SystemExit("TYPESAFE_API_KEY env var required (in-memory only)")

    gates = [tuple(float(x) for x in g.split(":")) for g in args.gates.split(",")]

    # connectivity probe first
    try:
        ans, dt = ask_jev(key, "what time is it", timeout=25)
        print(f"probe OK ({dt*1000:.0f} ms) -> {ans.get('choice')} "
              f"conf={ans.get('confidence')}")
    except Exception as e:
        raise SystemExit(f"PROBE FAILED: {e!r}")

    report = {"model": MODEL, "gate_results": {}, "latency_ms": {}}
    for name in args.slices.split(","):
        rows = load_slice(name, args.n)
        results, lat = [], []
        for r in rows:
            try:
                ans, dt = ask_jev(key, r["text"])
            except Exception as e:
                print(f"  request failed on: {r['text'][:50]!r}: {e!r}")
                continue
            probs = ans.get("probabilities") or {}
            pred = str(ans.get("choice", ""))
            p = float(probs.get(pred, 0.0))
            second = max((v for k, v in probs.items() if k != pred), default=0.0)
            results.append((r["label"], pred, p, p - float(second)))
            lat.append(dt * 1000)
        n = len(results)
        per = {"items": n,
               "accuracy_overall": round(
                   sum(1 for t, p, _, _ in results if t == p) / n, 4),
               "gates": {}}
        for g in gates:
            per["gates"][f"tau{g[0]}_gap{g[1]}"] = analyse(results, g)
        report["gate_results"][name] = per
        report["latency_ms"][name] = {
            "p50": round(statistics.median(lat), 1),
            "p95": round(sorted(lat)[int(len(lat) * 0.95)], 1),
            "mean": round(statistics.mean(lat), 1),
        }
        print(f"\n=== {name} (n={n}) ===")
        print(f"  overall acc {per['accuracy_overall']:.4f}")
        for g, v in per["gates"].items():
            print(f"  {g}: accept {v['accept_rate']:.3f} correctFP {v['correct_fastpath']:.3f} "
                  f"safeOther {v['safe_other']:.3f} UNSAFE {v['unsafe_of_accepted']:.4f}")
        print(f"  latency p50 {report['latency_ms'][name]['p50']} ms, "
              f"p95 {report['latency_ms'][name]['p95']} ms")

    (OUT / "gate5_jev_baseline.json").write_text(json.dumps(report, indent=2))
    print(f"\nwrote {OUT / 'gate5_jev_baseline.json'}")


if __name__ == "__main__":
    main()
