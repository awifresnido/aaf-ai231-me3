"""Pinned v4 inference contract from main ed98e51; no inference dependencies."""

import hashlib
import json
import math
from pathlib import Path

TAU = 0.50
GAP = 0.05
QUESTION_SHA256 = "824fd9c3237e9e0f81a7203d11f6bfea6e49b3d9f2d26d71b7c7383cc0c752b3"
BUNDLED_QUESTION_SHA256 = "7f04b4852e88876fd79e12c9300a92a9ca2de2edc83fb2a86d204b16d5843860"
CALIBRATION_SHA256 = "6bb7a87077438fa279cbc5350b26394c36ffdc7e72481e3cf69897bb1264994c"
TEMPERATURE = [1.9951245784759521, 1.0, 1.0]
QUESTIONS_PATH = Path(__file__).with_name("laya_questions.json")
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
            raise ValueError(f"Unverified Laya artifact: {path.name}")
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
    return {"route": choice if accepted else "other", "accepted": accepted,
            "raw_choice": choice, "top_prob": top, "gap": top - second,
            "probabilities": probs}
