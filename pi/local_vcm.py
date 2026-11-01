"""Single-host VCM trial: one structured model decision, then a tool receipt.

Choose ThinkPad or VPS explicitly. ROUTER_MODEL=laya opts into the local
classifier with separate deterministic argument validation and reply policy.
"""

import asyncio
import json
import os
import re
import time
from contextlib import nullcontext
from collections import deque

from loguru import logger
from pipecat.frames.frames import LLMContextFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from orchestration import FAST_TOOLS, SmallModelClient, _multiple_actions, direct_arguments, validate_arguments


VOICE_OF_PI_GREETING = (
    "Hello, I'm the Voice of Pi. I can help with time, weather, reminders, "
    "timers, alarms, lights, temperature, and music commands. What can I do for you?"
)

LOCAL_VCM_INSTRUCTION = """You are Voice of Pi, a voice agent on a Raspberry Pi.
You have basic VCM command tools. Select ONE tool or ask a short clarification.
Output only JSON: {"tool":"NAME","arguments":{...}}.
Available tools and exact arguments:
get_time: {} (current local time only, not date)
get_weather: {} (current configured local weather only; no other city or forecast)
list_reminders: {}
add_reminder: {"text":"exact reminder note"} (no scheduling)
set_thermostat: {"degrees":26} (integer Celsius, 16 to 32)
control_lights examples:
  Turn lights on -> {"tool":"control_lights","arguments":{"action":"on","value":""}}
  Turn lights off -> {"tool":"control_lights","arguments":{"action":"off","value":""}}
  Set lights to blue -> {"tool":"control_lights","arguments":{"action":"color","value":"Blue"}}
  Make lights green -> {"tool":"control_lights","arguments":{"action":"color","value":"Green"}}
  Set brightness to 80 percent -> {"tool":"control_lights","arguments":{"action":"brightness","value":"80"}}
  Color values are Red/Blue/Green. A color request MUST use action color, not on.
set_timer: {"duration_s":300} (integer seconds 1 to 86400; five minutes is 300)
set_alarm: {"time_str":"09:00 PM"} (explicit AM/PM required)
playback_control: {"action":"pause"} (pause/stop/resume/next/volume_up/volume_down)
play_music: {"query":"exact requested artist, title, genre or mood"}
Stop the music -> {"tool":"playback_control","arguments":{"action":"stop"}}
Play some jazz music -> {"tool":"play_music","arguments":{"query":"jazz"}}
reply: {"text":"one short spoken sentence"} (greeting, help, clarification or unsupported request)
Use conversation context to resolve an answer to your previous question. Never
invent missing arguments, places, recipients, or tool results. If missing details,
ask a question with reply. For multiple commands ask for one command at a time.
Messaging, email, calls, radio, location lookup, forecasts and complex tasks are
unavailable in this trial. Never claim an action happened in reply. Actual actions
are executed by the controller and their result is spoken without another model
call. Device tools record agent state; music searches a catalog, not a real player.
Keep reply text brief, without code, URLs, lists, or emojis.
Send a message to my contact -> {"tool":"reply","arguments":{"text":"Messaging is not available in this trial."}}
Play the radio -> {"tool":"reply","arguments":{"text":"Radio is not available."}}
"""


def decision_schema():
    choices = []
    for tool, fields in {**FAST_TOOLS, "reply": {"text": str}}.items():
        properties = {key: {"type": "integer" if kind is int else "string"}
                      for key, kind in fields.items()}
        if tool == "set_thermostat":
            properties["degrees"].update(minimum=16, maximum=32)
        elif tool == "set_timer":
            properties["duration_s"].update(minimum=1, maximum=86400)
        elif tool == "playback_control":
            properties["action"]["enum"] = ["pause", "stop", "resume", "next", "volume_up", "volume_down"]
        arguments = {"type": "object", "properties": properties,
                     "required": list(fields), "additionalProperties": False}
        if tool == "control_lights":
            arguments = {"anyOf": [
                {"type": "object", "properties": {
                    "action": {"type": "string", "enum": actions},
                    "value": value}, "required": ["action", "value"], "additionalProperties": False}
                for actions, value in [
                    (["on", "off"], {"type": "string", "enum": [""]}),
                    (["color"], {"type": "string", "enum": ["Red", "Blue", "Green"]}),
                    (["brightness"], {"type": "string", "pattern": "^(?:100|[0-9]{1,2})$"}),
                ]
            ]}
        choices.append({
            "type": "object",
            "properties": {
                "tool": {"type": "string", "enum": [tool]},
                "arguments": arguments,
            },
            "required": ["tool", "arguments"], "additionalProperties": False,
        })
    return {"anyOf": choices}


class LocalVCMClient(SmallModelClient):
    def __init__(self):
        self.model_host = os.getenv("LOCAL_VCM_MODEL_HOST", "thinkpad").strip().lower()
        if self.model_host not in {"thinkpad", "vps"}:
            raise ValueError("LOCAL_VCM_MODEL_HOST must be thinkpad or vps")
        prefix = "SMALL_LLM_PRIMARY" if self.model_host == "thinkpad" else "SMALL_LLM_SECONDARY"
        url = os.getenv(prefix + "_URL", "").strip()
        if not url:
            raise ValueError(f"local_vcm requires {prefix}_URL")
        super().__init__([(
            url, os.getenv(prefix + "_PROTOCOL", "openai"),
            os.getenv(prefix + "_MODEL", "llama3.2:3b" if self.model_host == "thinkpad" else "llama3.2-3b"),
            os.getenv(prefix + "_API_KEY_FILE", ""),
        )], timeout=float(os.getenv("LOCAL_VCM_MODEL_TIMEOUT_SECS", "12")))

    async def decide(self, context):
        # Plain recent conversation only: cloud tool schemas/results never enter
        # this request, and the system identity cannot be displaced by history.
        recent = []
        for message in context.get_messages():
            if (isinstance(message, dict) and message.get("role") in {"user", "assistant"}
                    and isinstance(message.get("content"), str)):
                recent.append({"role": message["role"], "content": message["content"][:600]})
        messages = [{"role": "system", "content": LOCAL_VCM_INSTRUCTION}, *recent[-6:]]
        raw = await self._complete(messages, schema=decision_schema(), max_tokens=160)
        return json.loads(raw) if raw else None


class LocalVCMProcessor(FrameProcessor):
    def __init__(self, mcp_client, *, model=None, timing_observer=None, **kwargs):
        super().__init__(**kwargs)
        engine = os.getenv("ROUTER_MODEL", "llama").strip().lower()
        if engine not in {"llama", "laya"}:
            raise ValueError("local_vcm ROUTER_MODEL must be llama or laya")
        self.router_model = engine
        self._laya_consumed = deque(maxlen=64)
        if model is None and engine == "laya":
            from laya_router import LayaDecisionClient
            model = LayaDecisionClient(timing_observer=timing_observer)
        self.model = model if model is not None else LocalVCMClient()
        self.model_host = getattr(self.model, "model_host", "test")
        self.mcp_client = mcp_client
        self.timing = timing_observer
        self.diagnostics = getattr(timing_observer, "diagnostics", None)
        self.model_timeout = float(os.getenv("LOCAL_VCM_MODEL_TIMEOUT_SECS", "12"))
        self.tool_timeout = float(os.getenv("LOCAL_VCM_TOOL_TIMEOUT_SECS", "20"))

    async def cleanup(self):
        await self.model.close()
        await super().cleanup()

    def record(self, event, turn, **fields):
        fields = {"model_host": self.model_host, **fields}
        if self.timing:
            self.timing.record(event, turn=turn, **fields)
        scope = self.diagnostics.span("route_log", timing_event=event, turn=turn) if self.diagnostics else nullcontext()
        with scope:
            logger.info("Local VCM {}: {}", event, fields)

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if not isinstance(frame, LLMContextFrame) or direction != FrameDirection.DOWNSTREAM:
            await self.push_frame(frame, direction)
            return
        # Consume all context frames: this mode has no downstream LLM/fallback.
        if frame.speculation:
            return
        messages = frame.context.get_messages()
        if not messages or not isinstance(messages[-1], dict) or messages[-1].get("role") != "user":
            return
        text = messages[-1].get("content", "")
        if not isinstance(text, str) or not text.strip():
            return
        if self.router_model == "laya":
            # Consume a user-message object before awaiting classification or a
            # write. Replayed context after timeout/cancellation cannot retry it.
            # A newly spoken request has a new message object, even if identical.
            if any(messages[-1] is previous for previous in self._laya_consumed):
                return
            self._laya_consumed.append(messages[-1])
        turn = self.timing.turn if self.timing else None
        started = time.monotonic()
        tool_issued = False
        try:
            scope = self.diagnostics.span("model_client", turn=turn, model_host=self.model_host) if self.diagnostics else nullcontext()
            with scope:
                decision = await asyncio.wait_for(self.model.decide(frame.context), self.model_timeout)
            model_s = time.monotonic() - started
            if not isinstance(decision, dict) or set(decision) != {"tool", "arguments"}:
                raise ValueError("Invalid model decision")
            tool, args = decision["tool"], decision["arguments"]
            self.record("local_decision", turn, tool=tool, model_s=model_s)
            if tool == "reply":
                if (not isinstance(args, dict) or set(args) != {"text"}
                        or not isinstance(args["text"], str) or not args["text"].strip()
                        or len(args["text"]) > 400):
                    raise ValueError("Invalid spoken reply")
                spoken = args["text"].strip()
                self.record("route_local_reply", turn, model_s=model_s)
            else:
                if not isinstance(tool, str) or not validate_arguments(tool, args):
                    raise ValueError("Unsupported tool or invalid arguments")
                if _multiple_actions(text):
                    raise ValueError("Multiple commands require clarification")
                if tool in {"play_music", "playback_control"} and re.search(r"\bradio\b", text, re.I):
                    raise ValueError("Radio is not supported")
                explicit = direct_arguments(tool, text)
                if (tool == "playback_control" and explicit is None
                        and re.search(r"\b(play|listen|put on)\b", text, re.I)):
                    raise ValueError("Playback action conflicts with music search request")
                if tool in {"add_reminder", "play_music"} and explicit is not None:
                    field = "text" if tool == "add_reminder" else "query"
                    if explicit[field].casefold() == args[field].casefold():
                        args = explicit  # Preserve the user's capitalization.
                if explicit is not None and explicit != args:
                    raise ValueError("Model arguments conflict with explicit request")
                if tool == "get_weather" and direct_arguments(tool, text) is None:
                    spoken = "I can check current local weather only in this trial."
                    self.record("route_local_reply", turn, reason="unsupported_weather", model_s=model_s)
                else:
                    tool_issued = True
                    mcp_started = time.monotonic()
                    raw = await asyncio.wait_for(self.mcp_client._call_tool_text(tool, args), self.tool_timeout)
                    payload = json.loads(raw)
                    if not isinstance(payload, dict) or not isinstance(payload.get("spoken"), str):
                        raise ValueError("Invalid tool receipt")
                    spoken = payload["spoken"]
                    # Existing tools update state/catalog metadata, not a player.
                    if payload.get("ok") and tool == "play_music":
                        spoken = "I found a music catalog match, but music playback is not connected yet."
                    elif payload.get("ok") and tool == "playback_control":
                        spoken = "I've recorded the playback command, but music playback is not connected yet."
                    self.record("route_local_tool", turn, tool=tool, model_s=model_s,
                                mcp_s=time.monotonic() - mcp_started, total_s=time.monotonic() - started)
                    frame.context.add_message({"role": "assistant", "content":
                        f"Executed {tool} {json.dumps(args)}. Result: {spoken}"})
        except Exception as exc:
            self.record("route_local_failure", turn, error=type(exc).__name__,
                        tool_issued=tool_issued, total_s=time.monotonic() - started)
            spoken = ("I couldn't confirm that command's outcome. Please check its state before repeating it."
                      if tool_issued else "I couldn't process that with my local model. Please try one basic command.")
        await self.push_frame(TTSSpeakFrame(text=spoken))
