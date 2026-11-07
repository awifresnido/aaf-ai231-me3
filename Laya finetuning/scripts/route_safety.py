#!/usr/bin/env python3
"""Safety-oriented routing analysis.

Routing accuracy conflates two very different failures:
  * wrong-tool execution  -- router accepts and a DIFFERENT tool runs (unsafe)
  * conservative fallthrough -- router picks `other` / abstains, so GLM handles
    the turn (slower, but the user still gets the right outcome)

This script reports, per slice and per gate: unsafe misroute rate, safe
fallthrough rate, and correct fast-path rate.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import laya
from eval_router import OPTIONS, QUESTIONS

DATA = Path.home() / "projects/laya-router/data"


def analyse(agent, rows, name, gates) -> dict:
    n = len(rows)
    preds = []
    for r in rows:
        res = agent.predict(r["text"], QUESTIONS)
        ans = res["answers"]["route"]
        probs = ans.get("probabilities") or {}
        pred = ans.get("choice")
        p = float(probs.get(pred, 0.0))
        second = max((v for k, v in probs.items() if k != pred), default=0.0)
        preds.append((r["label"], pred, p, p - float(second)))

    out = {"slice": name, "items": n, "gates": {}, "unsafe_pairs": [],
           "safe_fallthrough_pairs": []}
    for tau, gmin in gates:
        accepted = [x for x in preds if x[2] >= tau and x[3] >= gmin]
        correct = sum(1 for t, p, _, _ in accepted if t == p)
        safe_ft = sum(1 for t, p, _, _ in accepted if t != p and p == "other")
        unsafe = sum(1 for t, p, _, _ in accepted if t != p and p != "other")
        out["gates"][f"tau{tau}_gap{gmin}"] = {
            "accept_rate": round(len(accepted) / n, 4),
            "correct_fastpath": round(correct / n, 4),
            "safe_fallthrough_via_other": round(safe_ft / n, 4),
            "unsafe_wrong_tool": round(unsafe / n, 6),
            "unsafe_of_accepted": round(unsafe / max(len(accepted), 1), 6),
            "correct_of_accepted": round(correct / max(len(accepted), 1), 4),
        }
    unsafe_pairs = Counter((t, p) for t, p, _, _ in preds if t != p and p != "other")
    safe_pairs = Counter((t, p) for t, p, _, _ in preds if t != p and p == "other")
    out["unsafe_pairs"] = [{"true": t, "pred": p, "n": c}
                           for (t, p), c in unsafe_pairs.most_common(8)]
    out["safe_fallthrough_pairs"] = [{"true": t, "pred": p, "n": c}
                                     for (t, p), c in safe_pairs.most_common(5)]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    agent = laya.load(args.checkpoint, device=args.device)
    gates = [(0.90, 0.20), (0.95, 0.20), (0.99, 0.05)]
    results = []
    for name in ("paraphrase_holdout", "personal_awi", "test"):
        p = DATA / f"routes_{name}.csv"
        if not p.exists():
            continue
        with p.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        rep = analyse(agent, rows, name, gates)
        results.append(rep)
        print(f"\n=== {name} (n={rep['items']}) ===")
        for g, v in rep["gates"].items():
            print(f"  {g}: accept {v['accept_rate']:.3f} | correct-fastpath {v['correct_fastpath']:.3f} "
                  f"| safe-other {v['safe_fallthrough_via_other']:.3f} "
                  f"| UNSAFE {v['unsafe_of_accepted']:.4f}")
        print("  unsafe pairs:", rep["unsafe_pairs"][:4])
        print("  safe-to-other:", rep["safe_fallthrough_pairs"][:3])
    out = Path(args.out or (Path(args.checkpoint) / "safety_analysis.json"))
    out.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
