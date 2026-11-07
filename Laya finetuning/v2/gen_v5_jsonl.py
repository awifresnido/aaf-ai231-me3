#!/usr/bin/env python3
"""Emit Laya v5 training/eval JSONL with the EXACT 9-group inference question.

Pitfall 1: the question must be byte-for-byte the one used at inference. Keep
GROUP_QUESTION identical to the deployment contract; do not reword criteria.

Run on DGX:  .venv/bin/python gen_v5_jsonl.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUTDIR = Path.home() / "projects/laya-router/data_v5"

# ---- the exact inference question (byte-for-byte) ---------------------------
GROUP_QUESTION = {
    "type": "choice",
    "instructions": ("Select the single group of tools that can serve this utterance; "
                     "if it is plain conversation needing no tool, choose chitchat"),
    "criteria": {
        "home": "Lights on, off, a colour, or brightness; or the thermostat temperature",
        "clock": "The current time, one timer, or one alarm",
        "reminders": "Add, list, or complete a reminder",
        "media": "Play music by genre, mood, artist, or title; or control the current playback",
        "weather": "Current weather or a short forecast",
        "comms": "Send a message or an email, or place a phone call",
        "knowledge": "Look something up on the web, open a URL, or search the user's documents",
        "workspace": "Multi-step work on files, code, a shell, or GitHub",
        "chitchat": "A greeting, thanks, or conversational reply that needs no tool",
    },
}

SPLITS = ["train", "val", "calibration", "test", "paraphrase_holdout",
          "synthetic_holdout", "personal_awi"]


def main() -> None:
    (OUTDIR / "questions.json").write_text(json.dumps({"route": GROUP_QUESTION}, indent=2))
    for name in SPLITS:
        src = OUTDIR / f"routes_{name}.jsonl"
        if not src.exists():
            continue
        dst = OUTDIR / f"jsonl_{name}.jsonl"
        n = 0
        with src.open(encoding="utf-8") as fh, dst.open("w", encoding="utf-8") as out:
            for line in fh:
                x = json.loads(line)
                if x["group"] not in GROUP_QUESTION["criteria"]:
                    continue
                out.write(json.dumps({
                    "state": x["state_text"],
                    "questions": {"route": GROUP_QUESTION},
                    "expected": {"route": x["group"]},
                }, ensure_ascii=False) + "\n")
                n += 1
        print(f"{name}: {n} -> {dst.name}")
    print("questions.json written (9 groups)")


if __name__ == "__main__":
    main()
