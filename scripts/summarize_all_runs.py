#!/usr/bin/env python3
"""Uniform metric extraction across all me3 voice-trial runs.

Classifier latency comes from classifier_result (jev + laya) and
laya_classification (hybrid local_vcm+laya). Outputs one JSON line per run.
"""
import json, glob, os, statistics
from collections import Counter, defaultdict

BASE = '/opt/data/cache/me3/all-runs/dev/shm/voice-agent-diagnostics'

CLASSIFIER_EVENTS = ('classifier_result', 'laya_classification')
ROUTE_EVENTS = ('route_tool', 'route_glm', 'route_smalltalk',
                'route_local_tool', 'route_local_reply', 'route_local_failure')


def stats(v):
    if not v:
        return {'n': 0, 'med': None, 'p95': None, 'max': None}
    s = sorted(v)
    return {'n': len(s), 'med': round(statistics.median(s), 3),
            'p95': round(s[max(0, int(0.95 * len(s)) - 1)], 3),
            'max': round(s[-1], 3)}


def analyze(run):
    per_turn = defaultdict(lambda: defaultdict(list))
    cfg = {}
    for p in glob.glob(os.path.join(BASE, run, '*.jsonl')):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get('event') != 'turn_event':
                    continue
                t = d.get('turn')
                if t is None:
                    continue
                te = d.get('timing_event')
                fld = d.get('fields') or {}
                if te == 'configuration':
                    for k in ('orchestration_mode', 'router_model', 'cloud_escalation',
                              'tts_backend', 'tts_model', 'asr_backend', 'classifier_timeout_s',
                              'small_llm_primary_model'):
                        if k in fld:
                            cfg[k] = fld[k]
                per_turn[t][te].append(fld)

    e2e = [f['seconds'] for t, by in per_turn.items()
           for f in by.get('native_user_bot_latency', []) if f.get('seconds')]
    asr_ms = [f['since_speech_end_ms'] for t, by in per_turn.items()
              for f in by.get('asr_transcript', [])
              if f.get('finalized') and f.get('since_speech_end_ms') is not None]
    clf = [f['classifier_s'] for t, by in per_turn.items()
           for name in CLASSIFIER_EVENTS for f in by.get(name, [])
           if f.get('classifier_s') is not None]
    clf_server = [f['server_classifier_s'] for t, by in per_turn.items()
                  for name in CLASSIFIER_EVENTS for f in by.get(name, [])
                  if f.get('server_classifier_s')]
    tts_first = [f['first_audio_s'] for t, by in per_turn.items()
                 for f in by.get('tts_qwen_first_audio', []) if f.get('first_audio_s') is not None]
    tts_done = [f['request_s'] for t, by in per_turn.items()
                for f in by.get('tts_qwen_complete', []) if f.get('request_s') is not None]
    routes = Counter()
    for t, by in per_turn.items():
        for name in ROUTE_EVENTS:
            if by.get(name):
                routes[name] += 1
    fails = sum(1 for t, by in per_turn.items()
                for f in by.get('classifier_failure', [])
                if f.get('status') in ('timeout', 'error'))
    # success classifier count (status ok)
    clf_ok = sum(1 for t, by in per_turn.items()
                 for name in CLASSIFIER_EVENTS for f in by.get(name, [])
                 if str(f.get('status', 'ok')).lower() in ('ok', 'accepted'))
    turns = len(e2e)
    return {
        'run': run, 'cfg': cfg, 'turns': turns,
        'e2e': stats(e2e),
        'asr_ms': stats(asr_ms),
        'classifier': stats(clf),
        'classifier_server': stats(clf_server),
        'classifier_ok': clf_ok,
        'classifier_fail': fails,
        'tts_first': stats(tts_first),
        'tts_done': stats(tts_done),
        'routes': dict(routes),
    }


def main():
    runs = sorted(os.listdir(BASE))
    for run in runs:
        p = os.path.join(BASE, run)
        if not os.path.isdir(p):
            continue
        r = analyze(run)
        print(json.dumps(r))


if __name__ == '__main__':
    main()
