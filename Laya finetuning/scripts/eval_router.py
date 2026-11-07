#!/usr/bin/env python3
"""Evaluate a fine-tuned Laya router on text-disjoint slices.

Slices (all text-disjoint from train after Task 3):
  routes_paraphrase_holdout.csv  -- unseen phrasings (the generalization test)
  routes_personal_awi.csv        -- Awi's own voice, never trained
  routes_test.csv                -- small independent split

Reports accuracy, macro-F1, ECE, Brier, per-route confusion, and the
wrong-route / accept / fall-through rates at Jev-comparable gates.

Usage: .venv/bin/python eval_router.py <checkpoint_dir> [--device cuda]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import laya

DATA = Path.home() / "projects/laya-router/data"

# Match pi/orchestration.py OPTIONS (play_radio dropped by user decision).
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
QUESTIONS = {
    "route": {
        "type": "choice",
        "instructions": "Which single route should handle this utterance?",
        "criteria": OPTIONS,
    }
}


def load_split(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def ece(conf: list[float], correct: list[bool], n_bins: int = 15) -> float:
    bins = defaultdict(list)
    for c, ok in zip(conf, correct):
        bins[min(int(c * n_bins), n_bins - 1)].append((c, ok))
    total, out = len(conf), 0.0
    for items in bins.values():
        acc = sum(1 for _, ok in items if ok) / len(items)
        avg_c = sum(c for c, _ in items) / len(items)
        out += abs(acc - avg_c) * len(items) / total
    return out


def macro_f1(y_true: list[str], y_pred: list[str], labels: list[str]) -> float:
    f1s = []
    for lab in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == lab and p == lab)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != lab and p == lab)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == lab and p != lab)
        if tp == 0:
            continue
        prec, rec = tp / (tp + fp), tp / (tp + fn)
        f1s.append(2 * prec * rec / (prec + rec))
    return sum(f1s) / len(f1s) if f1s else 0.0


def evaluate(agent, rows: list[dict], name: str, gates: list[tuple[float, float]]) -> dict:
    y_true, y_pred, conf, top2gap = [], [], [], []
    for r in rows:
        text, truth = r["text"], r["label"]
        res = agent.predict(text, QUESTIONS)
        ans = res["answers"]["route"]
        probs = ans.get("probabilities") or {}
        pred = ans.get("choice")
        p = float(probs.get(pred, 0.0))
        second = max((v for k, v in probs.items() if k != pred), default=0.0)
        y_true.append(truth)
        y_pred.append(pred)
        conf.append(p)
        top2gap.append(p - float(second))

    n = len(rows)
    correct = [t == p for t, p in zip(y_true, y_pred)]
    acc = sum(correct) / n
    report = {
        "slice": name,
        "items": n,
        "accuracy": round(acc, 4),
        "macro_f1": round(macro_f1(y_true, y_pred, list(OPTIONS)), 4),
        "mean_confidence": round(sum(conf) / n, 4),
        "ece": round(ece(conf, correct), 4),
        "brier_top1": round(sum((c - (1.0 if ok else 0.0)) ** 2 for c, ok in zip(conf, correct)) / n, 4),
        "per_route": {},
        "gate_sweep": {},
    }
    for lab in sorted(set(y_true)):
        idx = [i for i, t in enumerate(y_true) if t == lab]
        report["per_route"][lab] = {
            "n": len(idx),
            "recall": round(sum(correct[i] for i in idx) / len(idx), 4),
            "mean_conf": round(sum(conf[i] for i in idx) / len(idx), 4),
        }
    # confusion: where do misses go?
    misses = Counter((t, p) for t, p in zip(y_true, y_pred) if t != p)
    report["top_confusions"] = [{"true": t, "pred": p, "n": c}
                               for (t, p), c in misses.most_common(8)]

    # Gate sweep in the Jev acceptance style: accept only if top prob >= tau
    # AND gap >= gap_min; otherwise the turn falls through to GLM.
    for tau, gmin in gates:
        accepted = [i for i in range(n) if conf[i] >= tau and top2gap[i] >= gmin]
        wrong = [i for i in accepted if not correct[i]]
        report["gate_sweep"][f"tau{tau}_gap{gmin}"] = {
            "accept_rate": round(len(accepted) / n, 4),
            "correct_accept_rate": round(sum(1 for i in accepted if correct[i]) / n, 4),
            "wrong_route_rate": round(len(wrong) / n, 6),
            "wrong_of_accepted": round(len(wrong) / max(len(accepted), 1), 6),
            "fallthrough_rate": round(1 - len(accepted) / n, 4),
        }
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    agent = laya.load(args.checkpoint, device=args.device)
    slices = [
        ("paraphrase_holdout", "routes_paraphrase_holdout.csv"),
        ("personal_awi", "routes_personal_awi.csv"),
        ("test", "routes_test.csv"),
        ("val_contaminated", "routes_val.csv"),  # for reference only, overlaps train
    ]
    gates = [(0.90, 0.20), (0.95, 0.20), (0.97, 0.10), (0.99, 0.05)]
    results = []
    for name, fname in slices:
        p = DATA / fname
        if not p.exists():
            continue
        rows = load_split(p)
        rep = evaluate(agent, rows, name, gates)
        results.append(rep)
        print(f"\n=== {name} (n={rep['items']}) ===")
        print(f"  acc {rep['accuracy']:.4f} | macroF1 {rep['macro_f1']:.4f} | "
              f"ECE {rep['ece']:.4f} | meanconf {rep['mean_confidence']:.4f}")
        for g, v in rep["gate_sweep"].items():
            print(f"  {g}: accept {v['accept_rate']:.3f} "
                  f"wrong/of-accepted {v['wrong_of_accepted']:.4f} "
                  f"fallthrough {v['fallthrough_rate']:.3f}")
        if rep["top_confusions"]:
            print("  top confusions:", rep["top_confusions"][:4])

    out = Path(args.out or (Path(args.checkpoint) / "eval_disjoint.json"))
    out.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
