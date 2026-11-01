#!/usr/bin/env python3
"""Task 3: augment the routing dataset.

Adds:
  1. small_talk examples (synthetic templates + mined Pi-log real turns)
  2. play_radio examples (synthetic; me2 has no radio intent)
  3. other hard negatives from the branch test matrix (synthetic)
  4. phrase-family holdout: gold_paraphrase/gold_numerals families unseen in
     train are moved wholesale into routes_paraphrase_holdout.jsonl
  5. downsample majority routes to <=3:1 vs the smallest route count

Run on DGX: .venv/bin/python augment_dataset.py
Writes data/routes_{train,val}.jsonl (augmented) + augment_stats.json.
"""
from __future__ import annotations

import csv
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

OUTDIR = Path.home() / "projects/laya-router/data"
SEED = 20261101
MAX_IMBALANCE = 3.0

random.seed(SEED)

# ---- 1. small_talk: mined from Pi logs (real ASR turns) + synthetic --------
REAL_SMALL_TALK = [
    "hello", "hi", "hey there", "good morning", "good evening",
    "thank you", "thanks a lot", "thank you so much",
    "how are you", "how's it going", "what's up",
    "you're welcome", "nice work", "good job", "awesome",
    "goodbye", "bye", "see you later", "good night",
    "sorry", "my bad", "never mind", "oops",
    "are you there", "you there", "hey you",
]

SMALL_TALK_TEMPLATES = [
    "hello", "hi there", "hey", "good morning", "good afternoon",
    "good evening", "how are you doing", "how are you today",
    "what's up", "how's it going", "thanks", "thank you",
    "thanks a bunch", "appreciate it", "you're the best",
    "great job", "well done", "nice one", "that's helpful",
    "goodbye", "bye now", "see you", "talk later", "good night",
    "nice to meet you", "long time no see", "what a day",
    "i'm tired", "i'm hungry", "nice weather we're having",
    "how was your day", "guess what", "just checking in",
    "are you awake", "knock knock", "surprise", "wow",
    "cool", "okay great", "sounds good", "got it", "understood",
]

SMALL_TALK_FILLERS = ["", "hey um", "uh", "um so", "okay so", "alright"]

def _fill(text: str) -> str:
    f = random.choice(SMALL_TALK_FILLERS)
    return f"{f} {text}".strip()

def small_talk_examples(n: int) -> list[dict]:
    out = []
    base = REAL_SMALL_TALK + SMALL_TALK_TEMPLATES
    for _ in range(n):
        t = random.choice(base)
        if random.random() < 0.35:
            t = _fill(t)
        if random.random() < 0.2:
            t = t.rstrip(".") + "."
        out.append({"state_text": t, "route": "small_talk",
                    "source": "synthetic_small_talk"})
    # mined real turns get their own marker, down-weighted duplication avoided
    for t in REAL_SMALL_TALK:
        out.append({"state_text": t, "route": "small_talk",
                    "source": "pi_log_mined"})
    return out

# ---- 2. play_radio: DROPPED per user decision 2026-11-01 (excluded from the
# final project). The route option is removed from ROUTES everywhere; the
# orchestration.py tool stays unused until integration, out of scope here.
RADIO_QUERIES = ["news", "jazz", "rock", "pop", "classical", "love songs",
                 "opm", "chill", "80s hits", "morning show", "talk radio",
                 "my favorite station", "the hits station", "berry breeze",
                 "monster radio", "wavelength"]
RADIO_TEMPLATES = [
    "play radio", "play {q} radio", "tune in to {q}", "put on the radio",
    "start the radio", "listen to {q} radio", "radio {q}",
    "turn on the radio", "play some {q} on the radio",
    "open the radio station {q}", "switch to {q} radio",
    "can you play the radio", "put on {q} fm",
]

def play_radio_examples(n: int) -> list[dict]:
    return []  # dropped per user decision

# ---- 3. hard negatives per branch test matrix -> other ----------------------
HARD_NEGATIVES = [
    # multi-action (GLM coordinates these)
    "set the lights to red and a timer", "turn on the lights and play music",
    "set a timer and an alarm for six", "dim the lights then skip the song",
    "pause the music and set the temperature to twenty",
    "remind me to study and set a five minute timer",
    "call mom and send a message to dad", "play jazz and turn the volume up",
    "turn off the lights and lock up", "set the thermostat to twenty and play lofi",
    # capability / range questions
    "what is the maximum thermostat setting", "what's the lowest temperature",
    "what temperature range do you support", "how high can the volume go",
    "what colors can the lights be", "how long can a timer run",
    "what alarms are supported", "which stations can you play",
    # weather out of scope
    "what's the weather tomorrow", "will it rain this weekend",
    "weather forecast for tonight", "how was the weather yesterday",
    "weather in cebu next week", "is it going to snow tonight",
    # future-timed alarms/timers belong to the GLM path (GATE 4c: the router
    # predicted set_alarm at 0.90+ for "set alarm tomorrow at six am"); the
    # deterministic parser cannot validate future dates, so these are `other`.
    "set an alarm for tomorrow at six am", "set alarm tomorrow morning",
    "put an alarm and wake me up at six am tomorrow",
    "add an alarm for tomorrow morning", "wake me up tomorrow at seven",
    "set an alarm for next monday at six am", "set a timer for tomorrow afternoon",
    "alarm for the day after tomorrow at six",
    "set my alarm for this weekend", "wake me up next week at six am",
    # ambiguous / clarification. NOTE: "turn it up" / "make it louder please" are
    # NOT here -- me2 labels those VOLUME_UP -> playback_control, and putting them
    # in `other` created a direct label contradiction that showed up as
    # playback_control -> other confusion.
    "change that", "do the thing", "you know what i mean", "that one", "again",
    # negated commands (GATE 4: genuine unsafe error class)
    "do not set an alarm", "don't set a timer", "don't play music",
    "do not turn on the lights", "don't add a reminder", "never mind the timer",
    "do not change the temperature", "don't touch the thermostat",
    "stop setting alarms", "no need to remind me", "don't bother with the lights",
    "do not pause the music", "don't skip the song", "no timer please",
    # out-of-range values
    "set temperature to thirty five degrees", "set temperature to ten degrees",
    "brightness two hundred percent", "timer for zero seconds",
    # questions & reasoning -> GLM
    "who is helen keller", "explain quantum computing in two sentences",
    "tell me a joke", "what's the capital of france",
    "why is the sky blue", "can you explain that again",
    "how do i make adobo", "what year did martial law end",
]

def other_hard_examples(n: int) -> list[dict]:
    out = []
    for _ in range(n):
        out.append({"state_text": random.choice(HARD_NEGATIVES), "route": "other",
                    "source": "synthetic_hard_negative"})
    return out

# ---- main -------------------------------------------------------------------
def main() -> None:
    train = [json.loads(l) for l in (OUTDIR / "routes_train.jsonl").open()]
    val = [json.loads(l) for l in (OUTDIR / "routes_val.jsonl").open()]

    # 4. unseen-phrasing holdout.
    # The manifest carries no phrase_family_id (column is empty for every row),
    # so phrase families cannot be used as the holdout key. The defensible
    # substitute is TEXT-DISJOINTNESS: any gold_paraphrase / gold_numerals row
    # whose normalized transcript is byte-identical to a gold_synthetic TRAIN
    # row is a duplicate and is removed from both train and the holdout;
    # paraphrase rows whose text never appears in synthetic-train are the
    # genuine unseen-phrasing evaluation set.
    manifest = Path.home() / "projects/tiny-vcm/data/manifests/me2_gold_v1.csv"
    syn_train_texts, para_rows = set(), []
    with manifest.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            text = (r.get("normalized_transcript") or "").strip().lower()
            cid = r.get("corpus_id")
            if cid == "gold_synthetic" and r.get("source_split") == "train" and text:
                syn_train_texts.add(text)
            elif cid in ("gold_paraphrase", "gold_numerals") and text:
                para_rows.append(r)

    para_unseen = [r for r in para_rows
                   if (r.get("normalized_transcript") or "").strip().lower()
                   not in syn_train_texts]
    para_dupes = len(para_rows) - len(para_unseen)

    # pull those exact unseen-phrasing rows OUT of train (they were labelled
    # source_split='train' in the adapter) so the holdout is genuinely unseen
    unseen_texts = {(r.get("normalized_transcript") or "").strip().lower()
                    for r in para_unseen}
    moved, kept_train = [], []
    for x in train:
        if x["state_text"].strip().lower() in unseen_texts:
            x["holdout_reason"] = "unseen_paraphrase_text"
            moved.append(x)
        else:
            kept_train.append(x)
    # also drop byte-identical paraphrase duplicates from train
    kept_train = [x for x in kept_train
                  if not (x.get("corpus_id") in ("gold_paraphrase", "gold_numerals")
                          and x["state_text"].strip().lower() in syn_train_texts)]

    (OUTDIR / "routes_paraphrase_holdout.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in moved) + "\n" if moved else "")

    # 1-3: augment train + a small slice into val
    n_small = 900
    n_other = 350
    aug_train = (small_talk_examples(n_small) + other_hard_examples(n_other))
    aug_val = (small_talk_examples(120) + other_hard_examples(60))
    # cap synthetic smalltalk near-duplicates: dedupe by text
    seen = set()
    aug_train = [x for x in aug_train
                 if not (x["state_text"] in seen or seen.add(x["state_text"]))]
    aug_val = [x for x in aug_val
               if not (x["state_text"] in seen or seen.add(x["state_text"]))]

    train_aug = kept_train + aug_train
    val_aug = val + aug_val

    # 5. downsample majority routes to <= MAX_IMBALANCE x smallest count
    counts = Counter(x["route"] for x in train_aug)
    smallest = min(counts.values())
    cap = int(smallest * MAX_IMBALANCE)
    by_route = defaultdict(list)
    random.shuffle(train_aug)
    for x in train_aug:
        by_route[x["route"]].append(x)
    train_balanced = []
    downsampled = {}
    for route, items in by_route.items():
        if len(items) > cap:
            keep_real = [x for x in items if x.get("source", "").startswith(("gold", "personal"))]
            keep_syn = [x for x in items if not x.get("source", "").startswith(("gold", "personal"))]
            n_keep_real = min(len(keep_real), cap)
            train_balanced.extend(keep_real[:n_keep_real])
            if len(keep_real) < cap:
                train_balanced.extend(keep_syn[: cap - len(keep_real)])
            downsampled[route] = len(items) - min(len(items), cap)
        else:
            train_balanced.extend(items)
    random.shuffle(train_balanced)

    (OUTDIR / "routes_train.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in train_balanced) + "\n")
    (OUTDIR / "routes_val.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in val_aug) + "\n")

    stats = {
        "seed": SEED,
        "holdout_method": "text_disjointness (phrase_family_id is empty in manifest)",
        "paraphrase_rows_total": len(para_rows),
        "paraphrase_dupes_removed": para_dupes,
        "paraphrase_holdout_rows": len(moved),
        "train_before_aug": len(train),
        "train_after_aug": len(train_aug),
        "train_after_balance": len(train_balanced),
        "augmented_counts": {"small_talk": n_small + len(REAL_SMALL_TALK),
                             "other_hard": n_other,
                             "val_adds": len(val_aug) - len(val)},
        "downsampled": downsampled,
        "route_counts_final_train": dict(Counter(x["route"] for x in train_balanced)),
        "route_counts_final_val": dict(Counter(x["route"] for x in val_aug)),
    }
    (OUTDIR / "augment_stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))

if __name__ == "__main__":
    main()
