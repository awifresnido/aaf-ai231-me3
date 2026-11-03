"""FastAPI hub for the ME3 voice-agent dashboard.

Owns all state (parsed runs) and serves read-only JSON to the React frontend.
The dashboard never drives the pipeline and never calls a model — it only reads
diagnostics already captured on disk.
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import groups as G
from . import ingest

DEFAULT_DATA_DIR = str(Path(__file__).resolve().parents[1] / "data")
DATA_DIR = os.environ.get("DASHBOARD_DATA_DIR", DEFAULT_DATA_DIR)

app = FastAPI(title="ME3 voice-agent dashboard", version="0.1.0")

# Allow the Vite dev server to hit the API during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _load_all():
    return ingest.list_runs(DATA_DIR)


def _find(run_id):
    for run in _load_all():
        if run.run_id == run_id:
            return run
    raise HTTPException(status_code=404, detail=f"no such run: {run_id}")


@app.get("/api/state")
def state():
    runs = [r.summary() for r in _load_all()]
    return {
        "data_dir": DATA_DIR,
        "runs": runs,
        "groups": list(G.GROUPS),
        "display_names": {
            "groups": G.GROUP_DISPLAY,
            "outcomes": G.OUTCOME_DISPLAY,
            "dispatch": G.DISPATCH_DISPLAY,
            "tools": G.TOOL_DISPLAY,
        },
    }


@app.get("/api/runs")
def runs():
    return [r.summary() for r in _load_all()]


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    return _find(run_id).detail()


@app.get("/api/runs/{run_id}/turns")
def run_turns(run_id: str):
    return _find(run_id).turns


# Serve the built frontend (npm run build -> dashboard/frontend/dist) if present.
_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
