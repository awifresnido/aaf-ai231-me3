"""Voice agent tools MCP server (ME3 M5).

One MCP server (stdio) that carries the ME2 command set over to the ME3
voice agent as dynamic tool calls. The ME2 commands were fixed VCM labels;
here a cloud LLM decides which tool to call with what arguments, so the
same commands become free-form (e.g. "Play some chill jazz" -> play_music).

Command -> tool map (from me2 configs/ontology.json):
  PLAY_MUSIC            -> play_music (ME2: local mpv; here: open music APIs)
  WEATHER               -> get_weather (Open-Meteo, no key, same as ME2)
  TIME                  -> get_time (local tz, no network)
  TIMER / ALARM         -> set_timer / set_alarm (me2 parse_duration_s/next_alarm logic)
  CREATE_REMINDER /
  LIST_REMINDERS        -> add_reminder / list_reminders (SQLite, same as ME2 store)
  TEMPERATURE           -> set_thermostat (state + UI event)
  LIGHT_ON/OFF,
  BRIGHTNESS, COLOR     -> control_lights (state + UI event)
  PAUSE/STOP/NEXT/
  VOLUME_UP/DOWN        -> playback_control (targets the same active stream)
  CALL / MESSAGE        -> send_message / place_call (open APIs; see notes)
  (new)                 -> send_email (SMTP, open standard)

Open-source APIs used (all free, no vendor lock-in):
  Music   : Jamendo Client API (open-licensed, needs a free client id) with
            Internet Archive as the no-key fallback.
  Weather : Open-Meteo (no key).
  Time    : local time via zoneinfo (no network).
  Messages: Telegram Bot API (open HTTP API, free bot token).
  Email   : SMTP (open standard; any provider).
  Calls   : real telephony needs a carrier; no open-source carrier exists.
            place_call() is a stateful stub that emits a UI event so the
            later dashboard can route it (e.g. a SIP softphone or a webhook).

Run: .venv/bin/python voice_tools_mcp_server.py   (stdio transport)
Env: see env.example block in docs/runbooks/milestone-5.md.
"""
from __future__ import annotations

import base64
import asyncio
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from contextlib import nullcontext, suppress
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo
import uuid

from mcp.server.mcpserver import MCPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stall_diagnostics import Diagnostics, META_KEY
from vcm_state import state_store_from_env

diagnostics = Diagnostics.from_env("mcp")


class ProfiledToolServer(MCPServer):
    async def call_tool(self, name, arguments, context=None):
        if diagnostics is None:
            return await super().call_tool(name, arguments, context)
        ctx = context if context is not None else self.get_context()
        try:
            meta = ctx.request_context.meta or {}
            call_id = meta.get(META_KEY, "")
        except (ValueError, AttributeError):
            call_id = ""
        if not isinstance(call_id, str) or not re.fullmatch(r"[0-9a-f]{32}", call_id):
            call_id = uuid.uuid4().hex
        with diagnostics.call(call_id), diagnostics.span("mcp_server_call", tool=name, arguments=arguments) as end_fields:
            result = await super().call_tool(name, arguments, ctx)
            if name in {"play_music", "playback_control", "list_reminders", "send_message", "set_timer", "set_alarm"}:
                payload = getattr(result, "structured_content", None)
                if payload is None:
                    content = getattr(result, "content", [])
                    payload = getattr(content[0], "text", None) if content else None
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except ValueError:
                        payload = None
                if isinstance(payload, dict):
                    end_fields["result"] = payload
            return result

    async def run_stdio_async(self):
        if diagnostics is None:
            return await super().run_stdio_async()
        task = asyncio.create_task(diagnostics.monitor_loop())
        try:
            return await super().run_stdio_async()
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


def trace_tool(fn):
    if diagnostics is None:
        return fn
    @wraps(fn)
    def measured(*args, **kwargs):
        with diagnostics.span("tool_execute", tool=fn.__name__):
            return fn(*args, **kwargs)
    return measured

# ---------------------------------------------------------------- config ----
STATE_BACKEND = os.getenv("VCM_STATE_BACKEND", "jetson_sqlite").strip().lower()
STATE_STORE = state_store_from_env(diagnostics=diagnostics)
if diagnostics:
    diagnostics.emit("vcm_server_configuration", tool_server_host=os.getenv("VCM_TOOL_SERVER_HOST", "pi"),
                     state_backend=STATE_BACKEND,
                     sqlite_version=sqlite3.sqlite_version if STATE_BACKEND == "local_sqlite" else None)
TIMEZONE = os.getenv("VOICE_TOOLS_TZ", "Asia/Manila")
JAMENDO_CLIENT_ID = os.getenv("JAMENDO_CLIENT_ID", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)

DEFAULT_LAT = float(os.getenv("WEATHER_LAT", "10.7"))       # default: Leyte, PH
DEFAULT_LON = float(os.getenv("WEATHER_LON", "124.97"))

# ---- music playback (mpv → PulseAudio voice sink → JV801P speakerphone) --
MPV_SOCKET = "/tmp/me3_music.sock"                          # mpv IPC control socket
VOLUME_LEVELS = 5                                           # 0..4 inclusive
DEFAULT_VOLUME = 3                                          # 90%
VOLUME_PCT = (0, 60, 75, 90, 100)                           # level 1 is audible at PCM 60%
MUSIC_DIR = os.getenv("MUSIC_DIR", str(Path.home() / "music"))

server = ProfiledToolServer(
    name="voice-agent-tools",
    version="0.1.0",
    instructions=(
        "Tools for the voice agent: music playback, weather, "
        "time, timer, alarm, reminders, thermostat, lights, and messaging. "
        "Call one tool per user command; all return a short dict that is "
        "safe to speak back to the user."
    ),
)


# ---------------------------------------------------------------- helpers ---
def _http_json(url: str, timeout: float = 6.0) -> dict:
    scope = diagnostics.span("http_request", host=urllib.parse.urlparse(url).hostname) if diagnostics else nullcontext()
    with scope:
        req = urllib.request.Request(url, headers={"User-Agent": "me3-voice-agent/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))


def _set_state(key: str, value: dict) -> None:
    STATE_STORE.dispatch("set_state", {"key": key, "value": value})


def _get_state(key: str) -> dict | None:
    return STATE_STORE.dispatch("get_state", {"key": key})


# ------------------------------------------------------------------ media ---
def _jamendo_search(query: str, limit: int = 5) -> dict | None:
    if not JAMENDO_CLIENT_ID:
        return None
    try:
        url = (
            "https://api.jamendo.com/v3.0/tracks/?"
            + urllib.parse.urlencode(
                {
                    "client_id": JAMENDO_CLIENT_ID,
                    "format": "json",
                    "limit": limit,
                    "search": query,
                    "include": "musicinfo",
                }
            )
        )
        data = _http_json(url)
        if data.get("results"):
            return data
    except Exception:
        pass
    return None


def _archive_search(query: str, limit: int = 5) -> dict | None:
    try:
        url = (
            "https://archive.org/advancedsearch.php?q="
            + urllib.parse.quote(f'mediaType:(audio) AND title:({query})')
            + f"&fl[]=identifier&fl[]=title&rows={limit}&output=json"
        )
        return _http_json(url)
    except Exception:
        return None


def _archive_audio_url(identifier: str) -> str | None:
    """Resolve a direct, playable audio file URL for an archive.org item."""
    try:
        meta = _http_json(f"https://archive.org/metadata/{identifier}")
    except Exception:
        return None
    for f in meta.get("files", []) or []:
        name = f.get("name", "")
        fmt = (f.get("format") or "").lower()
        if name.lower().endswith((".mp3", ".ogg", ".m4a", ".flac", ".wav")) or fmt in ("vbr mp3", "mp3", "ogg vorbis"):
            return f"https://archive.org/download/{identifier}/{urllib.parse.quote(name)}"
    return None


def _volume_pct(level: int) -> int:
    return VOLUME_PCT[max(0, min(VOLUME_LEVELS - 1, int(level)))]


def _mpv_send(command: list) -> bool:
    """Send a JSON command to the running mpv over its IPC socket."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(MPV_SOCKET)
        s.sendall((json.dumps({"command": command}) + "\n").encode())
        s.close()
        return True
    except Exception:
        return False


def _mpv_stop() -> None:
    _mpv_send(["quit"])
    with suppress(FileNotFoundError):
        Path(MPV_SOCKET).unlink()


def _mpv_play(url: str, volume: int) -> None:
    _mpv_stop()
    env = dict(os.environ)
    env["PULSE_SINK"] = "voice_agent_aec_sink"
    env["PULSE_SERVER"] = f"unix:/run/user/{os.getuid()}/pulse/native"
    cmd = [
        "mpv", "--no-video", "--no-terminal", "--ao=pulse",
        f"--input-ipc-server={MPV_SOCKET}",
        f"--volume={_volume_pct(volume)}",
        "--", url,
    ]
    with open("/tmp/me3_mpv.err", "ab") as mpv_errors:
        process = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=mpv_errors,
                                   start_new_session=True)
    threading.Thread(target=process.wait, name="mpv-reaper", daemon=True).start()


def _local_tracks() -> list:
    d = Path(MUSIC_DIR)
    if not d.is_dir():
        return []
    exts = {".mp3", ".flac", ".m4a", ".wav", ".ogg", ".aac", ".opus"}
    return sorted(p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in exts)


def _local_queue(query: str) -> list[Path]:
    """Queue matching local files in filename order, or all files if none match."""
    tracks = _local_tracks()
    if not tracks:
        return []
    words = [w for w in re.findall(r"[a-z0-9']+", (query or "").lower()) if len(w) > 2]
    if not words:
        return tracks
    def score(p):
        name = p.stem.lower()
        return sum(1 for w in words if w in name)
    matched = [p for p in tracks if score(p) > 0]
    return matched or tracks


def _detect_source(text: str) -> str:
    t = (text or "").lower()
    local = r"\b(?:my\s+)?(?:files?|folder|local|offline|stored|library|downloaded)\b"
    net = r"\b(?:internet|online|stream|web|cloud|jamendo|archive)\b"
    has_local = bool(re.search(local, t))
    has_net = bool(re.search(net, t))
    if has_local and not has_net:
        return "local"
    if has_net and not has_local:
        return "internet"
    return ""


def _clean_query(text: str) -> str:
    q = re.sub(r"\b(?:from|on|via|the|some|my|me)\b", " ", text, flags=re.I)
    q = re.sub(r"\b(?:local\s+)?(?:files?|folder|offline|stored|library|downloaded)\b", " ", q, flags=re.I)
    q = re.sub(r"\b(?:internet|online|stream|web|cloud|jamendo|archive)\b", " ", q, flags=re.I)
    q = re.sub(r"\b(?:music|songs?|tracks?|play|put\s+on|listen\s+to)\b", " ", q, flags=re.I)
    return re.sub(r"\s+", " ", q).strip()


@server.tool(
    name="play_music",
    description=(
        "Play music. Pass source='local' to play a file from the user's local "
        "music folder, or source='internet' to stream from an open-licensed "
        "catalog (Jamendo / Internet Archive). If the user did not say which, "
        "call this tool with no source and it will ask them to choose."
    ),
)
@trace_tool
def play_music(query: str, source: str = "") -> dict:
    q = (query or "").strip()
    src = (source or "").strip().lower()
    if not src:
        src = _detect_source(q)
    q_clean = _clean_query(q)
    if not src:
        # Ambiguous: ask, and remember the genre/title for the follow-up answer.
        _set_state("music_pending", {"query": q_clean or "music"})
        return {"ok": True, "ask_source": True,
                "spoken": "Would you like me to play from your local files or from the internet?"}
    if not q_clean:
        pending = _get_state("music_pending") or {}
        q_clean = pending.get("query") or "music"
    _set_state("music_pending", {})

    if src == "local":
        queue = _local_queue(q_clean)
        if not queue:
            return {"ok": False, "spoken": "I don't see any music in your local folder yet."}
        path = queue[0]
        prev = _get_state("media") or {}
        volume = int(prev.get("volume", DEFAULT_VOLUME))
        try:
            _mpv_play(str(path), volume)
        except Exception as exc:
            return {"ok": False, "spoken": "I could not start playback.", "error": str(exc)}
        title = path.stem
        media = {"mode": "music", "title": title, "artist": "", "url": str(path),
                 "source": "local", "status": "playing", "volume": volume,
                 "queue": [str(p) for p in queue], "queue_pos": 0}
        _set_state("media", media)
        return {"ok": True, "spoken": f"Now playing {title} from your files.",
                "track": {"title": title, "source": "local"}, "media": media}

    j = _jamendo_search(q_clean)
    if j:
        t = j["results"][0]
        track = {
            "title": t.get("name", "unknown"),
            "artist": t.get("artist_name", "unknown"),
            "url": t.get("audio", ""),
            "source": "jamendo",
        }
    else:
        a = _archive_search(q_clean)
        if not a or not a.get("response", {}).get("docs"):
            return {"ok": False, "spoken": "I could not find any music for that."}
        d = a["response"]["docs"][0]
        ident = d["identifier"]
        audio_url = _archive_audio_url(ident)
        if not audio_url:
            return {"ok": False, "spoken": "I found a match but it has no playable audio."}
        track = {
            "title": d.get("title", ident),
            "artist": "",
            "url": audio_url,
            "source": "internet-archive",
        }
    if not track["url"]:
        return {"ok": False, "spoken": "I could not resolve a playable stream for that."}
    prev = _get_state("media") or {}
    volume = int(prev.get("volume", DEFAULT_VOLUME))
    try:
        _mpv_play(track["url"], volume)
    except Exception as exc:
        return {"ok": False, "spoken": "I could not start playback.", "error": str(exc)}
    media = {"mode": "music", "title": track["title"], "artist": track["artist"],
             "url": track["url"], "source": track["source"], "status": "playing",
             "volume": volume, "queue": [track["url"]], "queue_pos": 0}
    _set_state("media", media)
    return {"ok": True, "spoken": f"Now playing {track['title']}.", "track": track,
            "media": media}


@server.tool(
    name="playback_control",
    description=(
        "Control the currently playing music: pause, stop, resume, next, "
        "volume_up, volume_down. Volume has five levels."
    ),
)
@trace_tool
def playback_control(action: str) -> dict:
    media = _get_state("media")
    if media is None:
        return {"ok": False, "spoken": "Nothing is playing right now."}
    a = (action or "").strip().lower()
    level = int(media.get("volume", DEFAULT_VOLUME))
    status = media.get("status", "playing")
    if a == "pause":
        _mpv_send(["set_property", "pause", True])
        status, spoken = "paused", "Paused."
    elif a == "resume":
        _mpv_send(["set_property", "pause", False])
        status, spoken = "playing", "Resumed."
    elif a == "stop":
        _mpv_stop()
        status, spoken = "stopped", "Stopped."
    elif a == "next":
        queue = media.get("queue") or []
        if media.get("source") != "local" or len(queue) < 2:
            spoken = "There is no next track in the queue."
        else:
            pos = (int(media.get("queue_pos", 0)) + 1) % len(queue)
            path = Path(queue[pos])
            try:
                _mpv_play(str(path), level)
            except Exception as exc:
                return {"ok": False, "spoken": "I could not skip to the next track.",
                        "error": str(exc)}
            media.update(queue_pos=pos, title=path.stem, url=str(path))
            status = "playing"
            spoken = f"Now playing {path.stem}."
    elif a == "volume_up":
        level = min(VOLUME_LEVELS - 1, level + 1)
        _mpv_send(["set_property", "volume", _volume_pct(level)])
        spoken = f"Volume {level + 1} of {VOLUME_LEVELS}."
    elif a == "volume_down":
        level = max(0, level - 1)
        _mpv_send(["set_property", "volume", _volume_pct(level)])
        spoken = f"Volume {level + 1} of {VOLUME_LEVELS}."
    else:
        return {"ok": False, "spoken": f"Unknown playback action: {action}"}
    media["status"] = status
    media["volume"] = level
    _set_state("media", media)
    return {"ok": True, "spoken": spoken, "media": media}


# ---------------------------------------------------------------- weather ---
def _geocode(place: str) -> dict | None:
    """Resolve a place name to coordinates via Open-Meteo's free geocoding API.

    Returns ``{"name", "latitude", "longitude", "country", "admin1"}`` for the
    top hit, or ``None`` if the place can't be resolved (or the API is down).
    """
    if not place or not place.strip():
        return None
    try:
        url = (
            "https://geocoding-api.open-meteo.com/v1/search?"
            + urllib.parse.urlencode(
                {"name": place.strip(), "count": 1, "language": "en", "format": "json"}
            )
        )
        data = _http_json(url)
        results = data.get("results") or []
    except Exception:
        return None
    if not results:
        return None
    r = results[0]
    return {
        "name": r.get("name") or place.strip(),
        "latitude": float(r["latitude"]),
        "longitude": float(r["longitude"]),
        "country": r.get("country"),
        "admin1": r.get("admin1"),
    }


@server.tool(
    name="get_weather",
    description=(
        "Current weather for a place. Pass the place NAME as a string "
        "(e.g. 'Manila', 'Baguio', 'London') and it is geocoded automatically. "
        "Pass latitude/longitude only if you already have coordinates."
    ),
)
@trace_tool
def get_weather(place: str = "", latitude: float = DEFAULT_LAT, longitude: float = DEFAULT_LON) -> dict:
    label = place.strip() if place else None
    lat, lon = latitude, longitude
    if label:
        geo = _geocode(label)
        if geo is None:
            return {"ok": False, "spoken": f"I couldn't find the weather for {label}."}
        lat, lon = geo["latitude"], geo["longitude"]
        label = geo["name"]
        if geo.get("country") and geo["country"].lower() != geo["name"].lower():
            label = f"{geo['name']}, {geo['country']}"
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast?"
            + urllib.parse.urlencode(
                {
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,apparent_temperature,"
                               "relative_humidity_2m,weather_code,wind_speed_10m",
                    "timezone": "auto",
                }
            )
        )
        cur = _http_json(url)["current"]
    except Exception as exc:
        return {"ok": False, "spoken": "I could not reach the weather service.", "error": str(exc)}
    wmo = {
        0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
        45: "fog", 48: "rime fog", 51: "light drizzle", 53: "drizzle",
        55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
        80: "rain showers", 81: "heavy showers", 95: "thunderstorm",
        96: "thunderstorm with hail", 99: "severe thunderstorm",
    }
    code = int(cur.get("weather_code", 0))
    temp = cur.get("temperature_2m")
    cond = wmo.get(code, "unknown conditions")
    spoken = (
        f"In {label}, it's {temp} degrees with {cond} right now."
        if label
        else f"It's {temp} degrees with {cond} right now."
    )
    return {"ok": True, "spoken": spoken, "place": label, "current": cur, "provider": "open-meteo"}


@server.tool(
    name="get_time",
    description="Current time (local timezone). No network needed.",
)
@trace_tool
def get_time() -> dict:
    now = datetime.now(ZoneInfo(TIMEZONE))
    return {"ok": True, "spoken": now.strftime("It's %I:%M %p."), "iso": now.isoformat()}


# ------------------------------------------------------------------ timers --
_DURATION_RE = re.compile(
    r"^\s*(\d+)\s*(second|seconds|minute|minutes|hour|hours)\s*$", re.I
)
_UNIT_S = {"second": 1, "minute": 60, "hour": 3600}


@server.tool(
    name="set_timer",
    description=(
        "Start a countdown timer. Pass the duration as a number of seconds "
        "(e.g. '30 seconds' -> 30). Returns when the timer ends."
    ),
)
@trace_tool
def set_timer(duration_s: int) -> dict:
    if not (1 <= duration_s <= 86400):
        return {"ok": False, "spoken": "Timers must be between 1 second and 1 day."}
    ends = time.time() + duration_s
    STATE_STORE.dispatch("add_timer", {"label": f"{duration_s}s", "ends_at": ends})
    mins = duration_s // 60
    secs = duration_s % 60
    spoken = f"Timer set for {mins} minute{'s' if mins != 1 else ''}" if secs == 0 else \
             f"Timer set for {duration_s} seconds."
    if secs == 0 and mins == 0:
        spoken = "Timer set for 1 minute."
    return {"ok": True, "spoken": spoken, "ends_at": ends}


@server.tool(
    name="set_alarm",
    description=(
        "Set an alarm for a time like '6:00 AM' (next occurrence). Returns "
        "when it will ring."
    ),
)
@trace_tool
def set_alarm(time_str: str) -> dict:
    try:
        t = datetime.strptime(time_str.strip().upper(), "%I:%M %p").time()
    except ValueError:
        return {"ok": False, "spoken": f"I could not parse that alarm time: {time_str}"}
    now = datetime.now(ZoneInfo(TIMEZONE))
    cand = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    if cand <= now:
        cand += timedelta(days=1)
    STATE_STORE.dispatch("add_alarm", {"time_str": time_str})
    return {"ok": True, "spoken": f"Alarm set for {time_str}.",
            "next_ring": cand.isoformat()}


# --------------------------------------------------------------- reminders --
@server.tool(
    name="add_reminder",
    description="Create a reminder (e.g. 'Drink water'). Persistent.",
)
@trace_tool
def add_reminder(text: str) -> dict:
    STATE_STORE.dispatch("add_reminder", {"text": text.strip(), "created_ms": time.time() * 1000})
    return {"ok": True, "spoken": f"Reminder added: {text}"}


@server.tool(
    name="list_reminders",
    description="List outstanding reminders.",
)
@trace_tool
def list_reminders() -> dict:
    rows = STATE_STORE.dispatch("list_reminders", {})
    if not rows:
        return {"ok": True, "spoken": "You have no reminders.", "reminders": []}
    texts = [r[1] for r in rows]
    recent = texts[:3]
    prefix = f"You have {len(texts)} reminders. The latest three are " if len(texts) > 3 else "Your reminders are "
    return {"ok": True, "spoken": prefix + ", ".join(recent) + ".", "reminders": texts}


# ------------------------------------------------------- thermostat/lights --
@server.tool(
    name="set_thermostat",
    description=(
        "Set the target temperature in degrees Celsius (e.g. 18, 22, 26). "
        "State is stored for the later dashboard UI."
    ),
)
@trace_tool
def set_thermostat(degrees: int) -> dict:
    if not (16 <= degrees <= 32):
        return {"ok": False, "spoken": "Temperature must be between 16 and 32 degrees."}
    _set_state("thermostat", {"degrees": degrees, "set_at": time.time()})
    return {"ok": True, "spoken": f"Temperature set to {degrees} degrees."}


@server.tool(
    name="control_lights",
    description=(
        "Control the smart lights. action: 'on' | 'off' | 'brightness' | "
        "'color'. value: 0-100 for brightness, or Red/Blue/Green for color."
    ),
)
@trace_tool
def control_lights(action: str, value: str = "") -> dict:
    if action == "on":
        changes = {"power": True}
        spoken = "Lights on."
    elif action == "off":
        changes = {"power": False}
        spoken = "Lights off."
    elif action == "brightness":
        try:
            pct = int(value)
        except ValueError:
            return {"ok": False, "spoken": "Brightness must be a number like 60."}
        if not (0 <= pct <= 100):
            return {"ok": False, "spoken": "Brightness must be between 0 and 100."}
        changes = {"brightness": str(pct), "power": True}
        spoken = f"Brightness set to {pct} percent."
    elif action == "color":
        color = value.strip().capitalize()
        if color not in {"Red", "Blue", "Green"}:
            return {"ok": False, "spoken": f"Color must be Red, Blue, or Green."}
        changes = {"color": color, "power": True}
        spoken = f"Lights set to {color}."
    else:
        return {"ok": False, "spoken": f"Unknown light action: {action}"}
    state = STATE_STORE.dispatch("patch_state", {"key": "lights", "changes": changes,
        "defaults": {"power": False, "brightness": "100", "color": None}})
    return {"ok": True, "spoken": spoken, "lights": state}


# ------------------------------------------------------ calls/messages/email
@server.tool(
    name="send_message",
    description=(
        "Send a text message via Telegram Bot API (open HTTP API, free). "
        "Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID. Returns the "
        "Telegram message id."
    ),
)
@trace_tool
def send_message(text: str, to: str = "") -> dict:
    if to.strip().lower() in {"mom", "dad", "john"}:
        contact = to.strip().capitalize()
        _set_state("message", {"status": "simulated", "to": contact, "text": text, "at": time.time()})
        return {"ok": True, "spoken": f"Simulated message to {contact}: {text}", "simulated": True, "to": contact, "text": text}
    if to.strip():
        return {"ok": False, "spoken": "I can only simulate messages to Mom, Dad, or John."}
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return {"ok": False, "spoken": "Messaging is not configured yet.",
                "error": "missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID"}
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        body = urllib.parse.urlencode(
            {"chat_id": TELEGRAM_CHAT_ID, "text": text}
        ).encode()
        req = urllib.request.Request(url, data=body)
        with urllib.request.urlopen(req, timeout=6.0) as r:
            data = json.loads(r.read().decode())
    except Exception as exc:
        return {"ok": False, "spoken": "I could not send that message.", "error": str(exc)}
    if not data.get("ok"):
        return {"ok": False, "spoken": "The message service rejected that.",
                "error": data.get("description")}
    msg_id = data["result"]["message_id"]
    return {"ok": True, "spoken": "Message sent.", "message_id": msg_id}


@server.tool(
    name="send_email",
    description=(
        "Send an email via SMTP (open standard; any provider). Requires "
        "SMTP_HOST/SMTP_USER/SMTP_PASSWORD env. Falls back to send_message "
        "via Telegram if SMTP is not configured."
    ),
)
@trace_tool
def send_email(to: str, subject: str, body: str) -> dict:
    if not SMTP_HOST or not SMTP_USER:
        return {"ok": False,
                "spoken": "Email is not configured; I can send it via Telegram instead.",
                "fallback": "send_message"}
    import smtplib
    from email.message import EmailMessage
    try:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = SMTP_FROM, to, subject
        msg.set_content(body)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
    except Exception as exc:
        return {"ok": False, "spoken": "I could not send that email.", "error": str(exc)}
    return {"ok": True, "spoken": "Email sent."}


@server.tool(
    name="place_call",
    description=(
        "Place a voice call. Real telephony needs a carrier (no open-source "
        "carrier API exists), so this records the call request and returns a "
        "UI event the later dashboard can route to a SIP softphone or a "
        "webhook-based carrier. This mirrors the ME2 simulated CALL."
    ),
)
@trace_tool
def place_call(to: str = "") -> dict:
    _set_state("call", {"status": "calling", "to": to or "default", "at": time.time()})
    return {"ok": True, "spoken": f"Simulating a call to {to or 'your default contact'}.",
            "note": "carrier integration is pending UI (see milestone-5)"}


if __name__ == "__main__":
    try:
        if hasattr(STATE_STORE, "start"):
            STATE_STORE.start()
        server.run("stdio")
    finally:
        STATE_STORE.close()
        if diagnostics:
            diagnostics.close()
