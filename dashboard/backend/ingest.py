"""Parse voice-agent pipeline diagnostics (JSONL) into the dashboard domain model.

Reads the two files the Pi writes per run into
``/dev/shm/voice-agent-diagnostics/<run-id>/``:

- ``pi-<pid>.jsonl``   — turn events + timing measurements.
- ``mcp-<pid>.jsonl``  — MCP tool-call spans.

This module is **read-only**: it only parses JSON lines.  It never executes any
model, tool, or cloud call, and it ignores transcript payloads (the diagnostics
deliberately omit spoken text).

Gate reconstruction: the diagnostics record the classifier *result* (raw choice,
top probability, gap) and the *dispatch* (local tool / GLM / smalltalk) but not
an explicit accepted/rejected boolean.  We reconstruct the gate from the
observable dispatch plus the known routing rules (escalate groups always go to
GLM; a non-escalate group that ends up at GLM was rejected for low confidence).
See ``docs/runbooks/`` / the runbook for the exact rules.
"""

import glob
import json
import os
from collections import Counter, defaultdict

from . import devices
from . import groups as G
from . import metrics


_TURN_EVENT = "turn_event"

# Gate labels.  Order matters only for readability.
GATE_ACCEPTED = "accepted"
GATE_ESCALATED = "escalated"        # correctly routed to an escalate group -> GLM
GATE_REJECTED = "rejected"          # low confidence (or legacy "other") -> GLM
GATE_TIMEOUT = "timeout"
GATE_ERROR = "error"
GATE_BYPASS = "bypass"              # classifier skipped (explicit override)
GATE_MULTI = "multiple_actions"     # classifier skipped (multi-tool detection)


def _finite_float(v):
    try:
        f = float(v)
        return f if f == f and abs(f) != float("inf") else None
    except (TypeError, ValueError):
        return None


class Run:
    """A single diagnostics run (one run-id directory)."""

    def __init__(self, run_id, path):
        self.run_id = run_id
        self.path = path
        self.config = {}
        self.turns = []           # list[dict], sorted by turn number
        self.tool_spans = []      # list[dict] from mcp spans
        self.started_at = None    # float | None
        self.ended_at = None      # float | None

    # -- API-friendly summary -------------------------------------------------
    def summary(self):
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "schema": self.schema(),
            "turns": len(self.turns),
            "median_e2e_s": self._e2e_stat("median"),
            "p95_e2e_s": self._e2e_stat("p95"),
            "classifier_ok": self.classifier_counts()["ok"],
            "classifier_fail": self.classifier_counts()["fail"],
            "config": self._config_summary(),
        }

    def _e2e_stat(self, key):
        vals = [t["timings"]["e2e_s"] for t in self.turns]
        return metrics.summarize(vals)[key]

    def classifier_counts(self):
        ok = fail = 0
        for t in self.turns:
            g = t["gate"]
            if g in (GATE_ACCEPTED, GATE_ESCALATED):
                ok += 1
            elif g in (GATE_TIMEOUT, GATE_ERROR):
                fail += 1
        return {"ok": ok, "fail": fail}

    def _config_summary(self):
        c = self.config
        return {
            "orchestration_mode": c.get("orchestration_mode"),
            "router_model": c.get("router_model"),
            "tts_backend": c.get("tts_backend"),
            "tts_model": c.get("tts_model"),
            "tts_voice": c.get("tts_voice"),
            "asr_backend": c.get("asr_backend"),
            "asr_model": c.get("asr_model"),
            "small_llm_primary_model": c.get("small_llm_primary_model"),
            "classifier_timeout_s": c.get("classifier_timeout_s"),
            "cloud_escalation": c.get("cloud_escalation"),
        }

    def schema(self):
        """Detect the router contract from the raw choices present.

        ``"v2_9group"`` if any turn carried a 9-group raw choice, ``"v4_tool"``
        if tool names / ``other`` / ``small_talk`` were seen, else ``"unknown"``.
        """
        group_seen = tool_seen = False
        for t in self.turns:
            rc = t.get("raw_choice")
            if rc in G.GROUPS:
                group_seen = True
            elif rc is not None:
                tool_seen = True
        if group_seen:
            return "v2_9group"
        if tool_seen:
            return "v4_tool"
        return "unknown"

    def detail(self):
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "schema": self.schema(),
            "config": self._config_summary(),
            "turns": self.turns,
            "aggregates": self._aggregates(),
            "group_distribution": self._group_distribution(),
            "classifier_health": self._classifier_health(),
            "tool_activity": self._tool_activity(),
            "tool_timeline": self._tool_timeline(),
            "dispatch_breakdown": self._dispatch_breakdown(),
            "devices": devices.reconstruct(self.tool_spans),
        }

    def _classifier_latencies(self):
        """Classifier inference times for turns where the classifier actually ran."""
        ran = (GATE_ACCEPTED, GATE_ESCALATED, GATE_REJECTED, GATE_TIMEOUT, GATE_ERROR)
        return [t["timings"]["classifier_s"] for t in self.turns
                if t["gate"] in ran and t["timings"]["classifier_s"] is not None]

    def _aggregates(self):
        e2e = [t["timings"]["e2e_s"] for t in self.turns]
        asr = [t["timings"]["asr_s"] for t in self.turns]
        tool = [t["timings"]["tool_s"] for t in self.turns]
        tts = [t["timings"]["tts_first_s"] for t in self.turns]
        return {
            "e2e_s": metrics.summarize(e2e),
            "asr_s": metrics.summarize(asr),
            "classifier_s": metrics.summarize(self._classifier_latencies()),
            "tool_s": metrics.summarize(tool),
            "tts_first_s": metrics.summarize(tts),
        }

    def _group_distribution(self):
        dist = Counter(t["outcome"] for t in self.turns)
        ordered = {}
        for g in G.GROUPS:
            if dist[g]:
                ordered[g] = dist[g]
        for k in (GATE_REJECTED, GATE_TIMEOUT, GATE_ERROR, GATE_MULTI, "unknown"):
            if dist[k]:
                ordered[k] = dist[k]
        return ordered

    def _classifier_health(self):
        counts = Counter(t["gate"] for t in self.turns)
        lat = self._classifier_latencies()
        return {
            "accepted": counts.get(GATE_ACCEPTED, 0),
            "escalated": counts.get(GATE_ESCALATED, 0),
            "rejected": counts.get(GATE_REJECTED, 0),
            "timeout": counts.get(GATE_TIMEOUT, 0),
            "error": counts.get(GATE_ERROR, 0),
            "bypass": counts.get(GATE_BYPASS, 0),
            "multiple_actions": counts.get(GATE_MULTI, 0),
            "latency": metrics.summarize(lat),
            "histogram": metrics.histogram(
                lat, [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5]),
        }

    def _tool_activity(self):
        by_tool = defaultdict(lambda: {"count": 0, "durations": [], "group": None})
        for s in self.tool_spans:
            key = s["tool"]
            entry = by_tool[key]
            entry["count"] += 1
            entry["group"] = G.TOOL_TO_GROUP.get(key)
            if s.get("duration_s") is not None:
                entry["durations"].append(s["duration_s"])
        activity = []
        for tool, e in sorted(by_tool.items(), key=lambda kv: -kv[1]["count"]):
            activity.append({
                "tool": tool,
                "group": e["group"],
                "count": e["count"],
                "median_s": metrics.summarize(e["durations"])["median"],
            })
        return activity

    def _tool_timeline(self):
        return sorted(
            ({"tool": s["tool"], "group": G.TOOL_TO_GROUP.get(s["tool"]),
              "at": s["at"], "duration_s": s["duration_s"]}
             for s in self.tool_spans if s["tool"]),
            key=lambda s: (s["at"] is None, s["at"] or 0),
        )

    def _dispatch_breakdown(self):
        c = Counter(t["dispatch"] for t in self.turns)
        return {k: c.get(k, 0) for k in ("tool", "glm", "smalltalk", "none")}


def _parse_run(run_id, path):
    run = Run(run_id, path)
    pi_files = sorted(glob.glob(os.path.join(path, "pi-*.jsonl")))
    mcp_files = sorted(glob.glob(os.path.join(path, "mcp-*.jsonl")))

    per_turn = defaultdict(lambda: defaultdict(list))
    started = ended = None

    for pf in pi_files:
        with open(pf, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if d.get("event") != _TURN_EVENT:
                    continue
                at = _finite_float(d.get("at"))
                if at is not None:
                    started = at if started is None else min(started, at)
                    ended = at if ended is None else max(ended, at)
                turn = d.get("turn")
                if not isinstance(turn, int) or turn < 1:
                    continue
                per_turn[turn][d.get("timing_event")].append(d.get("fields") or {})

    for mf in mcp_files:
        with open(mf, "r", encoding="utf-8") as f:
            _parse_mcp_spans(f, run)

    run.started_at = started
    run.ended_at = ended
    run.config = _extract_config(pi_files)

    for turn in sorted(per_turn):
        run.turns.append(_build_turn(turn, per_turn[turn]))

    return run


def _extract_config(pi_files):
    config = {}
    for pf in pi_files:
        with open(pf, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if d.get("event") != _TURN_EVENT:
                    continue
                te = d.get("timing_event")
                if te == "configuration" and not config:
                    config = dict(d.get("fields") or {})
                # asr_model is null in the configuration event but is carried on
                # each per-turn whisper event; backfill it for the pipeline view.
                if not config.get("asr_model") and te in (
                    "asr_whisper_start", "asr_whisper_complete",
                ):
                    m = (d.get("fields") or {}).get("asr_model")
                    if m:
                        config["asr_model"] = m
        if config and config.get("asr_model"):
            break
    return config


def _parse_mcp_spans(fh, run):
    open_spans = {}
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        ev = d.get("event")
        span_id = d.get("span_id")
        if ev == "span_start" and d.get("phase") == "mcp_server_call":
            open_spans[span_id] = {"tool": d.get("tool"), "at": _finite_float(d.get("at")),
                                   "arguments": d.get("arguments")}
        elif ev == "span_end" and span_id in open_spans:
            start = open_spans.pop(span_id)
            end_at = _finite_float(d.get("at"))
            duration = None
            if start["at"] is not None and end_at is not None:
                duration = round(end_at - start["at"], 3)
            elif d.get("elapsed_ms") is not None:
                duration = round(d["elapsed_ms"] / 1000.0, 3)
            run.tool_spans.append({
                "tool": start["tool"],
                "at": start["at"],
                "duration_s": duration,
                "error": d.get("error"),
                "arguments": start.get("arguments"),
                "result": d.get("result"),
            })


def _first(events, key=None):
    """First event in file order, optionally filtered on a truthy field."""
    for e in events:
        if key is None or e.get(key):
            return e
    return None


def _build_turn(turn, events_by_te):
    t = {
        "turn": turn,
        "group": None,
        "raw_choice": None,
        "router_model": None,
        "top_prob": None,
        "gap": None,
        "gate": "unknown",
        "dispatch": "none",
        "tool": None,
        "glm_reason": None,
        "escalate": False,
        "timings": {
            "asr_s": None,
            "classifier_s": None,
            "tool_s": None,
            "tts_first_s": None,
            "e2e_s": None,
        },
    }

    # ASR: finalized transcript's since_speech_end_ms (ms -> s).
    asr = _first(events_by_te.get("asr_transcript", []), key="finalized")
    if asr:
        sse = _finite_float(asr.get("since_speech_end_ms"))
        if sse is not None:
            t["timings"]["asr_s"] = round(sse / 1000.0, 3)

    # Classifier result / failure / bypass.
    cr = _first(events_by_te.get("classifier_result", []))
    cf = _first(events_by_te.get("classifier_failure", []))
    cb = _first(events_by_te.get("classifier_bypass", []))
    if cr:
        t["raw_choice"] = cr.get("raw_choice")
        t["router_model"] = cr.get("router_model")
        t["top_prob"] = _finite_float(cr.get("top_prob"))
        t["gap"] = _finite_float(cr.get("gap"))
        t["timings"]["classifier_s"] = _finite_float(cr.get("classifier_s"))
    elif cf:
        t["router_model"] = cf.get("router_model")
        status = (cf.get("status") or "").lower()
        t["timings"]["classifier_s"] = _finite_float(cf.get("classifier_s"))
        t["gate"] = GATE_TIMEOUT if status == "timeout" else GATE_ERROR
    elif cb:
        t["router_model"] = cb.get("router_model")
        t["gate"] = GATE_BYPASS

    # Dispatch: which downstream handled the turn.
    rt = _first(events_by_te.get("route_tool", []))
    rg = _first(events_by_te.get("route_glm", []))
    rs = _first(events_by_te.get("route_smalltalk", []))
    if rt:
        t["dispatch"] = "tool"
        t["tool"] = rt.get("tool")
        t["timings"]["tool_s"] = _finite_float(rt.get("mcp_s"))
    elif rg:
        t["dispatch"] = "glm"
        t["glm_reason"] = rg.get("reason")
        t["timings"]["tool_s"] = _finite_float(rg.get("router_s"))
    elif rs:
        t["dispatch"] = "smalltalk"
        t["timings"]["tool_s"] = _finite_float(rs.get("llama_s"))

    # Resolve gate for turns where the classifier ran / was skipped.
    if cf:
        pass  # already set to timeout/error above
    elif cb:
        pass  # already set to bypass above
    elif cr:
        if t["dispatch"] in ("tool", "smalltalk"):
            t["gate"] = GATE_ACCEPTED
        elif t["dispatch"] == "glm":
            if t["glm_reason"] == "multiple_actions":
                t["gate"] = GATE_MULTI
            elif t["raw_choice"] in G.ESCALATE_GROUPS:
                t["gate"] = GATE_ESCALATED
            elif t["raw_choice"] == G.LEGACY_REJECT:
                t["gate"] = GATE_REJECTED
            else:
                # fast/chitchat group escalated to GLM => low-confidence reject
                t["gate"] = GATE_REJECTED
        else:
            t["gate"] = GATE_ACCEPTED
    else:
        # no classifier result/failure/bypass recorded
        if t["glm_reason"] == "multiple_actions":
            t["gate"] = GATE_MULTI

    # TTS first audio (first occurrence — time to first audio).
    tts = events_by_te.get("tts_qwen_first_audio", [])
    if tts:
        t["timings"]["tts_first_s"] = _finite_float(tts[0].get("first_audio_s"))

    # End-to-end latency.
    e2e = _first(events_by_te.get("native_user_bot_latency", []))
    if e2e:
        t["timings"]["e2e_s"] = _finite_float(e2e.get("seconds"))

    # Derive the 9-group id (from raw choice, else from the concrete tool).
    group = G.group_of(t["raw_choice"]) if t["raw_choice"] is not None else None
    if group is None and t["tool"]:
        group = G.TOOL_TO_GROUP.get(t["tool"])
    t["group"] = group
    t["escalate"] = t["dispatch"] == "glm"

    # Routing-trace outcome bucket.
    if t["gate"] in (GATE_TIMEOUT, GATE_ERROR):
        t["outcome"] = t["gate"]
    elif t["gate"] == GATE_REJECTED:
        t["outcome"] = GATE_REJECTED
    elif t["gate"] == GATE_MULTI:
        t["outcome"] = GATE_MULTI
    elif group is not None:
        t["outcome"] = group
    else:
        t["outcome"] = "unknown"

    return t


def load_run(run_id, data_dir):
    path = os.path.join(data_dir, run_id)
    if not os.path.isdir(path):
        raise FileNotFoundError(f"no such run: {run_id}")
    return _parse_run(run_id, path)


def list_runs(data_dir):
    """Return run summaries sorted by start time (oldest first)."""
    if not os.path.isdir(data_dir):
        return []
    runs = []
    for name in sorted(os.listdir(data_dir)):
        path = os.path.join(data_dir, name)
        if not os.path.isdir(path):
            continue
        if not (glob.glob(os.path.join(path, "pi-*.jsonl"))
                or glob.glob(os.path.join(path, "mcp-*.jsonl"))):
            continue
        runs.append(_parse_run(name, path))
    runs.sort(key=lambda r: (r.started_at is None, r.started_at or 0))
    return runs
