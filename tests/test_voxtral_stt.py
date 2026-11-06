"""Voxtral endpoint configuration, audio ordering and serving contract checks."""

import base64
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))
from voxtral_stt import VoxtralSTTService, VOXTRAL_MODEL
from pipecat.frames.frames import ErrorFrame, TranscriptionFrame
from test_qwen_audio_stt import wav_bytes, completion


class VoxtralSTTTests(unittest.IsolatedAsyncioTestCase):
    def service(self, handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.aclose)
        timing = SimpleNamespace(turn=4, diagnostics=None, record=Mock())
        with patch.dict(os.environ, {'DGX_API_KEY': 'unrelated-private-key',
                                    'DGX_ASR_MODEL': 'wrong-qwen-model', 'VOXTRAL_API_KEY': ''}):
            service = VoxtralSTTService(client=client, timing_observer=timing)
        return service, timing

    async def test_audio_first_request_has_no_dgx_key_or_chat_answer_prompt(self):
        seen = []
        def handler(req):
            seen.append(req)
            return httpx.Response(200, json=completion('What time is it?'))
        service, timing = self.service(handler)
        data = wav_bytes()
        frames = [f async for f in service.run_stt(data)]
        self.assertIsInstance(frames[0], TranscriptionFrame)
        self.assertEqual(frames[0].text, 'What time is it?')
        body = json.loads(seen[0].content)
        self.assertEqual(body['model'], VOXTRAL_MODEL)
        self.assertNotIn('authorization', seen[0].headers)
        parts = body['messages'][0]['content']
        self.assertEqual(parts[0]['type'], 'input_audio')
        self.assertEqual(base64.b64decode(parts[0]['input_audio']['data']), data)
        self.assertEqual(parts[1]['text'], 'Transcribe the audio exactly. Output only the spoken words.')
        self.assertEqual(timing.record.call_args.args[0], 'asr_voxtral_complete')
        self.assertEqual(timing.record.call_args.kwargs['asr_backend'], 'voxtral_mini')

    async def test_truncated_transcription_fails_without_retry(self):
        seen = []
        def handler(req):
            seen.append(req)
            return httpx.Response(200, json=completion('incomplete', finish_reason='length'))
        service, timing = self.service(handler)
        frames = [f async for f in service.run_stt(wav_bytes())]
        self.assertEqual(len(seen), 1)
        self.assertIsInstance(frames[-1], ErrorFrame)
        self.assertEqual(timing.record.call_args.args[0], 'asr_voxtral_failure')

    async def test_expected_template_and_model_are_verified(self):
        template = (Path(__file__).resolve().parents[1] / 'deploy/jetson/voxtral-chat.jinja').read_text()
        def handler(req):
            return httpx.Response(200, json={'chat_template': template, 'modalities': {'audio': True}}
                if req.url.path == '/props' else {'data': [{'id': VOXTRAL_MODEL}]})
        service, _ = self.service(handler)
        await service.validate_server()

    async def test_wrong_template_or_model_is_rejected_before_transcription(self):
        template = (Path(__file__).resolve().parents[1] / 'deploy/jetson/voxtral-chat.jinja').read_text()
        for bad_template, bad_model in [(True, False), (False, True)]:
            def handler(req):
                return httpx.Response(200, json={'chat_template': 'Devstral' if bad_template else template,
                    'modalities': {'audio': True}} if req.url.path == '/props'
                    else {'data': [{'id': 'wrong' if bad_model else VOXTRAL_MODEL}]})
            service, _ = self.service(handler)
            with self.assertRaises(ValueError): await service.validate_server()
