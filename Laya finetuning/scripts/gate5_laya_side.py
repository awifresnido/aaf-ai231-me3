#!/usr/bin/env python3
"""GATE 5 counterpart: run the fine-tuned Laya v4 router over the SAME
sampled slices the Jev baseline used (identical seed & cap), producing the
comparison table and the pre-registered decision verdict.

Run on DGX: CUDA_VISIBLE_DEVICES=3 .venv/bin/python gate5_laya_side.py
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / "projects/laya-router"))
from gate5_jev_baseline import OPTIONS, QUESTION, load_slice  # noqa: E402
import laya  # noqa: E402

DATA = Path.home() / "projects/laya-router/data"
OUT = Path.home() / "projects/laya-router/laya-router-v4-softce"
N_PER_SLICE = 200
GATES = [(0.90, 0.20), (0.50, 0.05)]


def analyse(results, gate) -> dict:
    tau, gmin = gate
    n = len(results)
    accepted = [x for x in results if x[2] >= tau and x[3] >= gmin]
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
    agent = laya.load("./laya-router-v4-softce", device="cuda",
                      calibration="./laya-router-v4-softce/calibration_refit.json")
    questions = {"route": QUESTION}
    report = {}
    for name in ("paraphrase_holdout", "test", "personal_awi"):
        rows = load_slice(name, N_PER_SLICE)
        results, lat = [], []
        for r in rows:
            t0 = __import__("time").perf_counter()
            ans = agent.predict(r["text"], questions)["answers"]["route"]
            lat.append((__import__("time").perf_counter() - t0) * 1000)
            probs = ans.get("probabilities") or {}
            pred = ans.get("choice")
            p = float(probs.get(pred, 0.0))
            second = max((v for k, v in probs.items() if k != pred), default=0.0)
            results.append((r["label"], pred, p, p - float(second)))
        n = len(results)
        per = {"items": n,
               "accuracy_overall": round(sum(1 for t, p, _, _ in results if t == p) / n, 4),
               "gates": {}}
        for g in GATES:
            per["gates"][f"tau{g[0]}_gap{g[1]}"] = analyse(results, g)
        report[name] = per
        report.setdefault("latency_ms", {})[name] = {
            "p50": round(statistics.median(lat), 1),
            "p95": round(sorted(lat)[int(len(lat) * 0.95)], 1),
            "mean": round(statistics.mean(lat), 1)}
        print(f"\n=== {name} (n={n}) ===")
        print(f"  overall acc {per['accuracy_overall']:.4f}")
        for g, v in per["gates"].items():
            print(f"  {g}: accept {v['accept_rate']:.3f} correctFP {v['correct_fastpath']:.3f} "
                  f"safeOther {v['safe_other']:.3f} UNSAFE {v['unsafe_of_accepted']:.4f}")
        print(f"  latency p50 {report['latency_ms'][name]['p50']} ms, "
              f"p95 {report['latency_ms'][name]['p95']} ms")

    (OUT / "gate5_laya_side.json").write_text(json.dumps(report, indent=2))
    print(f"\nwrote {OUT / 'gate5_laya_side.json'}")


if __name__ == "__main__":
    main()
