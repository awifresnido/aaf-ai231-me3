#!/usr/bin/env python3
"""GATE 4: calibration refit + operating-point sweep on text-disjoint data.

Part A — refit temperature on the text-disjoint calibration slice
         (routes_calibration.csv -> {state, questions, expected} records),
         apply it to the v2-softce checkpoint, and re-measure ECE on the
         holdout / own-voice / test slices.

Part B — operating-point sweep on the CALIBRATED model. Objective (user
         decision, 2026-11-01): zero unsafe wrong-tool executions, maximize
         correct fast-path coverage. Sweep tau x gap, report per point:
         accept rate, correct fast-path, safe-other, unsafe rate.
         Cross-validate the chosen point on the disjoint test slice.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import laya
from laya.calibrate import fit_temperatures, records_from_labeled, calibration_payload

from eval_router import QUESTIONS

DATA = Path.home() / "projects/laya-router/data"
CHECKPOINT = Path.home() / "projects/laya-router/laya-router-v2-softce"
DEVICE = "cuda"


def rows_to_pairs(rows: list[dict]) -> list[tuple]:
    """records_from_labeled wants numeric target distributions, not label strings.

    Option order = the criteria dict order used in QUESTIONS (same everywhere).
    """
    labels = list(QUESTIONS["route"]["criteria"].keys())
    idx = {lab: i for i, lab in enumerate(labels)}
    pairs = []
    for r in rows:
        target = [0.0] * len(labels)
        target[idx[r["label"]]] = 1.0
        pairs.append((r["text"], QUESTIONS, {"route": target}))
    return pairs


def load(name: str) -> list[dict]:
    with (DATA / f"routes_{name}.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def sweep(agent, rows, gates, label_temp: float | None = None) -> dict:
    """Collect (truth, pred, top_p, gap) once, then evaluate all gates."""
    import math
    preds = []
    for r in rows:
        res = agent.predict(r["text"], QUESTIONS)
        ans = res["answers"]["route"]
        probs = ans.get("probabilities") or {}
        pred = ans.get("choice")
        p = float(probs.get(pred, 0.0))
        second = max((v for k, v in probs.items() if k != pred), default=0.0)
        preds.append((r["label"], pred, p, p - float(second)))
    n = len(rows)
    out = {"items": n, "gates": {}, "unsafe_pairs_by_gate": {}}
    for tau, gmin in gates:
        accepted = [x for x in preds if x[2] >= tau and x[3] >= gmin]
        correct = sum(1 for t, p, _, _ in accepted if t == p)
        safe_other = sum(1 for t, p, _, _ in accepted if t != p and p == "other")
        unsafe = [(t, p) for t, p, _, _ in accepted if t != p and p != "other"]
        out["gates"][f"tau{tau}_gap{gmin}"] = {
            "accept_rate": round(len(accepted) / n, 4),
            "correct_fastpath": round(correct / n, 4),
            "safe_other": round(safe_other / n, 4),
            "unsafe_wrong_tool": round(len(unsafe) / n, 6),
            "unsafe_of_accepted": round(len(unsafe) / max(len(accepted), 1), 6),
        }
        if unsafe:
            out["unsafe_pairs_by_gate"][f"tau{tau}_gap{gmin}"] = [
                {"true": t, "pred": p, "n": c}
                for (t, p), c in defaultdict(int, {k: unsafe.count(k) for k in set(unsafe)}).items()
            ][:6]
    return out


def main() -> None:
    agent = laya.load(str(CHECKPOINT), device=DEVICE)

    # ---------- Part A: refit temperature on text-disjoint calibration slice --
    cal_rows = load("calibration")
    pairs = rows_to_pairs(cal_rows)
    records = records_from_labeled(agent, pairs)
    fit = fit_temperatures(records, compute_ece=True)
    print("=== refit temperatures (text-disjoint calibration slice) ===")
    print(json.dumps(fit, indent=2, default=str)[:1500])

    # build payload and reload agent with the refit temperature
    payload = calibration_payload(
        temperature=fit["temperature"],
        temperature_by_options=fit.get("temperature_by_options"),
        model_id_or_path=str(CHECKPOINT),
    )
    (CHECKPOINT / "calibration_refit.json").write_text(json.dumps(payload, indent=2, default=str))
    agent_cal = laya.load(str(CHECKPOINT), device=DEVICE,
                          calibration=str(CHECKPOINT / "calibration_refit.json"))

    gates = [(0.90, 0.20), (0.95, 0.20), (0.97, 0.10), (0.99, 0.05),
             (0.995, 0.02), (0.85, 0.30)]
    report = {"temperature_refit": fit, "slices": {}}

    # ---------- Part B: sweep on calibrated model -----------------------------
    for name in ("paraphrase_holdout", "personal_awi", "test"):
        rows = load(name)
        rep = sweep(agent_cal, rows, gates)
        report["slices"][name] = rep
        print(f"\n=== {name} (n={rep['items']}, calibrated) ===")
        print(f"{'gate':18s} {'accept':>7s} {'correctFP':>9s} {'safeOther':>9s} {'UNSAFE':>8s}")
        for g, v in rep["gates"].items():
            print(f"{g:18s} {v['accept_rate']:7.3f} {v['correct_fastpath']:9.3f} "
                  f"{v['safe_other']:9.3f} {v['unsafe_of_accepted']:8.4f}")
        for g, pairs_ in rep["unsafe_pairs_by_gate"].items():
            print(f"  unsafe@{g}: {pairs_}")

    # quick ECE re-check after calibration on holdout
    rows = load("paraphrase_holdout")
    conf, correct = [], []
    for r in rows:
        res = agent_cal.predict(r["text"], QUESTIONS)
        ans = res["answers"]["route"]
        p = float((ans.get("probabilities") or {}).get(ans.get("choice"), 0.0))
        conf.append(p)
        correct.append(ans.get("choice") == r["label"])
    bins = defaultdict(list)
    for c, ok in zip(conf, correct):
        bins[min(int(c * 15), 14)].append((c, ok))
    ece = sum(abs(sum(1 for _, ok in v if ok) / len(v) - sum(c for c, _ in v) / len(v))
              * len(v) / len(conf) for v in bins.values())
    acc = sum(correct) / len(correct)
    report["calibrated_holdout_summary"] = {
        "accuracy": round(acc, 4), "ece": round(ece, 4), "n": len(rows)}
    print(f"\ncalibrated holdout: acc {acc:.4f} ece {ece:.4f}")

    out = CHECKPOINT / "gate4_calibration_sweep.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
