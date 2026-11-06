# Laya integration assessment — 2026-11-01

This records the Laya preflight before the subsequent user-requested
[Jev + GLM live reactivation at 22:05](jev-glm-live-trial-20261101.md).
References below to the live Llama-only selection describe that assessment's
capture time. The uncommitted optional Laya implementation remains available.

Branch `laya-integration` starts at `b059cd4`. Implementation is uncommitted.
The live Pi service still uses the original Llama decision path. Its MCP
servers remain on Pi, SQLite on the Jetson worker, and speakerphone/AEC settings
are unchanged. No live database was replaced or reset. The optional classifier
was started separately on ThinkPad loopback `8082`, with a separate Pi loopback
reverse tunnel at `18082`. These are temporary processes, not installed units.

**Assessment: suitable for an experimental integration comparison; the evidence
does not support replacing Jev or the live Llama path yet.** The classifier works
with the existing execution/storage split, but rejects some valid number-word
thermostat commands and is slower than hosted Jev on this CPU.

## Calibration and training provenance

Inspected `Laya finetuning/` directly from `ed98e51` on `origin/main`, without
merging main. The [artifact audit](../profiling/laya-integration-20261101/artifact-audit.json)
records source commit, local and source hashes, reports and embedded calibration.

- The local external calibration is **byte-identical** to the source payload:
  `temperature=[1.9951245784759521,1,1]`. Both READMEs' **2.58** description
  conflicts with the actual published payload. Do not substitute 2.58.
- Embedded choice temperature is **0.9904223084449768**. Runtime inspection
  confirmed explicit external loading installs **1.9951245784759521** and an
  empty per-option temperature map. The loader warns about the DGX checkpoint
  path differing from its ThinkPad copy; the payload is still installed.
- The local `questions.json` and source `questions_block.json` have identical
  parsed content and option order. Their whitespace/file hashes differ. The
  integration bundles the source file exactly and pins both file hashes.
- Local training report equals the source v4 report: `soft-ce`, four epochs,
  effective batch 64, seed 20261101, encoder LR 2.5e-5, head LR 1e-4, encoder
  unfrozen. Held-out report: **91.99%**, ECE **0.0615**, 1,473 items.
- Source augmentation reports **6,069** final training rows, synthetic
  conversation/negative additions, class balancing, and a 1,473-row phrase
  holdout. Training on the exact natural-language criteria fixes an important
  mismatch with the earlier CSV-label formulation. Excluding mislabeled
  `UNKNOWN` commands and adding negations/future-time negatives are sensible.

Acceptance remains **top >= 0.50 AND gap >= 0.05**. Tests verify both boundaries
and reject malformed distributions. The service and client both compute the
gate; they do not trust an `accepted` flag from a response. Hash mismatches stop
startup or reject the response. No thresholds or temperatures were refitted.

The discrepancy is resolved as a **documentation-versus-artifact mismatch**,
not proof that the supplied calibration has the published statistical quality.
The complete calibration/holdout rows, per-item predictions and v4 gate4c script
are absent here. The mirrored gate4/gate4b scripts still hardcode v2 checkpoint
paths. The supplied operating-point report is not bound to weight/calibration
hashes. Consequently the claimed calibrated ECE 0.0481 and the gate's full
statistical validity could not be independently reproduced.

Additional evidence limits:

- The larger gate4c report has **0.2716% unsafe non-other predictions** on the
  phrase holdout and **0.2283%** pooled, versus zero on the 200-row gate5 sample.
  Zero sample errors is not a zero-risk guarantee or a record of executed tools.
- Gate4b selects on pooled holdout + test; successive model changes also use
  observed evaluation failures. These slices have participated in development.
- The dataset script audits train/test speaker overlap, not all pairwise
  train/validation/calibration overlaps. The augmentation script's phrase filter
  does not establish a complete all-split final-text leakage audit. The initial
  calibration stats have no `small_talk` rows. Final data are needed to audit
  calibration coverage and disjointness fully.
- The builder tags negated/compound rows but only explicitly remaps the
  weather/future-time cases to `other`; final-row label auditing is needed to
  establish how all the tagged negatives and synthetic additions interact.
- `correct_fastpath` in the evaluation scripts counts every correct accepted
  label, including `other`; it is not actual successful tool execution coverage.
- At their own gates, source gate5 phrase accuracy is Laya **91.5%**, Jev
  **93.5%**; correct accepted labels are **90.5% vs 88.5%**. The README's
  claimed -2.5-point failure compares Laya's liberal gate against Jev's liberal
  gate (**93%**), not Jev's deployed 0.90/0.20 gate. Keep denominators/gates clear.

## Fresh matched text comparison

Both actual services classified the same 38 authored cases, with exactly the
trained question. Order alternated by case. Jev used `jev-1.14.0`, gate
0.90/0.20; Laya used the pinned external calibration and gate 0.50/0.05.
Both then used the new identical argument guard, without executing any tools.
Credentials stayed on Pi. Request failures remain in all denominators.

| Measurement | Laya, ThinkPad CPU / Pi tunnel | Jev, hosted / Pi client |
|---|---:|---:|
| Requests / failures | 38 / 0 | 38 / 0 |
| Raw route accuracy | 30/38, **78.95%** | 28/38, **73.68%** |
| Exact supported action or appropriate no-tool outcome | 36/38, **94.74%** | 38/38, **100%** |
| Wrong accepted actionable routes before argument guard | **3** | **4** |
| Wrong proposed tools after argument guard | **0** | **0** |
| Client round-trip p50 | **0.979 s** | **0.296 s** |
| Client round-trip p95, nearest-rank | **1.311 s** | **0.719 s** |

These are challenge-set outcomes, **not population accuracy, an independent
held-out estimate, or live voice measurements**. Some cases intentionally omit
values or request unsupported capabilities. The no-tool score does not grade
the quality of spoken clarifications or conversational answers. The comparison
uses the new guard for both engines; it is not a measurement of the historical
Jev controller with its different question, reminder bypass and Llama extractor.

Laya's two action misses were “Set the thermostat to twenty six degrees” and
“Set the room temperature to twenty eight degrees,” both high-confidence
`other`. A [follow-up probe](../profiling/laya-integration-20261101/temperature-probe.json)
confirmed numeric forms and “twenty-six degrees Celsius” route correctly,
while some spaced number-word forms do not. No intent override was added to
hide these errors. ASR's number normalization may affect the actual voice result.

The saved [comparison](../profiling/laya-integration-20261101/text-comparison.json)
contains per-case outputs; [cases](../../tests/fixtures/laya_challenge.json) are
synthetic and contain no private speech.

## Integration and checks

Use `ORCHESTRATION_MODE=local_vcm`, `LOCAL_VCM_MODEL_HOST=thinkpad` and
`ROUTER_MODEL=laya` to opt in. `ROUTER_MODEL=llama` restores the current decision
path. Default remains `llama`. The existing two-brain/Jev path is unchanged.

Laya runs in `/home/aldlinux/ai/laya-env/bin/python` (Laya 0.4.19), CPU, two
inference threads, one interop thread. The [new-process startup check](../profiling/laya-integration-20261101/startup.json)
measured **4.827 s to health readiness**, including preload, warmup and weight
hashing; filesystem cache was already warm. This is not a disk-cache-cold test.
Source 30 ms measurements ran on DGX CUDA, not this ThinkPad CPU. The original
Llama service/port were not replaced. Prepared systemd unit templates under
`deploy/thinkpad/` provide residency/tunnel setup after review; none were installed.

On this i5-1345U (12 logical CPUs), a separate five-case model-only
[contention probe](../profiling/laya-integration-20261101/contention.json) measured
Laya median **1.165 s** with sequential requests versus **3.489 s** while Llama
was generating concurrently (six configured Llama threads). All five concurrent
Laya requests exceeded the trial client's **two-second deadline**. The probe
deliberately allowed twelve seconds to observe completions; the voice client
would return an unavailable reply and execute no tool. This is a small stress
probe with prompt-cache/order effects, not a controlled CPU scheduling study.
No thread allocation or deadline was changed to hide the result. CPU contention
must be resolved or accepted explicitly before relying on this route in live use.

The client classifies only the current transcript. Whole-command grounding,
existing deterministic extraction and schema/range validation are independent
of confidence. A valid route with missing/unsupported arguments asks for details;
it never calls an LLM tool extractor. Grammar coverage is intentionally narrower
than all possible paraphrases. Ambiguous follow-ups require a complete command.
The grammar rejects negations, malformed/noisy commands, compounds, unsupported
colors, Fahrenheit, nonlocal/forecast weather, and absent setter values.
Reminder text keeps user capitalization. Hearing checks get a local reply.

`LAYA_FALLBACK_POLICY=clarify` is the default for `other`/abstention.
`llama_reply` explicitly permits a **ThinkPad-only conversational reply**.
Accepted `small_talk` uses that local conversational path. A model reply cannot
return an executable decision. Router failures/invalid responses return a local
unavailable reply even with `llama_reply` selected. Cloud policies and VPS model
selection are rejected for this trial. No rejection or timeout enables GLM.

User context is consumed before awaiting inference/execution. Repeated context,
concurrent delivery, cancellation, lost/malformed receipt and write timeout cannot
automatically issue the same write again. The existing durable worker replay
protection and uncertain-outcome handling remain in place. A new spoken request
still has a new identity; check state before manually repeating an uncertain write.

The real [integration preflight](../profiling/laya-integration-20261101/integration-preflight.json)
passed **12/12** cases: seven valid tool calls and five no-tool cases. It used a
fresh, separate Jetson directory `state/preflight/laya-preflight-5cb7c45d71` and
temporary Pi state directory. All SQLite spans were on Jetson's `state`
component; all MCP client/server work remained on Pi. Replayed contexts issued
no extra calls. There were no unfinished spans, incomplete trace lines or dropped
events in the 607-event [capture and summary](../profiling/laya-integration-20261101/preflight-summary.json).
Six writing calls had durable commits around 2–3 ms. This preflight excluded
ASR, endpointing, TTS and physical speaker output.

Regression tests passed on Pi; see the [recorded validation](../profiling/laya-integration-20261101/validation.txt).
They cover gate boundaries, malformed probabilities, unsupported/missing
arguments, transport/total deadlines, cloud isolation, uncertain receipts,
concurrent/cancelled writes, placement/storage durability, and nested timings.

Timing now separates `classifier_client`, `argument_validation`, and
`model_fallback` spans and records them by turn. `model_s` retains total decision
time for baseline compatibility. The voice summarizer exposes the nested stages
separately; do not add classifier time to the total decision time.

Reproduce on Pi from the review checkout (currently `/tmp/laya-review-20261101`):

```bash
PY=/home/aldwinrpi4/pipecat-quickstart/server/.venv/bin/python
$PY -m unittest discover -s tests
$PY scripts/compare_laya_jev.py --jev \
  --env-file /home/aldwinrpi4/.voice-agent-env --output /tmp/laya-jev.json
$PY scripts/probe_laya_integration.py \
  --env-file /home/aldwinrpi4/.voice-agent-env --output /tmp/laya-preflight.json
$PY scripts/probe_laya_contention.py \
  --env-file /home/aldwinrpi4/.voice-agent-env --output /tmp/laya-contention.json
```

The Jev comparison explicitly requests hosted classification of synthetic text;
it does not enable cloud escalation in the voice service. The model-only
contention probe issues no tools. Regression, preflight and comparison source
remain in the review checkout, outside the live Pi project.

## Matched speakerphone trials — pending human participation

**No Laya end-to-end voice result exists yet.** Historical reference remains
**5.468 s over 22 replies**, run `afe7b8b933`. Text/model benchmarks cannot
establish improvement over it. The live service has not been restarted or opted
into Laya because the speakerphone passes require the user to speak the commands.

For the next session:

1. Preserve a private backup of the live Pi source and environment before
   copying `bot.py`, `local_vcm.py`, `laya_router.py`, `laya_contract.py`, and
   `laya_questions.json` from this reviewed branch into the Pi project. Keep
   `orchestration.py`, MCP servers, worker and audio configuration unchanged.
2. Start the resident service/tunnel from the supplied unit templates or the
   equivalent foreground commands. Check `127.0.0.1:18082/health` from Pi and
   confirm the expected hashes, device, and thread count. Retain the separate
   Llama service/tunnel throughout the experiment. The current temporary
   classifier/tunnel can be reused for immediate trials; stop those processes
   before installing/starting the units on the same ports.
3. Record the original `VCM_JETSON_DATA_DIR`. For matched initial state, use
   two new, initially empty directories under Jetson
   `state/trials/laya-match-<session>/llama` and `/laya`. Never overwrite the
   current trial database or copy stale Pi state onto NVMe. Restore the original
   path after testing so live state history remains available.
4. Run one fresh-process pass with `ROUTER_MODEL=llama`, then another with
   `ROUTER_MODEL=laya`, `LAYA_FALLBACK_POLICY=clarify`, timeout two seconds.
   Restart the Pi audio service between passes to clear model conversation.
   Set a distinct `VAD_EXPERIMENT` per mode. Keep Pi MCP + Jetson SQLite,
   speakerphone AEC, VAD 0.3, Smart Turn two threads, pacat 150 ms and queued
   logging/diagnostics fixed. Record the actual run IDs and explicit pass bounds.
5. Speak the following exact list in each pass, waiting for each completed
   response: “Can you hear my voice?”, “Turn on the lights”, “Set the lights
   to blue”, “Set the lights to eighty percent brightness”, “Set the thermostat
   to twenty six degrees”, “Remind me to Review Laya Results”, “List my
   reminders”, “Set a five minute timer”, “Set an alarm for nine PM”, “What
   time is it now?”, “What is the weather today?”, “Stop the music”, “Play
   some jazz music”, “What is the weather in Cebu?”, “Set the thermostat”,
   “Turn the lights green and lower the volume”, “Do not turn on the lights”,
   and “Thank you”. Timer/alarm delivery and real music playback remain absent.
6. Assess actual ASR transcripts and expected tool/arguments separately from
   mechanical receipts. Include missing replies, startup self-hearing, validation
   errors, rejected valid commands and unintended actions. Keep private speech
   in the Pi log; publish only labels/metadata. Capture Pi/MCP/worker traces from
   each run, and filter TTS first-byte metadata from the matching log.
7. Use `summarize_voice_trial.py --pass-turns FIRST:LAST` and
   `summarize_stall_diagnostics.py` per run. Compare matched-turn correctness,
   speech-end-to-first-playback, classifier, argument check, local model reply,
   MCP, storage RPC, commit and TTS timings. Native/playback timestamps still
   do not independently measure physical acoustic onset. Restore
   `ROUTER_MODEL=llama` and the original state directory after collection.

The user was asked asynchronously about speakerphone availability. No response
was received during the implementation/preflight work. These passes remain open;
do not record them as completed or claim a speedup against the historical run.
