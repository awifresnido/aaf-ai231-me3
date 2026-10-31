# Two-brain-plus-Jev pilot runbook

This branch adds an opt-in fast path before the existing GLM service. The
default `ORCHESTRATION_MODE=single` retains current behavior. The initial
fast path covers time, reminder listing, thermostat, lights and timers.
Confident short conversation also goes to Llama. Other commands pass to GLM.
Jev selects a route; deterministic parsing or Llama 3.2 3B extracts arguments;
the existing MCP server executes the tool;
its `spoken` result goes directly to Magpie TTS.

## Deployed setup

1. The ThinkPad's model lives at the GGUF path in
   `deploy/thinkpad/voice-agent-llama.service`. Its user service is enabled
   and serves `llama3.2:3b` on `192.168.5.10:8080`. The Pi could not reach
   that listener directly, so `voice-agent-llama-tunnel.service` holds an SSH
   reverse forward to Pi loopback port 18080. Both services are enabled on
   the ThinkPad; verify them after a reboot. No Pi systemd dependency can
   guarantee that WSL is online. The GLM path handles missing model service.
2. The VPS `llama-server.service` is enabled and runs the GGUF model as
   `llama3.2-3b` on `127.0.0.1:8010`. It requires the root-owned API key at
   `/etc/voice-agent/llama-api-key` (mode 600). The Pi's enabled user service
   `voice-agent-vps-model-tunnel.service` forwards `127.0.0.1:18081` through
   SSH; Pi user lingering is enabled. Its dedicated SSH key has a forced
   failing command and can only forward to VPS loopback port 8010. The
   matching API key is stored on the Pi at
   `~/.config/voice-agent/vps-model-api-key` (mode 600). Neither key belongs
   in Git or the bot's environment variable values.
3. `TYPESAFE_API_KEY` and the routing settings are in the Pi's existing
   private environment file (`~/.voice-agent-env`, mode 600). The supplied
   credential has not been written to the repository.
4. The adapter supports llama.cpp's OpenAI-compatible
   `/v1/chat/completions` and Ollama's `/api/chat`. Confirm the actual server
   before selecting a protocol. llama.cpp reports readiness at `/health`
   and the loaded model at `/v1/models`.

Active Pi environment settings (the key value is omitted):

```text
ORCHESTRATION_MODE=two_brain_plusjev
TYPESAFE_API_KEY=<private value>
JEV_MODEL=jev-1.14.0
JEV_DEADLINE_MS=1200
SMALL_LLM_MODEL=llama3.2:3b
SMALL_LLM_PRIMARY_URL=http://127.0.0.1:18080
SMALL_LLM_PRIMARY_PROTOCOL=openai
SMALL_LLM_PRIMARY_MODEL=llama3.2:3b
SMALL_LLM_SECONDARY_URL=http://127.0.0.1:18081
SMALL_LLM_SECONDARY_PROTOCOL=openai
SMALL_LLM_SECONDARY_MODEL=llama3.2-3b
SMALL_LLM_SECONDARY_API_KEY_FILE=/home/aldwinrpi4/.config/voice-agent/vps-model-api-key
SMALL_LLM_DEADLINE_MS=2500
```

The second small-model host is tried after a transport failure. The GLM
route retains `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, and `OLLAMA_API_KEY` for now;
the Pi's current private environment points them at OpenRouter and
`z-ai/glm-5.3-flash`.

The Pi project at `/home/aldwinrpi4/voice-agent` has the branch's `bot.py`
and `orchestration.py`. Its previous `bot.py` is backed up as
`bot.py.bak-two-brain-20261031-220845`. The WebRTC bot is managed by
`voice-agent-two-brain-webrtc.service` on port 7860, with logs in
`two-brain-webrtc.log`. It is currently stopped and disabled at boot.
`me3-local-audio.service` is enabled and active, using the JV801P speakerphone
with PCM set to 100%. Its log is `me3-local-audio.log`. The two services
conflict so only one runs at a time. Both load the same private routing
settings. The handoff bot on port 7861 is independent.

When the WebRTC service is active, open its console from the ThinkPad's Windows browser at
`http://localhost:7860/client/` (or `http://127.0.0.1:7860/client/`). The
Windows localhost endpoint was verified to reach this bot. The Pi's plain
HTTP LAN URL is an insecure browser origin, which can suppress microphone
access and show “WebRTC not supported or suppressed.”

Service verification on the ThinkPad:

```bash
systemctl --user status voice-agent-llama.service voice-agent-llama-tunnel.service
curl --noproxy '*' -fsS http://192.168.5.10:8080/health
```

From the Pi, use `curl --noproxy '*' -fsS http://127.0.0.1:18080/health`.
For the VPS fallback, use `systemctl --user status
voice-agent-vps-model-tunnel.service` on the Pi and `curl --noproxy '*' -fsS
http://127.0.0.1:18081/health`. On the VPS, check `systemctl status
llama-server.service` and `ss -ltnp 'sport = :8010'`. The listener must show
`127.0.0.1:8010`. The first cold start took about 34 seconds and `/health`
returned 503 until ready; a subsequent systemd restart was ready in 5
seconds. On 2026-10-31, Pi completion requests
without a key returned 401, while an authenticated request returned 200 and
the model replied `OK`. The branch's `SmallModelClient` also fell back from
an unavailable primary endpoint and received `OK` through the authenticated
tunnel. A public port 8010 probe timed out.
Observed on 2026-10-31: health was `ok`; Pi inference through the tunnel took
1.27 seconds for a short response, and a validated thermostat extraction
took about 2–3 seconds including Python startup. The Pi reached the VPS
health endpoint in 135 ms; one first inference took 7.9 seconds, while later
small inferences took about 1.2 seconds. These are probes, not latency
percentiles. The CPU-only ThinkPad model service uses about 3.6 GiB of RAM.

## Draft test matrix

| Utterance | Expected route and result |
|---|---|
| “What time is it?” | Jev -> `get_time` -> direct spoken result |
| “Hello” | Jev -> Llama short reply -> TTS |
| “Set the lights green” | Jev -> validated `control_lights` -> direct result |
| “Set temperature to 26 degrees” | Jev -> validated `set_thermostat` -> direct result |
| “Set temperature to 35 degrees” | No fast execution; GLM handles rejection |
| “Set a five minute timer” | Jev -> `set_timer(300)` -> direct result |
| “Set the lights to red and a timer” | GLM; no duplicate fast action |
| “What is the maximum thermostat setting?” | GLM; expected answer 32 C |
| Ambiguous/noisy location | GLM or clarification, no invented coordinates |
| Correction while bot speaks | Stale response is discarded by Pipecat interruption path |
| Jev timeout/low confidence | Original context goes to GLM |
| Llama malformed arguments | Original context goes to GLM |
| MCP result cannot be decoded | Speak uncertain outcome; do not repeat a possible action |

Unit checks are in `tests/test_orchestration.py`. Run in the Pi's existing
Pipecat environment or another environment with Pipecat 1.13 and `httpx`:

```bash
python -m unittest discover -s tests -v
```

On 2026-10-31, Jev 1.14.0 classified time, greeting, and a complex question
correctly from the Pi. A real Jev-plus-MCP `get_time` route took 0.54 seconds
and a real Jev-plus-ThinkPad-Llama greeting took 0.74 seconds in direct router
probes. The isolated and live WebRTC bots accepted an audio connection. An
automated WebRTC speech probe then played “What time is it?” into the live
bot: Nemotron transcribed it, Jev chose `get_time`, the MCP tool returned the
time, and Magpie synthesized the response. The fast route took 0.286 seconds
and Magpie first audio took 0.859 seconds. ASR final to TTS first audio was
about 1.86 seconds. The ten offline orchestration tests passed in the Pi's
Pipecat 1.13 environment. This probe did not use the physical speakerphone.

The user's first WebRTC test and the Pi-local switch are measured in
`docs/runbooks/live-latency-20261031.md`. Next, collect at least 30 warm
spoken turns per route on the speakerphone, measure Jev, Llama, tool, and TTS
stages, and compare with the six-turn baseline in
`docs/TWO-BRAIN-PLUSJEV-PLAN.md`.

Known draft limits: direct execution uses Pipecat's existing MCP client's
internal `_call_tool_text` method, so this needs a supported shared executor
interface before long-term deployment. Receipt tracking is in-memory and
only guards concurrent duplicate work; it is not a durable exactly-once
mechanism. The implementation has no complete conversation-ledger parity
test yet. Do not enable externally consequential tools on this fast path.
