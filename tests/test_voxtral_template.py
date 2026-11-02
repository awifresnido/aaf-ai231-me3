"""Verify that served prompts retain audio and never inject the wrong agent role."""

from pathlib import Path
import hashlib
import unittest

import jinja2


class VoxtralTemplateTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(__file__).resolve().parents[1] / "deploy/jetson/voxtral-chat.jinja"
        self.template = jinja2.Environment().from_string(self.path.read_text())

    def test_audio_precedes_transcription_instruction(self):
        rendered = self.template.render(messages=[{"role": "user", "content": [
            {"type": "media_marker", "text": "AUDIO_MARKER"},
            {"type": "text", "text": "Transcribe exactly."}]}])
        self.assertEqual(rendered, '<s>[INST]AUDIO_MARKERTranscribe exactly.[/INST]')
        self.assertNotIn('Devstral', rendered)

    def test_small_model_instruction_is_merged_into_user_turn(self):
        rendered = self.template.render(messages=[
            {"role": "system", "content": "Reply in one short sentence."},
            {"role": "user", "content": "Hello"}])
        self.assertEqual(rendered, '<s>[INST]Reply in one short sentence.\n\nHello[/INST]')

    def test_assistant_history_is_terminated(self):
        rendered = self.template.render(messages=[{"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"}, {"role": "user", "content": "Thanks"}])
        self.assertEqual(rendered, '<s>[INST]Hi[/INST]Hello</s>[INST]Thanks[/INST]')

    def test_normalized_template_matches_the_server_contract(self):
        self.assertEqual(hashlib.sha256(self.path.read_text().strip().encode()).hexdigest(),
            '3faa7f0b8d012e01c58769d7ca81a8a87719acc57b59588afbfa47cee0e66dec')
