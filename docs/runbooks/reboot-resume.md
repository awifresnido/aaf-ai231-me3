# Resume the voice agent work after a reboot

Latest requested experiment (2026-11-01): ThinkPad-only VCM with queued
logging and Pi/MCP tracing; Jev, VPS fallback, and GLM disabled. See
[Queued logging trial](queued-logging-trial-20261101.md) for the test,
end-to-end latency comparison, RAM traces, and rollback. Confirm
`ORCHESTRATION_MODE`, `LOCAL_VCM_MODEL_HOST`, `VOICE_DIAGNOSTICS`, and
`VOICE_QUEUED_LOGGING` before using older setup instructions below.
The preceding diagnosis is in
[Pi/MCP profiling results](thinkpad-mcp-profile-results-20261101.md).
Prior comparisons are recorded in
[VPS results](vps-vcm-results-20261101.md),
[ThinkPad results](local-vcm-results-20261101.md), and
[Pre-refactor retest](pre-refactor-retest-20261101.md).

The workspace branch is `two-brain-plusjev` in
`awifresnido/aaf-ai231-me3`. The latest checkpoint is committed locally;
publication to GitHub is a separate step, so the remote may be behind.
Reopen this conversation and say: “Resume from `two-brain-plusjev`; inspect
the ThinkPad-only queued-logging checkpoint and continue SQLite latency
profiling.” The latest two voice tests are assessed in
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

1. Isolate SQLite durability-flush versus commit-lock waits. Eleven of
   thirteen writes in the queued tests spent over one second in commit,
   reaching 14.714 s. Keep current durability while diagnosing.
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
