"""Contract checks for fast command routing; no credentials or live tools."""

import sys
import unittest
import json
import tempfile
from unittest.mock import AsyncMock
import httpx
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

from orchestration import SmallModelClient, TwoBrainRouter, accepted_route, direct_arguments, latest_user_text, validate_arguments
from pipecat.frames.frames import LLMContextFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection


class RouteTests(unittest.TestCase):
    def test_high_probability_single_command(self):
        result = SimpleNamespace(choice="control_lights", probabilities={"control_lights": 0.93, "other": 0.07})
        self.assertEqual(accepted_route(result), "control_lights")

    def test_ambiguous_or_unsupported_stays_with_glm(self):
        for result in (
            SimpleNamespace(choice="control_lights", probabilities={"control_lights": 0.88, "other": 0.12}),
            SimpleNamespace(choice="control_lights", probabilities={"control_lights": 0.91, "other": 0.75}),
            SimpleNamespace(choice="other", probabilities={"other": 0.99}),
        ):
            self.assertIsNone(accepted_route(result))

    def test_argument_validation(self):
        self.assertTrue(validate_arguments("set_thermostat", {"degrees": 32}))
        self.assertFalse(validate_arguments("set_thermostat", {"degrees": 35}))
        self.assertFalse(validate_arguments("set_thermostat", {"degrees": "26"}))
        self.assertFalse(validate_arguments("control_lights", {"action": "color", "value": "Purple"}))
        self.assertFalse(validate_arguments("set_timer", {"duration_s": 0}))
        self.assertTrue(validate_arguments("set_alarm", {"time_str": "09:00 PM"}))
        self.assertFalse(validate_arguments("set_alarm", {"time_str": "13:00 PM"}))
        self.assertFalse(validate_arguments("playback_control", {"action": "mute"}))
        self.assertFalse(validate_arguments("add_reminder", {"text": " "}))

    def test_deterministic_extraction(self):
        self.assertEqual(direct_arguments("set_thermostat", "set temperature to 26 degrees"), {"degrees": 26})
        self.assertEqual(direct_arguments("set_timer", "set a 5 minute timer"), {"duration_s": 300})
        self.assertEqual(direct_arguments("control_lights", "make lights green"), {"action": "color", "value": "Green"})
        self.assertIsNone(direct_arguments("set_thermostat", "set temperature to 25 or 26"))
        self.assertEqual(direct_arguments("set_thermostat", "set temperature to seventeen degrees"), {"degrees": 17})
        self.assertEqual(direct_arguments("set_timer", "set a five minute timer"), {"duration_s": 300})
        self.assertEqual(direct_arguments("control_lights", "set lights to eighty percent"), {"action": "brightness", "value": "80"})
        self.assertEqual(direct_arguments("control_lights", "set lights to 80%"), {"action": "brightness", "value": "80"})
        self.assertEqual(direct_arguments("set_alarm", "set an alarm for nine PM"), {"time_str": "09:00 PM"})
        self.assertEqual(direct_arguments("add_reminder", "remind me to study"), {"text": "study"})
        self.assertEqual(direct_arguments("playback_control", "lower the volume of the music"), {"action": "volume_down"})
        self.assertEqual(direct_arguments("playback_control", "stop the music"), {"action": "stop"})
        self.assertEqual(direct_arguments("play_music", "play some jazz music"), {"query": "jazz"})
        self.assertEqual(direct_arguments("get_weather", "what is the weather today"), {})
        self.assertIsNone(direct_arguments("get_weather", "what is the weather tomorrow"))
        self.assertIsNone(direct_arguments("set_alarm", "alarm for nine or ten PM"))
        self.assertIsNone(direct_arguments("playback_control", "stop"))

    def test_latest_user_turn(self):
        context = SimpleNamespace(get_messages=lambda: [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "second"},
        ])
        self.assertEqual(latest_user_text(context), "second")


class ProcessorTests(unittest.IsolatedAsyncioTestCase):
    async def test_llama_cpp_schema_request(self):
        seen = []

        def respond(request):
            seen.append((request.url.path, json.loads(request.content)))
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"tool":"set_thermostat","arguments":{"degrees":26}}'}}]})

        client = SmallModelClient([("http://example.test:8080", "openai")])
        await client.client.aclose()
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        self.assertEqual(await client.extract("set_thermostat", "set to 26 degrees"), {"degrees": 26})
        self.assertEqual(seen[0][0], "/v1/chat/completions")
        self.assertEqual(seen[0][1]["response_format"]["type"], "json_schema")
        await client.close()

    async def test_fallback_uses_vps_model_id(self):
        seen = []

        def respond(request):
            seen.append((json.loads(request.content)["model"], request.headers.get("authorization")))
            if request.url.host == "primary.test":
                raise httpx.ConnectError("offline")
            return httpx.Response(200, json={"choices": [{"message": {"content": "Hello."}}]})

        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "model-key"
            key_file.write_text("test-only-key\n")
            client = SmallModelClient([
                ("http://primary.test:8080", "openai", "llama3.2:3b"),
                ("http://vps.test:18081", "openai", "llama3.2-3b", str(key_file)),
            ])
            await client.client.aclose()
            client.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            self.assertEqual(await client.answer("Hello"), "Hello.")
            self.assertEqual(seen, [("llama3.2:3b", None), ("llama3.2-3b", "Bearer test-only-key")])
            await client.close()

    async def test_fast_tool_speaks_without_glm_call(self):
        result = SimpleNamespace(choice="get_time", probabilities={"get_time": 0.99, "other": 0.01})
        classifier = SimpleNamespace(choice=AsyncMock(return_value={"intent": result}))
        extractor = SimpleNamespace(extract=AsyncMock())
        mcp = SimpleNamespace(_call_tool_text=AsyncMock(return_value='{"ok":true,"spoken":"It is 9 PM."}'))
        router = TwoBrainRouter(mcp, classifier=classifier, extractor=extractor)
        router.push_frame = AsyncMock()
        context = SimpleNamespace(get_messages=lambda: [{"role": "user", "content": "What time is it?"}])
        await router.process_frame(LLMContextFrame(context=context), FrameDirection.DOWNSTREAM)
        frame = router.push_frame.call_args.args[0]
        self.assertIsInstance(frame, TTSSpeakFrame)
        self.assertEqual(frame.text, "It is 9 PM.")
        extractor.extract.assert_not_awaited()

    async def test_uncertain_route_reaches_glm(self):
        result = SimpleNamespace(choice="get_time", probabilities={"get_time": 0.6, "other": 0.4})
        classifier = SimpleNamespace(choice=AsyncMock(return_value={"intent": result}))
        extractor = SimpleNamespace(extract=AsyncMock())
        mcp = SimpleNamespace(_call_tool_text=AsyncMock())
        router = TwoBrainRouter(mcp, classifier=classifier, extractor=extractor)
        router.push_frame = AsyncMock()
        context = SimpleNamespace(get_messages=lambda: [{"role": "user", "content": "Tell me something"}])
        original = LLMContextFrame(context=context)
        await router.process_frame(original, FrameDirection.DOWNSTREAM)
        self.assertIs(router.push_frame.call_args.args[0], original)
        mcp._call_tool_text.assert_not_awaited()

    async def test_forecast_cannot_be_fast_current_weather(self):
        result = SimpleNamespace(choice="get_weather", probabilities={"get_weather": 0.99, "other": 0.01})
        classifier = SimpleNamespace(choice=AsyncMock(return_value={"intent": result}))
        extractor = SimpleNamespace(extract=AsyncMock())
        mcp = SimpleNamespace(_call_tool_text=AsyncMock())
        router = TwoBrainRouter(mcp, classifier=classifier, extractor=extractor)
        router.push_frame = AsyncMock()
        original = LLMContextFrame(context=SimpleNamespace(get_messages=lambda: [{"role": "user", "content": "What is the weather tomorrow?"}]))
        await router.process_frame(original, FrameDirection.DOWNSTREAM)
        self.assertIs(router.push_frame.call_args.args[0], original)
        extractor.extract.assert_not_awaited()
        mcp._call_tool_text.assert_not_awaited()

    async def test_multiple_actions_skip_fast_execution(self):
        classifier = SimpleNamespace(choice=AsyncMock())
        extractor = SimpleNamespace(extract=AsyncMock())
        mcp = SimpleNamespace(_call_tool_text=AsyncMock())
        router = TwoBrainRouter(mcp, classifier=classifier, extractor=extractor)
        router.push_frame = AsyncMock()
        original = LLMContextFrame(context=SimpleNamespace(get_messages=lambda: [{"role": "user", "content": "Stop music and set the thermostat to 20"}]))
        await router.process_frame(original, FrameDirection.DOWNSTREAM)
        self.assertIs(router.push_frame.call_args.args[0], original)
        classifier.choice.assert_not_awaited()
        mcp._call_tool_text.assert_not_awaited()

    async def test_small_talk_uses_small_brain(self):
        result = SimpleNamespace(choice="small_talk", probabilities={"small_talk": 0.97, "other": 0.03})
        classifier = SimpleNamespace(choice=AsyncMock(return_value={"intent": result}))
        extractor = SimpleNamespace(answer=AsyncMock(return_value="Hello there."), extract=AsyncMock())
        mcp = SimpleNamespace(_call_tool_text=AsyncMock())
        router = TwoBrainRouter(mcp, classifier=classifier, extractor=extractor)
        router.push_frame = AsyncMock()
        context = SimpleNamespace(get_messages=lambda: [{"role": "user", "content": "Hello"}])
        await router.process_frame(LLMContextFrame(context=context), FrameDirection.DOWNSTREAM)
        frame = router.push_frame.call_args.args[0]
        self.assertIsInstance(frame, TTSSpeakFrame)
        self.assertEqual(frame.text, "Hello there.")
        mcp._call_tool_text.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
