"""Tests for diagnostics ingestion against the committed sample data.

These pin the parser's behaviour against real (verbatim, heartbeat-stripped)
diagnostics so a refactor cannot silently change the numbers the dashboard
shows.  Sample runs and what they exercise:

- ``7ead383cab`` — v2 9-group, clean (no timeouts), all local + escalate routes.
- ``ecf65b32d7`` — v2 9-group, fp32/CPU era: 27 classifier timeouts + 1 error.
- ``3ba3a6592d`` — v4 tool-level contract (tool names, ``other``, ``small_talk``).
"""

from pathlib import Path

import pytest

from backend import groups as G
from backend import ingest

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(scope="module")
def runs():
    return {r.run_id: r for r in ingest.list_runs(str(DATA_DIR))}


def test_three_sample_runs_load(runs):
    assert set(runs) == {"7ead383cab", "ecf65b32d7", "3ba3a6592d"}


def test_schema_detection(runs):
    assert runs["7ead383cab"].schema() == "v2_9group"
    assert runs["ecf65b32d7"].schema() == "v2_9group"
    assert runs["3ba3a6592d"].schema() == "v4_tool"


def test_turn_counts(runs):
    assert len(runs["7ead383cab"].turns) == 26
    assert len(runs["ecf65b32d7"].turns) == 64
    assert len(runs["3ba3a6592d"].turns) == 24


def test_timeout_and_error_counts(runs):
    health = runs["ecf65b32d7"].detail()["classifier_health"]
    assert health["timeout"] == 27
    assert health["error"] == 1
    # the clean v2 run had no classifier failures
    assert runs["7ead383cab"].detail()["classifier_health"]["timeout"] == 0
    assert runs["7ead383cab"].detail()["classifier_health"]["error"] == 0


def test_timeout_turn_marks_two_second_classifier(runs):
    # fp32/CPU-era timeouts hit the ~2 s classifier timeout.
    timeout_turns = [t for t in runs["ecf65b32d7"].turns if t["gate"] == "timeout"]
    assert timeout_turns
    for t in timeout_turns:
        assert t["timings"]["classifier_s"] is not None
        assert 1.9 <= t["timings"]["classifier_s"] <= 2.1
        assert t["dispatch"] == "glm"
        assert t["escalate"] is True


def test_group_mapping(runs):
    # v4 tool names and the legacy small_talk label map to the nine groups.
    assert G.group_of("control_lights") == "home"
    assert G.group_of("get_time") == "clock"
    assert G.group_of("small_talk") == "chitchat"
    assert G.group_of("other") is None
    assert G.group_of(None) is None
    # a v2 run carries group-name raw choices directly
    groups = {t["group"] for t in runs["7ead383cab"].turns if t["group"]}
    assert groups <= set(G.GROUPS)


def test_gate_reconstruction(runs):
    gates = {t["gate"] for t in runs["7ead383cab"].turns}
    assert gates <= {
        "accepted", "escalated", "rejected", "timeout", "error",
        "bypass", "multiple_actions", "unknown",
    }
    # escalate groups (knowledge/workspace) that reach GLM are "escalated",
    # not "rejected".
    for t in runs["7ead383cab"].turns:
        if t["raw_choice"] in G.ESCALATE_GROUPS and t["dispatch"] == "glm":
            assert t["gate"] == "escalated"


def test_honest_missing_values_are_null(runs):
    # Turns without an e2e latency must carry null, never an invented 0.
    for run in runs.values():
        for t in run.turns:
            if t["gate"] == "unknown" and t["dispatch"] == "none":
                assert t["timings"]["e2e_s"] is None
            for key, val in t["timings"].items():
                assert val is None or isinstance(val, (int, float))


def test_display_names_complete():
    for g in G.GROUPS:
        assert g in G.GROUP_DISPLAY, f"missing display name for group {g}"
        assert "name" in G.GROUP_DISPLAY[g]
        assert "color" in G.GROUP_DISPLAY[g]
    for tool in G.TOOL_TO_GROUP:
        assert tool in G.TOOL_DISPLAY, f"missing display name for tool {tool}"


def test_tool_activity_from_spans(runs):
    activity = runs["7ead383cab"].detail()["tool_activity"]
    assert activity, "expected tool activity from mcp spans"
    for entry in activity:
        assert entry["count"] >= 1
        assert entry["tool"] in G.TOOL_DISPLAY


def test_summary_metrics_match_detail(runs):
    for run in runs.values():
        s = run.summary()
        d = run.detail()
        assert s["turns"] == len(d["turns"])
        assert s["median_e2e_s"] == d["aggregates"]["e2e_s"]["median"]
        assert s["classifier_ok"] + s["classifier_fail"] == \
            d["classifier_health"]["accepted"] + d["classifier_health"]["escalated"] \
            + d["classifier_health"]["timeout"] + d["classifier_health"]["error"]
