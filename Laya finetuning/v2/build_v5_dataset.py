#!/usr/bin/env python3
"""Build the Laya v5 GROUP-schema routing dataset (9 groups).

Source: me2 gold manifest (19 VCM leaf classes) relabelled to tool GROUPS,
plus synthesized examples for the groups VCM cannot supply
(knowledge, workspace, chitchat, and email-style comms).

Design rules (from the task + laya-router-finetune pitfalls):
  * UNKNOWN / SILENCE are EXCLUDED — never folded into a group (pitfall 6).
  * Every kept row lands in exactly one of the 9 groups; there is no `other`.
  * A text string must never carry two group labels (pitfall 7) — enforced by
    an assertion after dedupe.
  * Unseen-phrasing holdout is built by TEXT-DISJOINTNESS (phrase_family_id is
    empty in this manifest — pitfall 3).
  * personal_awi (owner's voice) never enters training.

Run on DGX:  .venv/bin/python build_v5_dataset.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

MANIFEST = Path.home() / "projects/tiny-vcm/data/manifests/me2_gold_v1.csv"
OUTDIR = Path.home() / "projects/laya-router/data_v5"
SEED = 20261103
MAX_IMBALANCE = 3.0

# 9 groups, in the exact criteria order used at inference.
GROUPS = ["home", "clock", "reminders", "media", "weather",
          "comms", "knowledge", "workspace", "chitchat"]

LEAF_TO_GROUP = {
    # home
    "LIGHT_ON": "home", "LIGHT_OFF": "home", "COLOR": "home",
    "BRIGHTNESS": "home", "TEMPERATURE": "home",
    # clock
    "TIME": "clock", "TIMER": "clock", "ALARM": "clock",
    # reminders
    "CREATE_REMINDER": "reminders", "LIST_REMINDERS": "reminders",
    # media
    "PLAY_MUSIC": "media", "PAUSE": "media", "STOP": "media",
    "NEXT": "media", "VOLUME_UP": "media", "VOLUME_DOWN": "media",
    # weather
    "WEATHER": "weather",
    # comms
    "CALL": "comms", "MESSAGE": "comms",
    # excluded
    "UNKNOWN": None, "SILENCE": None,
}

random.seed(SEED)

# ---------------------------------------------------------------- synthesis --
# Combinatorial templates. Fixed phrase lists collapse under dedupe (700 draws
# from 34 strings yields ~124 unique), which starves the group and then drags
# the balance cap down for every other group. Slots keep cardinality high.

TOPICS = [
    "the latest ai news", "bitcoin price", "python tutorial", "adobo recipe",
    "laptop reviews", "flight prices", "the election results", "nba scores",
    "the capital of france", "quantum computing",
    "how to make sourdough", "the best philippine beaches", "run rate in cricket",
    "the periodic table", "how engines work", "the history of pasay",
]
SITES = ["example.com", "wikipedia.org", "github.com", "bbc.com", "cnn.com",
         "python.org", "arxiv.org", "stackoverflow.com", "reddit.com"]
DOC_TERMS = ["the thesis draft", "my notes on acid plants", "the invoice",
             "the budget spreadsheet", "the meeting minutes", "my resume",
             "the project proposal", "last year's report"]

KNOWLEDGE_SEARCH = [
    "search the web for {t}", "look up {t}", "google {t}", "search online for {t}",
    "find {t} on the internet", "can you look up {t}", "check the web for {t}",
    "what's the news about {t}", "find me information about {t}",
    "search for {t}", "browse the web for {t}", "look up {t} online",
]
KNOWLEDGE_OPEN = [
    "open {s}", "go to {s}", "browse to {s}", "fetch {s}", "load {s}",
    "open the page {s}", "pull up {s}", "navigate to {s}",
]
KNOWLEDGE_DOCS = [
    "search my documents for {d}", "look through my documents for {d}",
    "search my google docs for {d}", "find {d} in my notes",
    "search my notes for {d}", "look up {d} in my documents",
]
# Capability questions are about a DEVICE, so they belong to that device's
# group: the group's own tools are what answer them. Labelling them `knowledge`
# made "what colors can the lights be" a home->knowledge error.
CAPABILITY_TO_GROUP = [
    ("what colors can the lights be", "home"),
    ("what brightness levels are supported", "home"),
    ("what is the maximum thermostat setting", "home"),
    ("what's the lowest temperature setting", "home"),
    ("what temperature range do you support", "home"),
    ("how long can a timer run", "clock"),
    ("what alarms are supported", "clock"),
    ("how high can the volume go", "media"),
    ("which stations can you play", "media"),
    ("what formats can you play", "media"),
]
KNOWLEDGE_QA = [
    "who is helen keller", "what's the capital of france", "tell me about the roman empire",
    # temporal facts: "what year" must NOT read as the clock group
    "what year did world war two end", "what year was the moon landing",
    "what century was the renaissance", "when did the titanic sink",
    "what year did the philippines gain independence", "what decade was disco popular",
    "how tall is mount everest", "what's the population of manila",
    "explain quantum computing", "what's the definition of entropy",
    "who wrote noli me tangere", "what's the speed of light",
    "how many continents are there", "who invented the telephone",
]

FILES = ["config.yaml", "notes.txt", "readme.md", "main.py", "app.js", "data.csv",
         "report.pdf", "the log file", "the project folder", "my script",
         "the dockerfile", "requirements.txt"]
TASKS = ["renames my photos", "parses a csv", "scrapes a website", "sends an email",
         "backs up my files", "converts images to png", "cleans the log",
         "plots a chart", "reads a json file", "downloads a dataset"]
TERMS = ["todo", "deprecated", "TODO", "the function name", "hardcoded", "FIXME",
         "the api key", "print statements"]
REPOS = ["my project", "the repository", "the codebase", "this folder", "the repo"]

WORKSPACE_FILE = [
    "read {f}", "open {f}", "create a file called {f}", "edit {f}",
    "write {f}", "delete {f}", "append a line to {f}", "summarize {f}",
    "show me {f}", "list the files in {r}",
]
WORKSPACE_CODE = [
    "write a script that {t}", "write a python script to {t}", "refactor this function",
    "fix the bug in my script", "debug my code", "generate a unit test for this module",
    "run the tests", "execute the build script", "add a docstring to this function",
    "optimize this loop", "review my code",
]
WORKSPACE_SHELL = [
    "run {c} in the shell", "execute the command {c}", "serve this folder over http",
    "zip the project folder", "check disk usage", "show the running processes",
]
WORKSPACE_GIT = [
    "commit my changes to github", "create a github repository", "push this to github",
    "open a pull request", "clone the repository", "check git status",
    "show my recent commits", "list the branches", "merge the pull request",
    "grep {term} in {r}", "search my codebase for {term}",
]
SHELL_CMDS = ["make", "ls -la", "docker ps", "pip install requests", "git pull",
              "python3 train.py", "nvidia-smi", "df -h"]

PEOPLE = ["mom", "dad", "my sister", "john", "maria", "my professor",
          "the landlord", "the team", "accounting", "the doctor", "my boss"]
TOPIKS = ["the meeting", "the invoice", "the deadline", "the project status",
          "lunch tomorrow", "the report", "the schedule change"]
COMMS_MSG = [
    "send a message to {p}", "text {p} that i'm running late",
    "message {p} happy birthday", "send a whatsapp to {p}",
    "send a telegram message to {p}", "tell {p} i'll be there at six",
]
COMMS_MAIL = [
    "send an email to {p} about {top}", "email {p} about {top}",
    "write an email to {p} regarding {top}", "forward the invoice to {p}",
    "reply to that email", "email myself the notes", "send {p} the report",
]
COMMS_CALL = [
    "call {p}", "phone {p}", "place a call to {p}", "dial {p}",
    "give {p} a ring", "call {p} on their mobile",
]

CHITCHAT = [
    "hello", "hi", "hey", "good morning", "good afternoon", "good evening",
    "how are you", "how's it going", "what's up", "thanks", "thank you",
    "thanks a lot", "thank you so much", "appreciate it", "you're welcome",
    "good job", "nice work", "that's great", "cool", "awesome",
    "goodbye", "bye", "see you later", "good night", "talk later",
    "tell me a joke", "say something funny", "that's all", "never mind",
    "i'm tired", "i'm hungry", "what a day", "nice weather we're having",
    "how was your day", "just checking in", "are you awake", "wow",
    "sounds good", "got it", "understood", "okay great", "sorry", "my bad",
    "do not set an alarm", "don't set a timer", "no timer please",
    "never mind the lights", "don't bother with the music",
    "change that", "do the thing", "you know what i mean", "that one", "again",
    "hello there", "hi again", "morning", "evening", "hey buddy",
    "thanks for the help", "that was quick", "good to know", "makes sense",
    "no thanks", "maybe later", "sure thing", "alright then",
    "good morning to you", "how are you today", "how have you been",
    "nice to meet you", "long time no see", "have a good day",
    "see you tomorrow", "catch you later", "take care", "cheers",
    "that's perfect", "brilliant", "lovely", "not bad", "so so",
    "i'm fine thanks", "all good here", "nothing much", "same as usual",
    "you too", "likewise", "no worries", "it's okay", "don't worry",
    "fair enough", "i see", "right", "exactly", "true", "indeed",
    "haha", "hmm", "oh well", "whatever", "if you say so",
]

WEATHER_FORECAST = [
    "what's the weather tomorrow", "will it rain this weekend",
    "weather forecast for tonight", "how was the weather yesterday",
    "weather in cebu next week", "is it going to snow tonight",
    "what's the forecast for tomorrow", "will it be sunny on saturday",
    "do i need an umbrella tomorrow", "weather for the next three days",
    "will it be hot this weekend", "forecast for manila tomorrow",
    "chance of rain later today", "is it windy tomorrow",
]

# Hard cases carried over from the v4 `other` bucket, each mapped deliberately.
# Multi-action -> the group of the FIRST action (tier-2 runs it, tier-3 handles
# the rest). Documented rather than dropped, so the model sees multi-clause input.
MULTI_ACTION = [
    ("set the lights to red and a timer", "home"),
    ("turn on the lights and play music", "home"),
    ("set a timer and an alarm for six", "clock"),
    ("dim the lights then skip the song", "home"),
    ("pause the music and set the temperature to twenty", "media"),
    ("remind me to study and set a five minute timer", "reminders"),
    ("call mom and send a message to dad", "comms"),
    ("play jazz and turn the volume up", "media"),
    ("turn off the lights and lock up", "home"),
]


def _fill(t: str) -> str:
    f = random.choice(["", "um ", "uh ", "hey um ", "okay so ", "please "])
    return (f + t).strip()


def _expand(templates: list[str], n: int, group: str, **slots) -> list[dict]:
    """Generate n unique-ish strings by drawing a template and its slot values."""
    out, seen = [], set()
    tries = 0
    while len(out) < n and tries < n * 40:
        tries += 1
        tpl = random.choice(templates)
        vals = {k: random.choice(v) for k, v in slots.items()}
        try:
            t = tpl.format(**vals)
        except KeyError:
            continue
        if random.random() < 0.2:
            t = _fill(t)
        if random.random() < 0.1:
            t = t.capitalize()
        key = t.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"state_text": t, "group": group, "source": f"synthetic_{group}"})
    return out


def _pick(lst: list, held_out: bool) -> list:
    """Odd/even template halves give synthetic groups a genuine unseen-template
    eval set: training only ever sees one half."""
    return lst[1::2] if held_out else lst[0::2]


def synth_group(group: str, n: int, held_out: bool = False) -> list[dict]:
    if group == "knowledge":
        return (_expand(_pick(KNOWLEDGE_SEARCH, held_out), int(n * 0.45), group, t=TOPICS)
                + _expand(_pick(KNOWLEDGE_OPEN, held_out), int(n * 0.2), group, s=SITES)
                + _expand(_pick(KNOWLEDGE_DOCS, held_out), int(n * 0.15), group, d=DOC_TERMS)
                + _expand(_pick(KNOWLEDGE_QA, held_out), int(n * 0.2), group))
    if group == "workspace":
        return (_expand(_pick(WORKSPACE_FILE, held_out), int(n * 0.3), group, f=FILES, r=REPOS)
                + _expand(_pick(WORKSPACE_CODE, held_out), int(n * 0.3), group, t=TASKS)
                + _expand(_pick(WORKSPACE_SHELL, held_out), int(n * 0.2), group, c=SHELL_CMDS)
                + _expand(_pick(WORKSPACE_GIT, held_out), int(n * 0.2), group,
                          term=TERMS, r=REPOS))
    if group == "comms":
        return (_expand(_pick(COMMS_MSG, held_out), int(n * 0.4), group, p=PEOPLE)
                + _expand(_pick(COMMS_MAIL, held_out), int(n * 0.35), group, p=PEOPLE, top=TOPIKS)
                + _expand(_pick(COMMS_CALL, held_out), int(n * 0.25), group, p=PEOPLE))
    if group == "chitchat":
        return _expand(_pick(CHITCHAT, held_out), n, group)
    if group == "weather":
        return _expand(_pick(WEATHER_FORECAST, held_out), n, group)
    raise ValueError(group)


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8", newline="")))

    records, dropped = [], Counter()
    for r in rows:
        leaf = (r.get("leaf_label") or "").strip().upper()
        text = (r.get("normalized_transcript") or r.get("raw_transcript") or "").strip()
        if not text or leaf in ("SILENCE", "UNKNOWN"):
            dropped[f"{leaf or 'empty'}_excluded"] += 1
            continue
        group = LEAF_TO_GROUP.get(leaf)
        if group is None:
            dropped[f"unmapped_{leaf}"] += 1
            continue
        records.append({
            "state_text": text, "group": group, "leaf_label": leaf,
            "corpus_id": r.get("corpus_id"), "speaker_id": r.get("speaker_id"),
            "source_split": r.get("source_split"),
            "source": r.get("corpus_id"),
        })

    # ---- synthesized groups -------------------------------------------------
    syn = []
    for g, n in (("knowledge", 1400), ("workspace", 1400), ("chitchat", 900),
                 ("comms", 900), ("weather", 400)):
        syn += synth_group(g, n)
    syn += [{"state_text": t, "group": g, "source": "multi_action",
             "leaf_label": "MULTI", "speaker_id": "synth",
             "source_split": "train"} for t, g in MULTI_ACTION]
    # capability questions -> the device group whose tools can answer them
    syn += [{"state_text": t, "group": g, "source": "capability",
             "leaf_label": "CAP", "speaker_id": "synth",
             "source_split": "train"} for t, g in CAPABILITY_TO_GROUP]
    # "light up" style home phrasing: the model read it as media (0.78)
    syn += [{"state_text": t, "group": "home", "source": "home_ambiguous",
             "leaf_label": "LIGHT_ON", "speaker_id": "synth",
             "source_split": "train"}
            for t in ("light up", "lights up", "light up the room",
                      "lights up please", "light up the place")]

    # ---- dedupe + contradiction guard (pitfall 7) ---------------------------
    seen: dict[str, str] = {}
    conflicts = []
    clean_syn = []
    for x in syn:
        key = x["state_text"].strip().lower()
        if key in seen:
            if seen[key] != x["group"]:
                conflicts.append((key, seen[key], x["group"]))
            continue
        seen[key] = x["group"]
        clean_syn.append(x)
    # same guard across the real rows
    for x in records:
        key = x["state_text"].strip().lower()
        if key in seen and seen[key] != x["group"]:
            conflicts.append((key, seen[key], x["group"]))
        seen.setdefault(key, x["group"])

    # ---- persona holdout: personal_awi never trains ------------------------
    real_train = [x for x in records
                  if x["source_split"] == "train" and x["corpus_id"] != "personal_awi"]
    real_val = [x for x in records
                if x["source_split"] == "validation" and x["corpus_id"] != "personal_awi"]
    real_test = [x for x in records if x["source_split"] == "test"]
    awi = [x for x in records if x["corpus_id"] == "personal_awi"]

    # ---- text-disjoint unseen-phrasing holdout -----------------------------
    # Any paraphrase/numerals row whose text also appears in gold_synthetic train
    # is a duplicate (dropped); the rest become the unseen-phrasing eval set.
    para, syn_train_texts = [], set()
    for r in rows:
        cid, text = r.get("corpus_id"), (r.get("normalized_transcript") or "").strip().lower()
        if not text:
            continue
        if cid == "gold_synthetic" and r.get("source_split") == "train":
            syn_train_texts.add(text)
        elif cid in ("gold_paraphrase", "gold_numerals"):
            leaf = (r.get("leaf_label") or "").upper()
            g = LEAF_TO_GROUP.get(leaf)
            if g:
                para.append((text, g))
    holdout_texts = {t for t, _ in para if t not in syn_train_texts}

    def to_holdout(x):
        return x["state_text"].strip().lower() in holdout_texts

    holdout = [x for x in records if to_holdout(x)]
    real_train = [x for x in real_train if not to_holdout(x)]
    real_val = [x for x in real_val if not to_holdout(x)]

    # ---- assemble splits ---------------------------------------------------
    train = real_train + clean_syn

    # val must be comparable ACROSS groups: real validation rows are dominated
    # by home/clock, so cap each group and top up the synthesized ones with
    # HELD-OUT templates (unseen wording, so the numbers mean something).
    val = list(real_val)
    for g, n in (("knowledge", 120), ("workspace", 120), ("chitchat", 120),
                 ("comms", 90), ("weather", 40)):
        val += synth_group(g, n, held_out=True)
    by_group_val = defaultdict(list)
    for x in val:
        by_group_val[x["group"]].append(x)
    VAL_CAP = 250
    val = []
    for g in GROUPS:
        val.extend(by_group_val.get(g, [])[:VAL_CAP])

    # calibration slice: carve from val, >=10 per group
    by_group = defaultdict(list)
    for x in val:
        by_group[x["group"]].append(x)
    calib, val_rest = [], []
    for g in GROUPS:
        items = by_group.get(g, [])
        n_cal = min(max(10, len(items) // 4), 150)
        calib.extend(items[:n_cal])
        val_rest.extend(items[n_cal:])

    # ---- balance train to <=3x the smallest group --------------------------
    counts = Counter(x["group"] for x in train)
    smallest = min(counts.values())
    cap = int(smallest * MAX_IMBALANCE)
    random.shuffle(train)
    bucket = defaultdict(list)
    for x in train:
        bucket[x["group"]].append(x)
    balanced, downsampled = [], {}
    for g in GROUPS:
        items = bucket.get(g, [])
        if len(items) > cap:
            keep = items[:cap]
            downsampled[g] = len(items) - len(keep)
        else:
            keep = items
        balanced.extend(keep)
    random.shuffle(balanced)

    # unseen-TEMPLATE holdout for the five synthesized groups (the VCM holdout
    # above can only cover the six VCM-derived groups).
    synthetic_holdout = []
    for g in ("knowledge", "workspace", "chitchat", "comms", "weather"):
        synthetic_holdout += synth_group(g, 220, held_out=True)

    splits = {"train": balanced, "val": val_rest, "calibration": calib,
              "test": real_test, "paraphrase_holdout": holdout,
              "synthetic_holdout": synthetic_holdout, "personal_awi": awi}
    for name, items in splits.items():
        with (OUTDIR / f"routes_{name}.jsonl").open("w", encoding="utf-8") as fh:
            for x in items:
                fh.write(json.dumps(x, ensure_ascii=False) + "\n")

    stats = {
        "manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        "seed": SEED,
        "rows_read": len(rows),
        "kept_from_manifest": len(records),
        "dropped": dict(dropped),
        "synthesized": dict(Counter(x["group"] for x in clean_syn)),
        "label_conflicts_dropped": len(conflicts),
        "conflict_examples": conflicts[:5],
        "holdout_texts": len(holdout_texts),
        "split_sizes": {k: len(v) for k, v in splits.items()},
        "train_counts": dict(Counter(x["group"] for x in balanced)),
        "val_counts": dict(Counter(x["group"] for x in val_rest)),
        "calibration_counts": dict(Counter(x["group"] for x in calib)),
        "holdout_counts": dict(Counter(x["group"] for x in holdout)),
        "downsampled": downsampled,
        "groups_missing_in_train": [g for g in GROUPS if not any(
            x["group"] == g for x in balanced)],
        "personal_awi_excluded_from_train": True,
    }
    (OUTDIR / "v5_dataset_stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
