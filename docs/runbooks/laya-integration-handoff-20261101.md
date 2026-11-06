# New-terminal handoff: integrate the fine-tuned Laya decision router

## Task to give Codex

Continue the Voice of Pi project from `two-brain-plusjev`, configuration
checkpoint `dda6ddc`. Create a new `laya-integration` branch from that
checkpoint's branch tip after checking the working tree. Integrate the
already trained local Laya router as an optional decision layer, with a
controlled comparison against the existing Llama-only path. Start with
read-only inspection of the actual hosts, configuration, local model, and
instructions. Preserve the tested Pi-hosted MCP/Jetson persistence split.
Implement and test the integration, keep rollback available, and leave
implementation changes uncommitted for my review. Do not retrain the model
or replace the live model service merely to begin the work.

## Workspace and checkpoint

- WSL workspace: `/home/aldlinux/ai/voice-agent-cluster/aaf-ai231-me3`.
- Repository: `awifresnido/aaf-ai231-me3`.
- Baseline branch: `two-brain-plusjev`; code checkpoint `dda6ddc`.
- A following documentation commit adds this handoff. Start the new branch
  from the latest published `two-brain-plusjev` tip so the handoff is included.
- Read `docs/runbooks/reboot-resume.md`,
  `docs/runbooks/pi-mcp-jetson-state-trial-20261101.md`, and
  `docs/runbooks/pi-mcp-worker-results-20261101.md` first.

Do not switch the implementation to `main` or merge it blindly. The model's
README says training methodology lives in a `Laya finetuning/` directory on
`main`; inspect that material from the appropriate remote ref separately.
Its presence/content was not verified when this handoff was written.

## Verified local Laya artifacts

Actual checkpoint directory: **`/home/aldlinux/ai/laya_v1`**.

- `model.safetensors`: approximately 804 MiB.
- `encoder/config.json`, `tokenizer/`, `rl_agent_config.json`.
- `questions.json`: the fixed twelve-way routing question.
- `calibration_refit.json`: the external calibration payload.
- `train_report.json`, `README.md`, `use_router.py`.
- `RESULTS.md` is mentioned by the README but is absent.

Actual interpreter: **`/home/aldlinux/ai/laya-env/bin/python`**, Python 3.14
environment, installed Laya **0.4.19**. The README's `laya_env` underscore
path does not exist here. CLI entry points include `laya-serve` and
`laya-mcp-server`; use the HTTP/in-process serving path on ThinkPad so a
new MCP server is not introduced there.

`use_router.py` loads the model once with:

```python
laya.load(checkpoint_path, device=None, calibration=calibration_path)
```

It calls `agent.predict(text, questions)` and reads `answers["route"]`.
Acceptance requires top class probability >= **0.50** AND probability gap
to the runner-up >= **0.05**. Its returned route becomes `other` if the
gate rejects, while `accepted` preserves the gate verdict.

**Resolve a calibration discrepancy before deploying:** the README describes
temperature 2.58, but the actual external calibration file contains
`temperature: [1.9951245784759521, 1.0, 1.0]`. The checkpoint configuration
also contains older embedded temperatures. Verify calibration lineage and
the gate's validity for the actual supplied payload. Always load the
external file explicitly; do not silently use the embedded temperature or
change thresholds to make examples pass. Do not rephrase `questions.json`:
its criteria are part of training.

The README claims approximately 30 ms routing and strong evaluation results.
Those are artifact claims, not measured latency/accuracy on this ThinkPad
voice pipeline. No Laya inference, model serving, package upgrade, or live
integration was performed during the handoff.

## Router contract and important capability limits

The twelve options are:

```text
get_time, get_weather, list_reminders, add_reminder, set_thermostat,
control_lights, set_timer, set_alarm, playback_control, play_music,
small_talk, other
```

Laya classifies a route. It does **not** generate the validated tool argument
object needed by the current controller. Keep routing separate from argument
extraction and actual execution. Reuse the existing deterministic parsers/
validators where appropriate; any optional Llama extraction must be bounded
and grounded in the utterance/context. Missing parameters require clarification,
not values copied from prompt examples. A route probability is not authorization
to execute a setter with invented arguments.

The training criteria map `small_talk` toward Llama and `other` toward the
complex model. The **current baseline has GLM disabled**. Keep complex-model
fallback an explicit mode/policy; a rejected route, timeout, or invalid
argument must not silently restore cloud escalation or issue a tool.

The checkpoint's weather criterion includes stated locations, but the current
VCM path cannot geocode names or provide forecasts. A high-confidence weather
route must not silently answer local weather for a different city. Multi-action
requests also need explicit handling; the old controller sometimes performed
only the lights portion of a lights-plus-volume request.

The installed `laya.serve` documents `/v1/systemone` for Jev-compatible
inference and `/health`. Its `/v1/route` endpoint is described as routing
without inference; do not assume it performs the fine-tuned tool classifier.
Inspect custom-checkpoint registration and external-calibration loading before
using the built-in server. It is not an OpenAI chat-completions replacement:
do not simply point `SMALL_LLM_PRIMARY_URL` at Laya.

## Live architecture and access

Pi: `aldwinrpi4@192.168.5.12`; project `/home/aldwinrpi4/voice-agent`.
Jetson: `aldwin@192.168.5.11`; models `/home/aldwin/models`.
WSL SSH identity `/home/aldlinux/.ssh/id_ed25519_pihost`, known-hosts file
`/home/aldlinux/.ssh/known_hosts_pihost`. Use `-F /dev/null`, batch mode,
and those explicit paths for inspection; do not print private key contents.

Pi service: `systemctl --user ... me3-local-audio.service`.
Pi Python: `/home/aldwinrpi4/pipecat-quickstart/server/.venv/bin/python`.
Private configuration: `/home/aldwinrpi4/.voice-agent-env`, mode 600.
Main log: `/home/aldwinrpi4/voice-agent/me3-local-audio.log`.

Actual selected settings at handoff:

```ini
ORCHESTRATION_MODE=local_vcm
LOCAL_VCM_MODEL_HOST=thinkpad
VCM_TOOL_SERVER_HOST=pi
VCM_STATE_BACKEND=jetson_sqlite
VCM_JETSON_DATA_DIR=/home/aldwin/voice-agent-vcm/state/trials/nvme-20261101
VOICE_DIAGNOSTICS=1
VOICE_QUEUED_LOGGING=1
VAD_STOP_SECS=0.3
SMART_TURN_CPU_COUNT=2
```

Every active MCP server must stay on Pi. Only a non-MCP SQLite worker runs
on Jetson, over persistent restricted SSH. It uses FULL durable commits,
atomic updates, and persistent request replay protection. Do not move the
database back to Pi USB, mount SQLite over a network filesystem, acknowledge
before commit, or reset/overwrite the NVMe state. The original Pi database
is preserved separately. All model weights, private configuration, live
state, and credentials remain outside Git.

Pi audio uses its JOUNIVO JV801P speakerphone, hardware PCM 100%, paired
`voice_agent_aec_source` / `voice_agent_aec_sink`, pacat output with 150 ms
buffer. Jetson Docker services are `nemotron-asr-server` (50051) and
`magpie-tts-lan` (50052). Jev, GLM, and VPS model fallback are currently off.

Current ThinkPad model is Llama 3.2 3B Q4_K_M at `192.168.5.10:8080`, alias
`llama3.2:3b`, six CPU threads. Pi reaches it through `127.0.0.1:18080`.
WSL user units are `voice-agent-llama.service` and
`voice-agent-llama-tunnel.service`. Port 8080 is occupied: choose/check a
separate port and tunnel for Laya rather than replacing that service. In
this Codex shell `systemctl --user` could not reach the user bus while 8080
was listening; verify the real user/runtime context before diagnosing an outage.

## Implementation entry points and validation

- `pi/local_vcm.py`: current model decision schema, system instruction,
  single-host processor, tool execution and direct spoken receipts.
- `pi/orchestration.py`: ten `FAST_TOOLS`, `direct_arguments`,
  `validate_arguments`, compound guard, old Jev/two-brain path.
- `pi/bot.py`: pipeline and mode selection.
- `pi/vcm_server_location.py`, `pi/vcm_state.py`, `pi/vcm_state_worker.py`:
  placement and persistence; preserve this split.
- `pi/turn_timing.py`, `pi/stall_diagnostics.py`, `pi/profiled_mcp.py` and
  `scripts/summarize_stall_diagnostics.py`, `scripts/summarize_voice_trial.py`:
  baseline instrumentation and analysis.

Keep Laya resident/preloaded on ThinkPad. Check actual device, cold startup,
warm p50/p95, CPU thread budget, and contention with the existing Llama
service. A fast classifier only removes model latency for tool paths that
can extract/validate arguments without a second full Llama decision call.
Implement an opt-in engine/mode and a clean return to the current baseline.

The current checkpoint passed **57 tests on Pi**. Latest run `afe7b8b933`
had 22 replies: median response **5.468 s**, model **3.517 s**, endpoint
**793 ms**, TTS first byte **1.014 s**, non-HTTP MCP **20.760 ms**, SQLite
commit **2.651 ms**. Llama-server medians were **1.956 s prompt evaluation**
and **1.470 s generation**. Classifier integration should target this cost,
not retune working audio/storage simultaneously.

Required regression cases include hearing checks (previously misrouted to
time), noisy ASR, missing setter values, exact reminder text, colors,
timers/alarms, unsupported-location weather, compounds, abstention, timeouts,
invalid responses, and duplicate/uncertain write outcomes. Music is a catalog
lookup with state bookkeeping; real music playback and timer/alarm delivery
are not implemented. Compare two matched speakerphone passes and capture
classifier, argument extraction, model fallback, MCP, worker, commit, TTS,
and final speech-end-to-response timing separately. Do not claim improvement
from router microbenchmarks alone.
