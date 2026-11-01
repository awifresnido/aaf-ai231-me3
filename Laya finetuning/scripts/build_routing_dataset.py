#!/usr/bin/env python3
"""Build Laya routing dataset from the TinyVCM ME2 gold manifest.

Input : ~/projects/tiny-vcm/data/manifests/me2_gold_v1.csv  (19,200 rows)
Output: routes_{train,val,test}.jsonl + routing_dataset_stats.json

Route options match pi/orchestration.py on branch two-brain-plusjev (14 options).
Run on DGX:  .venv/bin/python build_routing_dataset.py
"""
from __future__ import annotations

import csv
import json
import random
import hashlib
from collections import Counter, defaultdict
from pathlib import Path

MANIFEST = Path.home() / "projects/tiny-vcm/data/manifests/me2_gold_v1.csv"
OUTDIR = Path.home() / "projects/laya-router/data"
SEED = 20261101

# 14 route options of pi/orchestration.py (two-brain-plusjev)
ROUTES = [
    "get_time", "get_weather", "list_reminders", "add_reminder", "set_thermostat",
    "control_lights", "set_timer", "set_alarm", "playback_control", "play_music",
    "play_radio", "small_talk", "other",
]

# me2 leaf_label -> route option.  Merges follow the plan: do NOT fine-grain,
# the router only distinguishes 13 actionable/conversational options.
LEAF_TO_ROUTE = {
    "TIME": "get_time",
    "WEATHER": "get_weather",
    "LIST_REMINDERS": "list_reminders",
    "CREATE_REMINDER": "add_reminder",
    "TEMPERATURE": "set_thermostat",
    "LIGHT_ON": "control_lights",
    "LIGHT_OFF": "control_lights",
    "COLOR": "control_lights",
    "BRIGHTNESS": "control_lights",
    "TIMER": "set_timer",
    "ALARM": "set_alarm",
    "STOP": "playback_control",
    "PAUSE": "playback_control",
    "NEXT": "playback_control",
    "VOLUME_UP": "playback_control",
    "VOLUME_DOWN": "playback_control",
    "PLAY_MUSIC": "play_music",
    # Calls/messages are GLM-path in the current tool registry.
    # UNKNOWN (oos + negatives) — v3: EXCLUDED entirely.
    # me2's UNKNOWN means "not one of the VCM's 19 leaf classes"; for a routing
    # router most UNKNOWN transcripts are actionable commands ("set a timer",
    # "what are my reminders"), so folding them into `other` poisons that class
    # (GATE 4 finding, 2026-11-01: all 70 own-voice "unsafe" errors were this).
    # `other` is taught from gold_oos / synthetic_negative (real non-commands)
    # + CALL/MESSAGE + the synthetic hard-negative set instead.
    "CALL": "other",
    "MESSAGE": "other",
    # SILENCE has no transcript -> dropped
}

DEFAULT_LOCATIONS = ["manila", "quezon city", "cebu", "davao", "baguio"]


def weather_positive(text: str) -> bool:
    """User decision: located weather requests route to get_weather, not other."""
    t = text.lower()
    return "weather" in t


def is_hard_negative(text: str) -> str | None:
    """Tag the me2 rows that must NOT be treated as a simple fast-path command."""
    t = text.lower()
    if any(k in t for k in (" and ", " then ", " also ")) and sum(
        k in t for k in ("light", "timer", "music", "remind", "temperature", "alarm")
    ) > 1:
        return "multi_action"
    if any(k in t for k in ("forecast", "tomorrow", "tonight", "weekend", "yesterday",
                            "next week", "next day", "later today")):
        return "weather_out_of_scope"
    if any(k in t for k in ("maximum", "minimum", "highest", "lowest", "range", "setting")):
        return "capability_question"
    # Negated commands: "do not set an alarm", "don't play music yet" etc.
    # GATE 4 found these are the router's genuine unsafe error class.
    if any(k in t for k in ("do not ", "don't ", "dont ", "never ", "stop setting",
                            "no need to", "don't bother", "do not bother")):
        return "negated_command"
    return None


def main() -> None:
    random.seed(SEED)
    OUTDIR.mkdir(parents=True, exist_ok=True)

    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8", newline="")))
    records = []
    dropped = Counter()

    for r in rows:
        leaf = (r.get("leaf_label") or "").strip().upper()
        text = (r.get("normalized_transcript") or r.get("raw_transcript") or "").strip()
        if not text or leaf == "SILENCE":
            dropped["silence_or_empty"] += 1
            continue
        route = LEAF_TO_ROUTE.get(leaf)
        if route is None:
            dropped[f"unmapped:{leaf}"] += 1
            continue

        hn = is_hard_negative(text)
        if hn == "weather_out_of_scope":
            route = "other"
        elif hn and route == "get_weather":
            route = "other"

        records.append({
            "state_text": text,
            "route": route,
            "leaf_label": leaf,
            "corpus_id": r.get("corpus_id"),
            "speaker_id": r.get("speaker_id"),
            "session_id": r.get("session_id"),
            "source_split": r.get("source_split"),
            "sample_type": r.get("sample_type"),
            "hard_negative_kind": hn,
        })

    # ---- speaker-disjointness audit + personal_awi exclusion -----------------
    # personal_awi is Awi's own voice: held out of train entirely.
    train_pool = [x for x in records
                  if x["source_split"] == "train" and x["corpus_id"] != "personal_awi"]
    val_pool = [x for x in records
                if x["source_split"] == "validation" and x["corpus_id"] != "personal_awi"]
    test_pool = [x for x in records if x["source_split"] == "test"]
    awi_pool = [x for x in records if x["corpus_id"] == "personal_awi"]

    train_speakers = {x["speaker_id"] for x in train_pool if x["speaker_id"]}
    test_speakers = {x["speaker_id"] for x in test_pool if x["speaker_id"]}
    overlap = train_speakers & test_speakers

    # Any test-pool record whose speaker also appears in train is displaced into
    # val (never silently kept: a leaked speaker inflates paraphrase accuracy).
    if overlap:
        moved = [x for x in test_pool if x["speaker_id"] in overlap]
        test_pool = [x for x in test_pool if x["speaker_id"] not in overlap]
        val_pool.extend(moved)
        leakage_moved = len(moved)
    else:
        leakage_moved = 0

    # ---- calibration slice: >=10 items per route, taken from val ------------
    by_route = defaultdict(list)
    for x in val_pool:
        by_route[x["route"]].append(x)
    calibration, remaining_val = [], []
    for route, items in by_route.items():
        n_cal = min(len(items) // 4, 200)
        if n_cal < 10:
            n_cal = min(len(items), 10)
        calibration.extend(items[:n_cal])
        remaining_val.extend(items[n_cal:])

    splits = {"train": train_pool, "val": remaining_val,
              "calibration": calibration, "test": test_pool, "personal_awi": awi_pool}

    for name, items in splits.items():
        path = OUTDIR / f"routes_{name}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for x in items:
                fh.write(json.dumps(x, ensure_ascii=False) + "\n")

    # ---- stats -------------------------------------------------------------
    stats = {
        "manifest": str(MANIFEST),
        "manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        "seed": SEED,
        "rows_read": len(rows),
        "records_kept": len(records),
        "dropped": dict(dropped),
        "split_sizes": {k: len(v) for k, v in splits.items()},
        "route_counts": {k: dict(Counter(x["route"] for x in v))
                         for k, v in splits.items()},
        "leaf_counts_train": dict(Counter(x["leaf_label"] for x in train_pool)),
        "hard_negative_counts": dict(Counter(
            x["hard_negative_kind"] for x in records if x["hard_negative_kind"])),
        "speaker_leakage": {
            "train_speakers": len(train_speakers),
            "test_speakers_after": len({x["speaker_id"] for x in test_pool if x["speaker_id"]}),
            "overlap_found": len(overlap),
            "records_moved_to_val": leakage_moved,
        },
        "calibration_min_per_route": min(
            (sum(1 for x in calibration if x["route"] == r) for r in ROUTES), default=0),
        "routes_missing_in_train": [r for r in ROUTES
                                    if not any(x["route"] == r for x in train_pool)],
        "personal_awi_excluded_from_train": True,
    }
    (OUTDIR / "routing_dataset_stats.json").write_text(
        json.dumps(stats, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
