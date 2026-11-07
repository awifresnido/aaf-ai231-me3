#!/usr/bin/env python3
"""Laya v5 (9-group) calibration refit + gate sweep + per-group gates.

Two modes:
  calib  -> fit temperatures on the text-disjoint calibration slice, write
            calibration_refit.json, then re-sweep tau x gap on the calibrated
            model (pitfall 5: thresholds do not survive recalibration).
  eval   -> per-group accuracy, confusion matrix, unsafe-of-accepted, ECE on
            every holdout slice.

Usage: .venv/bin/python v5_gates.py calib|eval [--ckpt DIR]
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import laya
from laya.calibrate import calibration_payload, fit_temperatures, records_from_labeled

DATA = Path.home() / "projects/laya-router/data_v5"

GROUP_QUESTION = json.loads((DATA / "questions.json").read_text())["route"]
QUESTIONS = {"route": GROUP_QUESTION}
GROUPS = list(GROUP_QUESTION["criteria"].keys())

# Groups that execute tools. A predicted `chitchat` runs nothing, so routing
# there is conservative (slower, not dangerous); any other wrong group runs a
# tool from the WRONG family -> that is the unsafe case.
TOOL_GROUPS = {"home", "clock", "reminders", "media", "weather",
               "comms", "knowledge", "workspace"}


def load(name: str) -> list[dict]:
    with (DATA / f"routes_{name}.jsonl").open(encoding="utf-8") as fh:
        return [json.loads(l) for l in fh]


def ece(conf, correct, n_bins=15):
    bins = defaultdict(list)
    for c, ok in zip(conf, correct):
        bins[min(int(c * n_bins), n_bins - 1)].append((c, ok))
    total, out = len(conf), 0.0
    for items in bins.values():
        acc = sum(1 for _, ok in items if ok) / len(items)
        avg = sum(c for c, _ in items) / len(items)
        out += abs(acc - avg) * len(items) / total
    return out


def predict_all(agent, rows):
    out = []
    for r in rows:
        ans = agent.predict(r["state_text"], QUESTIONS)["answers"]["route"]
        probs = ans.get("probabilities") or {}
        pred = ans.get("choice")
        p = float(probs.get(pred, 0.0))
        second = max((v for k, v in probs.items() if k != pred), default=0.0)
        out.append((r["group"], pred, p, p - float(second)))
    return out


def gate_metrics(preds, tau, gap):
    n = len(preds)
    acc = [x for x in preds if x[2] >= tau and x[3] >= gap]
    correct = sum(1 for t, p, _, _ in acc if t == p)
    safe_chit = sum(1 for t, p, _, _ in acc if t != p and p == "chitchat")
    unsafe = sum(1 for t, p, _, _ in acc if t != p and p in TOOL_GROUPS)
    return {
        "accept_rate": round(len(acc) / n, 4),
        "correct_fastpath": round(correct / n, 4),
        "safe_chitchat_fallthrough": round(safe_chit / n, 4),
        "unsafe_of_accepted": round(unsafe / max(len(acc), 1), 6),
        "unsafe_rate": round(unsafe / n, 6),
    }


def report_slice(agent, name, gates):
    rows = load(name)
    # dedupe by text: the gold corpus repeats a take many times, and duplicates
    # would otherwise weight a single ambiguous phrase (e.g. "light up" x9).
    seen, uniq = set(), []
    for r in rows:
        k = r["state_text"].strip().lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    rows = uniq
    preds = predict_all(agent, rows)
    n = len(preds)
    correct = [t == p for t, p, _, _ in preds]
    conf = [p for _, _, p, _ in preds]

    per_group = {}
    for g in GROUPS:
        idx = [i for i, (t, _, _, _) in enumerate(preds) if t == g]
        if not idx:
            continue
        per_group[g] = {
            "n": len(idx),
            "accuracy": round(sum(correct[i] for i in idx) / len(idx), 4),
            "mean_conf": round(sum(conf[i] for i in idx) / len(idx), 4),
        }

    confusion = Counter((t, p) for t, p, _, _ in preds if t != p)
    top_conf = [{"true": t, "pred": p, "n": c} for (t, p), c in confusion.most_common(12)]

    return {
        "slice": name,
        "items": n,
        "accuracy": round(sum(correct) / n, 4),
        "ece": round(ece(conf, correct), 4),
        "per_group": per_group,
        "confusion": top_conf,
        "gates": {f"tau{t}_gap{g}": gate_metrics(preds, t, g) for t, g in gates},
    }


def numeric_pairs(rows):
    """records_from_labeled wants distributions, not label strings."""
    order = {g: i for i, g in enumerate(GROUPS)}
    pairs = []
    for r in rows:
        target = [0.0] * len(GROUPS)
        target[order[r["group"]]] = 1.0
        pairs.append((r["state_text"], QUESTIONS, {"route": target}))
    return pairs


GATES = [(0.50, 0.05), (0.60, 0.10), (0.70, 0.10), (0.80, 0.20), (0.90, 0.20)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["calib", "eval", "sweep"])
    ap.add_argument("--ckpt", default="./laya-router-v5-groups")
    args = ap.parse_args()

    if args.mode == "calib":
        agent = laya.load(args.ckpt, device="cuda")
        cal_rows = load("calibration")
        fit = fit_temperatures(records_from_labeled(agent, numeric_pairs(cal_rows)),
                              compute_ece=True)
        payload = calibration_payload(temperature=fit["temperature"],
                                      temperature_by_options=fit.get("temperature_by_options"),
                                      model_id_or_path=args.ckpt)
        out = Path(args.ckpt) / "calibration_refit.json"
        out.write_text(json.dumps(payload, indent=2, default=str))
        print(json.dumps({"temperature": fit["temperature"],
                          "n_by_bucket": fit.get("n_by_bucket"),
                          "calibration_items": len(cal_rows)}, indent=2))
        print(f"wrote {out}")

    elif args.mode == "sweep":
        ckpt = Path(args.ckpt)
        agent = laya.load(args.ckpt, device="cuda",
                          calibration=str(ckpt / "calibration_refit.json"))
        pooled = load("paraphrase_holdout") + load("synthetic_holdout")
        preds = predict_all(agent, pooled)
        rows = []
        for tau in (0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
            for gap in (0.05, 0.1, 0.2, 0.3):
                m = gate_metrics(preds, tau, gap)
                rows.append({"tau": tau, "gap": gap, **m})
        feasible = [r for r in rows if r["unsafe_of_accepted"] <= 0.005]
        feasible.sort(key=lambda r: (-r["correct_fastpath"], r["unsafe_of_accepted"]))
        print(json.dumps({"pooled": len(pooled),
                          "feasible": len(feasible),
                          "top": feasible[:6]}, indent=2))

    else:
        ckpt = Path(args.ckpt)
        agent = laya.load(args.ckpt, device="cuda",
                          calibration=str(ckpt / "calibration_refit.json"))
        report = {}
        for name in ("paraphrase_holdout", "synthetic_holdout", "personal_awi",
                     "test", "val"):
            report[name] = report_slice(agent, name, GATES)
        (ckpt / "v5_gates.json").write_text(json.dumps(report, indent=2))
        for name, r in report.items():
            print(f"\n=== {name} (n={r['items']}) acc {r['accuracy']:.4f} ECE {r['ece']:.4f}")
            for g, v in sorted(r["per_group"].items(), key=lambda kv: kv[1]["accuracy"]):
                flag = "  <-- BELOW 0.9" if v["accuracy"] < 0.9 else ""
                print(f"   {g:11s} n={v['n']:4d} acc {v['accuracy']:.3f} conf {v['mean_conf']:.3f}{flag}")
            print("   gates (tau0.5/0.05):", r["gates"]["tau0.5_gap0.05"])
            print("   top confusions:", r["confusion"][:5])


if __name__ == "__main__":
    main()
