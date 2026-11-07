"""Group schema for the 4-tier router (tier 1: utterance -> tool group).

A single flat question over ~27 tools is what the trials showed failing. The
router instead answers ONE coarse question — which *group* of tools can serve
this utterance — and tier 2 then works inside a small candidate set (1-4 tools).

Groups handled on the fast path (regex grammar, then the local 3B as a bounded
fallback) are FAST_GROUPS. Groups that need real tool-calling + multi-step
reasoning (web/document lookup, files/shell/github) are ESCALATE_GROUPS and go
straight to the escalation LLM, which owns the full tool surface.
"""

GROUP_CRITERIA = {
    "home": "Lights on, off, a colour, or brightness; or the thermostat temperature",
    "clock": "The current time, one timer, or one alarm",
    "reminders": "Add, list, or complete a reminder",
    "media": "Play music by genre, mood, artist, or title; or control the current playback",
    "weather": "Current weather or a short forecast",
    "comms": "Send a message or an email, or place a phone call",
    "knowledge": "Look something up on the web, open a URL, or search the user's documents",
    "workspace": "Multi-step work on files, code, a shell, or GitHub",
    "chitchat": "A greeting, thanks, or conversational reply that needs no tool",
}

GROUPS = tuple(GROUP_CRITERIA)

# Tool candidates handed to tier 2 per group (ordered: deterministic first).
GROUP_TOOLS = {
    "home": ["control_lights", "set_thermostat"],
    "clock": ["get_time", "set_timer", "set_alarm"],
    "reminders": ["add_reminder", "list_reminders"],
    "media": ["play_music", "playback_control"],
    "weather": ["get_weather"],
    "comms": ["send_message", "send_email", "place_call"],
    "knowledge": ["search", "fetch_content"],
    "workspace": ["read_file", "write_file", "edit_file", "grep", "github_repo", "send_file", "bash", "serve"],
    "chitchat": [],
}

FAST_GROUPS = frozenset({"home", "clock", "reminders", "media", "weather", "comms"})
ESCALATE_GROUPS = frozenset({"knowledge", "workspace"})
CHITCHAT = "chitchat"

# JSON-schema property types for the local 3B, per tool. Used to build the
# narrowed response_format in SmallModelClient.extract_group so the model can
# only emit well-typed arguments.
TOOL_JSON_PROPERTIES = {
    "get_time": {},
    "get_weather": {},
    "list_reminders": {},
    "add_reminder": {"text": {"type": "string", "description": "the reminder note"}},
    "set_thermostat": {"degrees": {"type": "integer", "description": "celsius temperature 16-32"}},
    "control_lights": {
        "action": {"type": "string", "enum": ["on", "off", "color", "brightness"]},
        "value": {"type": "string", "description": "colour name, or percent 0-100 for brightness, empty for on/off"},
    },
    "set_timer": {"duration_s": {"type": "integer", "description": "duration in seconds"}},
    "set_alarm": {"time_str": {"type": "string", "description": "HH:MM AM/PM"}},
    "playback_control": {
        "action": {"type": "string", "enum": ["stop", "pause", "resume", "next", "volume_up", "volume_down"]},
    },
    "play_music": {"query": {"type": "string", "description": "genre, mood, artist or title"}},
    "send_message": {"text": {"type": "string", "description": "the message body"}},
    "send_email": {
        "to": {"type": "string", "description": "recipient"},
        "subject": {"type": "string", "description": "subject line"},
        "body": {"type": "string", "description": "email body"},
    },
    "place_call": {"to": {"type": "string", "description": "contact name"}},
}


def narrow_schema_flat(tools):
    """Flatter schema that llama.cpp accepts reliably (no oneOf).

    ``arguments`` carries the union of the candidate tools' properties with
    ``additionalProperties: false`` but no forced ``required`` list — per-tool
    key sets are enforced afterwards by validate_arguments(), which rejects
    anything that does not exactly match the chosen tool's schema.
    """
    return {
        "type": "object",
        "properties": {
            "tool": {"type": "string", "enum": list(tools)},
            "arguments": {
                "type": "object",
                "properties": {
                    key: spec
                    for tool in tools
                    for key, spec in TOOL_JSON_PROPERTIES.get(tool, {}).items()
                },
                "additionalProperties": False,
            },
        },
        "required": ["tool", "arguments"],
        "additionalProperties": False,
    }
