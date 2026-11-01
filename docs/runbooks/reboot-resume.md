# Resume the voice agent work after a reboot

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
`awifresnido/aaf-ai231-me3`. The latest checkpoint is committed locally;
publication to GitHub is a separate step, so the remote may be behind.
Identify the current configuration with `git log -1`: its subject is
`feat(pi): keep MCP on Pi with Jetson SQLite persistence`. The commit includes
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

The original routing commits were pushed earlier; newer checkpoint commits
are local until explicitly pushed. Main voice logs and private environment
remain on the Pi. Saved metadata traces from both profiling trials are in
`docs/profiling/`, so those captures survive Pi reboot even though live
`/dev/shm` traces do not.

After the 2026-11-01 reboot, the ThinkPad model/tunnel services, Pi speakerphone
and model tunnel, Jetson Docker services, and VPS model service all returned.
The first Pi process then exited cleanly at Pipecat's five-minute idle limit.
The current branch disables that timeout for `TRANSPORT_MODE=local`, and the
speakerphone service has been restarted with the fix. The local bot should now
remain active while idle; systemd still restarts it after a process failure.
