"""Reconstruct the simulated smart-home state from voice-tool calls.

The voice tools (``control_lights``, ``set_thermostat``, ``play_music``, …) mutate
a persistent state on every call.  Since 2026-11 the diagnostics also log each
tool call's ``arguments`` (see ``pi/mcp_servers/voice_tools_mcp_server.py``), so
the dashboard can deterministically replay each tool's side effect and render it
— the same device state the TinyVCM demo app's ``Devices`` UI shows.

This is a **reconstruction**: a faithful simulation of the tool's effect, derived
from the recorded arguments.  It is *not* a read of the live SQLite ``state.db``.
Two honest caveats follow from that:

- ``play_music`` resolves the actual track over a network call, so here we surface
  the *requested query*, not the resolved track title.
- Runs captured before argument logging carry no ``arguments``; for those the
  panel shows tool names only and a clear "arguments not recorded" notice.
"""

import copy

# Initial device state (matches the tools' defaults).
INITIAL = {
    "lights": {"power": False, "brightness": "100", "color": None},
    "thermostat": {"degrees": None, "set_at": None},
    "media": {"mode": None, "title": None, "status": "stopped", "volume": 3},
    "timers": [],       # [{label, ends_at}]
    "alarms": [],       # [{time_str}]
    "reminders": [],    # [{text, created_ms}]
    "call": {"status": "idle", "to": None, "at": None},
    "message": {"status": "idle", "to": None, "text": None, "at": None},
}

# Tools that mutate device state, and which they touch (for the activity feed).
STATE_TOOLS = {
    "control_lights", "set_thermostat", "play_music", "playback_control",
    "set_timer", "set_alarm", "add_reminder", "list_reminders", "place_call", "send_message",
}


def _apply(state, tool, args, at, result=None):
    """Apply one tool call's effect to ``state``; return a short change summary."""
    args = args if isinstance(args, dict) else {}

    if tool == "control_lights":
        action = str(args.get("action", "")).strip().lower()
        value = str(args.get("value", "")).strip()
        if action == "on":
            state["lights"]["power"] = True
            summary = "light on"
        elif action == "off":
            state["lights"]["power"] = False
            summary = "light off"
        elif action == "brightness":
            state["lights"]["power"] = True
            state["lights"]["brightness"] = value
            summary = f"brightness {value}%"
        elif action == "color":
            state["lights"]["power"] = True
            state["lights"]["color"] = value.capitalize() or None
            summary = f"colour {value}"
        else:
            summary = f"lights {action or '(no action)'}"
    elif tool == "set_thermostat":
        degrees = args.get("degrees")
        state["thermostat"] = {"degrees": degrees, "set_at": at}
        summary = f"set to {degrees}°C" if degrees is not None else "set thermostat"
    elif tool == "play_music":
        query = str(args.get("query", "")).strip()
        if isinstance(result, dict) and result.get("ask_source"):
            summary = "asked for music source"
        elif isinstance(result, dict) and result.get("ok") is False:
            summary = "music request failed"
        else:
            state["media"].update({"mode": "music", "title": query, "status": "playing"})
            summary = f"play “{query}”"
    elif tool == "playback_control":
        action = str(args.get("action", "")).strip().lower()
        if isinstance(result, dict) and result.get("ok") is False:
            return "playback control failed"
        status = {"pause": "paused", "stop": "stopped", "resume": "playing"}.get(
            action, state["media"]["status"])
        state["media"]["status"] = status
        if action == "volume_up":
            state["media"]["volume"] = min(4, int(state["media"].get("volume", 3)) + 1)
        elif action == "volume_down":
            state["media"]["volume"] = max(0, int(state["media"].get("volume", 3)) - 1)
        vol = state["media"]["volume"]
        summary = {"pause": "paused", "stop": "stopped", "resume": "resumed",
                   "next": "next track",
                   "volume_up": f"volume {vol + 1}/5",
                   "volume_down": f"volume {vol + 1}/5"}.get(action, action or "control")
    elif tool == "set_timer":
        dur = args.get("duration_s")
        if isinstance(result, dict) and result.get("ok") is False:
            return "timer not set"
        ends_at = result.get("ends_at") if isinstance(result, dict) else None
        if not isinstance(ends_at, (int, float)):
            ends_at = (at + dur) if (at is not None and isinstance(dur, (int, float))) else None
        state["timers"].append({"label": f"{dur}s", "ends_at": ends_at})
        summary = f"timer {dur}s"
    elif tool == "set_alarm":
        if isinstance(result, dict) and result.get("ok") is False:
            return "alarm not set"
        t = str(args.get("time_str", "")).strip()
        state["alarms"].append({"time_str": t})
        summary = f"alarm {t}"
    elif tool == "add_reminder":
        text = str(args.get("text", "")).strip()
        state["reminders"].append(
            {"text": text, "created_ms": at * 1000 if at is not None else None})
        summary = f"reminder “{text}”"
    elif tool == "list_reminders":
        if isinstance(result, dict) and result.get("ok") and isinstance(result.get("reminders"), list):
            state["reminders"] = [{"text": str(text), "created_ms": None} for text in result["reminders"]]
        summary = "listed reminders"
    elif tool == "place_call":
        to = str(args.get("to", "")).strip() or "default"
        state["call"] = {"status": "calling", "to": to, "at": at}
        summary = f"call {to}"
    elif tool == "send_message":
        if isinstance(result, dict) and result.get("simulated"):
            to = str(result.get("to", ""))
            state["message"] = {"status": "simulated", "to": to, "text": result.get("text", ""), "at": at}
            summary = f"simulated message to {to}"
        elif isinstance(result, dict) and result.get("ok") and result.get("to") == "Telegram":
            state["message"] = {"status": "sent", "to": "Telegram", "text": result.get("text", ""), "at": at}
            summary = "message sent to Telegram"
        else:
            summary = "message sent" if isinstance(result, dict) and result.get("ok") else "message not confirmed"
    else:
        summary = tool

    if tool in {"play_music", "playback_control"} and isinstance(result, dict):
        media = result.get("media")
        if result.get("ok") and isinstance(media, dict):
            for key in ("mode", "title", "status", "volume", "source", "queue_pos"):
                if key in media:
                    state["media"][key] = media[key]
            if tool == "playback_control" and action in {"volume_up", "volume_down"}:
                summary = f"volume {state['media']['volume'] + 1}/5"

    return summary


def reconstruct(tool_spans):
    """Replay the recorded tool calls into a device state.

    ``tool_spans`` is the list already parsed by ``ingest`` (each entry has
    ``tool``, ``at``, ``duration_s``, ``error`` and, when captured,
    ``arguments``).  Returns ``{final, events, args_recorded}``.
    """
    state = copy.deepcopy(INITIAL)
    events = []
    args_recorded = False
    results_recorded = False
    ordered = sorted(tool_spans, key=lambda s: (s.get("at") is None, s.get("at") or 0))
    for span in ordered:
        tool = span.get("tool")
        args = span.get("arguments")
        if isinstance(args, dict):
            args_recorded = True
            result = span.get("result")
            if isinstance(result, dict):
                results_recorded = True
            summary = _apply(state, tool, args, span.get("at"), result) if tool else None
        else:
            # Pre-argument-logging run: the tool fired but we don't know its
            # arguments, so we must not mutate state or invent an action.
            summary = None
        events.append({
            "tool": tool,
            "arguments": args,
            "at": span.get("at"),
            "duration_s": span.get("duration_s"),
            "change": summary,
        })
    return {
        "reconstructed": True,
        "args_recorded": args_recorded,
        "results_recorded": results_recorded,
        "final": state,
        "events": events,
    }
