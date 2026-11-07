"""Optional Laya decision client. Route confidence never supplies tool arguments."""

import asyncio
from contextlib import nullcontext
import os
import re
import time

import httpx

from laya_contract import CONTRACT, gate
from orchestration import _NUMBER, _multiple_actions, direct_arguments, validate_arguments


def grounded_arguments(tool, text):
    """Conservative whole-command grammar plus existing parsers and validators.

    In particular, the existing empty argument parsers are not intent checks.
    No LLM extraction fills missing values on this experimental fast path.
    """
    text = text.strip().strip(".?!").strip()
    text = re.sub(r"^(?:please\s+|(?:can|could|would) you\s+)", "", text, flags=re.I)
    text = re.sub(r",?\s+please$", "", text, flags=re.I)
    if _multiple_actions(text) or re.search(
        r"\b(?:and|then|also)\b.*\b(?:lower|raise|increase|decrease|dim|switch|list|show)\b", text, re.I
    ):
        return None
    number = rf"(?:{_NUMBER})"
    patterns = {
        "get_time": r"(?:what time is it(?: now)?|what(?:'s| is) (?:the )?(?:current |local )?time(?: now)?|tell me (?:the )?(?:current |local )?time|time(?: now)?)",
        "list_reminders": r"(?:list|show|read)(?: me)? (?:my|the|all(?: my)?) reminders|what (?:are|were) my reminders",
        "get_weather": r"(?:what(?:'s| is) (?:the )?(?:current |local )?weather(?: like)?(?: (?:today|now))?|how(?:'s| is) the weather(?: today)?|(?:check|tell me) (?:the )?(?:current |local )?weather)",
        "set_thermostat": rf"set (?:the |my )?(?:thermostat|(?:room )?temperature) to {number}(?: degrees(?: celsius)?| celsius)?",
        "control_lights": rf"(?:(?:turn|switch) (?:the |my )?lights? (?:on|off)|(?:turn|switch) (?:on|off) (?:the |my )?lights?|(?:set|turn|make) (?:the |my )?lights? (?:to )?(?:red|blue|green)|(?:set|turn|make) (?:the |my )?(?:light )?brightness to {number}(?: percent|%)|(?:set|turn|make) (?:the |my )?lights? to {number}(?: percent|%)(?: brightness)?)",
        "set_timer": rf"(?:set|start)(?: me)? (?:a |the )?(?:timer for {number} (?:seconds?|minutes?|hours?)|{number}[ -](?:seconds?|minutes?|hours?) timer)",
        "set_alarm": rf"(?:set|start)(?: me)? (?:an? |the )?alarm (?:for |at ){number}(?::[0-5]\d)?\s*(?:am|pm)",
        "add_reminder": r"(?:remind me to|(?:add|create|set|make) (?:a )?reminder (?:to|for|that)) .+",
        "playback_control": r"(?:(?:stop|pause|resume|continue|skip) (?:the |my )?(?:music|song|track|playback)|(?:skip to |play )?(?:the )?next (?:song|track)|(?:turn|set|raise|lower|increase|decrease) (?:the )?(?:music )?volume(?: (?:up|down))?)",
        "play_music": r"(?:play|put on|listen to) .+",
    }
    if tool not in patterns or not re.fullmatch(patterns[tool], text, re.I):
        return None
    if tool in {"add_reminder", "play_music"} and re.search(
        r"\b(?:and|then|also)\b.*\b(?:set|turn|play|stop|send|call|lower|raise)\b", text, re.I
    ):
        return None
    # The timer parser expects whitespace, not a hyphen, between number/unit.
    parse_text = re.sub(r"(?<=\w)-(?=seconds?\b|minutes?\b|hours?\b)", " ", text, flags=re.I)
    args = direct_arguments(tool, parse_text)
    return args if args is not None and validate_arguments(tool, args) else None


class LayaDecisionClient:
    def __init__(self, *, conversation=None, timing_observer=None):
        if os.getenv("LOCAL_VCM_MODEL_HOST", "thinkpad").strip().lower() != "thinkpad":
            raise ValueError("Laya trial requires ThinkPad-local conversation; cloud fallback is disabled")
        self.policy = os.getenv("LAYA_FALLBACK_POLICY", "clarify")
        if self.policy not in {"clarify", "llama_reply"}:
            raise ValueError("LAYA_FALLBACK_POLICY must be clarify or llama_reply")
        self.url = os.getenv("LAYA_ROUTER_URL", "http://127.0.0.1:18082").rstrip("/")
        self.timeout = float(os.getenv("LAYA_ROUTER_TIMEOUT_SECS", "2"))
        self.client = httpx.AsyncClient(timeout=self.timeout, trust_env=False)
        if conversation is None:
            from local_vcm import LocalVCMClient
            conversation = LocalVCMClient()
        self.conversation = conversation
        self.model_host = "thinkpad_laya"
        self.timing = timing_observer
        self.diagnostics = getattr(timing_observer, "diagnostics", None)

    def record(self, event, **fields):
        if self.timing:
            self.timing.record(event, turn=self.timing.turn, **fields)

    def span(self, phase):
        return self.diagnostics.span(phase, turn=self.timing.turn) if self.diagnostics else nullcontext()

    async def decide(self, context):
        text = context.get_messages()[-1]["content"]
        started = time.monotonic()
        reason = "route_unavailable"
        try:
            with self.span("classifier_client"):
                response = await asyncio.wait_for(
                    self.client.post(self.url + "/classify", json={"text": text}), self.timeout)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or payload.get("contract") != CONTRACT:
                    raise ValueError("Laya contract mismatch")
                route = gate({"choice": payload.get("raw_choice"),
                              "probabilities": payload.get("probabilities")})
            self.record("laya_classification", classifier_s=time.monotonic() - started,
                        server_classifier_s=payload.get("classifier_s"),
                        **{k: v for k, v in route.items() if k != "probabilities"})
            tool = route["route"]
            if route["accepted"] and tool not in {"other", "small_talk"}:
                args_started = time.monotonic()
                with self.span("argument_validation"):
                    args = grounded_arguments(tool, text)
                self.record("laya_arguments", tool=tool, valid=args is not None,
                            extraction="direct", extraction_s=time.monotonic() - args_started)
                if args is not None:
                    return {"tool": tool, "arguments": args}
                # A failed argument check never re-enters a model tool decision.
                return self.reply(self.clarification(tool))
            reason = "abstained" if not route["accepted"] else tool
        except (httpx.HTTPError, TimeoutError, ValueError, TypeError, KeyError):
            self.record("laya_classification_failure", classifier_s=time.monotonic() - started)
            return self.reply("The local router is unavailable. Please try again.")
        if re.fullmatch(r"(?:can|could) you hear (?:me|my voice)[.?!]*", text.strip(), re.I):
            return self.reply("Yes, I can hear you.")
        if reason == "small_talk" or self.policy == "llama_reply":
            fallback_started = time.monotonic()
            with self.span("model_fallback"):
                answer = await self.conversation.answer(text)
            self.record("laya_local_reply", reason=reason, fallback_s=time.monotonic() - fallback_started)
            if answer:
                return self.reply(answer)
        self.record("laya_clarification", reason=reason)
        return self.reply("Please give one basic command with its required details.")

    @staticmethod
    def reply(text):
        return {"tool": "reply", "arguments": {"text": text}}

    @staticmethod
    def clarification(tool):
        return {
            "set_thermostat": "What temperature from sixteen to thirty two degrees Celsius would you like?",
            "control_lights": "Please give one light action: on, off, red, blue, green, or a brightness percentage.",
            "set_timer": "What duration should I use for the timer?",
            "set_alarm": "What alarm time would you like, including AM or PM?",
            "add_reminder": "What exact note should I add to your reminders?",
            "get_weather": "I can check current local weather only in this trial.",
        }.get(tool, "Please repeat one basic command with its required details.")

    async def close(self):
        await self.client.aclose()
        await self.conversation.close()
