# Resume the voice agent work after a reboot

The project is on GitHub branch `two-brain-plusjev` in
`awifresnido/aaf-ai231-me3`. Reopen this conversation and say: “Resume from
`two-brain-plusjev`; continue the two-brain routing and latency work.” The
active experiment and echo-feedback repair are documented in
`docs/runbooks/vad-03-threads2-results-20261101.md`.
The latest user test is assessed in `docs/runbooks/aec-trial-results-20261101.md`.
Current findings and the tuning queue are in
`docs/runbooks/live-latency-20261101.md`, with the earlier baseline in
`docs/runbooks/live-latency-20261031.md`.

## Restore the workspace

Open the ThinkPad's WSL distribution, then run:

```bash
cd /home/aldlinux/ai/voice-agent-cluster/aaf-ai231-me3
git switch two-brain-plusjev
git pull --ff-only
git status --short
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

Work next on the issues measured in the live report:

1. Collect another set of spoken turns through the JV801P and compare fast
   routes with GLM routes.
2. Reduce the variable MCP wait on local state calls and record Jev, Llama,
   MCP, and Magpie stages separately.
3. Fix duplicate late ASR finals that can interrupt a fast answer and cause a
   second GLM request.
4. Review Jev decisions for reminders, alarms, playback controls, current
   weather, and lights; keep multi-action requests on GLM.
5. Investigate long GLM tails and Jev timeouts without changing the GLM
   fallback for complex requests.

The router changes in this branch have been committed and pushed. The live
latency assessment is in `docs/runbooks/live-latency-20261031.md`.

After the 2026-11-01 reboot, the ThinkPad model/tunnel services, Pi speakerphone
and model tunnel, Jetson Docker services, and VPS model service all returned.
The first Pi process then exited cleanly at Pipecat's five-minute idle limit.
The current branch disables that timeout for `TRANSPORT_MODE=local`, and the
speakerphone service has been restarted with the fix. The local bot should now
remain active while idle; systemd still restarts it after a process failure.
