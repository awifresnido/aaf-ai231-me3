# VPS-only VCM comparison trial

The completed speakerphone trial is assessed in
[VPS results](vps-vcm-results-20261101.md): native median 9.442 s versus
ThinkPad 6.368 s, with slower model calls and persistent Pi/tool stalls.
The subsequent [ThinkPad profiling trial](thinkpad-mcp-profile-20261101.md)
returns to ThinkPad and adds Pi/MCP diagnostics. Check current configuration
before treating this earlier trial as active.

Requested 2026-11-01 after the ThinkPad-only voice test. The bot retains
`ORCHESTRATION_MODE=local_vcm`, with explicit `LOCAL_VCM_MODEL_HOST=vps`.
The module/mode name is retained for compatibility; inference is remote on
the VPS in this trial. There is exactly one model endpoint and no fallback.

## What changes

Pi → existing authenticated SSH tunnel at `http://127.0.0.1:18081` → VPS
`llama-server.service`, model alias `llama3.2-3b`, loopback port 8010.
The API key is read from the existing private
`SMALL_LLM_SECONDARY_API_KEY_FILE`; it is not copied into Git or logs.
The client selects the previously secondary endpoint directly. ThinkPad,
Jev, and GLM are not used, even if the VPS is unavailable or times out.

`LOCAL_VCM_MODEL_HOST=thinkpad` restores selection of the configured primary
ThinkPad endpoint. Unknown host selectors fail startup rather than silently
choosing a host. Model events now identify `model_host`; configuration also
records `vcm_model_host`.

## Comparison controls

The deployment checks that the Voice of Pi greeting, instruction, structured
decision schema, model `decide()` method, and processor `process_frame()`
method match the actual preceding ThinkPad deployment. Its VCM tools,
validation behavior, six-message context window, token budget, and direct
spoken tool receipts remain the same. The only behavior change is explicit
model host selection, with additional host metadata in logs.

Settings retained: model deadline 12 s, MCP deadline 20 s, VAD silence 0.3 s,
Smart Turn two threads, paired JV801P echo cancellation, PCM 100%, pacat
target buffer 150 ms, and Jetson Nemotron/Magpie speech services.
Experiment label: `vcm-vps-only-nojev-20261101`.

The VPS runs Llama-3.2-3B-Instruct-Q4_K_M.gguf with two CPU threads, context
4096, and one parallel slot on a two-vCPU host. ThinkPad uses its existing
six-thread service. This compares the deployed hosts/services and network
paths, not two different model architectures or identical hardware. No model
service thread/context settings were changed for this trial.

Known issues from the ThinkPad test—startup greeting echo, split turns,
variable local MCP waits, music misclassification, and compound handling—
are preserved as comparison limits. Weather/music still contact external
APIs. Media commands remain catalog/state operations, not physical playback.

## Preflight

All 31 regression checks passed, including VPS authentication/model alias,
single-endpoint selection, and failure without ThinkPad fallback.

The first VPS request with the full prompt exceeded the 12 s deadline; the
VPS journal confirms cancellation. A subsequent complete run of the same
fourteen model-only probes passed all decisions, with median 2.013 s and
range 1.553–3.277 s. These were single-utterance requests after the prompt
prefix had been processed, with no real tools or spoken audio. Preserve the
initial timeout as part of the evidence; warm timing does not characterize
cold prompt processing or a growing voice conversation.

The ThinkPad's final preflight had a first new-prefix request of 6.856 s,
then thirteen model-only requests with median 2.159 s. These short runs do
not establish a significant host advantage. The ThinkPad live voice trial
had median 6.368 s over sixteen native latency records, and successful
model decisions excluding greeting echo had median 2.874 s. Compare the
next voice test per command and per stage, including failures.

## User test

Use the Pi speakerphone with the same commands and wait for each response:

1. “What time is it now?”
2. “Turn on the lights.”
3. “Set the lights to green.”
4. “Set the room temperature to twenty-seven degrees.”
5. “What is the weather today?”
6. “Remind me to study.”
7. “List my reminders.”
8. “Turn off the lights.”

Optional: repeat a timer, alarm, music, or compound request to compare
correctness as well as timing. Reminder and device commands retain their
normal state effects. Single commands provide the cleanest latency rows.
Afterward say “done” in the conversation for log analysis.

## Logs, persistence, rollback

The persistent Pi service remains `me3-local-audio.service`. Log:
`/home/aldwinrpi4/voice-agent/me3-local-audio.log`. The VPS model journal is
UTC; convert to Asia/Manila when aligning it with the Pi. Compare request
duration separately from server compute duration and local MCP/output waits.

The prior ThinkPad metadata remains at
`/home/aldwinrpi4/voice-agent/local-vcm-trial.json`. New trial metadata at
`/home/aldwinrpi4/voice-agent/vps-vcm-trial.json` identifies the start/log
offset, unchanged-contract check, and backups. Backups use suffix
`.bak-vps-vcm-TIMESTAMP` for the private environment, `bot.py`, and
`local_vcm.py`.

Deployment verified at 14:58 Asia/Manila: run `fc95bf51f3`, VPS host in
configuration, ten VCM tools, pipeline ready, and Voice of Pi greeting at
software playback. Backups use `.bak-vps-vcm-20261101-145822`; the new log
offset is 2,446,064 bytes. Live Python hashes match the workspace files.

To return to ThinkPad with the compatible code, set
`LOCAL_VCM_MODEL_HOST=thinkpad` and
`VAD_EXPERIMENT=local-vcm-thinkpad-nojev-20261101` in the private environment,
then restart the same service. To restore the exact previous deployment,
restore its files/environment from the backups listed in VPS trial metadata,
then restart. Never print the private environment or API key contents.
The selected host persists across reboot; an unavailable VPS produces a
local failure reply rather than a model handoff.

Related: [ThinkPad results](local-vcm-results-20261101.md),
[ThinkPad setup](local-vcm-trial-20261101.md).
