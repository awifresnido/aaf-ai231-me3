# Milestone 5: Voice-agent command tools (MCP, dynamic tool calls)

Status: server implemented and live-tested from the ME2 command set
(2026-10-29). Dashboard/UI integration is deferred.

## What this is

`pi/mcp_servers/voice_tools_mcp_server.py` — one MCP server (stdio) that
turns the fixed ME2 VCM command set (19 labels, `me2 configs/ontology.json`)
into free-form tool calls. The cloud LLM (Ollama Cloud gemma4:31b) decides
which tool to call with what arguments, so the same commands become dynamic:
"Play some chill jazz" -> `play_music`, not a fixed `PLAY_MUSIC` label.

## Command -> tool map

| ME2 command | ME3 tool | Backend (open source) |
|---|---|---|
| PLAY_MUSIC | `play_music(query)` | Jamendo (open-licensed, free client id) -> Internet Archive fallback (no key) |
| (new) | `play_radio(query)` | Radio Browser API (`de1.api.radio-browser.info`, community, no key) |
| PAUSE / STOP / NEXT / VOLUME_UP / VOLUME_DOWN | `playback_control(action)` | state on the active stream |
| WEATHER | `get_weather(lat, lon)` | Open-Meteo (no key) — same provider as ME2 |
| TIME | `get_time()` | local `zoneinfo` (no network) |
| TIMER | `set_timer(duration_s)` | local, sqlite |
| ALARM | `set_alarm(time_str)` | local, sqlite |
| CREATE_REMINDER / LIST_REMINDERS | `add_reminder` / `list_reminders` | sqlite, same schema as ME2 |
| TEMPERATURE | `set_thermostat(degrees)` | state, for the later dashboard UI |
| LIGHT_ON / LIGHT_OFF / BRIGHTNESS / COLOR | `control_lights(action, value)` | state, for the later dashboard UI |
| CALL | `place_call(to)` | state stub — no open-source carrier API exists; dashboard routes later (SIP softphone / carrier webhook) |
| MESSAGE | `send_message(text)` | Telegram Bot API (open HTTP API, free bot token) |
| (new) | `send_email(to, subject, body)` | SMTP (open standard, any provider) |

Every tool returns `{"ok": bool, "spoken": str, ...}` — `spoken` is what the
TTS layer reads aloud, so the pipeline never has to re-render a tool result.

## Wiring into the Pi (M5)

1. Copy `pi/mcp_servers/voice_tools_mcp_server.py` to the Pi alongside the
   ASR/TTS servers (same folder, same `.venv` — no extra deps beyond `mcp`).
2. Env vars (put in `~/.voice-agent-env`, chmod 600, outside the repo):

```
VOICE_TOOLS_TZ=Asia/Manila
JAMENDO_CLIENT_ID=          # optional: api.jamendo.com, free account
TELEGRAM_BOT_TOKEN=         # optional: BotFather bot for send_message
TELEGRAM_CHAT_ID=           # optional: target chat for send_message
SMTP_HOST= SMTP_PORT=587 SMTP_USER= SMTP_PASSWORD=   # optional: send_email
WEATHER_LAT=10.7 WEATHER_LON=124.97                  # default location
```

3. Register it with the LLM via Pipecat's MCPClient (same pattern as
   `mcp_servers/asr_mcp_server.py`): it is a stdio subprocess, so the
   launch config is:

```
python3 pi/mcp_servers/voice_tools_mcp_server.py
```

4. When a user says a command, the LLM now emits a tool call (e.g.
   `play_radio(query="Love Radio")`) instead of a fixed label; the tool's
   `spoken` field goes straight to `MCPTTSService` for playback.

## Verified live (2026-10-29, from this repo's test run)

- `play_music("acoustic folk")` -> Jamendo track with stream URL.
- `play_radio("Love Radio")` -> "Love Radio Digital" station resolved.
- `get_weather()` -> "It's 25.8 degrees with light drizzle right now."
- `get_time()`, `set_timer(30)`, `set_alarm("6:00 AM")`,
  `add_reminder`/`list_reminders`, `set_thermostat(22)`,
  `control_lights` (color + brightness), `playback_control("pause")`,
  `place_call` — all return ok.
- `send_message` / `send_email` return a clean "not configured" spoken
  fallback when their env vars are absent — no silent failure.

## Gotchas

- The state DB lives at `$VOICE_TOOLS_DATA/state.db` (default
  `~/voice-agent-tools/state.db` on the Pi). It persists across restarts —
  same idea as ME2's ReminderStore.
- Calls: no open-source telephony API exists. `place_call` is a state
  stub that the dashboard (M7, deferred) should wire to a real carrier.
- If Jamendo has no client id, music silently falls back to Internet
  Archive; if both fail, the tool returns `ok=False` with a spoken
  "I could not find any music for that."
