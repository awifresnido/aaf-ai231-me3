"""Route confidence, argument grounding, transport isolation and write replay."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))
from laya_contract import CONTRACT, QUESTIONS_PATH, ROUTES, BUNDLED_QUESTION_SHA256, gate
from laya_router import LayaDecisionClient, grounded_arguments
from local_vcm import LocalVCMProcessor
from pipecat.frames.frames import LLMContextFrame
from pipecat.processors.frame_processor import FrameDirection


def answer(tool, top=0.99):
    probs = dict.fromkeys(ROUTES, (1 - top) / (len(ROUTES) - 1))
    probs[tool] = top
    return {"choice": tool, "probabilities": probs}


class ContractTests(unittest.TestCase):
    def test_trained_questions_are_pinned(self):
        self.assertEqual(hashlib.sha256(QUESTIONS_PATH.read_bytes()).hexdigest(), BUNDLED_QUESTION_SHA256)

    def test_both_inclusive_gate_boundaries(self):
        data = answer("get_time", 0.5)
        data["probabilities"] = dict.fromkeys(ROUTES, 0.005)
        data["probabilities"].update(get_time=0.5, other=0.45)
        self.assertTrue(gate(data)["accepted"])
        data["probabilities"].update(get_time=0.4999, other=0.4501)
        self.assertFalse(gate(data)["accepted"])
        data["probabilities"].update(get_time=0.5001, other=0.4502, small_talk=0.0047)
        self.assertFalse(gate(data)["accepted"])

    def test_malformed_distributions_fail_closed(self):
        for value in [float("nan"), float("inf"), -0.1, 2, True, "0.99"]:
            data = answer("get_time")
            data["probabilities"]["get_time"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                gate(data)
        for data in [{}, {"choice": "send_message", "probabilities": {}},
                     {"choice": "get_time", "probabilities": {"get_time": 1}},
                     {**answer("other"), "choice": "get_time"}]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                gate(data)

    def test_grounding_preserves_all_ten_tool_contracts(self):
        cases = [
            ("get_time", "What time is it now?", {}),
            ("get_weather", "What is the weather like today?", {}),
            ("list_reminders", "List my reminders", {}),
            ("add_reminder", "Remind me to Review Laya's Results", {"text": "Review Laya's Results"}),
            ("set_thermostat", "Set the room temperature to twenty eight degrees", {"degrees": 28}),
            ("control_lights", "Set the lights to blue", {"action": "color", "value": "Blue"}),
            ("control_lights", "Turn off the lights", {"action": "off", "value": ""}),
            ("control_lights", "Set the lights to eighty percent brightness", {"action": "brightness", "value": "80"}),
            ("set_timer", "Set a five-minute timer", {"duration_s": 300}),
            ("set_alarm", "Set an alarm for nine PM", {"time_str": "09:00 PM"}),
            ("playback_control", "Stop the music", {"action": "stop"}),
            ("play_music", "Play some jazz music", {"query": "jazz"}),
        ]
        for tool, text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(grounded_arguments(tool, text), expected)

    def test_schema_valid_but_ungrounded_routes_cannot_execute(self):
        cases = [
            ("get_time", "Can you hear me?"), ("get_time", "zqx blarg forty six"),
            ("get_time", "What is today's date?"),
            ("set_thermostat", "Set the thermostat"),
            ("set_thermostat", "Set the thermostat to 99"),
            ("set_thermostat", "Set the thermostat to 26 Fahrenheit"),
            ("set_thermostat", "Do not set the thermostat to 26"),
            ("control_lights", "Turn the lights green and lower the volume"),
            ("control_lights", "Turn the lights on and off"),
            ("control_lights", "Can you control the lights?"),
            ("control_lights", "Set the lights to purple"),
            ("set_timer", "Set a timer"), ("set_timer", "Set a 1.5 minute timer"),
            ("set_timer", "Set a one hour and thirty minute timer"),
            ("set_alarm", "Set an alarm for nine"),
            ("set_alarm", "Set an alarm tomorrow at nine AM"),
            ("get_weather", "What is the weather in Cebu?"),
            ("get_weather", "What is the weather tomorrow?"),
            ("play_music", "Play the radio"),
            ("playback_control", "Play some jazz music"),
        ]
        for tool, text in cases:
            with self.subTest(text=text):
                self.assertIsNone(grounded_arguments(tool, text))


class ClientTests(unittest.IsolatedAsyncioTestCase):
    def context(self, text):
        messages = [{"role": "user", "content": text}]
        return SimpleNamespace(get_messages=lambda: messages, add_message=messages.append)

    async def client(self, payload=None, handler=None, **env):
        conversation = SimpleNamespace(answer=AsyncMock(return_value="Hello."), close=AsyncMock())
        with patch.dict(os.environ, {"LOCAL_VCM_MODEL_HOST": "thinkpad", "LAYA_FALLBACK_POLICY": "clarify", **env}):
            client = LayaDecisionClient(conversation=conversation)
        await client.client.aclose()
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(
            handler or (lambda _: httpx.Response(200, json=payload))))
        self.addAsyncCleanup(client.close)
        return client

    def payload(self, tool):
        data = answer(tool)
        return {"raw_choice": tool, "probabilities": data["probabilities"], "contract": CONTRACT}

    async def test_no_argument_model_needed_for_tool(self):
        client = await self.client(self.payload("control_lights"))
        result = await client.decide(self.context("Set the lights to blue"))
        self.assertEqual(result, {"tool": "control_lights", "arguments": {"action": "color", "value": "Blue"}})
        client.conversation.answer.assert_not_awaited()

    async def test_high_confidence_does_not_invent_missing_value(self):
        client = await self.client(self.payload("set_thermostat"), LAYA_FALLBACK_POLICY="llama_reply")
        result = await client.decide(self.context("Set the thermostat"))
        self.assertEqual(result["tool"], "reply")
        client.conversation.answer.assert_not_awaited()

    async def test_abstention_recomputed_even_if_server_claims_accepted(self):
        data = self.payload("get_time")
        data.update(accepted=True, probabilities=dict.fromkeys(ROUTES, 1 / len(ROUTES)))
        client = await self.client(data)
        self.assertEqual((await client.decide(self.context("What time is it?")))["tool"], "reply")
        client.conversation.answer.assert_not_awaited()

    async def test_invalid_contract_and_transport_never_escalate(self):
        def timeout(_):
            raise httpx.ReadTimeout("test")
        def malformed(_):
            return httpx.Response(200, text="not json")
        for payload, handler in [(None, timeout), (None, malformed),
                                  ({**self.payload("get_time"), "contract": {}}, None)]:
            client = await self.client(payload, handler, LAYA_FALLBACK_POLICY="llama_reply")
            self.assertEqual((await client.decide(self.context("time now")))["tool"], "reply")
            client.conversation.answer.assert_not_awaited()

    async def test_total_deadline_cancels_slow_classification_without_model_fallback(self):
        async def slow(_):
            await asyncio.sleep(1)
            return httpx.Response(200, json=self.payload("control_lights"))
        client = await self.client(handler=slow, LAYA_FALLBACK_POLICY="llama_reply")
        client.timeout = .01
        decision = await client.decide(self.context("Turn on the lights"))
        self.assertEqual(decision["tool"], "reply")
        client.conversation.answer.assert_not_awaited()

    async def test_smalltalk_only_calls_local_conversation(self):
        client = await self.client(self.payload("small_talk"))
        self.assertEqual((await client.decide(self.context("Hello")))["arguments"], {"text": "Hello."})
        client.conversation.answer.assert_awaited_once_with("Hello")

    async def test_hearing_check_is_not_time(self):
        client = await self.client(self.payload("other"))
        for text in ["Can you hear me?", "Can you hear my voice?"]:
            self.assertEqual((await client.decide(self.context(text)))["arguments"],
                             {"text": "Yes, I can hear you."})

    async def test_cloud_policy_and_vps_selection_are_rejected(self):
        for env in [{"LAYA_FALLBACK_POLICY": "cloud"}, {"LOCAL_VCM_MODEL_HOST": "vps"}]:
            with patch.dict(os.environ, env), self.assertRaises(ValueError):
                LayaDecisionClient()

    async def test_uncertain_write_context_is_consumed_once(self):
        model = await self.client(self.payload("set_timer"))
        mcp = SimpleNamespace(_call_tool_text=AsyncMock(side_effect=TimeoutError))
        with patch.dict(os.environ, {"ROUTER_MODEL": "laya"}):
            processor = LocalVCMProcessor(mcp, model=model)
        processor.push_frame = AsyncMock()
        context = self.context("Set a one minute timer")
        frame = LLMContextFrame(context=context)
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
        mcp._call_tool_text.assert_awaited_once_with("set_timer", {"duration_s": 60})
        self.assertIn("couldn't confirm", processor.push_frame.call_args.args[0].text)

    async def test_invalid_receipt_is_uncertain_and_not_retried(self):
        model = await self.client(self.payload("control_lights"))
        mcp = SimpleNamespace(_call_tool_text=AsyncMock(return_value='[]'))
        with patch.dict(os.environ, {"ROUTER_MODEL": "laya"}):
            processor = LocalVCMProcessor(mcp, model=model)
        processor.push_frame = AsyncMock()
        frame = LLMContextFrame(context=self.context("Turn on the lights"))
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
        mcp._call_tool_text.assert_awaited_once()
        self.assertIn("couldn't confirm", processor.push_frame.call_args.args[0].text)

    async def test_concurrent_context_and_cancelled_write_never_reissue(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def pending_write(*_):
            entered.set()
            await release.wait()
            return '{"ok":true,"spoken":"Timer set."}'

        model = await self.client(self.payload("set_timer"))
        mcp = SimpleNamespace(_call_tool_text=AsyncMock(side_effect=pending_write))
        with patch.dict(os.environ, {"ROUTER_MODEL": "laya"}):
            processor = LocalVCMProcessor(mcp, model=model)
        processor.push_frame = AsyncMock()
        frame = LLMContextFrame(context=self.context("Set a one minute timer"))
        task = asyncio.create_task(processor.process_frame(frame, FrameDirection.DOWNSTREAM))
        await asyncio.wait_for(entered.wait(), 2)
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
        mcp._call_tool_text.assert_awaited_once()
