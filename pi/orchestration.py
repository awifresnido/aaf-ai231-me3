"""Jev-directed fast tools with bounded Llama extraction and GLM fallback.

The processor sits immediately before the existing GLM service. A rejected or
unavailable fast route forwards the original context frame unchanged.
"""

import asyncio
import json
import os
import re
import time
from contextlib import nullcontext
from collections import deque
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
    "send_message": {"text": str},
    "send_email": {"to": str, "subject": str, "body": str},
    "place_call": {"to": str},
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
    "playback_control": "Pause, stop, resume, skip, or change volume of current music",
    "play_music": "Start playing music using a stated genre, mood, artist, or title",
    "small_talk": "A brief greeting, thanks, or simple conversational reply that needs no tool or factual research",
    "other": "Complex or multiple actions, forecasts, ambiguous follow-ups, factual questions, messaging, calls, unsupported radio requests, or any other tool",
}
DIRECT_ONLY_TOOLS = {"get_weather", "set_alarm", "add_reminder", "playback_control", "play_music"}

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
    # A leading connective continues the conversation without adding an action.
    text = re.sub(r"^\s*(?:(?:also|and|then)\b[\s,]*)+", "", text, flags=re.I)
    return bool(re.search(r"\b(?:and|then|also)\b.{0,70}\b(?:set|add|create|play|stop|turn|remind|call|send|pause|skip)\b", text, re.I))


def explicit_route_hint(text):
    """Recover an explicit reminder request when ASR prefixes it with filler."""
    if re.search(r"\b(?:remind me to|(?:add|create|set|make|great) (?:a )?reminder (?:to|for|that))\b", text, re.I):
        return "add_reminder"
    return None


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


def accepted_group(result, minimum=0.65, gap=0.10):
    """Require a clear tool-group choice (tier-1 of the 4-tier router).

    The 9-way group question is much coarser than the old 12-way tool question,
    so Jev's absolute confidence lands lower (0.7-0.9) while the margin over the
    runner-up stays large. Thresholds are lowered accordingly; anything genuinely
    uncertain still falls through to the escalation LLM.
    """
    from group_schema import GROUPS
    choice = result.choice
    scores = result.probabilities
    if choice not in GROUPS:
        return None
    top = scores.get(choice, 0.0)
    next_best = max((value for key, value in scores.items() if key != choice), default=0)
    if top < minimum or top - next_best < gap:
        return None
    return choice


def direct_arguments(tool, text):
    lowered = text.lower().replace(".", "")
    if tool == "get_time":
        if re.search(r"\b(time|clock|hour|o'clock)\b", lowered):
            return {}
        return None
    if tool == "list_reminders":
        if re.search(r"\b(reminder|reminders|remind)\b", lowered):
            return {}
        return None
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
        if not re.search(r"\b(music|song|track|playback|volume)\b", lowered):
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
    if tool == "play_music":
        if re.search(r"\bradio\b", lowered):
            return None
        match = re.search(r"\b(?:play|put on|listen to)\s+(?:some\s+)?(.+)$", text, re.I)
        if match:
            query = match[1].strip(" .?!")
            query = re.sub(r"\b(?:music|songs?|tracks?)$", "", query, flags=re.I).strip() or "music"
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
    if tool == "play_music":
        return 1 <= len(arguments["query"].strip()) <= 80 and "\n" not in arguments["query"]
    if tool == "send_message":
        return 1 <= len(arguments["text"].strip()) <= 500 and "\n" not in arguments["text"]
    if tool == "send_email":
        return all(isinstance(arguments.get(k), str) and arguments[k].strip()
                   for k in ("to", "subject", "body"))
    if tool == "place_call":
        return 1 <= len(arguments["to"].strip()) <= 80
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

    async def _complete(self, messages, schema=None, max_tokens=96):
        for url, protocol, endpoint_model, api_key_file in self.endpoints[:2]:
            if protocol == "ollama":
                path = "/api/chat"
                body = {"model": endpoint_model, "stream": False, "messages": messages,
                        "options": {"temperature": 0, "num_predict": max_tokens}}
                if schema:
                    body["format"] = schema
            elif protocol == "openai":
                path = "/v1/chat/completions"
                body = {"model": endpoint_model, "stream": False, "messages": messages,
                        "temperature": 0, "max_tokens": max_tokens}
                if schema:
                    body["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {"name": "voice_agent_decision", "schema": schema},
                    }
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

    async def extract_group(self, tools, text):
        """Choose one tool from a small candidate set and fill typed arguments.

        Returns ``(tool, arguments)`` when the reply is a valid, schema-exact
        call, else ``(None, None)``.
        """
        if not self.endpoints or not tools:
            return None, None
        from group_schema import TOOL_JSON_PROPERTIES, narrow_schema_flat
        schema = narrow_schema_flat(tools)
        hint = ", ".join(
            f"{tool}({', '.join(TOOL_JSON_PROPERTIES.get(tool, {}))})" for tool in tools
        )
        messages = [
            {"role": "system", "content":
                "You are the tool caller of a voice assistant. You are given ONE small set of "
                "candidate tools. Choose exactly one and fill its arguments from the user's words. "
                "Reply with JSON only: {\"tool\": <name>, \"arguments\": {...}}. "
                "Use exactly the argument names shown for the tool you pick. "
                "Never invent a tool outside the candidate set."},
            {"role": "user", "content": "Candidate tools (with their arguments): " + hint + "\nUtterance: " + text},
        ]
        raw = await self._complete(messages, schema=schema, max_tokens=120)
        if raw is None:
            return None, None
        try:
            proposed = json.loads(raw)
        except (TypeError, ValueError):
            return None, None
        tool = proposed.get("tool")
        args = proposed.get("arguments")
        if tool in tools and isinstance(args, dict) and validate_arguments(tool, args):
            return tool, args
        return None, None

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

    def __init__(self, mcp_client, *, classifier=None, extractor=None, timing_observer=None, **kwargs):
        super().__init__(**kwargs)
        self.timing_observer = timing_observer
        self.diagnostics = getattr(timing_observer, "diagnostics", None)
        self.mcp_client = mcp_client
        self.router_model = os.getenv("ROUTER_MODEL", "jev").strip().lower()
        if self.router_model not in {"jev", "laya"}:
            raise ValueError("two_brain_plusjev ROUTER_MODEL must be jev or laya")
        self.group_mode = (self.router_model == "jev"
                           and os.getenv("ROUTE_SCHEMA", "").strip().lower() == "group")
        if self.group_mode:
            logger.info("Group schema routing enabled (ROUTE_SCHEMA=group)")
        self.classifier_timeout = (float(os.getenv("LAYA_ROUTER_TIMEOUT_SECS", "2"))
            if self.router_model == "laya" else float(os.getenv("JEV_DEADLINE_MS", "800")) / 1000)
        if classifier is None and self.router_model == "laya":
            from laya_classifier import LayaClassifier
            classifier = LayaClassifier()
        self.classifier = classifier or JevClassifier(
            api_key=os.environ["TYPESAFE_API_KEY"], model=os.getenv("JEV_MODEL", "jev-1.14.0"),
            timeout=self.classifier_timeout)
        self.extractor = extractor or SmallModelClient(
            [(os.getenv("SMALL_LLM_PRIMARY_URL", ""), os.getenv("SMALL_LLM_PRIMARY_PROTOCOL", "openai"), os.getenv("SMALL_LLM_PRIMARY_MODEL", os.getenv("SMALL_LLM_MODEL", "llama3.2:3b")), os.getenv("SMALL_LLM_PRIMARY_API_KEY_FILE", "")),
             (os.getenv("SMALL_LLM_SECONDARY_URL", ""), os.getenv("SMALL_LLM_SECONDARY_PROTOCOL", "openai"), os.getenv("SMALL_LLM_SECONDARY_MODEL", "llama3.2-3b"), os.getenv("SMALL_LLM_SECONDARY_API_KEY_FILE", ""))],
            model=os.getenv("SMALL_LLM_MODEL", "llama3.2:3b"),
            timeout=float(os.getenv("SMALL_LLM_DEADLINE_MS", "2500")) / 1000,
        )
        self._inflight = set()
        self._laya_owners = deque(maxlen=64)

    def record(self, event, turn, **fields):
        if self.timing_observer:
            self.timing_observer.record(event, turn=turn, router_model=self.router_model, **fields)

    def span(self, phase, turn):
        return self.diagnostics.span(phase, turn=turn, router_model=self.router_model) if self.diagnostics else nullcontext()

    async def setup(self, setup):
        await super().setup(setup)
        await self.classifier.setup(self.task_manager)

    async def cleanup(self):
        await self.classifier.cleanup()
        await self.extractor.close()
        await super().cleanup()

    def _question(self):
        """Classifier question: tool groups for the group schema, flat tools otherwise."""
        if self.group_mode:
            from group_schema import GROUP_CRITERIA
            return {"intent": ChoiceQuestion(
                instructions="Select the single group of tools that can serve this utterance; "
                             "if it is plain conversation needing no tool, choose chitchat",
                options=GROUP_CRITERIA)}
        return {"intent": ChoiceQuestion(
            instructions="Select one supported command only when explicit and singular; otherwise other",
            options=OPTIONS)}

    async def _speak(self, text):
        await self.push_frame(TTSSpeakFrame(text=text))

    async def _execute_tool(self, tool, args, text, route_turn, classifier_fields, started,
                            owner, extraction="direct", extraction_s=0.0):
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
            if self.router_model == "laya" and not isinstance(spoken, str):
                raise ValueError("Invalid tool receipt")
            self.record("route_tool", route_turn, tool=tool, **classifier_fields,
                        extraction=extraction, extraction_s=extraction_s, mcp_s=mcp_s,
                        router_s=time.monotonic() - started)
            if owner is not None:
                owner["owner"] = "handled"
            await self._speak(spoken)
            logger.info("Fast route {}: {}={:.3f}s {}={:.3f}s mcp={:.3f}s total={:.3f}s",
                        tool, self.router_model, classifier_fields.get("classifier_s", 0.0),
                        extraction, extraction_s, mcp_s, time.monotonic() - started)
        finally:
            self._inflight.discard(receipt)

    async def _dispatch_group(self, group, text, frame, route_turn, classifier_fields, started, owner):
        """Tier-2/3/4 dispatch after the classifier has picked a group."""
        from group_schema import GROUP_TOOLS, FAST_GROUPS, CHITCHAT
        if group in FAST_TOOLS:
            # explicit-route bypass handed us a specific tool (e.g. add_reminder)
            args = direct_arguments(group, text)
            if args is not None and validate_arguments(group, args):
                await self._execute_tool(group, args, text, route_turn, classifier_fields, started, owner)
                return
            tool, args = await self.extractor.extract_group([group], text)
            if tool is not None:
                await self._execute_tool(tool, args, text, route_turn, classifier_fields, started, owner,
                                         extraction="group_llama")
                return
        elif group in (CHITCHAT, "small_talk"):
            reply_started = time.monotonic()
            with self.span("small_model_reply", route_turn):
                answer = await self.extractor.answer(text)
            if answer:
                self.record("route_smalltalk", route_turn, **classifier_fields,
                            llama_s=time.monotonic() - reply_started)
                if owner is not None:
                    owner["owner"] = "handled"
                await self._speak(answer)
                return
        elif group in FAST_GROUPS:
            tools = GROUP_TOOLS[group]
            # tier 2a: deterministic grammar over each candidate tool
            for tool in tools:
                args = direct_arguments(tool, text)
                if args is not None and validate_arguments(tool, args):
                    await self._execute_tool(tool, args, text, route_turn, classifier_fields, started, owner)
                    return
            # tier 2b: narrowed small-model extraction
            extraction_started = time.monotonic()
            tool, args = await self.extractor.extract_group(tools, text)
            extraction_s = time.monotonic() - extraction_started
            self.record("argument_result", route_turn, tool=tool or group, extraction="group_llama",
                        extraction_s=extraction_s, valid=tool is not None)
            if tool is not None:
                await self._execute_tool(tool, args, text, route_turn, classifier_fields, started, owner,
                                         extraction="group_llama", extraction_s=extraction_s)
                return
            logger.info("Group {} unresolved after direct + llama; escalating", group)
        # knowledge / workspace / unresolved -> escalate to the tool-bearing LLM
        self.record("route_glm", route_turn, classifier_s=classifier_fields.get("classifier_s", 0.0),
                    router_s=time.monotonic() - started)
        if owner is not None:
            owner["owner"] = "glm"
        await self.push_frame(frame, direction=FrameDirection.DOWNSTREAM)

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if direction != FrameDirection.DOWNSTREAM or not isinstance(frame, LLMContextFrame) or frame.speculation:
            await self.push_frame(frame, direction)
            return
        text = latest_user_text(frame.context)
        if not text:
            await self.push_frame(frame, direction)
            return
        route_turn = self.timing_observer.turn if self.timing_observer else None
        owner = None
        if self.router_model == "laya":
            message = next(m for m in reversed(frame.context.get_messages())
                           if isinstance(m, dict) and m.get("role") == "user"
                           and isinstance(m.get("content"), str))
            owner = next((entry for entry in self._laya_owners if entry["message"] is message), None)
            if owner is not None:
                if owner["owner"] == "glm":
                    # Tool-result continuations retain cloud ownership and history.
                    await self.push_frame(frame, direction)
                return
            owner = {"message": message, "owner": "routing"}
            self._laya_owners.append(owner)
        if _multiple_actions(text):
            self.record("route_glm", route_turn, reason="multiple_actions", router_s=0.0, classifier_s=0.0)
            logger.info("Multiple actions routed to GLM")
            if owner is not None:
                owner["owner"] = "glm"
            await self.push_frame(frame, direction)
            return
        started = time.monotonic()
        classifier_s = 0.0
        classifier_started = None
        classification_recorded = False
        tool_issued = False
        spec = getattr(self, "spec_layer", None)
        spec_group, spec_conf = (None, 0.0)
        spec_used = False
        if spec is not None:
            spec_group, spec_conf = spec.result
        try:
            tool = explicit_route_hint(text)
            result = None
            # Speculative fast path: during speech the speculator classified a
            # partial transcript. Trust it ONLY for local tool groups, and only
            # when the tier-2 argument grammar validates against the FINAL
            # transcript — a wrong speculation then just falls through to the
            # normal classify path, so it can never fire a wrong tool.
            if (not tool and spec_group
                    and os.getenv("LAYA_SCHEMA", "").strip().lower() == "v2"):
                from group_schema import FAST_GROUPS
                if spec_group in FAST_GROUPS:
                    from laya_router import grounded_arguments
                    from group_schema import GROUP_TOOLS
                    for spec_tool in GROUP_TOOLS[spec_group]:
                        args = grounded_arguments(spec_tool, text)
                        if args is not None and validate_arguments(spec_tool, args):
                            spec_used = True
                            spec.record_outcome(route_turn, spec_group, used=True)
                            self.record("spec_laya_hit", route_turn, group=spec_group,
                                        tool=spec_tool, conf=spec_conf,
                                        **{k: v for k, v in spec.spec_data().items() if k != "group"})
                            await self._execute_tool(spec_tool, args, text, route_turn,
                                                     {"classifier_s": 0.0, self.router_model + "_s": 0.0},
                                                     started, owner, extraction="spec_direct")
                            return
            if not tool:
                classifier_started = time.monotonic()
                with self.span("classifier_client", route_turn):
                    result = (await asyncio.wait_for(self.classifier.choice(
                        {"utterance": text}, self._question(),
                    ), timeout=self.classifier_timeout))["intent"]
                classifier_s = time.monotonic() - classifier_started
                if self.router_model == "laya":
                    if os.getenv("LAYA_SCHEMA", "").strip().lower() == "v2":
                        from laya_contract_v2 import TAU, GAP
                        tool = accepted_group(result, minimum=TAU, gap=GAP)
                    else:
                        from laya_contract import TAU, GAP
                        tool = accepted_route(result, minimum=TAU, gap=GAP)
                elif self.group_mode:
                    tool = accepted_group(result)
                else:
                    tool = accepted_route(result)
                top = float(result.probabilities.get(result.choice, 0))
                next_best = max((float(v) for k, v in result.probabilities.items() if k != result.choice), default=0)
                if spec is not None and spec_group is not None and not spec_used:
                    spec.record_outcome(route_turn, result.choice, used=False)
                server_s = getattr(result, "server_classifier_s", None)
                self.record("classifier_result", route_turn, classifier_s=classifier_s,
                            server_classifier_s=server_s,
                            client_outside_server_s=classifier_s-server_s if server_s is not None else None,
                            raw_choice=result.choice, top_prob=top, gap=top-next_best,
                            fast_route=tool, status="ok", input_scope="latest_utterance")
                classification_recorded = True
            else:
                self.record("classifier_bypass", route_turn, reason="explicit_reminder", classifier_s=0.0)
            classifier_fields = {"classifier_s": classifier_s, self.router_model + "_s": classifier_s}
            if self.group_mode or self.router_model == "laya":
                await self._dispatch_group(tool, text, frame, route_turn, classifier_fields, started, owner)
                return
            if tool == "small_talk":
                reply_started = time.monotonic()
                with self.span("small_model_reply", route_turn):
                    answer = await self.extractor.answer(text)
                if answer:
                    self.record("route_smalltalk", route_turn, **classifier_fields,
                                llama_s=time.monotonic() - reply_started)
                    if owner is not None:
                        owner["owner"] = "handled"
                    await self.push_frame(TTSSpeakFrame(text=answer))
                    logger.info("Small-brain conversation: {}={:.3f}s llama={:.3f}s total={:.3f}s",
                                self.router_model, classifier_s, time.monotonic() - reply_started, time.monotonic() - started)
                    return
            if tool in FAST_TOOLS:
                extraction = "direct"
                parse_started = time.monotonic()
                with self.span("argument_extraction", route_turn):
                    args = direct_arguments(tool, text)
                    if self.router_model == "laya":
                        from laya_router import grounded_arguments
                        args = grounded_arguments(tool, text)
                    elif args is None and tool not in DIRECT_ONLY_TOOLS:
                        args = await self.extractor.extract(tool, text)
                        extraction = "llama"
                parse_s = time.monotonic() - parse_started
                self.record("argument_result", route_turn, tool=tool, extraction=extraction,
                            extraction_s=parse_s, valid=args is not None and validate_arguments(tool, args))
                if args is not None and validate_arguments(tool, args):
                    receipt = (tool, json.dumps(args, sort_keys=True), text)
                    if receipt in self._inflight:
                        return
                    self._inflight.add(receipt)
                    try:
                        mcp_started = time.monotonic()
                        tool_issued = True
                        raw = await self.mcp_client._call_tool_text(tool, args)
                        mcp_s = time.monotonic() - mcp_started
                        try:
                            payload = json.loads(raw)
                        except (TypeError, ValueError):
                            payload = {"spoken": "I couldn't confirm that action. Please check its state before trying again."}
                        spoken = payload.get("spoken") or "I couldn't confirm that action. Please check its state before trying again."
                        if self.router_model == "laya" and not isinstance(spoken, str):
                            raise ValueError("Invalid tool receipt")
                        self.record("route_tool", route_turn, tool=tool, **classifier_fields,
                                    extraction=extraction, extraction_s=parse_s, mcp_s=mcp_s,
                                    router_s=time.monotonic() - started)
                        if owner is not None:
                            owner["owner"] = "handled"
                        await self.push_frame(TTSSpeakFrame(text=spoken))
                        logger.info("Fast route {}: {}={:.3f}s {}={:.3f}s mcp={:.3f}s total={:.3f}s",
                                    tool, self.router_model, classifier_s, extraction, parse_s, mcp_s, time.monotonic() - started)
                        return
                    finally:
                        self._inflight.discard(receipt)
                logger.info("Fast route {} lacked validated arguments; GLM after {:.3f}s", tool, time.monotonic() - started)
            else:
                logger.info("Route {} sent to GLM after {:.3f}s confidence={:.3f}",
                            result.choice if result else "other", time.monotonic() - started,
                            result.probabilities.get(result.choice, 0.0) if result else 0.0)
        except Exception as exc:
            if self.router_model == "laya" and tool_issued:
                owner["owner"] = "handled"
                self.record("route_tool_uncertain", route_turn, tool=tool,
                            classifier_s=classifier_s, error=type(exc).__name__,
                            router_s=time.monotonic()-started)
                await self.push_frame(TTSSpeakFrame(text="I couldn't confirm that command's outcome. Please check its state before repeating it."))
                return
            if classifier_started is not None and not classification_recorded:
                classifier_s = time.monotonic() - classifier_started
                self.record("classifier_failure", route_turn, classifier_s=classifier_s,
                            status="timeout" if isinstance(exc, TimeoutError) else "error", error=type(exc).__name__)
            logger.warning("Fast route fell back to GLM: {}", type(exc).__name__)
        except asyncio.CancelledError:
            if owner is not None:
                owner["owner"] = "cancelled"
            self.record("router_cancelled", route_turn, classifier_s=(time.monotonic()-classifier_started)
                        if classifier_started is not None and not classification_recorded else classifier_s,
                        stage="classifier" if classifier_started is not None and not classification_recorded else "after_classifier")
            raise
        self.record("route_glm", route_turn, classifier_s=classifier_s, router_s=time.monotonic() - started)
        if owner is not None:
            owner["owner"] = "glm"
        await self.push_frame(frame, direction)
