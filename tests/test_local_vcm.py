"""Local-only isolation, context, and execution contract checks."""

import json
import os
import sys
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))
from local_vcm import LocalVCMClient, LocalVCMProcessor
from pipecat.frames.frames import LLMContextFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection


class LocalVCMTests(unittest.IsolatedAsyncioTestCase):
    def context(self, text):
        messages = [{"role": "user", "content": text}]
        return SimpleNamespace(get_messages=lambda: messages, add_message=messages.append)

    async def run_decision(self, decision, text="Turn on the lights"):
        mcp = SimpleNamespace(_call_tool_text=AsyncMock(return_value='{"ok":true,"spoken":"Lights on."}'))
        model = SimpleNamespace(decide=AsyncMock(return_value=decision))
        processor = LocalVCMProcessor(mcp, model=model)
        processor.push_frame = AsyncMock()
        frame = LLMContextFrame(context=self.context(text))
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
        return processor, mcp, model, frame

    async def test_single_endpoint_and_conversation_reach_model(self):
        seen = []
        def respond(request):
            seen.append(request)
            return httpx.Response(200, json={"choices": [{"message": {"content":
                '{"tool":"set_alarm","arguments":{"time_str":"09:00 PM"}}'}}]})
        with patch.dict(os.environ, {"SMALL_LLM_PRIMARY_URL": "http://thinkpad.test",
                                     "SMALL_LLM_SECONDARY_URL": "http://vps.test"}):
            client = LocalVCMClient()
        self.assertEqual(len(client.endpoints), 1)
        await client.client.aclose()
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        messages = [{"role": "user", "content": "Set an alarm for nine"},
                    {"role": "assistant", "content": "AM or PM?"},
                    {"role": "user", "content": "PM"}]
        decision = await client.decide(SimpleNamespace(get_messages=lambda: messages))
        self.assertEqual(decision["arguments"], {"time_str": "09:00 PM"})
        body = json.loads(seen[0].content)
        self.assertIn("Voice of Pi", body["messages"][0]["content"])
        self.assertEqual(body["messages"][1:], messages)
        self.assertIn("anyOf", body["response_format"]["json_schema"]["schema"])
        self.assertNotIn("play_radio", json.dumps(body))
        await client.close()

    async def test_primary_transport_failure_never_contacts_secondary(self):
        hosts = []
        def fail(request):
            hosts.append(request.url.host)
            raise httpx.ConnectError("offline")
        with patch.dict(os.environ, {"SMALL_LLM_PRIMARY_URL": "http://thinkpad.test",
                                     "SMALL_LLM_SECONDARY_URL": "http://vps.test"}):
            client = LocalVCMClient()
        await client.client.aclose()
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
        self.assertIsNone(await client.decide(self.context("time now")))
        self.assertEqual(hosts, ["thinkpad.test"])
        await client.close()

    async def test_tool_executes_once_without_second_model_call_or_context_forward(self):
        processor, mcp, model, frame = await self.run_decision(
            {"tool": "control_lights", "arguments": {"action": "on", "value": ""}})
        mcp._call_tool_text.assert_awaited_once_with("control_lights", {"action": "on", "value": ""})
        model.decide.assert_awaited_once()
        self.assertIsInstance(processor.push_frame.call_args.args[0], TTSSpeakFrame)
        # A post-result context push must not execute the preceding request again.
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
        mcp._call_tool_text.assert_awaited_once()

    async def test_unsupported_invalid_or_unavailable_model_never_executes(self):
        for decision in [None, {"tool": "send_message", "arguments": {}},
                         {"tool": "play_radio", "arguments": {"query": "news"}},
                         {"tool": "set_thermostat", "arguments": {"degrees": 99}}]:
            with self.subTest(decision=decision):
                processor, mcp, _, _ = await self.run_decision(decision)
                mcp._call_tool_text.assert_not_awaited()
                self.assertIsInstance(processor.push_frame.call_args.args[0], TTSSpeakFrame)

    async def test_clarification_is_spoken_without_tool(self):
        processor, mcp, _, _ = await self.run_decision(
            {"tool": "reply", "arguments": {"text": "What temperature would you like?"}},
            "Set the thermostat")
        mcp._call_tool_text.assert_not_awaited()
        self.assertEqual(processor.push_frame.call_args.args[0].text, "What temperature would you like?")

    async def test_tool_failure_is_uncertain_and_never_retried(self):
        model = SimpleNamespace(decide=AsyncMock(return_value={"tool": "set_timer", "arguments": {"duration_s": 60}}))
        mcp = SimpleNamespace(_call_tool_text=AsyncMock(side_effect=TimeoutError))
        processor = LocalVCMProcessor(mcp, model=model)
        processor.push_frame = AsyncMock()
        await processor.process_frame(LLMContextFrame(context=self.context("Set a one minute timer")), FrameDirection.DOWNSTREAM)
        mcp._call_tool_text.assert_awaited_once()
        self.assertIn("couldn't confirm", processor.push_frame.call_args.args[0].text)

    async def test_remote_weather_is_not_silently_defaulted(self):
        _, mcp, _, _ = await self.run_decision({"tool": "get_weather", "arguments": {}},
                                              "What is the weather in Cebu?")
        mcp._call_tool_text.assert_not_awaited()

    async def test_wrong_but_schema_valid_light_action_is_not_executed(self):
        _, mcp, _, _ = await self.run_decision(
            {"tool": "control_lights", "arguments": {"action": "on", "value": ""}},
            "Set the lights to blue")
        mcp._call_tool_text.assert_not_awaited()

    async def test_compound_command_does_not_execute_partial_action(self):
        _, mcp, _, _ = await self.run_decision(
            {"tool": "control_lights", "arguments": {"action": "off", "value": ""}},
            "Stop music and turn off the lights")
        mcp._call_tool_text.assert_not_awaited()

    async def test_radio_cannot_be_executed_as_music(self):
        _, mcp, _, _ = await self.run_decision(
            {"tool": "play_music", "arguments": {"query": "news radio"}}, "Play news radio")
        mcp._call_tool_text.assert_not_awaited()

    async def test_reminder_preserves_user_case_after_model_capitalization(self):
        _, mcp, _, _ = await self.run_decision(
            {"tool": "add_reminder", "arguments": {"text": "Study"}}, "Remind me to study")
        mcp._call_tool_text.assert_awaited_once_with("add_reminder", {"text": "study"})

    async def test_music_search_cannot_be_misrouted_to_skip(self):
        _, mcp, _, _ = await self.run_decision(
            {"tool": "playback_control", "arguments": {"action": "next"}}, "Play some jazz music")
        mcp._call_tool_text.assert_not_awaited()

    async def test_vps_only_uses_secondary_model_and_key(self):
        seen = []
        def respond(request):
            seen.append(request)
            return httpx.Response(200, json={"choices": [{"message": {"content":
                '{"tool":"get_time","arguments":{}}'}}]})
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "key"
            key.write_text("test-only-key\n")
            with patch.dict(os.environ, {
                "LOCAL_VCM_MODEL_HOST": "vps", "SMALL_LLM_PRIMARY_URL": "http://thinkpad.test",
                "SMALL_LLM_SECONDARY_URL": "http://vps.test",
                "SMALL_LLM_SECONDARY_MODEL": "llama3.2-3b",
                "SMALL_LLM_SECONDARY_API_KEY_FILE": str(key),
            }):
                client = LocalVCMClient()
            self.assertEqual(len(client.endpoints), 1)
            await client.client.aclose()
            client.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            self.assertEqual(await client.decide(self.context("Time now")),
                             {"tool": "get_time", "arguments": {}})
            self.assertEqual(seen[0].url.host, "vps.test")
            self.assertEqual(seen[0].headers["authorization"], "Bearer test-only-key")
            self.assertEqual(json.loads(seen[0].content)["model"], "llama3.2-3b")
            await client.close()

    async def test_vps_failure_never_uses_thinkpad(self):
        hosts = []
        def fail(request):
            hosts.append(request.url.host)
            raise httpx.ConnectError("offline")
        with patch.dict(os.environ, {
            "LOCAL_VCM_MODEL_HOST": "vps", "SMALL_LLM_PRIMARY_URL": "http://thinkpad.test",
            "SMALL_LLM_SECONDARY_URL": "http://vps.test", "SMALL_LLM_SECONDARY_API_KEY_FILE": "",
        }):
            client = LocalVCMClient()
        await client.client.aclose()
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
        self.assertIsNone(await client.decide(self.context("Time now")))
        self.assertEqual(hosts, ["vps.test"])
        await client.close()

    async def test_invalid_host_does_not_silently_select_a_model(self):
        with patch.dict(os.environ, {"LOCAL_VCM_MODEL_HOST": "vpz"}):
            with self.assertRaises(ValueError):
                LocalVCMClient()
