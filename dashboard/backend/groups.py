"""Vendored 9-group routing schema + display names for the dashboard.

This is a **read-only copy** of the routing ontology defined in
``pi/group_schema.py`` (single source of truth lives there).  The dashboard
needs the group/tool taxonomy to map raw classifier choices back to the nine
groups, but it must not import ``pi/`` (which pulls in inference/runtime
dependencies).  Keep this in sync with ``pi/group_schema.py`` if the taxonomy
changes.
"""

# ---- Vendored taxonomy (from pi/group_schema.py) ---------------------------

GROUPS = (
    "home",
    "clock",
    "reminders",
    "media",
    "weather",
    "comms",
    "knowledge",
    "workspace",
    "chitchat",
)

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

GROUP_TOOLS = {
    "home": ["control_lights", "set_thermostat"],
    "clock": ["get_time", "set_timer", "set_alarm"],
    "reminders": ["add_reminder", "list_reminders"],
    "media": ["play_music", "playback_control"],
    "weather": ["get_weather"],
    "comms": ["send_message", "send_email", "place_call"],
    "knowledge": ["search", "fetch_content"],
    "workspace": [
        "read_file", "write_file", "edit_file", "grep", "bash",
        "github_repo", "send_file", "serve",
    ],
    "chitchat": [],
}

FAST_GROUPS = frozenset({"home", "clock", "reminders", "media", "weather", "comms"})
ESCALATE_GROUPS = frozenset({"knowledge", "workspace"})
CHITCHAT = "chitchat"

TOOL_TO_GROUP = {
    tool: group for group, tools in GROUP_TOOLS.items() for tool in tools
}

# The v4 (tool-level) router used these non-group labels that still show up in
# older runs.  "small_talk" is the v4 spelling of chitchat; "other" is the v4
# reject bucket.
LEGACY_SMALLTALK = "small_talk"
LEGACY_REJECT = "other"


def group_of(choice):
    """Map a raw classifier choice to its 9-group id.

    Returns a group id for group names and known tool names, ``CHITCHAT`` for
    the legacy ``small_talk`` label, and ``None`` for ``other`` / unknown /
    missing choices (rejected or unclassifiable turns).
    """
    if choice is None:
        return None
    if choice in GROUPS:
        return choice
    if choice == LEGACY_SMALLTALK:
        return CHITCHAT
    if choice == LEGACY_REJECT:
        return None
    return TOOL_TO_GROUP.get(choice)


# ---- Display names + colours (single source of truth for the UI) -----------

GROUP_DISPLAY = {
    "home": {"name": "Home", "color": "#f5a623", "description": GROUP_CRITERIA["home"]},
    "clock": {"name": "Clock", "color": "#38bdf8", "description": GROUP_CRITERIA["clock"]},
    "reminders": {"name": "Reminders", "color": "#a78bfa", "description": GROUP_CRITERIA["reminders"]},
    "media": {"name": "Media", "color": "#f472b6", "description": GROUP_CRITERIA["media"]},
    "weather": {"name": "Weather", "color": "#22d3ee", "description": GROUP_CRITERIA["weather"]},
    "comms": {"name": "Comms", "color": "#4ade80", "description": GROUP_CRITERIA["comms"]},
    "knowledge": {"name": "Knowledge", "color": "#fb923c", "description": GROUP_CRITERIA["knowledge"], "escalate": True},
    "workspace": {"name": "Workspace", "color": "#f87171", "description": GROUP_CRITERIA["workspace"], "escalate": True},
    "chitchat": {"name": "Chitchat", "color": "#94a3b8", "description": GROUP_CRITERIA["chitchat"]},
}

# Outcome buckets shown in the routing trace beyond the nine groups.
OUTCOME_DISPLAY = {
    "rejected": {"name": "Rejected (low conf.)", "color": "#64748b"},
    "timeout": {"name": "Classifier timeout", "color": "#ef4444"},
    "error": {"name": "Classifier error", "color": "#b91c1c"},
    "escalated": {"name": "Escalated to GLM", "color": "#eab308"},
}

DISPATCH_DISPLAY = {
    "tool": {"name": "Local tool", "color": "#4ade80"},
    "glm": {"name": "GLM (cloud)", "color": "#eab308"},
    "smalltalk": {"name": "Local LLM reply", "color": "#94a3b8"},
    "none": {"name": "None", "color": "#64748b"},
}

TOOL_DISPLAY = {
    "control_lights": "Control lights",
    "set_thermostat": "Set thermostat",
    "get_time": "Get time",
    "set_timer": "Set timer",
    "set_alarm": "Set alarm",
    "add_reminder": "Add reminder",
    "list_reminders": "List reminders",
    "play_music": "Play music",
    "playback_control": "Playback control",
    "get_weather": "Get weather",
    "send_message": "Send message",
    "send_email": "Send email",
    "place_call": "Place call",
    "search": "Search",
    "fetch_content": "Fetch content",
    "read_file": "Read file",
    "write_file": "Write file",
    "edit_file": "Edit file",
    "grep": "Grep",
    "bash": "Bash",
    "github_repo": "GitHub repo",
    "send_file": "Send file",
    "serve": "Serve",
}
