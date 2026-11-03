"""Pinned laya_v2 (9-group) inference contract; no inference dependencies.

Companion to laya_contract.py (the v4 12-tool contract). The v2 model routes to
tool GROUPS (home/clock/reminders/media/weather/comms/knowledge/workspace/chitchat)
with no ``other`` label; a rejected turn escalates to the reasoning tier.

Selected via LAYA_SCHEMA=v2 in laya_classifier.py and orchestration.py.
"""

import hashlib
import json
import math
from pathlib import Path

TAU = 0.90
GAP = 0.05
QUESTION_SHA256 = "75b84047dad87a9d66a64907ae67f357fbcfe5e6dace20149ed16f0984e14f1b"
BUNDLED_QUESTION_SHA256 = "75b84047dad87a9d66a64907ae67f357fbcfe5e6dace20149ed16f0984e14f1b"
CALIBRATION_SHA256 = "579b99c79edb1e27c7d2665adf08548aaf8a93ed0557c4018d1b936d04c68f96"
TEMPERATURE = [1.6589586734771729, 1.0, 1.0]
QUESTIONS_PATH = Path(__file__).with_name("laya_questions_v2.json")
QUESTIONS = json.loads(QUESTIONS_PATH.read_bytes())
ROUTES = tuple(QUESTIONS["route"]["criteria"])
CONTRACT = {"question_sha256": QUESTION_SHA256,
            "calibration_sha256": CALIBRATION_SHA256, "tau": TAU, "gap": GAP}


def verify_artifacts(checkpoint):
    checkpoint = Path(checkpoint)
    for path, digest in [(QUESTIONS_PATH, BUNDLED_QUESTION_SHA256),
                         (checkpoint / "questions.json", QUESTION_SHA256),
                         (checkpoint / "calibration_refit.json", CALIBRATION_SHA256)]:
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Unverified Laya v2 artifact: {path.name}")
    return checkpoint / "calibration_refit.json"


def gate(answer, tau=TAU, gap=GAP):
    """Recompute acceptance from the entire finite probability distribution."""
    if not isinstance(answer, dict):
        raise ValueError("Invalid route answer")
    choice, probs = answer.get("choice"), answer.get("probabilities")
    if choice not in ROUTES or not isinstance(probs, dict) or set(probs) != set(ROUTES):
        raise ValueError("Incomplete route distribution")
    if any(type(p) not in (float, int) or not math.isfinite(p) or not 0 <= p <= 1
           for p in probs.values()) or abs(sum(probs.values()) - 1) > 0.005:
        raise ValueError("Invalid route probabilities")
    top = probs[choice]
    second = max(p for name, p in probs.items() if name != choice)
    if top < second:
        raise ValueError("Choice is not the most probable route")
    accepted = top + 1e-12 >= tau and top - second + 1e-12 >= gap
    return {"route": choice if accepted else None, "accepted": accepted,
            "raw_choice": choice, "top_prob": top, "gap": top - second,
            "probabilities": probs}
