"""Jev-directed fast tools with bounded Llama extraction and GLM fallback.

The processor sits immediately before the existing GLM service. A rejected or
unavailable fast route forwards the original context frame unchanged.
"""

import asyncio
import json
import os
import re
import time
from pathlib import Path

import httpx
from loguru import logger
from pipecat.classifiers.base_classifier import ChoiceQuestion
from pipecat.classifiers.typesafe.jev.classifier import JevClassifier
from pipecat.frames.frames import LLMContextFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


FAST_TOOLS = {
    "get_time": {},
    "get_weather": {},
    "list_reminders": {},
    "add_reminder": {"text": str},
    "set_thermostat": {"degrees": int},
    "control_lights": {"action": str, "value": str},
    "set_timer": {"duration_s": int},
    "set_alarm": {"time_str": str},
    "playback_control": {"action": str},
    "play_music": {"query": str},
    "play_radio": {"query": str},
}
OPTIONS = {
    "get_time": "Ask for the current local clock time",
    "get_weather": "Ask for current local weather; no forecast or another location",
    "list_reminders": "Ask to list existing reminders",
    "add_reminder": "Create one reminder with stated note text, such as 'remind me to study'; no time is required",
    "set_thermostat": "Set the thermostat to one explicit Celsius temperature",
    "control_lights": "Turn lights on or off, set one light color, or set light brightness",
    "set_timer": "Start one countdown with an explicit duration",
    "set_alarm": "Set one alarm with an explicit clock time and AM or PM",
    "playback_control": "Pause, stop, resume, skip, or change volume of current music or radio",
    "play_music": "Start playing music using a stated genre, mood, artist, or title",
    "play_radio": "Start a radio station by stated name or genre",
    "small_talk": "A brief greeting, thanks, or simple conversational reply that needs no tool or factual research",
    "other": "Complex or multiple actions, forecasts, ambiguous follow-ups, factual questions, messaging, calls, or any other tool",
}
DIRECT_ONLY_TOOLS = {"get_weather", "set_alarm", "add_reminder", "playback_control", "play_music", "play_radio"}

_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
          "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
          "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
          "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
         "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_NUMBER = r"(?:\d{1,3}|(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[ -](?:one|two|three|four|five|six|seven|eight|nine))?|" + "|".join(_UNITS) + r")"


def _number(value):
    value = value.lower().replace("-", " ")
    if value.isdecimal():
        return int(value)
    if value in _UNITS:
        return _UNITS[value]
    words = value.split()
    return _TENS[words[0]] + (_UNITS[words[1]] if len(words) > 1 else 0)


def _multiple_actions(text):
    return bool(re.search(r"\b(?:and|then|also)\b.{0,70}\b(?:set|add|create|play|stop|turn|remind|call|send|pause|skip)\b", text, re.I))


def latest_user_text(context):
    for message in reversed(context.get_messages()):
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
    return ""


def accepted_route(result, minimum=0.90, gap=0.20):
    """Require a clear, supported choice. Never execute a tool on uncertainty."""
    choice = result.choice
    scores = result.probabilities
    if choice not in FAST_TOOLS and choice != "small_talk":
        return None
    top = scores.get(choice, 0.0)
    next_best = max((value for key, value in scores.items() if key != choice), default=0)
    if top < minimum or top - next_best < gap:
        return None
    return choice


def direct_arguments(tool, text):
    lowered = text.lower().replace(".", "")
    if tool in ("get_time", "list_reminders"):
        return {}
    if tool == "get_weather":
        if re.search(r"\b(tomorrow|tonight|later|next|forecast|weekend|yesterday)\b", lowered):
            return None
        if re.search(r"\b(?:in|at)\s+\w+|\bfor\s+(?!today\b|now\b)\w+", lowered):
            return None
        return {}
    if tool == "set_thermostat":
        numbers = [_number(m.group()) for m in re.finditer(rf"\b{_NUMBER}\b", lowered)]
        if len(numbers) == 1:
            return {"degrees": numbers[0]}
    if tool == "control_lights":
        if re.search(r"\b(lights?|brightness|dim)\b", lowered):
            brightness = list(re.finditer(rf"\b(?P<value>{_NUMBER})\s*(?:percent\b|%)", lowered))
            if len(brightness) == 1:
                return {"action": "brightness", "value": str(_number(brightness[0]["value"]))}
        if re.search(r"\b(off|turn off)\b", lowered):
            return {"action": "off", "value": ""}
        colors = [c for c in ("red", "blue", "green") if re.search(rf"\b{c}\b", lowered)]
        if len(colors) == 1:
            return {"action": "color", "value": colors[0].capitalize()}
        if re.search(r"\b(on|turn on)\b", lowered):
            return {"action": "on", "value": ""}
    if tool == "set_timer":
        matches = list(re.finditer(rf"\b(?P<value>{_NUMBER})\s*(?P<unit>seconds?|minutes?|hours?)\b", lowered))
        if len(matches) == 1:
            match = matches[0]
            unit = match["unit"]
            factor = 3600 if unit.startswith("hour") else 60 if unit.startswith("minute") else 1
            return {"duration_s": _number(match["value"]) * factor}
    if tool == "set_alarm":
        if re.search(r"\b(tomorrow|next|or|and|on monday|on tuesday|on wednesday|on thursday|on friday|on saturday|on sunday)\b", lowered):
            return None
        matches = list(re.finditer(rf"\b(?P<hour>{_NUMBER})(?::(?P<minute>\d{{2}}))?\s*(?P<period>am|pm)\b", lowered))
        if len(matches) == 1:
            match = matches[0]
            hour = _number(match["hour"])
            minute = int(match["minute"] or 0)
            if 1 <= hour <= 12 and minute <= 59:
                return {"time_str": f"{hour:02d}:{minute:02d} {match['period'].upper()}"}
    if tool == "add_reminder":
        match = re.search(r"\b(?:remind me to|(?:add|create|set|make|great) (?:a )?reminder (?:to|for|that))\s+(.+)$", text, re.I)
        if match:
            note = match[1].strip(" .?!")
            if note and not _multiple_actions(note):
                return {"text": note}
    if tool == "playback_control":
        if not re.search(r"\b(music|radio|song|track|playback|volume)\b", lowered):
            return None
        actions = {
            "stop": r"\b(stop|stup)\b",
            "pause": r"\bpause\b",
            "resume": r"\b(resume|continue)\b",
            "next": r"\b(next|skip)\b",
            "volume_down": r"\b(lower|decrease|quieter|down)\b",
            "volume_up": r"\b(raise|increase|louder|up)\b",
        }
        found = [action for action, pattern in actions.items() if re.search(pattern, lowered)]
        if len(found) == 1:
            return {"action": found[0]}
    if tool in ("play_music", "play_radio"):
        match = re.search(r"\b(?:play|put on|listen to)\s+(?:some\s+)?(.+)$", text, re.I)
        if match:
            query = match[1].strip(" .?!")
            if tool == "play_music":
                query = re.sub(r"\b(?:music|songs?|tracks?)$", "", query, flags=re.I).strip() or "music"
            else:
                query = re.sub(r"^radio\s*", "", query, flags=re.I).strip()
                if not query:
                    return None
            return {"query": query}
    return None


def validate_arguments(tool, arguments):
    schema = FAST_TOOLS.get(tool)
    if schema is None or not isinstance(arguments, dict) or set(arguments) != set(schema):
        return False
    if any(type(arguments[key]) is not kind for key, kind in schema.items()):
        return False
    if tool == "set_thermostat":
        return 16 <= arguments["degrees"] <= 32
    if tool == "set_timer":
        return 1 <= arguments["duration_s"] <= 86400
    if tool == "control_lights":
        action, value = arguments["action"], arguments["value"]
        return (action in {"on", "off"} and value == "") or (action == "color" and value in {"Red", "Blue", "Green"}) or (action == "brightness" and value.isdecimal() and 0 <= int(value) <= 100)
    if tool == "set_alarm":
        return bool(re.fullmatch(r"(?:0?[1-9]|1[0-2]):[0-5]\d (?:AM|PM)", arguments["time_str"]))
    if tool == "add_reminder":
        return 1 <= len(arguments["text"].strip()) <= 160 and "\n" not in arguments["text"]
    if tool == "playback_control":
        return arguments["action"] in {"pause", "stop", "resume", "next", "volume_up", "volume_down"}
    if tool in ("play_music", "play_radio"):
        return 1 <= len(arguments["query"].strip()) <= 80 and "\n" not in arguments["query"]
    return True


class SmallModelClient:
    """Bounded Llama calls through Ollama or an OpenAI-compatible server."""

    def __init__(self, endpoints, model="llama3.2:3b", timeout=2.5):
        self.endpoints = [
            (item[0].rstrip("/"), item[1], item[2] if len(item) > 2 else model,
             item[3] if len(item) > 3 else "")
            for item in endpoints if item[0]
        ]
        self.model = model
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)

    async def _complete(self, messages, schema=None):
        for url, protocol, endpoint_model, api_key_file in self.endpoints[:2]:
            if protocol == "ollama":
                path = "/api/chat"
                body = {"model": endpoint_model, "stream": False, "messages": messages,
                        "options": {"temperature": 0, "num_predict": 96}}
                if schema:
                    body["format"] = schema
            elif protocol == "openai":
                path = "/v1/chat/completions"
                body = {"model": endpoint_model, "stream": False, "messages": messages,
                        "temperature": 0, "max_tokens": 96}
                if schema:
                    body["response_format"] = {"type": "json_schema", "schema": schema}
            else:
                logger.warning("Unknown small-model protocol {}", protocol)
                return None
            try:
                headers = {}
                if api_key_file:
                    headers["Authorization"] = "Bearer " + Path(api_key_file).read_text().strip()
                response = await self.client.post(url + path, json=body, headers=headers)
                response.raise_for_status()
                data = response.json()
                return data["message"]["content"] if protocol == "ollama" else data["choices"][0]["message"]["content"]
            except httpx.TransportError:
                continue
            except (httpx.HTTPError, OSError, KeyError, ValueError, TypeError) as exc:
                logger.warning("Small-model call failed: {}", type(exc).__name__)
                return None
        return None

    async def extract(self, tool, text):
        if not self.endpoints:
            return None
        argument_properties = {
            name: {"type": "integer" if kind is int else "string"}
            for name, kind in FAST_TOOLS[tool].items()
        }
        schema = {
            "type": "object",
            "properties": {"tool": {"type": "string", "enum": [tool]},
                           "arguments": {"type": "object", "properties": argument_properties,
                                         "required": list(argument_properties), "additionalProperties": False}},
            "required": ["tool", "arguments"],
            "additionalProperties": False,
        }
        examples = {
            "set_thermostat": {"degrees": 26},
            "control_lights": {"action": "color", "value": "Green"},
            "set_timer": {"duration_s": 300},
        }
        example_args = examples.get(tool, {})
        example = json.dumps({"tool": tool, "arguments": example_args}, separators=(",", ":"))
        messages = [
                {"role": "system", "content": f"You are an argument extractor. Output exactly one JSON object with keys tool and arguments. Example: {example}. Never output any other keys or invent missing values."},
                {"role": "user", "content": text},
        ]
        raw = await self._complete(messages, schema=schema)
        if raw is None:
            return None
        try:
            proposed = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if proposed.get("tool") == tool and validate_arguments(tool, proposed.get("arguments")):
            return proposed["arguments"]
        return None

    async def answer(self, text):
        """Generate one bounded conversational reply with the small model."""
        if not self.endpoints:
            return None
        messages = [
                {"role": "system", "content": "Reply naturally in one short spoken sentence. Do not claim to have used a tool or performed an action."},
                {"role": "user", "content": text},
        ]
        answer = await self._complete(messages)
        return answer.strip()[:400] if isinstance(answer, str) and answer.strip() else None

    async def close(self):
        await self.client.aclose()


class TwoBrainRouter(FrameProcessor):
    """Handle confident routine commands and pass every other turn to GLM."""

    def __init__(self, mcp_client, *, classifier=None, extractor=None, **kwargs):
        super().__init__(**kwargs)
        self.mcp_client = mcp_client
        self.classifier = classifier or JevClassifier(
            api_key=os.environ["TYPESAFE_API_KEY"],
            model=os.getenv("JEV_MODEL", "jev-1.14.0"),
            timeout=float(os.getenv("JEV_DEADLINE_MS", "800")) / 1000,
        )
        self.extractor = extractor or SmallModelClient(
            [(os.getenv("SMALL_LLM_PRIMARY_URL", ""), os.getenv("SMALL_LLM_PRIMARY_PROTOCOL", "openai"), os.getenv("SMALL_LLM_PRIMARY_MODEL", os.getenv("SMALL_LLM_MODEL", "llama3.2:3b")), os.getenv("SMALL_LLM_PRIMARY_API_KEY_FILE", "")),
             (os.getenv("SMALL_LLM_SECONDARY_URL", ""), os.getenv("SMALL_LLM_SECONDARY_PROTOCOL", "openai"), os.getenv("SMALL_LLM_SECONDARY_MODEL", "llama3.2-3b"), os.getenv("SMALL_LLM_SECONDARY_API_KEY_FILE", ""))],
            model=os.getenv("SMALL_LLM_MODEL", "llama3.2:3b"),
            timeout=float(os.getenv("SMALL_LLM_DEADLINE_MS", "2500")) / 1000,
        )
        self._inflight = set()

    async def setup(self, setup):
        await super().setup(setup)
        await self.classifier.setup(self.task_manager)

    async def cleanup(self):
        await self.classifier.cleanup()
        await self.extractor.close()
        await super().cleanup()

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if direction != FrameDirection.DOWNSTREAM or not isinstance(frame, LLMContextFrame) or frame.speculation:
            await self.push_frame(frame, direction)
            return
        text = latest_user_text(frame.context)
        if not text:
            await self.push_frame(frame, direction)
            return
        if _multiple_actions(text):
            logger.info("Multiple actions routed to GLM")
            await self.push_frame(frame, direction)
            return
        started = time.monotonic()
        try:
            result = (await asyncio.wait_for(self.classifier.choice(
                {"utterance": text},
                {"intent": ChoiceQuestion(instructions="Select one supported command only when explicit and singular; otherwise other", options=OPTIONS)},
            ), timeout=float(os.getenv("JEV_DEADLINE_MS", "800")) / 1000))["intent"]
            jev_s = time.monotonic() - started
            tool = accepted_route(result)
            if tool == "small_talk":
                answer = await self.extractor.answer(text)
                if answer:
                    await self.push_frame(TTSSpeakFrame(text=answer))
                    logger.info("Small-brain conversation: jev={:.3f}s llama={:.3f}s total={:.3f}s",
                                jev_s, time.monotonic() - started - jev_s, time.monotonic() - started)
                    return
            if tool in FAST_TOOLS:
                args = direct_arguments(tool, text)
                extraction = "direct"
                if args is None and tool not in DIRECT_ONLY_TOOLS:
                    args = await self.extractor.extract(tool, text)
                    extraction = "llama"
                parse_s = time.monotonic() - started - jev_s
                if args is not None and validate_arguments(tool, args):
                    receipt = (tool, json.dumps(args, sort_keys=True), text)
                    if receipt in self._inflight:
                        return
                    self._inflight.add(receipt)
                    try:
                        mcp_started = time.monotonic()
                        raw = await self.mcp_client._call_tool_text(tool, args)
                        mcp_s = time.monotonic() - mcp_started
                        try:
                            payload = json.loads(raw)
                        except (TypeError, ValueError):
                            payload = {"spoken": "I couldn't confirm that action. Please check its state before trying again."}
                        spoken = payload.get("spoken") or "I couldn't confirm that action. Please check its state before trying again."
                        await self.push_frame(TTSSpeakFrame(text=spoken))
                        logger.info("Fast route {}: jev={:.3f}s {}={:.3f}s mcp={:.3f}s total={:.3f}s",
                                    tool, jev_s, extraction, parse_s, mcp_s, time.monotonic() - started)
                        return
                    finally:
                        self._inflight.discard(receipt)
                logger.info("Fast route {} lacked validated arguments; GLM after {:.3f}s", tool, time.monotonic() - started)
            else:
                logger.info("Route {} sent to GLM after {:.3f}s", result.choice, time.monotonic() - started)
        except Exception as exc:
            logger.warning("Fast route fell back to GLM: {}", type(exc).__name__)
        await self.push_frame(frame, direction)
