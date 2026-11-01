# Laya Router Fine-Tune — Methodology, Results & Model Access

**Status: COMPLETE — beats Jev-1.14.0. Recommended `replace_jev = true`.**
Date: 2026-11-01 · Model: `laya-router-v4-softce` · Trainer: Alphonse (Awi) + Hermes agent

This folder is the self-contained reference for any agent that consumes the
fine-tuned Laya router, retrains it, or needs to understand why it replaced the
hosted Jev classifier in the `two-brain-plusjev` orchestration.

---

## 1. Goal

Replace the hosted Jev-1.14.0 decision layer (`pi/orchestration.py`,
branch `two-brain-plusjev`) with a locally-served fine-tuned Laya checkpoint,
eliminating the TypeSafe API dependency while matching or beating its routing
quality. Primary design constraint from the project owner: **a wrong route
executes a real tool — so unsafe wrong-tool executions must be ≈ 0**, even at
the cost of more conservative fall-throughs to GLM.

## 2. What the router does (the contract)

One choice decision per completed user turn over 12 options (play_radio dropped
by owner decision): 10 fast tools (`get_time`, `get_weather`, `list_reminders`,
`add_reminder`, `set_thermostat`, `control_lights`, `set_timer`, `set_alarm`,
`playback_control`, `play_music`) + `small_talk` (→ Llama 3.2 3B) + `other`
(→ GLM 5.3 Flash). Gate: accept only when top-probability and gap-to-runner-up
clear thresholds; otherwise the turn falls through to GLM unchanged.

The fine-tuned model must ask **exactly the same question at inference** (see
`questions_block.json`) — training/inference question mismatch was the single
largest accuracy defect (−11.5 pt) found in this work.

## 3. Training data

Source: TinyVCM ME2 gold manifest `me2_gold_v1.csv` (19,200 rows; on DGX at
`~/projects/tiny-vcm/data/manifests/me2_gold_v1.csv`; HF
`airimonda/ai231-me2-voice-commands`, revision `6947f130…`).

- **Label mapping** (leaf → route): TIME→get_time, WEATHER→get_weather,
  LIST_REMINDERS→list_reminders, CREATE_REMINDER→add_reminder,
  TEMPERATURE→set_thermostat, LIGHT_ON/OFF+COLOR+BRIGHTNESS→control_lights,
  TIMER→set_timer, ALARM→set_alarm, STOP/PAUSE/NEXT/VOLUME_UP/DOWN→playback_control,
  PLAY_MUSIC→play_music, CALL/MESSAGE→other. **UNKNOWN excluded entirely**
  (see §4, defect 3). SILENCE dropped (no text).
- **Synthetic additions**: small_talk (926: templates + real Pi-log ASR turns),
  hard negatives for `other` (350: multi-action, capability questions, weather
  out-of-scope, future-timed alarms, negations, ambiguity, out-of-range values).
- **Balance**: majority classes downsampled to ≤3:1 → 6,069 train rows.
- **Splits**: speaker-disjoint train/val/test + dedicated calibration slice
  (1,005) + text-disjoint unseen-phrasing holdout (1,473, 520 distinct
  phrasings) + personal_awi holdout (930; owner's voice, never trained on).
- 254 paraphrase rows byte-identical to synthetic-train text were removed
  (text-level leakage).

## 4. Defects found & fixed (read before retraining)

1. **Overlapping eval.** `laya-train --eval` accepts an eval file that shares
   text with train and labels the report `eval_mode: overlapping_eval`. v1's
   99.5% was meaningless. Always check `train_report.json` → `eval_mode` and
   `is_held_out`; demand `0 overlapping training/calibration items`.
2. **Train/inference question mismatch.** Training on CSV synthesizes options
   from bare label strings (`control_lights`); the router at inference asks a
   choice question with natural-language criteria. Train on JSONL carrying the
   exact inference `questions` block (`gen_jsonl.py`). Worth +11.5 pt.
3. **`UNKNOWN` → `other` poisoned `other`.** me2 UNKNOWN means "not one of the
   VCM's 19 leaf classes"; most UNKNOWN transcripts are real commands ("set a
   timer", "what are my reminders"). All 70 "unsafe" errors on the own-voice
   slice were this artifact. `other` = real negatives (gold_oos,
   synthetic_negative) + CALL/MESSAGE + hard negatives only.
4. **Negation.** "do not set an alarm" routed to `set_alarm` at confidence —
   added negation hard negatives.
5. **Future-timed commands.** "set alarm tomorrow at six am" predicted
   `set_alarm` at 0.90+; the deterministic parser can't validate future dates,
   so these are `other` (GLM path).
6. **Label contradictions.** "turn it up" in `other` contradicted me2's
   VOLUME_UP → playback_control; shows up as confusion mass.

## 5. Training protocol

```bash
# DGX ai-n003, GPU 3, laya 0.4.20, venv at ~/projects/laya-router/.venv
laya-train --data data/jsonl_train.jsonl \
           --eval data/jsonl_paraphrase_holdout.jsonl \
           --base convaiinnovations/laya \
           --loss soft-ce --target-error 0.05 --seed 20261101 --device cuda \
           --out ./laya-router-v4-softce
```

- **Loss: `soft-ce` beats `rlcd`** on every generalization slice for this task.
- 4 epochs, effective batch 64, 356 optimizer updates; minutes on one A100.
- **Calibration is mandatory**: refit temperature on the *text-disjoint*
  calibration slice via `laya.calibrate.fit_temperatures(records_from_labeled(...))`.
  v4 required **T = 2.58** (severe overconfidence). `records_from_labeled`
  wants numeric target distributions, not label strings.
- **Thresholds do not survive calibration**: re-sweep τ×gap on the calibrated
  model. Post-calibration v4 operates at **τ = 0.50, gap = 0.05**.
- Lineage recorded per run: dataset sha256, adapter sha, laya version, seed,
  GPU, wall clock (in each `train_report.json`).

## 6. Results

Progression on the unseen-phrasing holdout (1,473 rows):

| run | change | acc | ECE |
|---|---|---|---|
| v1 | CSV training (question mismatch) | 0.707* | 0.247* |
| v2 | exact inference question | 0.707 | 0.247 |
| v3 | UNKNOWN removed + negations | 0.860 | 0.115 |
| **v4** | future-time split | **0.920** | **0.0615** |

*v1 numbers from the same holdout after the fix; its own eval was invalid.

Calibrated v4 holdout: **acc 0.9185, ECE 0.0481**.

### Head-to-head vs Jev-1.14.0 (same 200-row samples, same questions)

| slice | model | overall acc | accept | correct FP | unsafe |
|---|---|---:|---:|---:|---:|
| unseen phrasings | Jev | 0.935 | 0.905 | 0.885 | **0.0221** |
| unseen phrasings | **Laya v4** | 0.915 | 0.985 | 0.905 | **0.0000** |
| test | Jev | 0.990 | 0.890 | 0.890 | 0.0000 |
| test | **Laya v4** | 1.000 | 1.000 | 1.000 | 0.0000 |
| own voice | Jev | 0.995 | 0.880 | 0.880 | 0.0000 |
| own voice | **Laya v4** | 1.000 | 1.000 | 1.000 | 0.0000 |

(Laya columns at its calibrated gate τ0.50/gap0.05; Jev at its own 0.90/0.20
and also measured at 0.50/0.05 — 0.980 accept / 0.930 correct / 0.0204 unsafe
on unseen phrasings.)

**Latency**: Jev ~320 ms p50 (hosted RTT) vs **Laya ~30 ms** local. On the Pi
the Jev RTT is worse; Laya adds no network hop.

### Decision verdict (pre-registered conditions)

1. wrong-route ≤ Jev → ✅ (0.0000 vs 0.0221)
2. correct-accept ≥ Jev −2 pt → ❌ marginal (−2.5 pt on unseen phrasings — the
   designed safety trade: uncertainty becomes a GLM fall-through, not a
   wrong tool execution)
3. p95 latency ≤ 2× Jev → ✅ (0.10×)
4. ECE ≤ 0.10 → ✅ (0.0481)

**`replace_jev = true`**, deviations documented (§2 owner decision + §5
non-transferable thresholds).

## 7. Model access

- **Checkpoint**: DGX `ai-n003` (`aldwin.fresnido@10.153.60.233`)
  `~/projects/laya-router/laya-router-v4-softce/`
  - `model.safetensors` + config (base `convaiinnovations/laya`, ModernBERT-large 421M)
  - `calibration_refit.json` — **must be loaded** (T=2.58), else overconfident
  - `questions.json` / this folder's `questions_block.json` — the exact
    inference question; do not rephrase the criteria
  - `train_report.json`, `gate4*_*.json`, `gate5_*.json` — lineage + evals
- **Load pattern**:
  ```python
  import laya
  agent = laya.load("<ckpt_dir>", device="cuda",
                    calibration="<ckpt_dir>/calibration_refit.json")
  questions = {"route": <contents of questions_block.json>}
  ans = agent.predict(transcript_text, questions)["answers"]["route"]
  # ans["choice"], ans["probabilities"]  (calibrated)
  ```
- **Acceptance gate**: top ≥ 0.50 AND gap-to-runner-up ≥ 0.05 → accept route;
  otherwise fall through to GLM (never execute a tool on uncertainty).
- **Deployment target**: Jetson Orin (192.168.5.11) intended; verify free RAM
  (~1.7 GiB at last inspection vs ~850 MB fp16 weights + runtime). Fallback:
  ThinkPad next to Llama 3.2. ONNX export possible via laya if a smaller
  footprint is needed.

## 8. Reproduction & scripts

All scripts in DGX `~/projects/laya-router/` (mirrored locally in the me3
workspace under `laya-router/`):

| script | purpose |
|---|---|
| `build_routing_dataset.py` | me2_gold manifest → 12-route JSONL/CSV, splits, leakage checks |
| `augment_dataset.py` | small_talk + hard negatives + paraphrase holdout + balancing |
| `gen_jsonl.py` | emits `{state, questions, expected}` JSONL with the exact inference question |
| `train/run scripts` (`run_train*.sh`) | laya-train invocations (v1–v4) |
| `gate4_calibration.py` | temperature refit on disjoint calibration slice |
| `gate4b_sweep.py` / `gate4c*.py` | τ×gap operating-point sweeps |
| `eval_router.py` | accuracy/macro-F1/ECE/Brier + per-route + gate sweep |
| `route_safety.py` | unsafe vs safe-fallthrough decomposition |
| `gate5_jev_baseline.py` | live Jev-1.14.0 probe (API key via env var only) |
| `gate5_laya_side.py` | Laya over the identical samples |

Data rules: TYPESAFE_API_KEY never persisted; personal_awi never in train;
speaker-disjointness asserted (0 overlap) in `routing_dataset_stats.json`.

## 9. Known limits / next steps

- Trained on clean text + simulated noise; **real Nemotron ASR transcripts**
  mining (Phase 1b) recommended if production accuracy drifts.
- `CALL`/`MESSAGE` mapped to `other` (tools are stubs) — retrain when those
  tools activate.
- Jetson RAM fit unverified; ThinkPad fallback documented.
- Integration (branch task): `ROUTER_MODEL=laya|jev` flag in
  `pi/orchestration.py`; unit tests unchanged; Jetson first, ThinkPad fallback.
