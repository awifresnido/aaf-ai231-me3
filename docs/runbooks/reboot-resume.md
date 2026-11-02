# Resume the voice agent work after a reboot

Current live selection, 2026-11-02 16:10 Manila: **Nemotron ASR + Jev +
Jetson GPU Llama 3.2 3B / GLM 5.3 fallback + DGX Qwen3 Aiden TTS**,
run **`01993d4520`**. Pipeline ready, greeting first PCM **0.175 s**. The
MacBook TTS trial is complete and deselected. DGX versus Mac median native
reply onset was **3.901 versus 5.478 s**; Mac whole-WAV generation raised
median first audio from **0.171 to 1.725 s**. See the
[comparison](../profiling/jev-llama32-tts-comparison-20261102/comparison.md)
and [Mac trial rollback](jev-nemotron-llama32-mac-tts-trial-20261102.md).

Current live selection, 2026-11-02 15:56 Manila: **Nemotron ASR + Jev +
Jetson GPU Llama 3.2 3B / GLM 5.3 fallback + MacBook Qwen3 Aiden TTS**.
Only TTS changed from run `7373bf308b`. MacBook MLX server is reached on Pi
`127.0.0.1:18099` through two transient SSH forwards. Preflight returned
valid Aiden audio in 2.977 s. Experiment
`jev-nemotron-jetson-llama32-mac-qwen3-aiden-20261102`, corrected active run
**`9c5da96c89`**. Greeting played after **5.618 s** Mac generation, without
an audio-context error. Human trial pending;
see [MacBook trial details and rollback](jev-nemotron-llama32-mac-tts-trial-20261102.md).

Current live selection, 2026-11-02 15:46 Manila: **Nemotron ASR + Jev +
Jetson GPU Llama 3.2 3B / GLM 5.3 fallback + DGX Qwen3 Aiden TTS**.
Jetson Llama at `192.168.5.11:8084`, transient
`voice-agent-llama32-trial.service`; Voxtral stopped. Pi experiment
`jev-nemotron-jetson-llama32-qwen3-aiden-20261102`, run **`7373bf308b`**.
Llama reply/extraction probes
passed at 0.784/1.160 s, GPU activity was observed, and 113 regression tests
passed. MacBook Qwen3 TTS is available as a **dormant switchable option** via
the `mac_qwen` adapter and Pi port 18099 SSH forwards; DGX Aiden remains
selected. See the [trial runbook](jev-nemotron-jetson-llama32-mac-option-20261102.md).

Current live selection, 2026-11-02 15:01 Manila: **Jev + Jetson Voxtral Mini
ASR and small model + Qwen3 Aiden TTS**, run `7a50558fa3`, experiment
`jev-voxtral-jetson-asr-small-qwen3-aiden-20261102`. GLM remains 5.3 Flash.
Voxtral Q4 + Q8 audio projector runs at `192.168.5.11:8083`, transient
`voice-agent-voxtral-native.service`, with the pinned audio-first chat template.
Unused Jetson Laya is stopped to reclaim RAM; both Riva containers and SQLite
are preserved. All 113 regression tests passed. Synthetic ASR took ~2.1 s,
small greeting 0.31 s, extraction hit its 2.5 s deadline and retained fallback.
Live greeting playback succeeded. Human trial: 26 main-window replies,
direct median **4.153 s**, context **5.968 s**, overall **5.156 s**; Voxtral
ASR median **2.263 s**, Jev **0.290 s**, Qwen3 first PCM **0.164 s**. Seven
fast tools, 19 GLM routes, one smalltalk, two Jev timeouts. All 30 ASR HTTP
requests completed, though several transcripts were altered or answer-like.
Jetson RAM p95 **7031/7485 MB**, swap stable, zero model restarts. Resource
capture was stopped. See the [trial analysis](jev-voxtral-trial-20261102.md).
Services/SSH forwards are transient: after reboot follow
the [Voxtral configuration and rollback](jev-voxtral-trial-20261102.md), and
restore the existing DGX TTS forward before restarting the Pi pipeline.

Current live selection, 2026-11-02 12:44 Manila: **Jev + DGX Qwen2-Audio ASR
and small model + Qwen3 Aiden TTS**, run `72afa542c5`, experiment
`jev-qwen2-audio-asr-small-qwen3-aiden-20261102`. GLM remains 5.3 Flash.
DGX port 8000 is forwarded to Pi 18000; TTS 8001 still uses Pi 18001. The
Qwen audio-language model handles transcription and small replies/extraction
in separate calls around Jev. Both active ASR and small-model roles replace
Nemotron/Llama; their endpoints/services are preserved for rollback.
All 105 tests and a real VAD/Qwen-ASR/Jev/fake-tool preflight passed. Small
reply and thermostat extraction worked; color extraction failed validation
and must retain GLM fallback. Live test complete: **27 main-window reply
onsets**, direct median **4.433 s**, context **4.502 s**, overall **4.494 s**.
ASR HTTP median **0.744 s**, speech-end-to-transcript **1.052 s**, Jev
**0.290 s**, Qwen3 first PCM **0.172 s**. ASR forwarded refusals/commentary,
wrappers and answer-like outputs; no audio ground truth was recorded. The
conversational small-model slot had zero calls; its one extraction failed.
One **26.697 s** TTS stall caused a **29.884 s** response. Recommend isolating
Qwen2 as small model while restoring Nemotron for a further test; no setting
was changed during analysis. See
[comparison, configuration and rollback](jev-qwen2-audio-trial-20261102.md).

Current live selection, 2026-11-02 11:54 Manila: user-requested **Jetson CUDA
Laya + DGX Qwen Aiden**, run `016c1ab953`, experiment
`jetson-laya-glm-qwen-aiden-20261102`. Laya endpoint **192.168.5.11:8082** loads
`/home/aldwin/models/laya/laya_v1` with FP16 weights/autocast, exact pinned
questions and external calibration 1.995, gate 0.50/0.05. Jev is deselected;
GLM, Llama, ASR, tools, state and audio configuration are retained.
All 96 tests passed. Eight CPU/CUDA smoke comparisons had no route/gate flips;
server medians **0.711 / 0.093 s**, Pi CUDA wait about **0.10–0.13 s**.
Live test complete: **27 timed replies**, direct median **3.259 s**, context
**3.980 s**, overall **3.448 s**. Laya GPU server median **0.118 s**, Pi wait
**0.132 s**; no classifier timeouts. Only three replies used fast tools;
22 used GLM. Longest waits **15.762 / 27.041 s** were mainly GLM/external API.
Three speech segments lacked final ASR; message follow-up/argument coverage
issues remain. RAM about 5,387/7,485 MB, swap flat 785 MB in 228 samples;
classifier had no restarts. Resource capture stopped after test; classifier
and voice bot remain active. The Jetson classifier is a transient user unit
(not enabled across reboot); see
[results, restart and rollback](jetson-laya-aiden-trial-20261102.md).

Current live selection, 2026-11-02 11:03 Manila: user-requested **Jev + Qwen
Ryan**, run `9576b0bcb6`, experiment `jev-glm-qwen-ryan-20261102`.
Only TTS voice and experiment marker changed from Aiden; Jev/GLM, ASR, tools,
storage and speakerphone configuration are retained. Ryan preflight and live
startup playback passed. Live test complete: **23 replies**, direct median
**2.668 s**, context **4.975 s**, overall **3.188 s**. Fast-tool median
**1.317 s** and GLM-path median **4.419 s** match Aiden closely; more replies
used GLM (15/23 versus 12/23). All 20 Jev classifications completed without
timeout; all 31 human Qwen requests completed without errors, first PCM median
**0.170 s**, maximum **0.362 s**. One segment lacked final ASR. See
[results, capture and rollback](jev-ryan-trial-20261102.md).

Current live selection, 2026-11-02 10:46 Manila: user-requested **Jev + Qwen
Aiden**, run `f0c87b3a33`, experiment `jev-glm-qwen-aiden-20261102`.
Jev 1.14.0 uses its existing 1,200 ms deadline; DGX Qwen streaming TTS stays on
port 8001 via Pi 18001. Only router, voice and experiment marker changed;
GLM, ASR, MCP, storage and speakerphone settings remain as below.
The live test completed: 23 timed replies, direct median **1.477 s**, context
median **4.960 s**, overall **2.559 s**. Successful Jev client wait median
**0.283 s**; Qwen first PCM **0.165 s** across 30 completed human requests.
Two Jev timeouts, two missing-ASR segments, one interrupted spoken reply and
a **3.719 s** Qwen first-PCM stall remain. Context follow-up correctness needs
work (message body became a greeting). See
[results, capture and rollback](jev-aiden-trial-20261102.md).

Latest live selection, 2026-11-02: **DGX Qwen streaming TTS** (port 8001,
CustomVoice/Vivian), retaining Jetson Nemotron ASR and ThinkPad Laya + GLM.
Run `147f31abef`, experiment `laya-glm-qwen-dgx-20261102`; 92 tests passed.
The end-to-end test is complete: 30 native timed replies, direct median
**3.809 s**, context median **4.668 s**; 28 have same-turn playback timing.
Qwen first PCM median **0.163 s** across 41 successful human requests;
one **11.371 s** first-PCM stall and one failed follow-up request occurred.
Laya successful server classification median **0.748 s**, with one timeout,
one HTTP-status failure and two cancellations. The user reported varied voice
quality despite fixed Vivian selection; acoustic cause is not established.
See [results, capture and rollback](qwen-tts-trial-20261102.md).
Pi ports 18001 (DGX TTS) and 18082 (Laya) currently depend on a temporary
ThinkPad SSH reverse tunnel; verify both after reboot. New changes are
uncommitted on top of `e020464`.

Latest completed work: [Laya direct/contextual benchmark](laya-glm-results-20261101.md),
run `26c376b1c3`. Twenty classifications completed without timeout; Laya server
p50 **0.704 s**, Pi wait p50 **0.723 s**. End-to-end medians: direct **4.807 s**,
context **6.131 s**, with two missing-ASR segments and one interrupted fragment.
Guard phrasing/spacing coverage and pending affirmative follow-ups need fixes;
the Manila time request was misheard and answered as weather (user confirmed).
The [Jetson capacity check](jetson-laya-capacity-20261101.md) found inadequate
headroom for the stock FP32-parameter loader beside speech services. Laya
remains on ThinkPad CPU; no Jetson Laya installation or CUDA inference occurred.
The user requested committing progress on `laya-integration`.

Latest selection, 2026-11-01 22:47: user-requested **Laya + GLM** contextual
test, run `26c376b1c3`, `ROUTER_MODEL=laya` within `two_brain_plusjev`.
Jev is disabled; GLM remains enabled. Eighty-four tests passed. Pi MCP, Jetson
storage and speakerphone settings are preserved. Laya client/server inference
and end-to-end voice timings are recorded separately. See the
[active trial, capture and rollback](laya-glm-live-trial-20261101.md).
The following Jev + GLM selection describes the preceding comparison.

Latest live selection (2026-11-01 22:05 Asia/Manila): the user requested
Jev + GLM reactivation on `laya-integration`. Run `2a664e268a` selects
`ORCHESTRATION_MODE=two_brain_plusjev`, Jev 1.14.0 and GLM 5.3 Flash;
VPS small-model fallback is explicitly off. Pi MCP, Jetson storage and
speakerphone settings are preserved. The completed [live results](jev-glm-live-results-20261101.md)
measured median 4.761 s over 14 replies, but five speech segments lacked final
ASR and the user confirmed needing to repeat commands. Prioritize that upstream
audio/ASR failure, then GLM completion tails and weather API failure.
The later [contextual tool test](jev-glm-context-results-20261101.md), turns
21–35, shows sensible GLM tool inference and a multi-turn thermostat decision,
but three cloud waits were interrupted by repetition and two Jev calls timed
out. Combined timed replies: 25, median 5.093 s; silent waits are not included.
See [activation, capture and rollback](jev-glm-live-trial-20261101.md).
The Llama-only configuration described below is the preceding baseline.

Next-session context for the local fine-tuned decision router is in
[Laya integration handoff](laya-integration-handoff-20261101.md). Configuration
checkpoint `dda6ddc` has been pushed to GitHub on `two-brain-plusjev`.

Current experiment (2026-11-01):
[Pi-hosted VCM MCP with Jetson/NVMe persistence](pi-mcp-jetson-state-trial-20261101.md).
`VCM_TOOL_SERVER_HOST=pi` and `VCM_STATE_BACKEND=jetson_sqlite` keep every
MCP server on Pi; only a non-MCP SQLite worker runs on Jetson. This is now
the default Pi-option behavior. Current run `afe7b8b933`, experiment
`vcm-pi-mcp-nvme-worker-20261101`, has completed two voice passes; see
[the results](pi-mcp-worker-results-20261101.md).
The current state file is the same NVMe trial file used previously; all
existing rows were preserved and the original Pi database was unchanged.
Fifty-seven tests passed. Actual split preflights measured median complete
MCP calls of 25.044 ms and SQLite commit spans of 2.192 ms. The live voice
test measured median response 5.468 s over 22 replies, median commits
2.651 ms, and non-HTTP MCP calls 20.760 ms. This retains the storage benefit;
model time was 3.517 s and external APIs explain the longest replies.

The model remains ThinkPad-only Llama 3.2 3B; Jev, VPS fallback, and GLM are
disabled. VAD is 0.3 s, Smart Turn uses two threads, and queued logging/RAM
tracing are enabled. Confirm `VCM_TOOL_SERVER_HOST`, `VCM_STATE_BACKEND`,
`ORCHESTRATION_MODE`, `LOCAL_VCM_MODEL_HOST`, `VOICE_DIAGNOSTICS`, and
`VOICE_QUEUED_LOGGING` before using older instructions below.

The preceding [full-VCM-on-Jetson two-test results](vcm-nvme-results-20261101.md)
for run `625b1e52a7` measured median response 5.185 s (25 replies), versus
the Pi-local storage run's 6.931 s, and commit median 2.456 ms. The model
then dominated at 3.355 s: prompt evaluation 1.846 s and generation 1.352 s.
Startup self-hearing, validation failures, and compound partial actions
remain. Switching MCP host now retains NVMe state by default; selecting
`local_sqlite` explicitly uses the separate original Pi state history.
The preceding diagnosis is in
[Pi/MCP profiling results](thinkpad-mcp-profile-results-20261101.md).
The preceding controlled tests are in
[SQLite storage diagnosis](sqlite-storage-diagnosis-20261101.md): a temporary
MCP database reproduced a 3.10 s journal fdatasync, with separate raw-file
flush spikes and positive reader-lock controls. Live data/settings stayed
unchanged. New harnesses/results follow checkpoint `81cbbb8` locally.
The [DELETE/FULL versus WAL/FULL comparison](sqlite-wal-comparison-20261101.md)
found that reusable WAL reduces median commit time but retains 1.1–1.8 s
flush stalls. Fresh WAL also incurred slow shared-memory file creation;
DELETE had slow tiny journal writes. The
[storage activity diagnosis](storage-activity-diagnosis-20261101.md)
correlates tiny-write stalls with ext4 journal waits and unfinished USB
commands, despite little dirty memory. The same untraced probe measured
median commits of 792.73 ms on Pi USB versus 2.43 ms on Jetson NVMe,
motivating the subsequent full-server trial and current persistence split.
Prior comparisons are recorded in
[VPS results](vps-vcm-results-20261101.md),
[ThinkPad results](local-vcm-results-20261101.md), and
[Pre-refactor retest](pre-refactor-retest-20261101.md).

The workspace branch is `two-brain-plusjev` in
`awifresnido/aaf-ai231-me3`. Configuration checkpoint `dda6ddc`,
`feat(pi): keep MCP on Pi with Jetson SQLite persistence`, is published
there. A following documentation commit adds the Laya handoff. The configuration commit includes
the implementation, 57-test validation, storage investigations, two voice
comparisons, and resumption instructions. Private keys, environment files,
and live databases remain outside Git; the runbooks record the selected
non-secret settings and data locations.
Reopen this conversation and say: “Resume from `two-brain-plusjev`; inspect
the Pi-MCP/Jetson-storage trial and analyze the matching Pi/MCP/state-worker
traces.” The previous Pi-local storage voice tests are assessed in
[Queued logging results](queued-logging-results-20261101.md). The earlier
echo-feedback work remains in `vad-03-threads2-results-20261101.md` and
`aec-trial-results-20261101.md`.

## Restore the workspace

Open the ThinkPad's WSL distribution, then run:

```bash
cd /home/aldlinux/ai/voice-agent-cluster/aaf-ai231-me3
git switch two-brain-plusjev
git status --short
git log -5 --oneline
```

The GitHub token was used for a one-time push and was not stored. If a future
push asks for credentials, use the configured secure credential manager or
provide a fresh token for that push.

## Check the cluster

On the ThinkPad WSL shell, the user services start when the distribution is
running because user lingering is enabled:

```bash
systemctl --user is-active voice-agent-llama.service voice-agent-llama-tunnel.service
curl --noproxy '*' -fsS http://192.168.5.10:8080/health
```

From WSL, check the Pi:

```bash
ssh -i /home/aldlinux/.ssh/id_ed25519_pihost -o UserKnownHostsFile=/home/aldlinux/.ssh/known_hosts_pihost aldwinrpi4@192.168.5.12 \
  'systemctl --user is-active me3-local-audio.service voice-agent-vps-model-tunnel.service; pactl info | grep -E "Default Sink|Default Source"; amixer -c JV801P sget PCM | tail -2'
```

Expected audio devices are the JOUNIVO JV801P for both PulseAudio source and
sink, with PCM at 100%. The local service uses `pacat` playback. It is enabled
at boot and has no idle timeout; the WebRTC service is disabled and conflicts
with it.

The local bot's own streams now use `voice_agent_aec_source` and
`voice_agent_aec_sink`, a paired WebRTC echo canceller over the JV801P.
`ensure_echo_cancel.py` loads/verifies the pair in the unit's startup steps.
Check `pactl list source-outputs short` and `pactl list sink-inputs short` as
well as hardware defaults: the recording and playback streams must use the
virtual pair for echo cancellation to work. Current endpointing settings are
0.3 s VAD stop silence and two Smart Turn inference threads.

On the Jetson, Docker starts at boot and both containers use `unless-stopped`:

```bash
ssh -i /home/aldlinux/.ssh/id_ed25519_pihost -o UserKnownHostsFile=/home/aldlinux/.ssh/known_hosts_pihost aldwin@192.168.5.11 \
  'docker ps --format "{{.Names}} {{.Status}}"; ss -ltn | grep -E ":5005[12]"'
```

The VPS `llama-server.service` is enabled and binds only to loopback. The Pi's
enabled SSH tunnel exposes it to the bot at `127.0.0.1:18081`; the ThinkPad
model tunnel is `127.0.0.1:18080`. The API key files remain on the hosts with
mode 600 and are not in Git.

## Resume tuning

The latest deployed Pi files should match the branch files. Compare them with
`sha256sum pi/bot.py pi/orchestration.py` in WSL and the same command in
`/home/aldwinrpi4/voice-agent` on the Pi before making the next live change.
The branch has unit coverage for routing and argument validation. The Pi's
local bot logs to `me3-local-audio.log`.

Work next on the issues measured in the latest reports:

1. Keep the assessed Pi-MCP/Jetson-storage checkpoint; its three-component
   traces are saved locally. Next isolate ThinkPad prompt/history/cache
   and generation costs with a fixed command sequence. The hearing-check
   question was misrouted to time, and two decisions failed validation;
   strengthen intent/argument correctness alongside latency tuning. Address
   startup self-hearing and compound actions separately. Keep DELETE/FULL and preserve the
   separate original Pi database until an explicit state handover is chosen.
   Earlier voice commits reached 14.714 s.
2. Retain queued logging and the independent RAM traces. Logging caller
   stalls fell from 1.807 s to at most 10.963 ms, with no sampled loop lag
   above 50 ms in the two queued tests.
3. Strengthen intent/argument grounding: garbled speech triggered an
   unintended thermostat value, and compound requests can execute partially.
4. Investigate Smart Turn's roughly three-second silence tails and preserve
   interrupted-turn execution receipts before larger routing changes.
5. Keep Jev optional/off for this checkpoint. The full small/large-worker
   ownership refactor remains a design; do not restore automatic timeout
   escalation while measuring the local path.

The routing and current configuration commits are published on the branch.
Main voice logs and private environment
remain on the Pi. Saved metadata traces from both profiling trials are in
`docs/profiling/`, so those captures survive Pi reboot even though live
`/dev/shm` traces do not.

After the 2026-11-01 reboot, the ThinkPad model/tunnel services, Pi speakerphone
and model tunnel, Jetson Docker services, and VPS model service all returned.
The first Pi process then exited cleanly at Pipecat's five-minute idle limit.
The current branch disables that timeout for `TRANSPORT_MODE=local`, and the
speakerphone service has been restarted with the fix. The local bot should now
remain active while idle; systemd still restarts it after a process failure.
