# laya_v2 — Laya 9-GROUP tool router (v5c)

**Copy of**: DGX `~/projects/laya-router/laya-router-v5-groups` (trained 2026-11-03)
**Base**: convaiinnovations/laya (ModernBERT-large 421M) · **Loss**: soft-ce · **T**: 1.659
**Full report**: this folder's `REPORT.md`

## What it does

Routes one utterance (ASR transcript) to one of **nine tool groups** instead of a
single tool. This replaces `laya_v1`'s 12-label schema, whose single `other`
label swallowed 12 of 22 live turns and gave the escalation tier no signal.

```
home       lights on/off/colour/brightness; thermostat temperature
clock      current time, one timer, one alarm
reminders  add / list / complete a reminder
media      play music; control current playback
weather    current weather or a short forecast
comms      send a message or email; place a phone call
knowledge  look something up on the web, open a URL, search the user's documents
workspace  multi-step work on files, code, a shell, or GitHub
chitchat   greeting, thanks, conversational reply needing no tool
```

## Quick start

```bash
~/models/laya/laya_v2/use_router.py "search the web for bitcoin"
~/models/laya/laya_v2/use_router.py "send a message to mom"
~/models/laya/laya_v2/use_router.py "turn on the lights"
```

In code:

```python
import sys; sys.path.insert(0, "/home/aldwin/models/laya/laya_v2")
from use_router_v2 import route
out = route("who is helen keller")     # -> {"route": "knowledge", "accepted": True, ...}
```

## Important contract change

**There is no `other` label.** When the gate rejects a turn, `route` is `None`
and `accepted` is `False` — the caller must escalate. Do **not** substitute
`"other"`: it is not in the schema and the downstream group→tool mapping will
raise.

Recommended operating points (pooled held-out slices, 1,525 unique items):

| tau / gap | accept | correct fast path | unsafe misroute |
|---|---:|---:|---:|
| 0.50 / 0.05 | 99.4 % | 0.957 | 2.24 % |
| **0.90 / 0.05** (default) | **95.2 %** | **0.937** | **1.24 %** |
| 0.99 / 0.05 | 89.4 % | 0.889 | 0.59 % |

Override with `LAYA_TAU` / `LAYA_GAP`.

## Measured quality (calibrated)

| slice | accuracy | ECE |
|---|---:|---:|
| VCM unseen-phrasing holdout | 0.9701 | 0.0257 |
| synthetic unseen-template holdout | 0.9534 | 0.0228 |
| owner's own voice | 1.0000 | 0.0003 |
| test | 0.9844 | 0.0153 |

Weakest groups: `media` 0.898 (VCM holdout — "turn it up/down" ambiguity) and
`comms` 0.864 (unseen templates). See REPORT.md for the full confusion matrix.

## Contents

| file | what |
|---|---|
| `model.safetensors` | fine-tuned weights (842,609,220 B) |
| `encoder/`, `tokenizer/` | model + tokenizer config |
| `calibration_refit.json` | **required** — temperature 1.659 |
| `questions.json` | the exact 9-group question (sha256 `75b84047…`) |
| `use_router_v2.py` | loader + gate (no `other` fallback) |
| `README.md` | this file — NOTE: canonical copy is `use_router_v2.py` |
| `REPORT.md` | training report, per-group gates, confusion matrix |
| `v5_gates.json` | raw gate numbers per slice |
| `train_report.json` | lineage (seed 20261103, eval_mode=held_out) |
