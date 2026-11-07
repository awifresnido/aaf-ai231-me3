"""Audio-language transcription contract and native segmented STT lifecycle."""

import asyncio
import base64
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))
from qwen_audio_stt import QwenAudioSTTService, TRANSCRIBE_PROMPT
from pipecat.frames.frames import (EndFrame, ErrorFrame, InputAudioRawFrame,
    StartFrame, TranscriptionFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.workers.runner import WorkerRunner


def wav_bytes(rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate)
        wav.writeframes(b"\x01\x00" * (rate // 4))
    return buf.getvalue()


def completion(text="Turn on the lights.", **choice):
    return {"choices": [{"message": {"content": text}, "finish_reason": "stop", **choice}]}


class QwenAudioTests(unittest.IsolatedAsyncioTestCase):
    def service(self, handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.aclose)
        timing = SimpleNamespace(turn=5, diagnostics=None, record=Mock())
        with patch.dict(os.environ, {"DGX_API_KEY": "test-private-key"}):
            service = QwenAudioSTTService(client=client, timing_observer=timing)
        return service, timing

    async def test_audio_chat_request_and_finalized_transcript(self):
        seen = []
        def handler(request):
            seen.append(request)
            return httpx.Response(200, json=completion())
        service, timing = self.service(handler)
        audio = wav_bytes()
        frames = [f async for f in service.run_stt(audio)]
        self.assertEqual(len(frames), 1)
        self.assertIsInstance(frames[0], TranscriptionFrame)
        self.assertTrue(frames[0].finalized)
        self.assertEqual(frames[0].text, "Turn on the lights.")
        body = json.loads(seen[0].content)
        self.assertFalse(body['stream'])
        self.assertEqual(body['temperature'], 0)
        parts = body['messages'][0]['content']
        self.assertEqual(parts[0]['text'], TRANSCRIBE_PROMPT)
        self.assertEqual(base64.b64decode(parts[1]['input_audio']['data']), audio)
        self.assertEqual(seen[0].headers['authorization'], 'Bearer test-private-key')
        self.assertEqual([c.args[0] for c in timing.record.call_args_list],
                         ['asr_qwen2_start', 'asr_qwen2_complete'])

    async def test_no_speech_does_not_create_a_user_message(self):
        for text in ['', '[NO_SPEECH]']:
            service, timing = self.service(lambda _: httpx.Response(200, json=completion(text)))
            self.assertEqual([f async for f in service.run_stt(wav_bytes())], [])
            self.assertEqual(timing.record.call_args.args[0], 'asr_qwen2_no_speech')

    async def test_legitimate_apology_is_preserved_as_speech(self):
        service, _ = self.service(lambda _: httpx.Response(200, json=completion("I'm sorry I am late.")))
        frames = [f async for f in service.run_stt(wav_bytes())]
        self.assertEqual(frames[0].text, "I'm sorry I am late.")

    async def test_invalid_audio_never_calls_the_provider(self):
        seen = []
        for data in [b'not WAV', wav_bytes(24000)]:
            service, _ = self.service(lambda r: seen.append(r))
            frames = [f async for f in service.run_stt(data)]
            self.assertIsInstance(frames[-1], ErrorFrame)
        self.assertFalse(seen)

    async def test_bad_or_truncated_responses_fail_without_retry(self):
        cases = [(401, {}), (200, {}), (200, completion('partial', finish_reason='length')),
                 (200, completion(None)), (200, {'choices': []}),
                 (200, completion(message={'content': 'done', 'tool_calls': [{'id': 'x'}]}))]
        for status, payload in cases:
            seen = []
            def handler(request):
                seen.append(request)
                return httpx.Response(status, json=payload)
            service, timing = self.service(handler)
            frames = [f async for f in service.run_stt(wav_bytes())]
            self.assertEqual(len(seen), 1)
            self.assertIsInstance(frames[-1], ErrorFrame)
            self.assertEqual(timing.record.call_args.args[0], 'asr_qwen2_failure')

    async def test_captured_turn_survives_a_later_user_turn(self):
        service, timing = self.service(lambda _: httpx.Response(200, json=completion()))
        service._segment_metadata.append((7, 3, 0))
        frames = [f async for f in service.run_stt(wav_bytes())]
        self.assertEqual(timing.record.call_args.kwargs['turn'], 3)
        self.assertEqual(timing.record.call_args.kwargs['segment_id'], 7)
        self.assertTrue(frames)

    async def test_cancellation_is_not_retried_or_reported_complete(self):
        entered = asyncio.Event()
        async def handler(_):
            entered.set()
            await asyncio.Event().wait()
        service, timing = self.service(handler)
        async def collect(): return [f async for f in service.run_stt(wav_bytes())]
        task = asyncio.create_task(collect())
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(timing.record.call_args.args[0], 'asr_qwen2_cancelled')

    async def test_missing_key_is_rejected(self):
        with patch.dict(os.environ, {'DGX_API_KEY': ''}):
            with self.assertRaises(ValueError): QwenAudioSTTService()


class QwenNativeSegmentationTests(unittest.IsolatedAsyncioTestCase):
    service = QwenAudioTests.service

    async def test_vad_segment_transcribes_off_the_audio_path(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def handler(_):
            entered.set()
            await release.wait()
            return httpx.Response(200, json=completion())
        service, _ = self.service(handler)
        class Sink(FrameProcessor):
            def __init__(self):
                super().__init__(); self.ready = asyncio.Event(); self.transcribed = asyncio.Event()
                self.audio = 0; self.transcripts = []
            async def process_frame(self, frame, direction):
                await super().process_frame(frame, direction)
                if isinstance(frame, StartFrame): self.ready.set()
                if isinstance(frame, InputAudioRawFrame): self.audio += 1
                if isinstance(frame, TranscriptionFrame):
                    self.transcripts.append(frame); self.transcribed.set()
                await self.push_frame(frame, direction)
        sink = Sink()
        worker = PipelineWorker(Pipeline([service, sink]),
            params=PipelineParams(enable_metrics=True), idle_timeout_secs=None)
        runner = WorkerRunner(handle_sigint=False); await runner.add_workers(worker)
        task = asyncio.create_task(runner.run())
        try:
            await asyncio.wait_for(sink.ready.wait(), 5)
            await worker.queue_frames([VADUserStartedSpeakingFrame(),
                InputAudioRawFrame(b'\x01\x00'*8000, 16000, 1),
                VADUserStoppedSpeakingFrame(stop_secs=.3)])
            await asyncio.wait_for(entered.wait(), 3)
            await worker.queue_frames([InputAudioRawFrame(b'\x02\x00'*320, 16000, 1)])
            for _ in range(50):
                if sink.audio >= 2: break
                await asyncio.sleep(.01)
            self.assertGreaterEqual(sink.audio, 2)
            self.assertFalse(sink.transcripts)
            release.set(); await asyncio.wait_for(sink.transcribed.wait(), 3)
            self.assertTrue(sink.transcripts[0].finalized)
            await worker.queue_frames([EndFrame()]); await asyncio.wait_for(task, 5)
        finally:
            if not task.done():
                await runner.cancel(); await asyncio.gather(task, return_exceptions=True)
