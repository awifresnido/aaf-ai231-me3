# Laya v5 — 9-group routing schema: fine-tune report

Date: 2026-11-03 · DGX ai-n003 GPU 3 · laya 0.4.20 · loss soft-ce · seed 20261103

## Deliverables

```
~/projects/laya-router/laya-router-v5-groups/
  model.safetensors        842,609,220 B
  questions.json           888 B   sha256 75b84047dad87a9d66a64907ae67f357fbcfe5e6dace20149ed16f0984e14f1b
  calibration_refit.json   203 B   sha256 579b99c79edb1e27c7d2665adf08548aaf8a93ed0557c4018d1b936d04c68f96
  rl_agent_config.json     4,898 B
  train_report.json        2,520 B   (eval_mode=held_out, 0 overlapping items)
  v5_gates.json           10,622 B   (full per-group gates + confusion)
```

Refit temperature vector: **[1.659, 1.0, 1.0]** (choice, score, noul) on 442
text-disjoint calibration items.

## Data

19,200 manifest rows → 15,786 kept (UNKNOWN 2,813 + SILENCE 601 excluded —
never folded into a group). Label conflicts: **0**.

| split | rows | deduped-unique |
|---|---:|---:|
| train | 6,970 | — |
| val | 1,338 | 357 |
| calibration | 442 | — |
| test | 279 | 128 |
| paraphrase_holdout (VCM, text-disjoint) | 2,095 | 603 |
| synthetic_holdout (unseen templates) | 920 | 922 |
| personal_awi (owner's voice, never trained) | 930 | 93 |

Train counts: home/clock/reminders/media/comms/knowledge 954 each, workspace 581,
weather 347, chitchat 318 (≤3:1 imbalance).

Synthesized groups have a genuine held-out test: templates were split odd/even so
training never saw the eval half.

## Gate 1 — accuracy

| slice | accuracy | ECE (calibrated) |
|---|---:|---:|
| paraphrase holdout (VCM, unseen phrasing) | **0.9701** | 0.0257 |
| synthetic holdout (unseen templates) | **0.9534** | 0.0228 |
| personal_awi (your voice) | **1.0000** | 0.0003 |
| test | 0.9844 | 0.0153 |
| val | 0.9804 | 0.0178 |

Trainer's own text-disjoint eval: 0.4425 → 0.9427 (uncalibrated ECE 0.0573).

## Gate 2 — per-group accuracy (flag < 0.9)

VCM paraphrase holdout (n=603):

| group | n | acc |
|---|---:|---:|
| clock | 75 | 1.000 |
| reminders | 13 | 1.000 |
| weather | 26 | 1.000 |
| comms | 7 | 1.000 |
| home | 316 | 0.997 |
| **media** | 166 | **0.898 ⚠️** |

Synthetic holdout (n=922, unseen templates):

| group | n | acc |
|---|---:|---:|
| weather | 42 | 1.000 |
| knowledge | 220 | 0.991 |
| workspace | 220 | 0.982 |
| chitchat | 220 | 0.968 |
| **comms** | 220 | **0.864 ⚠️** |

personal_awi: every group 1.000 (n=93).

## Gate 3 — unsafe-of-accepted (accepted route → tool in a DIFFERENT group)

| slice | @ τ0.50/gap0.05 |
|---|---:|
| paraphrase holdout | **2.16 %** |
| synthetic holdout | **2.30 %** |
| personal_awi | **0.00 %** |
| test | 1.56 % |
| val | 0.28 % |

**Gate NOT met (target 0 %).** Best achievable by thresholding alone, pooled
holdouts (n=1,525):

| τ / gap | accept | correct fast path | unsafe of accepted |
|---|---:|---:|---:|
| 0.50 / 0.05 | 99.4 % | 0.957 | 2.24 % |
| 0.90 / 0.05 | 95.2 % | 0.937 | 1.24 % |
| 0.99 / 0.05 | 89.4 % | 0.889 | 0.59 % |
| 0.995 / 0.05 | 85.6 % | 0.851 | 0.46 % |

### Why it cannot reach 0 with this schema

The residual errors are boundary ambiguities in the 9 given criteria, not random
model failures:

* `media → home` (12): **"turn it down" / "turn it up"** — direction verbs shared
  by brightness, thermostat and volume. The criteria cannot separate them.
* `comms → chitchat` (13) and `comms → clock` (11): unseen comms templates
  ("give X a ring", "dial X") drifting to conversational/time groups.
* `chitchat → clock` (6): "good night", "see you tomorrow" contain time words.

There is no `other`/`abstain` label in this schema (by design), so a confident
boundary mistake has nowhere to go. Options, in order of preference:

1. **Add a 10th `abstain` label** to the question and train it on the boundary
   set — restores a safe fall-through, costs one schema revision.
2. **Rely on tier-2 validation** (already in the pipeline): "turn it down" routed
   to `home` reaches the brightness parser, which finds no light keyword and
   escalates. This converts most of the 2 % into a slower-but-correct turn.
3. **Operate at τ0.99** — 0.59 % unsafe, 89 % fast-path coverage.

## Gate 4 — calibration

**PASS.** Calibrated ECE ≤ 0.026 on every slice (gate ≤ 0.05). Refit temperature
1.659 (the uncalibrated checkpoint was overconfident: ECE 0.0573).

## Gate 5 — latency

**Unchanged by construction** — same architecture (421M ModernBERT-large) and the
same fp16 weights as v4 (842,609,220 B, byte-identical size). No CPU latency
measurement was repeated here; the deployed Pi/Jetson path is unaffected.

## Comparison with v4 (the `other` problem this addresses)

| | v4 (12 labels) | v5 (9 groups) |
|---|---|---|
| `other` collapse in live trial | 12 / 22 turns | no `other` label exists |
| routing signal for escalation | none (grab-bag) | every turn gets a real group |
| VCM holdout accuracy | 0.9199 | 0.9701 |
| own-voice accuracy | 1.000 | 1.000 |

Every utterance now lands in a group whose tool set is known, so tier-3 receives
a real capability hint instead of "other".

## Reproduction

```bash
cd ~/projects/laya-router
.venv/bin/python build_v5_dataset.py      # relabel + synthesize + splits
.venv/bin/python gen_v5_jsonl.py          # exact 9-group question
CUDA_VISIBLE_DEVICES=3 .venv/bin/laya-train \
  --data data_v5/jsonl_train.jsonl --eval data_v5/jsonl_paraphrase_holdout.jsonl \
  --base convaiinnovations/laya --loss soft-ce --target-error 0.05 \
  --seed 20261103 --device cuda --out ./laya-router-v5-groups
.venv/bin/python v5_gates.py calib        # temperature refit + payload
.venv/bin/python v5_gates.py eval         # per-group gates + confusion
.venv/bin/python v5_diag.py               # gate sweep table
```
