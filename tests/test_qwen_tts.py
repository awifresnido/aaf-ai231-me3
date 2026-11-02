"""Qwen raw PCM transport and native Pipecat direct/LLM-text lifecycle."""

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
from qwen_tts import QwenTTSService
from pipecat.frames.frames import (EndFrame, ErrorFrame, LLMFullResponseEndFrame,
    LLMFullResponseStartFrame, TextFrame, TTSAudioRawFrame, TTSSpeakFrame, TTSStoppedFrame)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.workers.runner import WorkerRunner


class QwenTransportTests(unittest.IsolatedAsyncioTestCase):
    def service(self, handler):
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.aclose)
        timing=SimpleNamespace(turn=5,diagnostics=None,record=Mock())
        with patch.dict(os.environ,{"DGX_API_KEY":"test-private-key","DGX_TTS_VOICE":"vivian"}):
            service=QwenTTSService(client=client,timing_observer=timing)
        for name in ['start_ttfb_metrics','stop_ttfb_metrics','start_tts_usage_metrics']:
            setattr(service,name,AsyncMock())
        return service,timing

    async def test_request_and_pcm_are_bound_to_native_audio_context(self):
        seen=[]
        def respond(request):
            seen.append(request)
            return httpx.Response(200,headers={"Content-Type":"audio/pcm"},content=b'\x01\x00'*960)
        service,timing=self.service(respond)
        self.assertIsNone(service._settings.language)
        frames=[frame async for frame in service.run_tts("Synthetic receipt.","ctx-test")]
        body=json.loads(seen[0].content)
        self.assertTrue(body['stream'])
        self.assertEqual(body['stream_format'],'audio')
        self.assertEqual(body['response_format'],'pcm')
        self.assertEqual(body['voice'],'vivian')
        self.assertEqual(body['sample_rate'],24000)
        self.assertEqual(seen[0].headers['authorization'],'Bearer test-private-key')
        self.assertTrue(all(isinstance(f,TTSAudioRawFrame) for f in frames))
        self.assertEqual(b''.join(f.audio for f in frames),b'\x01\x00'*960)
        self.assertTrue(all(f.context_id=='ctx-test' and f.sample_rate==24000 for f in frames))
        self.assertEqual([c.args[0] for c in timing.record.call_args_list],['tts_qwen_first_audio','tts_qwen_complete'])

    async def test_first_audio_precedes_full_http_completion(self):
        release=asyncio.Event()
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'\x01\x00'*480
                await release.wait()
                yield b'\x02\x00'*480
        service,timing=self.service(lambda _:httpx.Response(200,headers={'Content-Type':'audio/pcm'},stream=Stream()))
        generator=service.run_tts('Synthetic streaming sentence.','stream-ctx')
        first=await asyncio.wait_for(anext(generator),1)
        self.assertIsInstance(first,TTSAudioRawFrame)
        self.assertFalse(release.is_set())
        self.assertEqual(timing.record.call_args.args[0],'tts_qwen_first_audio')
        release.set()
        remainder=[f async for f in generator]
        self.assertTrue(remainder)
        self.assertEqual(timing.record.call_args.args[0],'tts_qwen_complete')

    async def test_http_or_invalid_audio_fails_without_retry(self):
        cases=[(401,'application/json',b'{}'),(200,'application/json',b'{}'),
               (200,'audio/pcm',b''),(200,'audio/pcm',b'x'),(200,'audio/pcm',b'RIFF'+b'\0'*960)]
        for status,media,body in cases:
            seen=[]
            def respond(request):
                seen.append(request)
                return httpx.Response(status,headers={'Content-Type':media},content=body)
            service,timing=self.service(respond)
            frames=[f async for f in service.run_tts('Synthetic sentence.','ctx')]
            self.assertEqual(len(seen),1)
            self.assertIsInstance(frames[-1],ErrorFrame)
            self.assertFalse(any(isinstance(f,TTSAudioRawFrame) for f in frames))
            self.assertEqual(timing.record.call_args.args[0],'tts_qwen_failure')

    async def test_interruption_cancels_stream_without_retry_or_completion(self):
        entered=asyncio.Event()
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'\0'*960
                entered.set()
                await asyncio.Event().wait()
        service,timing=self.service(lambda _:httpx.Response(200,headers={'Content-Type':'audio/pcm'},stream=Stream()))
        generator=service.run_tts('Synthetic sentence.','ctx')
        await anext(generator)
        task=asyncio.create_task(anext(generator))
        await asyncio.wait_for(entered.wait(),1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(timing.record.call_args.args[0],'tts_qwen_cancelled')

    async def test_empty_text_never_contacts_server(self):
        handler=Mock()
        service,_=self.service(handler)
        self.assertEqual([f async for f in service.run_tts('   ','ctx')],[])
        handler.assert_not_called()

    async def test_missing_credentials_rejected_at_construction(self):
        with patch.dict(os.environ,{'DGX_API_KEY':''}),self.assertRaises(ValueError):QwenTTSService()


class QwenPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, frames):
        class Sink(FrameProcessor):
            def __init__(self):
                super().__init__();self.audio=[];self.finished=asyncio.Event()
            async def process_frame(self,frame,direction):
                await super().process_frame(frame,direction)
                if isinstance(frame,TTSAudioRawFrame):self.audio.append(frame)
                if isinstance(frame,TTSStoppedFrame):self.finished.set()
                await self.push_frame(frame,direction)
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(
            200,headers={'Content-Type':'audio/pcm'},content=b'\0'*1920)))
        with patch.dict(os.environ,{'DGX_API_KEY':'test-only-key'}):service=QwenTTSService(client=client)
        sink=Sink();worker=PipelineWorker(Pipeline([service,sink]),params=PipelineParams(enable_metrics=True),idle_timeout_secs=None)
        runner=WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
        task=asyncio.create_task(runner.run())
        try:
            await worker.queue_frames(frames)
            await asyncio.wait_for(sink.finished.wait(),5)
            self.assertTrue(sink.audio)
            self.assertTrue(all(f.context_id for f in sink.audio))
            await worker.queue_frames([EndFrame()])
            await asyncio.wait_for(task,5)
        finally:
            if not task.done():
                await runner.cancel()
                await asyncio.gather(task,return_exceptions=True)
            await client.aclose()

    async def test_direct_spoken_receipt_reaches_audio_context(self):
        await self.exercise([TTSSpeakFrame(text='A synthetic tool receipt.')])

    async def test_glm_text_response_reaches_audio_context(self):
        await self.exercise([LLMFullResponseStartFrame(),TextFrame('A synthetic GLM sentence.'),LLMFullResponseEndFrame()])
