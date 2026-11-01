#!/usr/bin/env python3
"""Convert routing CSVs to Laya JSONL with the EXACT inference question.

Why: `laya-train` on a CSV synthesises options from the label column (bare
strings like "control_lights"). At inference the router asks a choice question
whose options are natural-language descriptions. That train/inference question
mismatch cost ~14 accuracy points and made `other` absorb everything. Training
on JSONL with the same `questions` block used at inference removes it.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

DATA = Path.home() / "projects/laya-router/data"

# Must stay identical to eval_router.OPTIONS and pi/orchestration.py OPTIONS.
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

SPLITS = ["train", "val", "calibration", "test", "paraphrase_holdout", "personal_awi"]


def main() -> None:
    for name in SPLITS:
        src = DATA / f"routes_{name}.csv"
        if not src.exists():
            continue
        dst = DATA / f"jsonl_{name}.jsonl"
        n = 0
        with src.open(encoding="utf-8", newline="") as fh, dst.open("w", encoding="utf-8") as out:
            for row in csv.DictReader(fh):
                label = row["label"]
                if label not in OPTIONS:
                    continue
                out.write(json.dumps({
                    "state": row["text"],
                    "questions": {"route": QUESTION},
                    "expected": {"route": label},
                }, ensure_ascii=False) + "\n")
                n += 1
        print(f"{name}: {n} -> {dst.name}")


if __name__ == "__main__":
    main()
