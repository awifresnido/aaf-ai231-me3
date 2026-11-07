#!/usr/bin/env python3
"""Summarise a Pi voice-trial diagnostics run with the same checks the
DGX-vs-Mac comparison used.

  python summarize_tts_trial.py <run_dir|pi-*.jsonl> [--label mac] [--turns FIRST:LAST]

Emits JSON with: run, e2e, asr_speech_end_to_transcript_ms, jev,
tts_first_audio, tts_complete, routes, classifier_failures.
One value per turn (the earliest of each event type inside that turn).
"""
import argparse, glob, json, math, os, statistics, sys
from collections import Counter, defaultdict

TTS_FIRST = ("tts_mac_first_audio", "tts_qwen_first_audio")
TTS_COMPLETE = ("tts_mac_complete", "tts_qwen_complete")
ROUTES = ("route_glm", "route_tool", "route_smalltalk", "route_local_tool",
          "route_local_reply", "route_local_failure")
CLASSIFIERS = ("classifier_result", "laya_classification")


def load(paths):
    events = []
    for p in paths:
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("event") == "turn_event" or d.get("timing_event"):
                    events.append(d)
    return events


def stats(values):
    if not values:
        return {"n": 0, "median_s": None, "p95_s": None, "max_s": None}
    v = sorted(values)
    k = max(0, math.ceil(0.95 * len(v)) - 1)
    return {"n": len(v), "median_s": round(statistics.median(v), 3),
            "p95_s": round(v[k], 3), "max_s": round(v[-1], 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--label", default="")
    ap.add_argument("--turns", default="", help="FIRST:LAST inclusive turn bounds")
    a = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(a.path, "*.jsonl"))) if os.path.isdir(a.path) else [a.path]
    events = load(paths)
    run = next((e.get("run") for e in events if e.get("run")), None)

    lo, hi = (int(x) for x in a.turns.split(":")) if a.turns else (None, None)
    per_turn = defaultdict(lambda: defaultdict(list))
    for e in events:
        t = e.get("turn")
        if t is None:
            continue
        if lo is not None and t < lo:
            continue
        if hi is not None and t > hi:
            continue
        per_turn[t][e.get("timing_event")].append(e.get("fields") or {})

    e2e, asr, jev, tts_first, tts_complete = [], [], [], [], []
    routes, failures, turns_used = Counter(), 0, 0
    for turn, by in sorted(per_turn.items()):
        got = False
        if by.get("native_user_bot_latency"):
            vals = [f.get("seconds") for f in by["native_user_bot_latency"] if f.get("seconds")]
            if vals:
                e2e.append(min(vals)); got = True
        for f in by.get("asr_transcript", []):
            if f.get("finalized") and f.get("since_speech_end_ms") is not None:
                asr.append(f["since_speech_end_ms"])
        for name in CLASSIFIERS:
            for f in by.get(name, []):
                if f.get("classifier_s") is not None:
                    jev.append(f["classifier_s"])
                if str(f.get("status", "ok")).lower() not in ("ok", "accepted", "none", "null"):
                    failures += 1
        for name in TTS_FIRST:
            tts_first.extend(f["first_audio_s"] for f in by.get(name, [])
                             if f.get("first_audio_s") is not None)
        for name in TTS_COMPLETE:
            tts_complete.extend(f["request_s"] for f in by.get(name, [])
                                if f.get("request_s") is not None)
        for name in ROUTES:
            if by.get(name):
                routes[name] += 1
        if got:
            turns_used += 1

    out = {"label": a.label or run, "run": run, "turns": turns_used,
           "e2e": stats(e2e),
           "asr_speech_end_to_transcript_ms": stats([x / 1000.0 for x in asr]),
           "jev": stats(jev),
           "tts_first_audio": stats(tts_first),
           "tts_complete": stats(tts_complete),
           "routes": dict(routes), "classifier_failures": failures}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
