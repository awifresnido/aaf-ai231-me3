#!/usr/bin/env python3
"""Load and use the fine-tuned Laya 9-GROUP router (laya_v2).

    ~/models/laya/laya_v2/use_router.py "search the web for bitcoin"

Differences from laya_v1 (the 12-tool router):
  * 9 GROUPS instead of 12 tools: home, clock, reminders, media, weather,
    comms, knowledge, workspace, chitchat.
  * There is NO `other` label. When the gate rejects a turn this returns
    route=None with accepted=False, and the caller must escalate (tier-3).
    Do not substitute "other" — it is not in the schema and the downstream
    mapping would fail.

Precision: fp16 weights + fp16 autocast by default on GPU (see PRECISION.md).
Gate default: TAU=0.90, GAP=0.05 -> ~95% accept, ~1.2% unsafe misroute on the
held-out slices. TAU=0.99 trades coverage (89%) for 0.6% unsafe.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CKPT = HERE

TAU = float(os.environ.get("LAYA_TAU", 0.90))
GAP = float(os.environ.get("LAYA_GAP", 0.05))

QUESTIONS_PATH = HERE / "questions.json"
CALIBRATION_PATH = HERE / "calibration_refit.json"

_precision = os.environ.get("LAYA_PRECISION", "fp16").strip().lower()
_have_cuda = False
try:
    import torch
    _have_cuda = torch.cuda.is_available()
except Exception:
    pass

if _precision in ("fp16", "float16") and _have_cuda:
    os.environ["LAYA_CUDA_AMP"] = "fp16"
elif _precision in ("bf16", "bfloat16") and _have_cuda:
    os.environ["LAYA_CUDA_AMP"] = "bf16"
elif _precision in ("fp32", "float32"):
    os.environ["LAYA_CUDA_AMP"] = "fp32"

import laya  # noqa: E402

_agent = None
_effective = None


def _describe(agent) -> str:
    model = getattr(agent, "model", None)
    if model is None:
        return "unknown"
    ptype = str(next(model.parameters()).dtype).replace("torch.", "")
    amp = getattr(agent, "amp_enabled", False)
    adtype = str(getattr(agent, "dtype", "")).replace("torch.", "")
    return f"weights={ptype} autocast={adtype if amp else 'off'}"


def load_router():
    global _agent, _effective
    if _agent is None:
        _agent = laya.load(str(CKPT), device=None, calibration=str(CALIBRATION_PATH))
        if _precision in ("fp16", "float16") and _have_cuda:
            model = getattr(_agent, "model", None)
            if model is not None:
                model.half()
                torch.cuda.empty_cache()
        _effective = _describe(_agent)
    return _agent


def route(text: str) -> dict:
    """Route one utterance to a tool GROUP.

    Returns accepted=False and route=None when the gate rejects the turn —
    the caller must escalate to the reasoning tier. Never invent a group.
    """
    agent = load_router()
    questions = json.loads(QUESTIONS_PATH.read_text())
    ans = agent.predict(text, questions)["answers"]["route"]
    probs = ans.get("probabilities") or {}
    choice = ans.get("choice")
    top = float(probs.get(choice, 0.0))
    second = max((v for k, v in probs.items() if k != choice), default=0.0)
    gap = top - second
    accept = top >= TAU and gap >= GAP
    return {
        "text": text,
        "route": choice if accept else None,
        "accepted": accept,
        "raw_choice": choice,
        "top_prob": round(top, 4),
        "gap": round(gap, 4),
        "precision": _effective or _precision,
        "gate": {"tau": TAU, "gap": GAP},
        "probabilities": {k: round(float(v), 4) for k, v in probs.items()},
    }


if __name__ == "__main__":
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "what time is it"
    print(json.dumps(route(text), indent=2))
