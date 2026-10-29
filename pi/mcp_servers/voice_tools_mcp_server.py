"""Voice agent tools MCP server (ME3 M5).

One MCP server (stdio) that carries the ME2 command set over to the ME3
voice agent as dynamic tool calls. The ME2 commands were fixed VCM labels;
here a cloud LLM decides which tool to call with what arguments, so the
same commands become free-form (e.g. "Play some chill jazz" -> play_music).

Command -> tool map (from me2 configs/ontology.json):
  PLAY_MUSIC            -> play_music (ME2: local mpv; here: open music APIs)
  (new)                 -> play_radio (new: Radio Browser API)
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
  Radio   : Radio Browser API (https://api.radio-browser.info) — community,
            open-source, no key.
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
import json
import os
import re
import sqlite3
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from mcp.server.mcpserver import MCPServer

# ---------------------------------------------------------------- config ----
DATA_DIR = Path(os.getenv("VOICE_TOOLS_DATA", Path.home() / "voice-agent-tools"))
DB_PATH = DATA_DIR / "state.db"
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

DATA_DIR.mkdir(parents=True, exist_ok=True)

server = MCPServer(
    name="voice-agent-tools",
    version="0.1.0",
    instructions=(
        "Tools for the voice agent: media playback (music/radio), weather, "
        "time, timer, alarm, reminders, thermostat, lights, and messaging. "
        "Call one tool per user command; all return a short dict that is "
        "safe to speak back to the user."
    ),
)


# ---------------------------------------------------------------- helpers ---
def _http_json(url: str, timeout: float = 6.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "me3-voice-agent/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    db.execute(
        "CREATE TABLE IF NOT EXISTS reminders ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL,"
        " created_ms REAL NOT NULL, done INTEGER NOT NULL DEFAULT 0)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS device_state ("
        " key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS timers ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT NOT NULL,"
        " ends_at REAL NOT NULL, fired INTEGER NOT NULL DEFAULT 0)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS alarms ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT NOT NULL,"
        " enabled INTEGER NOT NULL DEFAULT 1)"
    )
    db.commit()
    return db


def _set_state(key: str, value: dict) -> None:
    db = _db()
    db.execute(
        "INSERT INTO device_state(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )
    db.commit()
    db.close()


def _get_state(key: str) -> dict | None:
    db = _db()
    row = db.execute("SELECT value FROM device_state WHERE key=?", (key,)).fetchone()
    db.close()
    return json.loads(row[0]) if row else None


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


def _radio_search(query: str, limit: int = 5) -> list[dict]:
    try:
        url = (
            "https://de1.api.radio-browser.info/json/stations/search?"
            + urllib.parse.urlencode(
                {"name": query, "limit": limit, "hidebroken": "true", "order": "votes"}
            )
        )
        data = _http_json(url)
        return data if isinstance(data, list) else []
    except Exception:
        return []


@server.tool(
    name="play_music",
    description=(
        "Play music. Picks a track from an open-licensed music catalog "
        "(Jamendo; Internet Archive fallback) for the given free-form query "
        "(genre, mood, artist, or title). Returns track title and stream URL."
    ),
)
def play_music(query: str) -> dict:
    j = _jamendo_search(query)
    if j:
        t = j["results"][0]
        track = {
            "title": t.get("name", "unknown"),
            "artist": t.get("artist_name", "unknown"),
            "url": t.get("audio", ""),
            "source": "jamendo",
        }
    else:
        a = _archive_search(query)
        if not a or not a.get("response", {}).get("docs"):
            return {"ok": False, "spoken": "I could not find any music for that."}
        d = a["response"]["docs"][0]
        ident = d["identifier"]
        track = {
            "title": d.get("title", ident),
            "artist": "",
            "url": f"https://archive.org/download/{ident}/",
            "source": "internet-archive",
        }
    _set_state("media", {"mode": "music", "title": track["title"], "url": track["url"]})
    return {"ok": True, "spoken": f"Now playing {track['title']}.", "track": track}


@server.tool(
    name="play_radio",
    description=(
        "Play a radio station by name (e.g. 'Love Radio', 'news radio', "
        "'jazz'). Uses the open Radio Browser API. Returns station name and "
        "stream URL."
    ),
)
def play_radio(query: str) -> dict:
    stations = _radio_search(query, limit=3)
    if not stations:
        return {"ok": False, "spoken": f"I could not find a radio station named {query}."}
    s = stations[0]
    station = {
        "name": s.get("name", "unknown"),
        "url": s.get("url_resolved") or s.get("url", ""),
        "source": "radio-browser",
    }
    _set_state("media", {"mode": "radio", "title": station["name"], "url": station["url"]})
    return {"ok": True, "spoken": f"Tuning to {station['name']}.", "station": station}


@server.tool(
    name="playback_control",
    description=(
        "Control the currently playing music or radio: pause, stop, resume, "
        "next, volume_up, volume_down. These are the ME2 PAUSE/STOP/NEXT/"
        "VOLUME_UP/VOLUME_DOWN commands."
    ),
)
def playback_control(action: str) -> dict:
    media = _get_state("media") or {}
    if not media:
        return {"ok": False, "spoken": "Nothing is playing right now."}
    spoken = {
        "pause": "Paused.",
        "stop": "Stopped.",
        "resume": "Resumed.",
        "next": "Skipping to the next track.",
        "volume_up": "Volume up.",
        "volume_down": "Volume down.",
    }.get(action)
    if spoken is None:
        return {"ok": False, "spoken": f"Unknown playback action: {action}"}
    media["status"] = action
    _set_state("media", media)
    return {"ok": True, "spoken": spoken, "media": media}


# ---------------------------------------------------------------- weather ---
@server.tool(
    name="get_weather",
    description=(
        "Current weather for a place. Open-Meteo, no API key. Same provider "
        "as the ME2 weather service. Optionally pass place latitude/longitude."
    ),
)
def get_weather(latitude: float = DEFAULT_LAT, longitude: float = DEFAULT_LON) -> dict:
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast?"
            + urllib.parse.urlencode(
                {
                    "latitude": latitude,
                    "longitude": longitude,
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
    spoken = f"It's {temp} degrees with {wmo.get(code, 'unknown conditions')} right now."
    return {"ok": True, "spoken": spoken, "current": cur, "provider": "open-meteo"}


@server.tool(
    name="get_time",
    description="Current time (local timezone). No network needed.",
)
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
def set_timer(duration_s: int) -> dict:
    if not (1 <= duration_s <= 86400):
        return {"ok": False, "spoken": "Timers must be between 1 second and 1 day."}
    ends = time.time() + duration_s
    db = _db()
    db.execute("INSERT INTO timers(label, ends_at) VALUES (?, ?)", (f"{duration_s}s", ends))
    db.commit()
    db.close()
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
def set_alarm(time_str: str) -> dict:
    try:
        t = datetime.strptime(time_str.strip().upper(), "%I:%M %p").time()
    except ValueError:
        return {"ok": False, "spoken": f"I could not parse that alarm time: {time_str}"}
    now = datetime.now(ZoneInfo(TIMEZONE))
    cand = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    if cand <= now:
        cand += timedelta(days=1)
    db = _db()
    db.execute("INSERT INTO alarms(time, enabled) VALUES (?, 1)", (time_str, ))
    db.commit()
    db.close()
    return {"ok": True, "spoken": f"Alarm set for {time_str}.",
            "next_ring": cand.isoformat()}


# --------------------------------------------------------------- reminders --
@server.tool(
    name="add_reminder",
    description="Create a reminder (e.g. 'Drink water'). Persistent.",
)
def add_reminder(text: str) -> dict:
    db = _db()
    db.execute(
        "INSERT INTO reminders(text, created_ms) VALUES (?, ?)",
        (text.strip(), time.time() * 1000),
    )
    db.commit()
    db.close()
    return {"ok": True, "spoken": f"Reminder added: {text}"}


@server.tool(
    name="list_reminders",
    description="List outstanding reminders.",
)
def list_reminders() -> dict:
    db = _db()
    rows = db.execute(
        "SELECT id, text FROM reminders WHERE done=0 ORDER BY id DESC"
    ).fetchall()
    db.close()
    if not rows:
        return {"ok": True, "spoken": "You have no reminders.", "reminders": []}
    texts = [r[1] for r in rows]
    return {"ok": True, "spoken": "You have " + ", ".join(texts) + ".", "reminders": texts}


# ------------------------------------------------------- thermostat/lights --
@server.tool(
    name="set_thermostat",
    description=(
        "Set the target temperature in degrees Celsius (e.g. 18, 22, 26). "
        "State is stored for the later dashboard UI."
    ),
)
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
def control_lights(action: str, value: str = "") -> dict:
    state = _get_state("lights") or {"power": False, "brightness": "100", "color": None}
    if action == "on":
        state["power"] = True
        spoken = "Lights on."
    elif action == "off":
        state["power"] = False
        spoken = "Lights off."
    elif action == "brightness":
        try:
            pct = int(value)
        except ValueError:
            return {"ok": False, "spoken": "Brightness must be a number like 60."}
        if not (0 <= pct <= 100):
            return {"ok": False, "spoken": "Brightness must be between 0 and 100."}
        state["brightness"], state["power"] = str(pct), True
        spoken = f"Brightness set to {pct} percent."
    elif action == "color":
        color = value.strip().capitalize()
        if color not in {"Red", "Blue", "Green"}:
            return {"ok": False, "spoken": f"Color must be Red, Blue, or Green."}
        state["color"], state["power"] = color, True
        spoken = f"Lights set to {color}."
    else:
        return {"ok": False, "spoken": f"Unknown light action: {action}"}
    _set_state("lights", state)
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
def send_message(text: str) -> dict:
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
def place_call(to: str = "") -> dict:
    _set_state("call", {"status": "calling", "to": to or "default", "at": time.time()})
    return {"ok": True, "spoken": f"Calling {to or 'your default contact'}.",
            "note": "carrier integration is pending UI (see milestone-5)"}


if __name__ == "__main__":
    server.run("stdio")
