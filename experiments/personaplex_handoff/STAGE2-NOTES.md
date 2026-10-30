# Stage 2 notes — live PersonaPlex path (relay execution log)

Date: 2026-10-30. Continues EVIDENCE.md (Stage 1). Everything below was
executed by the relay (Hermes) against the live lab; no production services
were stopped or reconfigured.

## PP-01 PersonaPlex session management on the DGX

- Running as user `aldwin.fresnido`, **no tmux needed**: launched with
  `nohup ... & disown`, survives SSH disconnects (verified across many
  disconnects over 1h+).
- pidfile `~/pp_session.pid`, log `~/pp_session_20261030T144939.log`.
- Not reboot/crash resilient yet. Recommended hardening (relay-owned, no sudo):
  a `~/bin/pp-server.sh` auto-restart loop (same pattern as the Pi tunnel),
  optionally wrapped in a systemd **user** service if `systemctl --user` works
  on the DGX. TODO before long sessions.
- Manual restart command (if ever needed):
  ```
  cd ~/personaplex && CUDA_VISIBLE_DEVICES=2 nohup \
    ~/miniconda3/envs/personaplex/bin/python -m moshi.server \
    --hf-repo nvidia/personaplex-7b-v1 --host 127.0.0.1 --port 8998 \
    >> ~/pp_session.log 2>&1 & disown
  ```

## PP-02 Pi VPN (SHARC) — option 3, concurrent sessions verified

- Pi connected with the existing `~/SHARCHPC_profile.ovpn` (auth via
  `~/vpn.auth`, chmod 600) using **split-tunnel enforcement**:
  `--pull-filter ignore "redirect-gateway" --pull-filter ignore "dhcp-option"`.
  Result: Pi internet stays on the home LAN via wlan0; only `10.0.0.0/8`
  routes through `tun0` (Pi tun IP `192.168.100.23/22`).
- **ThinkPad was NOT kicked**: concurrent VPN sessions with the same profile
  work (conflict test verified from the ThinkPad side immediately after the
  Pi joined). This resolves the worry from the earlier incident.
- Pi keypair created (`~/.ssh/id_ed25519`, comment `pi-handoff-lab`) and its
  public key appended to the DGX `authorized_keys` (now 3 keys:
  hermes-container, codex-handoff-lab, pi-handoff-lab).
- Rollback: `sudo kill $(cat ~/openvpn-sharc.pid)` on the Pi; remove the
  pi-handoff-lab line on the DGX; remove `~/vpn.auth`.

## PP-03 PersonaPlex reachability — ufw finding + tunnel solution

- The DGX firewall (ufw, active) blocks inbound port **8998** from all
  sources including the VPN subnet: ports 22/8000/51122 pass, 8998 blackholes
  (verified from both Pi and ThinkPad over the VPN). PP itself answers 200
  from the DGX's own loopback and LAN IP.
- Aldwin has **no sudo** on the DGX → no firewall change possible or allowed.
- Solution: **loopback SSH tunnel**, systemd user service on the Pi:
  - `~/bin/pp-tunnel.sh` — reconnect loop; waits until DGX:22 is reachable
    (VPN up), then holds `-L 127.0.0.1:8998:127.0.0.1:8998`.
  - `~/.config/systemd/user/pp-tunnel.service` — enabled, auto-restarts.
  - Rollback: `systemctl --user disable --now pp-tunnel.service`.

## PP-04 PersonaPlex WebSocket protocol (verified against the live server)

Endpoint: `GET /api/chat?voice_prompt=<file>.pt&text_prompt=<text>` (ws).

- **`text_prompt` must be non-empty.** With an empty prompt the server raises
  `TypeError: 'NoneType' object is not iterable` during
  `step_system_prompts_async` (server bug; upstream fix candidate). Always
  pass a persona/system instruction.
- Handshake: server sends a single BINARY frame `b"\x00"` after the system
  prompt steps complete (~1 s after connect; voice prompt load is cached).
- Client → server audio: BINARY frames `b"\x01" + <opus data>`. **The opus
  data must be an OGG/Opus container stream** (what `sphn.OpusStreamReader`
  expects), NOT raw Opus packets. Sending raw packets silently produces zero
  generation. Verified: PyAV `av.open(BytesIO, "w", format="ogg")` +
  `add_stream("libopus", rate=24000)`, mux 20 ms frames, stream the container
  bytes paced in real time.
- Server → client: `b"\x01" + <ogg/opus bytes>` (speech), `b"\x02" + text`
  (transcript tokens), `b"\x03"` (segment end).
- Mimi sample rate 24 kHz mono. Voice prompts available: NATF0..3, NATM0..N
  (`voices/*.pt` in the HF snapshot).
- **First live result:** handshake → 4 s synthetic user audio → PP answered
  **" Hi there, how can I help you today?"** with 52 audio packets (10.7 KB).
  Full round-trip: Pi → tunnel → DGX (GPU 2) → tunnel → Pi.
- Reference client script preserved on the Pi at `/tmp/pp_duplex5.py`
  (volatile; the version in git history of this file is canonical).

## PP-05 Stage 2 implementation plan (next commit)

`pi/bot_handoff.py` — experimental entry point, port 7861, production
`pi/bot.py` untouched:

1. PersonaPlex WS client (aiohttp, already in the Pi venv; **no new installs**)
   with the protocol above; OGG framing via PyAV (also already installed).
2. PP audio → Pipecat output transport `send_audio()` (per README finding 1),
   24 kHz → transport rate resampling.
3. Ownership controller: FRONTDESK (PP) ↔ CASCADE states, epoch increments,
   revoke+interruption await per README finding 2.
4. Manual takeover: dev button/command in the web UI; no auto-routing.
5. Cascade path unchanged: Silero VAD → Jetson ASR → Ollama → Magpie TTS.
6. Logs to `bot_handoff.log`; artifacts ignored; no secrets in code (env via
   `~/.voice-agent-env`).

Acceptance for this stage (PLAN.md Stage 2/3 subset): PP greets on connect;
spoken takeover stops PP audio mid-stream without stale tail; fixed TTS
sentence plays through the same output; return to PP greets again.
