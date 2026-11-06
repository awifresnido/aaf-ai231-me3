# ThinkPad-only VCM trial

The subsequent [VPS-only comparison](vps-vcm-trial-20261101.md) explicitly
selects the other host while retaining this trial's controller and prompt.
Check `LOCAL_VCM_MODEL_HOST` and the experiment label for the active trial;
this document describes the preceding ThinkPad test.

The first speakerphone test is assessed in
[Local VCM results](local-vcm-results-20261101.md). Native median delay was
6.368 s; fourteen replies with stable timing references had median 5.940 s.
The test exposed local tool waits, startup greeting echo, and interrupted
turns; text-probe success did not establish live reliability.

Requested 2026-11-01 after the 14:08–14:13 pre-refactor retest. This is an
isolated comparison mode, `ORCHESTRATION_MODE=local_vcm`, on the existing
`two-brain-plusjev` branch. It does not implement the full two-brain ownership
refactor. This trial is preserved in the branch's local checkpoint alongside
the later VPS and queued-logging comparisons.

## Active path

JV801P microphone → Pi echo cancellation / Silero VAD → Jetson Nemotron ASR →
Pi Smart Turn → ThinkPad Llama 3.2 3B structured decision → validated Pi MCP
tool → spoken tool receipt → Jetson Magpie TTS → JV801P speaker.

Jev and the cloud LLM are not instantiated on this mode's pipeline. The small
client contains exactly one endpoint: the configured ThinkPad primary at
Pi loopback `http://127.0.0.1:18080`, through the existing SSH tunnel to
`192.168.5.10:8080`, model alias `llama3.2:3b`. The configured VPS endpoint
is ignored. Unavailable/invalid local decisions produce a short local error
response, with no model fallback. The other services may remain running but
are not used by this trial.

“Local” describes speech and model processing on this LAN. Weather and music
tools retain their external API dependencies; music still searches/records
catalog metadata rather than operating a real player. Playback commands
record state only. The trial's spoken media receipts disclose this limitation.

Every ordinary user request goes to the ThinkPad model; there is no
deterministic routing shortcut. The model selects a tool and its arguments
in one schema-constrained response. Runtime validation checks the tool
allowlist, argument ranges and agreement with explicitly parsed arguments.
Those checks do not replace the model request. Supported tool results are
spoken directly without a second model call. A text-only reply allows help,
small talk, missing-argument questions, or an unsupported-request response.

The ten VCM tools are `get_time`, `get_weather`, `list_reminders`,
`add_reminder`, `set_thermostat`, `control_lights`, `set_timer`, `set_alarm`,
`playback_control`, and `play_music`. Radio is absent; messaging, email, and
calls are excluded. Weather is current/default-location only. Use one command
at a time; mixed plans are outside this trial. Timers/alarms/reminders retain
the existing MCP tool behavior; this trial does not add scheduling delivery.

## Identity and conversation

Greeting: “Hello, I'm the Voice of Pi. I can help with time, weather,
reminders, timers, alarms, lights, temperature, and music commands. What can
I do for you?”

The model instruction identifies Voice of Pi as a voice agent, enumerates
its tool contracts and limitations, and requests short spoken replies. Up to
six recent user/assistant messages are included, bounded to 600 characters
each. Tool receipts enter context so an action does not exist only as an
unverified model claim. This is bounded context, not the durable receipt
ledger proposed for the later refactor. Do not assume interruption-safe
exactly-once execution across repeated user requests.

## Fixed settings and measurements

Keep VAD stop silence at **0.3 s**, Smart Turn at **two threads**, paired
WebRTC echo cancellation, PCM 100%, and pacat target latency 150 ms.
Label: `local-vcm-thinkpad-nojev-20261101`.

The outer model deadline is 12 s for this trial; it is not the old pair of
2.5 s endpoint waits. Tool waiting is limited to 20 s. No automatic action
retry follows a tool timeout or invalid receipt, since its outcome may be
uncertain. The existing private cloud/Jev/VPS settings are retained for
rollback but are unused in `local_vcm` mode.

Timing events include `configuration`, `local_decision` with `model_s`,
`route_local_tool` with tool, model/MCP/total seconds, `route_local_reply`,
and `route_local_failure`. Existing endpoint and first-playback measurements
remain enabled. Log: `/home/aldwinrpi4/voice-agent/me3-local-audio.log`.

The request adapter now uses llama.cpp's supported OpenAI-compatible schema
format: `response_format.json_schema.schema`. Local server source at
`tools/server/server-common.cpp:1384` confirmed that the older sibling
`response_format.schema` is ignored for type `json_schema`. Initial probes
caught invalid light arguments; the corrected request enforces the schema,
and runtime validation remains necessary for semantic errors. Real probes
also informed explicit light/media examples in the instruction. This means
the trial compares a changed controller/prompt as well as removal of Jev;
it is not a controlled estimate of Jev's isolated latency contribution.

Fresh instruction-prefix probes before the final prompt took 7–11 s;
subsequent requests were much shorter. Report first-prefix and warm/context
requests separately. Text probes exercise model decisions only, excluding
speech, actual tool execution, and playback; do not label them end-to-end
voice latency.

## Validation and user test

`tests/test_local_vcm.py` checks primary-only isolation, conversation
forwarding, unavailable models, invalid/out-of-scope arguments, tool failure,
semantic conflicts, and no second model call for a result. Existing
orchestration/timing tests also run in the Pi's installed environment.
`scripts/probe_local_vcm.py` sends real ThinkPad requests for all ten tool
types plus light variants and unsupported requests, without executing tools.

Deployment verified at 14:38 Asia/Manila: service active, pipeline ready,
exactly ten advertised tools, and the new greeting reached software playback.
Run ID: `666312d1d8`. Backups use suffix
`.bak-local-vcm-20261101-143734`; metadata records log offset 2,290,699 bytes.
All 28 regression tests and all 14 final real model probes passed. The final
probe's first instruction-prefix request took 6.856 s; the remaining thirteen
model-only requests had median 2.159 s, range 1.800–3.101 s. These are
single-sample text probes for each request, not voice latency percentiles.

For the speakerphone trial, use the same sequence as the earlier test:

1. “What time is it now?”
2. “Turn on the lights.”
3. “Set the lights to blue.”
4. “Set the room temperature to twenty-eight degrees.”
5. “What is the weather today?”
6. “Remind me to study.” Then “List my reminders.”
7. “Set a five-minute timer.”
8. “Set an alarm for nine PM.”

Wait for each result and note unexpected behavior. These commands retain
their normal state effects. Optional media commands test routing/search and
receipt latency, not actual music playback. Say “done” in the conversation
afterward so the session's speech-end, model, tool, TTS, and playback delays
can be compared with `pre-refactor-retest-20261101.md`.

## Deployment and rollback

Stage and validate before restarting `me3-local-audio.service`. Back up the
live `bot.py`, `orchestration.py`, any existing `local_vcm.py`, and the private
environment under suffix `.bak-local-vcm-TIMESTAMP`, retaining file modes.
The deployment writes nonsecret paths and prior trial settings to
`/home/aldwinrpi4/voice-agent/local-vcm-trial.json` for resumption/rollback.

To restore the previous trial, restore the saved private environment and
Python backups listed in that metadata, then restart the same user service.
Alternatively keep the compatible new code and restore
`ORCHESTRATION_MODE=two_brain_plusjev` and the previous
`VAD_EXPERIMENT=vad-0.3-threads-2-aec-20261101`, then restart. Do not print or
copy the private environment contents into Git or this conversation.

The selected mode persists through Pi reboot. When ThinkPad WSL/model/tunnel
is offline, local decisions fail rather than moving to the VPS or GLM. Resume
using this runbook and inspect the actual active mode before tuning further.
