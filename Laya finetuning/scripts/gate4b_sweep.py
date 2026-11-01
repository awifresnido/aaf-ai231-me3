#!/usr/bin/env python3
"""GATE 4b: dense operating-point sweep on the CALIBRATED v2-softce router.

Two gate families:

A. symmetric   accept if p >= tau and gap >= g
B. asymmetric  as A, but a NON-`other` prediction additionally needs
               p >= tau_tool. `other` is always allowed to fall through.
               This targets the only unsafe direction we observed
               (truth=`other` predicted as an actionable tool).

Selection rule (user decision: zero unsafe executions, keep fast-path coverage):
  1. pool the text-disjoint slices (paraphrase holdout + test)
  2. among points with unsafe_of_accepted <= 0.005, take the max correct_fastpath
  3. verify the winner on personal_awi (own voice) and report its unsafe rate
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import laya

from eval_router import QUESTIONS

DATA = Path.home() / "projects/laya-router/data"
CKPT = Path.home() / "projects/laya-router/laya-router-v2-softce"
CAL = CKPT / "calibration_refit.json"


def load(name: str) -> list[dict]:
    with (DATA / f"routes_{name}.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def collect(agent, rows) -> list[tuple]:
    preds = []
    for r in rows:
        ans = agent.predict(r["text"], QUESTIONS)["answers"]["route"]
        probs = ans.get("probabilities") or {}
        pred = ans.get("choice")
        p = float(probs.get(pred, 0.0))
        second = max((v for k, v in probs.items() if k != pred), default=0.0)
        preds.append((r["label"], pred, p, p - float(second)))
    return preds


def eval_gate(preds, tau, gap, tau_tool=None) -> dict:
    n = len(preds)
    acc = corr = safe = unsafe = 0
    unsaturated = 0
    for truth, pred, p, g in preds:
        if not (p >= tau and g >= gap):
            continue
        if pred != "other" and tau_tool is not None and p < tau_tool:
            continue
        acc += 1
        if truth == pred:
            corr += 1
        elif pred == "other":
            safe += 1
        else:
            unsafe += 1
    return {
        "accept_rate": acc / n,
        "correct_fastpath": corr / n,
        "safe_other": safe / n,
        "unsafe_of_accepted": unsafe / max(acc, 1),
        "unsafe_rate": unsafe / n,
    }


def main() -> None:
    agent = laya.load(str(CKPT), device="cuda", calibration=str(CAL))
    slices = {name: collect(agent, load(name))
              for name in ("paraphrase_holdout", "test", "personal_awi")}

    pooled = slices["paraphrase_holdout"] + slices["test"]
    taus = [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9]
    gaps = [0.05, 0.1, 0.15, 0.2, 0.3, 0.4]
    tau_tools = [None, 0.6, 0.7, 0.8]

    candidates = []
    for tt in tau_tools:
        for tau in taus:
            for g in gaps:
                m = eval_gate(pooled, tau, g, tt)
                candidates.append({"tau": tau, "gap": g, "tau_tool": tt, **m})

    feasible = [c for c in candidates if c["unsafe_of_accepted"] <= 0.005]
    feasible.sort(key=lambda c: (-c["correct_fastpath"], c["unsafe_of_accepted"]))
    print(f"pooled slices: {len(pooled)} items | feasible points (unsafe<=0.5%): {len(feasible)}")
    print("\ntop feasible operating points (pooled):")
    print(f"{'tau':>5} {'gap':>5} {'tau_tool':>9} {'accept':>7} {'correctFP':>10} {'safeOther':>10} {'unsafe':>8}")
    for c in feasible[:12]:
        print(f"{c['tau']:5.2f} {c['gap']:5.2f} {str(c['tau_tool']):>9} "
              f"{c['accept_rate']:7.3f} {c['correct_fastpath']:10.3f} "
              f"{c['safe_other']:10.3f} {c['unsafe_of_accepted']:8.4f}")

    best = feasible[0] if feasible else None
    report = {"pooled_items": len(pooled), "feasible_count": len(feasible),
              "top": feasible[:15], "chosen": best, "per_slice": {}}

    if best:
        print(f"\nCHOSEN: tau={best['tau']} gap={best['gap']} tau_tool={best['tau_tool']}")
        for name, preds in slices.items():
            m = eval_gate(preds, best["tau"], best["gap"], best["tau_tool"])
            report["per_slice"][name] = m
            print(f"  {name:20s} n={len(preds):5d} accept {m['accept_rate']:.3f} "
                  f"correctFP {m['correct_fastpath']:.3f} safeOther {m['safe_other']:.3f} "
                  f"UNSAFE {m['unsafe_of_accepted']:.4f}")

    out = CKPT / "gate4b_operating_point.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
