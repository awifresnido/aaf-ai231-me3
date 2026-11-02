"""Voxtral Mini audio-first transcription on the pinned Jetson trial server."""

import base64
import hashlib

from qwen_audio_stt import QwenAudioSTTService


VOXTRAL_MODEL = "mistralai/Voxtral-Mini-3B-2507"
# llama.cpp strips boundary whitespace when it loads a template file.
TEMPLATE_SHA256 = "3faa7f0b8d012e01c58769d7ca81a8a87719acc57b59588afbfa47cee0e66dec"


class VoxtralSTTService(QwenAudioSTTService):
    MODEL_ENV = "VOXTRAL_MODEL"
    BASE_ENV = "VOXTRAL_BASE"
    TIMEOUT_ENV = "VOXTRAL_ASR_TIMEOUT_SECS"
    KEY_ENV = "VOXTRAL_API_KEY"
    DEFAULT_MODEL = VOXTRAL_MODEL
    DEFAULT_BASE = "http://192.168.5.11:8083"
    KEY_REQUIRED = False
    BACKEND = "voxtral_mini"
    TIMING_PREFIX = "asr_voxtral"
    SERVICE_NAME = "Jetson Voxtral Mini"

    async def validate_server(self):
        headers = {"Authorization": "Bearer " + self.api_key} if self.api_key else {}
        response = await self.client.get(self.base_url + "/props", headers=headers)
        response.raise_for_status()
        props = response.json()
        template = props.get("chat_template")
        if (not isinstance(template, str)
                or hashlib.sha256(template.strip().encode()).hexdigest() != TEMPLATE_SHA256
                or props.get("modalities", {}).get("audio") is not True):
            raise ValueError("Voxtral server must use the pinned audio-capable template")
        response = await self.client.get(self.base_url + "/v1/models", headers=headers)
        response.raise_for_status()
        if not any(m.get("id") == self.model_name for m in response.json().get("data", [])):
            raise ValueError("Voxtral model identity mismatch")

    async def start(self, frame):
        await self.validate_server()
        self.record("asr_voxtral_server_verified", self.timing.turn if self.timing else None,
                    chat_template_sha256=TEMPLATE_SHA256)
        await super().start(frame)

    def request_body(self, audio):
        # This installed runtime answers instead of transcribing when the
        # instruction precedes audio. Keep media first and the task last.
        return {"model": self.model_name, "temperature": 0, "stream": False,
                "max_tokens": 256,
                "messages": [{"role": "user", "content": [{"type": "input_audio",
                    "input_audio": {"data": base64.b64encode(audio).decode(), "format": "wav"}},
                    {"type": "text", "text": "Transcribe the audio exactly. Output only the spoken words."}]}]}
