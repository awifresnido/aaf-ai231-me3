"""API tests for the FastAPI hub (read-only endpoints)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", str(DATA_DIR))
    with TestClient(app_module.app) as c:
        yield c


def test_state_lists_three_runs(client):
    state = client.get("/api/state").json()
    assert {r["run_id"] for r in state["runs"]} == \
        {"7ead383cab", "ecf65b32d7", "3ba3a6592d"}
    assert "home" in state["display_names"]["groups"]
    assert "control_lights" in state["display_names"]["tools"]


def test_runs_endpoint(client):
    runs = client.get("/api/runs").json()
    assert len(runs) == 3
    for r in runs:
        assert r["median_e2e_s"] is not None
        assert isinstance(r["turns"], int)


def test_run_detail(client):
    detail = client.get("/api/runs/ecf65b32d7").json()
    assert detail["run_id"] == "ecf65b32d7"
    assert detail["schema"] == "v2_9group"
    assert detail["classifier_health"]["timeout"] == 27
    assert len(detail["turns"]) == 64
    # aggregates + trace views are present
    for key in ("aggregates", "group_distribution", "classifier_health",
                "tool_activity", "tool_timeline", "dispatch_breakdown"):
        assert key in detail


def test_run_turns_endpoint(client):
    turns = client.get("/api/runs/7ead383cab/turns").json()
    assert len(turns) == 26
    assert all(t["turn"] >= 1 for t in turns)


def test_missing_run_404(client):
    resp = client.get("/api/runs/nonexistent")
    assert resp.status_code == 404
