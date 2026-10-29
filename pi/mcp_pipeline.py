"""Pipecat processors for the MCP speech path (Option A behind a switch).

MCPSTTService:
  SegmentedSTTService subclass — Pipecat buffers user audio while VAD
  says the user is speaking and hands us a WAV segment per utterance.
  We call the ASR MCP server's transcribe() tool and emit a
  TranscriptionFrame.

MCPTTSService:
  TTSService subclass — Pipecat splits LLM text into sentences and calls
  run_tts(text, context_id) per sentence. We call the TTS MCP server's
  synthesize() tool and yield TTSAudioRawFrame(s).

Both servers are spawned as subprocesses (stdio transport) and kept alive
for the lifetime of the bot.
"""
import asyncio
import base64
import io
import json
import os
import time
import wave
from typing import AsyncGenerator

from loguru import logger

from pipecat.frames.frames import ErrorFrame, TranscriptionFrame, TTSAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.tts_service import TTSService
from pipecat.utils.time import time_now_iso8601

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

VENV_PY = os.getenv("VENV_PY", "/home/aldwinrpi4/pipecat-quickstart/server/.venv/bin/python")
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ASR_SERVER = os.path.join(_THIS_DIR, "mcp_servers", "asr_mcp_server.py")
TTS_SERVER = os.path.join(_THIS_DIR, "mcp_servers", "tts_mcp_server.py")


class MCPSTTService(SegmentedSTTService):
    """Per-utterance ASR via MCP (one VAD-bounded turn at a time)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._session = None
        self._client_cm = None
        self._session_cm = None

    async def run_stt(self, audio: bytes) -> AsyncGenerator[TranscriptionFrame | ErrorFrame, None]:
        """Pipecat hands us a WAV container per VAD-bounded utterance."""
        try:
            session = await self._get_session()
            wav_b64 = base64.b64encode(audio).decode()
            t0 = time.time()
            result = await session.call_tool("transcribe", {"audio_wav_b64": wav_b64})
            elapsed_ms = (time.time() - t0) * 1000
            data = json.loads(result.content[0].text)
            text = data.get("text", "").strip()
            logger.debug(f"MCPSTT: transcript=[{text}] roundtrip_ms={elapsed_ms:.0f} asr_ms={data.get('asr_ms')}")
            if data.get("error"):
                logger.error(f"MCPSTT error: {data['error']}")
            if text:
                yield TranscriptionFrame(text, self._user_id, time_now_iso8601())
        except Exception as e:
            logger.error(f"MCPSTT failed: {e}")
            yield ErrorFrame(f"MCPSTT failed: {e}")

    async def _get_session(self) -> ClientSession:
        if self._session is None:
            params = StdioServerParameters(command=VENV_PY, args=[ASR_SERVER])
            self._client_cm = stdio_client(params)
            read, write = await self._client_cm.__aenter__()
            self._session_cm = ClientSession(read, write)
            self._session = await self._session_cm.__aenter__()
            await self._session.initialize()
            logger.info("MCPSTT: session established")
        return self._session


class MCPTTSService(TTSService):
    """Per-sentence TTS via MCP (non-streaming)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._session = None
        self._client_cm = None
        self._session_cm = None

    @staticmethod
    def _wav_b64_to_pcm(wav_b64: str) -> bytes:
        raw = base64.b64decode(wav_b64)
        with wave.open(io.BytesIO(raw), "rb") as f:
            return f.readframes(f.getnframes())

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[TTSAudioRawFrame | ErrorFrame, None]:
        try:
            session = await self._get_session()
            t0 = time.time()
            result = await session.call_tool("synthesize", {"text": text})
            elapsed_ms = (time.time() - t0) * 1000
            data = json.loads(result.content[0].text)
            if data.get("error"):
                logger.error(f"MCPTTS error: {data['error']}")
                yield ErrorFrame(f"MCPTTS error: {data['error']}")
                return
            wav_b64 = data["audio_wav_b64"]
            rate = data["sample_rate"]
            pcm = self._wav_b64_to_pcm(wav_b64)
            logger.debug(f"MCPTTS: text=[{text[:40]}] roundtrip_ms={elapsed_ms:.0f} tts_ms={data.get('tts_ms')} samples={len(pcm)//2}")
            yield TTSAudioRawFrame(audio=pcm, sample_rate=rate, num_channels=1, context_id=context_id)
        except Exception as e:
            logger.error(f"MCPTTS failed: {e}")
            yield ErrorFrame(f"MCPTTS failed: {e}")

    async def _get_session(self) -> ClientSession:
        if self._session is None:
            params = StdioServerParameters(command=VENV_PY, args=[TTS_SERVER])
            self._client_cm = stdio_client(params)
            read, write = await self._client_cm.__aenter__()
            self._session_cm = ClientSession(read, write)
            self._session = await self._session_cm.__aenter__()
            await self._session.initialize()
            logger.info("MCPTTS: session established")
        return self._session
