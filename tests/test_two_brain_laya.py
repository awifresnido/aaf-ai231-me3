"""Laya replacement in the two-brain slot, with explicit GLM continuation."""

import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))
from laya_classifier import LayaClassifier
from laya_contract import CONTRACT, ROUTES
from orchestration import TwoBrainRouter, _direct_chitchat
from pipecat.frames.frames import LLMContextFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection


def result(choice="other", top=.99):
    scores = dict.fromkeys(ROUTES, (1-top)/(len(ROUTES)-1))
    scores[choice] = top
    return SimpleNamespace(choice=choice, probabilities=scores, server_classifier_s=0.0)


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def adapter(self, handler):
        adapter = LayaClassifier()
        await adapter.client.aclose()
        adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(adapter.cleanup)
        return adapter

    async def test_request_uses_only_text_and_pinned_server_contract(self):
        seen=[]
        def respond(request):
            seen.append(request)
            if request.url.path == "/health":
                return httpx.Response(200, json={"ready": True, "contract": CONTRACT})
            value=result("control_lights", .7)
            return httpx.Response(200, json={"raw_choice":value.choice,
                "probabilities":value.probabilities,"contract":CONTRACT,"classifier_s":.01,
                "accepted":False})
        adapter=await self.adapter(respond)
        await adapter.setup(None)
        response=await adapter.choice({"utterance":"Set the lights to blue"},{"changed_question":"ignored"})
        self.assertEqual(json.loads(seen[-1].content), {"text":"Set the lights to blue"})
        self.assertTrue(response["intent"].gate_result["accepted"])
        self.assertEqual(response["intent"].server_classifier_s,.01)

    async def test_bad_contract_or_timing_cannot_be_used(self):
        value=result("get_time")
        for override in [{"contract":{}},{"classifier_s":float("nan")},{"classifier_s":-1}]:
            payload={"raw_choice":value.choice,"probabilities":value.probabilities,
                     "contract":CONTRACT,"classifier_s":.01,**override}
            # Encode NaN as raw response because strict HTTPX JSON forbids it.
            adapter=await self.adapter(lambda _, p=payload: httpx.Response(200,text=json.dumps(p)))
            with self.assertRaises(ValueError):
                await adapter.choice({"utterance":"time now"},{})

    async def test_failed_health_blocks_setup(self):
        adapter=await self.adapter(lambda _:httpx.Response(200,json={"ready":True,"contract":{}}))
        with self.assertRaises(ValueError):await adapter.setup(None)


class RouterTests(unittest.IsolatedAsyncioTestCase):
    def frame(self,text):
        messages=[{"role":"user","content":text}]
        return LLMContextFrame(context=SimpleNamespace(get_messages=lambda:messages,add_message=messages.append))

    def router(self, value, **env):
        classifier=SimpleNamespace(choice=AsyncMock(return_value={"intent":value}))
        extractor=SimpleNamespace(answer=AsyncMock(return_value="Hello."), extract=AsyncMock(), close=AsyncMock())
        mcp=SimpleNamespace(_call_tool_text=AsyncMock(return_value='{"ok":true,"spoken":"Done."}'))
        timing=SimpleNamespace(turn=7,diagnostics=None,record=Mock())
        with patch.dict(os.environ,{"ROUTER_MODEL":"laya",**env}):
            router=TwoBrainRouter(mcp,classifier=classifier,extractor=extractor,timing_observer=timing)
        router.push_frame=AsyncMock()
        return router,classifier,extractor,mcp,timing

    async def test_standalone_connection_questions_use_local_reply(self):
        for text in ("Can you hear me?", "Who are you?", "Are you listening?"):
            router, classifier, extractor, mcp, timing = self.router(result("other"))
            await router.process_frame(self.frame(text), FrameDirection.DOWNSTREAM)
            classifier.choice.assert_not_awaited()
            extractor.answer.assert_awaited_once_with(text)
            mcp._call_tool_text.assert_not_awaited()
            self.assertTrue(any(call.args[0] == "route_smalltalk" for call in timing.record.call_args_list))
        self.assertFalse(_direct_chitchat("Can you hear me and turn on the lights?"))

    async def test_laya_gate_and_timing_fast_path(self):
        router,classifier,extractor,mcp,timing=self.router(result("control_lights",.7))
        frame=self.frame("Set the lights to blue")
        await router.process_frame(frame,FrameDirection.DOWNSTREAM)
        mcp._call_tool_text.assert_awaited_once_with("control_lights",{"action":"color","value":"Blue"})
        extractor.extract.assert_not_awaited()
        events={c.args[0]:c.kwargs for c in timing.record.call_args_list}
        self.assertEqual(events["classifier_result"]["router_model"],"laya")
        self.assertEqual(events["classifier_result"]["server_classifier_s"],0)
        self.assertGreaterEqual(events["classifier_result"]["classifier_s"],0)
        self.assertIn("laya_s",events["route_tool"])
        self.assertNotIn("jev_s",events["route_tool"])
        await router.process_frame(frame,FrameDirection.DOWNSTREAM)
        classifier.choice.assert_awaited_once()
        mcp._call_tool_text.assert_awaited_once()

    async def test_context_reaches_glm_unchanged_and_continuations_skip_classifier(self):
        router,classifier,_,mcp,_=self.router(result("other"))
        frame=self.frame("I want to stay in my room")
        messages=frame.context.get_messages()
        messages.insert(0,{"role":"user","content":"It is very hot today"})
        await router.process_frame(frame,FrameDirection.DOWNSTREAM)
        self.assertIs(router.push_frame.call_args.args[0],frame)
        mcp._call_tool_text.assert_not_awaited()
        self.assertEqual(classifier.choice.call_args.args[0],{"utterance":"I want to stay in my room"})
        messages.append({"role":"tool","content":"stored result"})
        await router.process_frame(frame,FrameDirection.DOWNSTREAM)
        classifier.choice.assert_awaited_once()
        self.assertEqual(router.push_frame.await_count,2)

    async def test_missing_setter_never_uses_example_arguments(self):
        router,_,extractor,mcp,timing=self.router(result("set_thermostat"))
        frame=self.frame("Set the thermostat")
        await router.process_frame(frame,FrameDirection.DOWNSTREAM)
        extractor.extract.assert_not_awaited()
        mcp._call_tool_text.assert_not_awaited()
        self.assertIs(router.push_frame.call_args.args[0],frame)

    async def test_timeout_records_elapsed_and_passes_to_explicit_glm(self):
        router,classifier,_,mcp,timing=self.router(result(),LAYA_ROUTER_TIMEOUT_SECS=".01")
        async def slow(*_):await asyncio.sleep(1)
        classifier.choice.side_effect=slow
        frame=self.frame("The room is dark")
        await router.process_frame(frame,FrameDirection.DOWNSTREAM)
        self.assertIs(router.push_frame.call_args.args[0],frame)
        mcp._call_tool_text.assert_not_awaited()
        failures=[c.kwargs for c in timing.record.call_args_list if c.args[0]=="classifier_failure"]
        self.assertEqual(failures[0]["status"],"timeout")

    async def test_uncertain_write_never_falls_through_or_retries(self):
        router,_,_,mcp,timing=self.router(result("set_timer"))
        mcp._call_tool_text.side_effect=TimeoutError
        frame=self.frame("Set a five minute timer")
        await router.process_frame(frame,FrameDirection.DOWNSTREAM)
        await router.process_frame(frame,FrameDirection.DOWNSTREAM)
        mcp._call_tool_text.assert_awaited_once()
        self.assertEqual(router.push_frame.await_count,1)
        self.assertIsInstance(router.push_frame.call_args.args[0],TTSSpeakFrame)
        self.assertIn("couldn't confirm",router.push_frame.call_args.args[0].text)
        self.assertTrue(any(c.args[0]=="route_tool_uncertain" for c in timing.record.call_args_list))

    async def test_invalid_classifier_payload_cannot_issue_tool(self):
        router,classifier,_,mcp,_=self.router(result())
        classifier.choice.side_effect=ValueError("contract mismatch")
        frame=self.frame("Turn on the lights")
        await router.process_frame(frame,FrameDirection.DOWNSTREAM)
        mcp._call_tool_text.assert_not_awaited()
        self.assertIs(router.push_frame.call_args.args[0],frame)

    async def test_laya_construction_never_creates_jev_or_needs_key(self):
        extractor=SimpleNamespace(close=AsyncMock())
        with patch.dict(os.environ,{"ROUTER_MODEL":"laya"},clear=True), patch("orchestration.JevClassifier") as jev:
            router=TwoBrainRouter(SimpleNamespace(),extractor=extractor)
        jev.assert_not_called()
        self.assertIsInstance(router.classifier,LayaClassifier)
        await router.classifier.cleanup()
