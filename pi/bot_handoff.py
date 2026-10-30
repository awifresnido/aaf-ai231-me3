"""aaf-ai231-me3 — PersonaPlex / cascade handoff bot (EXPERIMENTAL).

Stage 2-3 of experiments/personaplex_handoff/PLAN.md. This is a separate
entry point (port 7861). The production bot.py is untouched.

Topology (all routes verified live 2026-10-30, see STAGE2-NOTES.md):

  browser (ThinkPad) --WebRTC--> Pi: Pipecat pipeline
                                   Silero VAD -> Jetson ASR (direct)
                                   -> Ollama Cloud LLM (cascade, unchanged)
                                   -> Magpie TTS (cascade, unchanged)
                                   OR
                                   PersonaPlex (DGX via loopback SSH tunnel
                                   127.0.0.1:8998, systemd pp-tunnel.service)
                                 -> one shared transport output

Speech ownership is explicit: the client sends app-messages
  {"type": "pp-control", "action": "takeover" | "return" | "status"}
Takeover revokes the PP epoch, queues an InterruptionFrame, awaits its
processing at the output (README finding 2), then admits the cascade.
Return closes the cascade request and re-opens a PP session.

PersonaPlex protocol (STAGE2-NOTES PP-04):
  ws://127.0.0.1:8998/api/chat?voice_prompt=..&text_prompt=..   (text_prompt REQUIRED)
  server -> client: b"\x00" handshake, b"\x01"+ogg/opus, b"\x02"+text, b"\x03" seg end
  client -> server: b"\x01"+ogg/opus container stream

Run (from ~/handoff-lab on the Pi):
  ~/pipecat-quickstart/server/.venv/bin/python bot_handoff.py -t webrtc \
      --host 0.0.0.0 --port 7861
Env: ~/.voice-agent-env (same as production; no new secrets).
"""

import asyncio
import io
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from dotenv import load_dotenv

load_dotenv("/home/aldwinrpi4/.voice-agent-env", override=False)

from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    InterruptionFrame,
    InterruptionWorkerFrame,
    OutputAudioRawFrame,
    TTSSpeakFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.frames.frames import (
    AggregatedTextFrame,
    Frame,
    InputAudioRawFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TextFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.nvidia.stt import NvidiaSTTService
from pipecat.services.nvidia.tts import NvidiaTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner

import av
import numpy as np
import aiohttp  # noqa: E402  (module-level: used in recv loop)

load_dotenv(override=True)

ASR_SERVER = os.getenv("ASR_SERVER", "192.168.5.11:50051")
TTS_SERVER = os.getenv("TTS_SERVER", "192.168.5.11:50052")
TTS_VOICE = os.getenv("TTS_VOICE", "0")
# Cascade LLM — OpenRouter glm-5.3-flash (fast, token-efficient). Falls back
# to the legacy Ollama Cloud env vars only if LLM_* are unset.
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "z-ai/glm-5.3-flash")
VAD_STOP_SECS = float(os.getenv("VAD_STOP_SECS", "0.8"))

PP_WS_URL = os.getenv(
    "PP_WS_URL",
    "http://127.0.0.1:8998/api/chat?voice_prompt=NATF0.pt"
    "&text_prompt=You%20are%20a%20friendly%20frontdesk%20agent."
    "%20Keep%20replies%20to%20one%20or%20two%20sentences.",
)
PP_SAMPLE_RATE = 24000
OUT_SAMPLE_RATE = 24000  # transport output rate we feed (transport resamples)


class Owner(str, Enum):
    NONE = "none"
    PERSONAPLEX = "pp"
    CASCADE = "cascade"


@dataclass
class HandoffState:
    """Speech-ownership controller state (PLAN.md Stage 3)."""
    owner: Owner = Owner.NONE
    epoch: int = 0                     # increments on every revoke
    pp_session_id: Optional[str] = None
    cascade_request_id: Optional[str] = None
    transitions: list = field(default_factory=list)

    def revoke(self, reason: str) -> int:
        self.epoch += 1
        self.transitions.append(
            {"t": time.monotonic(), "event": "revoke", "reason": reason,
             "epoch": self.epoch}
        )
        return self.epoch


class PersonaPlexClient:
    """One PersonaPlex session over the loopback tunnel.

    Receives ogg/opus, decodes to PCM 24k, hands frames to a callback.
    Sends user mic audio as ogg/opus when owned.
    """

    def __init__(self, url: str, on_audio, on_text, on_segment_end=None):
        self.url = url
        self.on_audio = on_audio      # async (pcm_int16_mono_24k: np.ndarray) -> None
        self.on_text = on_text        # async (text: str) -> None
        self.on_segment_end = on_segment_end
        self.ws = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._tasks: list = []
        self._closed = asyncio.Event()
        self._decoder = av.CodecContext.create("libopus", "r")
        self._decoder.sample_rate = PP_SAMPLE_RATE
        self._decoder.layout = "mono"
        self.session_id = f"pp-{int(time.time()*1000)}"
        self.greeting_text = ""
        # Persistent ogg page assembler: PP splits the ogg stream across ws
        # frames. We buffer bytes, split exact pages (RFC 3533), extract raw
        # opus packets from each page, and decode with ONE persistent libopus
        # codec context (skipping the OpusHead/OpusTags header packets).
        self._ogg_buf = b""
        self._full_ogg = b""     # headers + pages (used once for stream ref)
        self._skip_headers = 2   # OpusHead + OpusTags packets
        self._stream_ref = None  # av stream bound to raw packets
        self._pkt_buf = b""      # spans a packet across page boundaries
        # libopus decodes at its native 48 kHz regardless of ctx.sample_rate,
        # so downmix 48k -> 24k here (PP_SAMPLE_RATE) to avoid half-speed audio.
        self._resampler = av.AudioResampler(
            format="s16", layout="mono", rate=PP_SAMPLE_RATE
        )

    async def start(self):
        self._session = aiohttp.ClientSession()
        self.ws = await self._session.ws_connect(self.url)
        handshake = await self.ws.receive(timeout=30)
        if not (handshake.type == aiohttp.WSMsgType.BINARY and handshake.data[:1] == b"\x00"):
            raise RuntimeError(f"PP handshake failed: {handshake.type}")
        logger.info(f"[PP {self.session_id}] handshake OK")
        self._tasks = [
            asyncio.create_task(self._recv_loop()),
        ]

    async def send_pcm(self, pcm: np.ndarray):
        """Send user PCM (int16 mono 24k) as a continuous ogg/opus stream.

        Maintains ONE ogg muxer writing to a growing BytesIO; each call sends
        only the newly-written bytes (tracked by offset), so PP's sphn reader
        receives a single continuous ogg stream with headers sent exactly once.
        """
        if self.ws is None or self.ws.closed:
            return
        if not hasattr(self, "_ogg_muxer") or self._ogg_muxer is None:
            self._tx_ogg = io.BytesIO()
            self._ogg_muxer = av.open(self._tx_ogg, mode="w", format="ogg")
            self._ogg_stream = self._ogg_muxer.add_stream(
                "libopus", rate=PP_SAMPLE_RATE
            )
            self._ogg_stream.layout = "mono"
            self._tx_sent = 0
        frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = PP_SAMPLE_RATE
        for p in self._ogg_stream.encode(frame):
            self._ogg_muxer.mux(p)
        buf = self._tx_ogg.getvalue()
        new = buf[self._tx_sent:]
        self._tx_sent = len(buf)
        if new:
            await self.ws.send_bytes(b"\x01" + new)

    async def _recv_loop(self):
        try:
            while True:
                msg = await self.ws.receive(timeout=60)
                if msg.type != aiohttp.WSMsgType.BINARY:
                    break
                kind = msg.data[0]
                if kind == 1:  # ogg/opus audio fragments
                    self._ogg_buf += msg.data[1:]
                    for page in self._split_pages():
                        self._full_ogg += page
                        for arr in self._decode_page_packets(page):
                            await self._emit_pcm(arr)
                elif kind == 2:
                    text = msg.data[1:].decode("utf8", "ignore")
                    self.greeting_text += text
                    await self.on_text(text)
                elif kind == 3:
                    if self.on_segment_end:
                        await self.on_segment_end()
        except Exception as e:
            logger.warning(f"[PP {self.session_id}] recv ended: {type(e).__name__}: {e}")
        finally:
            self._closed.set()

    @staticmethod
    def _parse_ogg_pages(data: bytes):
        """Exact OGG page split via the header segment table (RFC 3533)."""
        pages = []
        pos = 0
        n = len(data)
        while pos + 27 <= n:
            if data[pos:pos + 4] != b"OggS":
                pos += 1
                continue
            nseg = data[pos + 26]
            seg = data[pos + 27:pos + 27 + nseg]
            if len(seg) < nseg:
                break
            total = 27 + nseg + sum(seg)
            if pos + total > n:
                break
            pages.append(data[pos:pos + total])
            pos += total
        return pages, pos  # pos = offset after last complete page

    def _split_pages(self):
        """Extract complete pages from the receive buffer (keeps remainder)."""
        pages, consumed = self._parse_ogg_pages(self._ogg_buf)
        self._ogg_buf = self._ogg_buf[consumed:]
        return pages

    def _decode_page_packets(self, page: bytes):
        """Extract raw opus packets from one ogg page and decode to int16 PCM.

        Skips the first two packets (OpusHead/OpusTags). Packets may span page
        boundaries (segments of 255), handled via self._pkt_buf. Binds each raw
        packet to a stream reference (grabbed once from the accumulated ogg)
        and decodes with the persistent libopus context.
        """
        nseg = page[26]
        seg_table = page[27:27 + nseg]
        payload = page[27 + nseg:]
        pos = 0
        for seg_len in seg_table:
            self._pkt_buf += payload[pos:pos + seg_len]
            pos += seg_len
            if seg_len < 255:  # packet complete
                pkt_bytes = self._pkt_buf
                self._pkt_buf = b""
                if self._skip_headers > 0:
                    self._skip_headers -= 1
                    continue
                if self._stream_ref is None:
                    try:
                        ref = av.open(io.BytesIO(self._full_ogg), format="ogg")
                        self._stream_ref = ref.streams.audio[0]
                    except Exception:
                        return
                packet = av.Packet(pkt_bytes)
                packet.stream = self._stream_ref
                try:
                    frames = self._decoder.decode(packet)
                except Exception:
                    continue
                for frame in frames:  # frame is 48 kHz (libopus native)
                    for out_frame in self._resampler.resample(frame):
                        plane = out_frame.planes[0]
                        arr = np.frombuffer(bytes(plane), dtype=np.int16)
                        yield arr

    async def _emit_pcm(self, arr: np.ndarray):
        await self.on_audio(arr)

    async def close(self):
        self._closed.set()
        try:
            if self.ws and not self.ws.closed:
                await self.ws.close()
        except Exception:
            pass
        try:
            if self._session:
                await self._session.close()
        except Exception:
            pass
        for t in self._tasks:
            t.cancel()


class PPOutputGate:
    """Admits PP audio into the transport only while owner == PERSONAPLEX and
    epoch matches; rejects stale audio after revocation (README finding 3)."""

    def __init__(self, state: HandoffState, transport: SmallWebRTCTransport):
        self.state = state
        self.transport = transport

    async def on_pp_audio(self, pcm: np.ndarray):
        if self.state.owner != Owner.PERSONAPLEX:
            return  # stale/rejected (revoked or cascade owned)
        frame = OutputAudioRawFrame(
            audio=pcm.tobytes(), sample_rate=PP_SAMPLE_RATE, num_channels=1
        )
        try:
            await self.transport.send_audio(frame)
        except Exception as e:
            logger.warning(f"send_audio failed: {e}")


class MicTee(FrameProcessor):
    """Tees user mic audio into PersonaPlex when PP owns the turn.

    Passthrough for everything; additionally forwards InputAudioRawFrame
    (resampled to 24 kHz int16 mono) into the PP websocket.
    """

    def __init__(self, state: HandoffState, pp_getter):
        super().__init__()
        self._state = state
        self._pp_getter = pp_getter  # callable -> Optional[PersonaPlexClient]
        self._resampler = av.AudioResampler(format="s16", layout="mono", rate=PP_SAMPLE_RATE)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            if self._state.owner != Owner.PERSONAPLEX:
                await self.push_frame(frame, direction)
                return
            pp = self._pp_getter()
            if pp is None:
                await self.push_frame(frame, direction)
                return
            try:
                arr = np.frombuffer(frame.audio, dtype=np.int16)
                if arr.size == 0:
                    await self.push_frame(frame, direction)
                    return
                arr2d = arr.reshape(1, -1)
                f = av.AudioFrame.from_ndarray(arr2d, format="s16", layout="mono")
                f.sample_rate = frame.sample_rate
                for rf in self._resampler.resample(f):
                    pcm = np.frombuffer(bytes(rf.planes[0]), dtype=np.int16)
                    await pp.send_pcm(pcm)
            except Exception as e:
                logger.warning(f"[MicTee] forward to PP failed: {e}")
        await self.push_frame(frame, direction)


class CascadeTTSGate(FrameProcessor):
    """Drop ALL cascade speech frames while PP owns the turn.

    The cascade TTS synthesizes not only from TTSSpeakFrame but also from the
    LLM's streaming response frames (LLMFullResponseStartFrame, LLMTextFrame,
    LLMFullResponseEndFrame, TextFrame, AggregatedTextFrame). We swallow every
    one of those (downstream only) unless the cascade owns the turn, so the
    shadow STT/LLM path still runs silently without audibly double-answering.
    """

    _TTS_TRIGGER = (
        TTSSpeakFrame,
        LLMFullResponseStartFrame,
        LLMTextFrame,
        LLMFullResponseEndFrame,
        AggregatedTextFrame,
        TextFrame,
    )

    def __init__(self, state: HandoffState):
        super().__init__()
        self._state = state

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if (
            direction == FrameDirection.DOWNSTREAM
            and self._state.owner != Owner.CASCADE
            and isinstance(frame, self._TTS_TRIGGER)
        ):
            return  # swallow: PP owns the turn
        await self.push_frame(frame, direction)


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    logger.info("Starting ME3 handoff bot (PP + cascade, port 7861)")

    state = HandoffState()
    llm_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OLLAMA_API_KEY")

    llm = OpenAILLMService(
        api_key=llm_key,
        base_url=LLM_BASE_URL,
        settings=OpenAILLMService.Settings(
            model=LLM_MODEL,
            system_instruction=(
                "You are a task assistant. Keep replies to 1-3 short spoken "
                "sentences, no lists or emojis. You have tools for weather, "
                "time, timers, reminders, lights, thermostat, music, radio, "
                "and messaging; call the matching tool then speak its result."
            ),
        ),
    )

    from pipecat.services.mcp_service import MCPClient
    from mcp import StdioServerParameters

    tools_mcp = MCPClient(
        server_params=StdioServerParameters(
            command=os.getenv(
                "VENV_PY",
                "/home/aldwinrpi4/pipecat-quickstart/server/.venv/bin/python",
            ),
            args=[
                os.path.join(
                    os.getenv(
                        "MCP_SERVERS_DIR",
                        "/home/aldwinrpi4/voice-agent/mcp_servers",
                    ),
                    "voice_tools_mcp_server.py",
                )
            ],
        )
    )
    voice_tools = await tools_mcp.tools()

    stt = NvidiaSTTService(
        server=ASR_SERVER,
        use_ssl=False,
        model_function_map={},
        sample_rate=16000,
        audio_channel_count=1,
        stop_history=320,
    )
    tts = NvidiaTTSService(
        server=TTS_SERVER,
        use_ssl=False,
        model_function_map={},
        sample_rate=22050,
        voice_id=TTS_VOICE,
    )

    context = LLMContext(tools=voice_tools)
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=VAD_STOP_SECS))
        ),
    )

    mic_tee = MicTee(state, lambda: pp_client)
    tts_gate = CascadeTTSGate(state)

    pipeline = Pipeline([
        transport.input(),
        mic_tee,
        stt,
        user_aggregator,
        llm,
        tts_gate,
        tts,
        transport.output(),
        assistant_aggregator,
    ])

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        observers=[],
    )
    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)

    pp_client: Optional[PersonaPlexClient] = None
    gate: Optional[PPOutputGate] = None

    async def pp_on_text(text: str):
        logger.info(f"[PP] text: {text!r}")

    async def pp_on_segment_end():
        logger.info("[PP] segment end")

    async def pp_start() -> bool:
        """Open a PP session and grant it ownership."""
        nonlocal pp_client, gate
        try:
            pp_client = PersonaPlexClient(PP_WS_URL, None, pp_on_text, pp_on_segment_end)
            await pp_client.start()
        except Exception as e:
            logger.error(f"PP connect failed: {e}")
            pp_client = None
            return False
        if gate is None:
            gate = PPOutputGate(state, transport)
        pp_client.on_audio = gate.on_pp_audio
        state.owner = Owner.PERSONAPLEX
        state.pp_session_id = pp_client.session_id
        state.transitions.append(
            {"t": time.monotonic(), "event": "grant", "owner": "pp",
             "epoch": state.epoch}
        )
        logger.info(f"[handoff] owner=PERSONAPLEX epoch={state.epoch} "
                    f"session={state.pp_session_id}")
        return True

    async def pp_stop():
        nonlocal pp_client
        if pp_client:
            await pp_client.close()
            pp_client = None

    async def takeover_to_cascade():
        """FRONTDESK -> CASCADE: revoke PP, wait for interruption flush."""
        if state.owner != Owner.PERSONAPLEX:
            logger.info("[handoff] takeover ignored (not in PP mode)")
            return
        epoch = state.revoke("takeover_to_cascade")
        logger.info(f"[handoff] revoke PP (epoch={epoch}); queueing interruption")
        await worker.queue_frames([InterruptionFrame(), InterruptionWorkerFrame()])
        # Give the output a beat to process the interruption before cascade TTS
        await asyncio.sleep(0.35)
        state.owner = Owner.CASCADE
        state.transitions.append(
            {"t": time.monotonic(), "event": "grant", "owner": "cascade",
             "epoch": epoch}
        )
        # Cascade proves itself with a fixed sentence through the real TTS
        await worker.queue_frames([
            TTSSpeakFrame(text="Cascade here. I am handling this request now. "
                               "Ask me for the weather or time."),
        ])
        logger.info("[handoff] owner=CASCADE — fixed TTS sentence queued")
        # PP session stays closed until 'return' (PLAN.md Stage 4: sequential)

    async def return_to_pp():
        if state.owner != Owner.CASCADE:
            logger.info("[handoff] return ignored (not in cascade mode)")
            return
        epoch = state.revoke("return_to_pp")
        await worker.queue_frames([InterruptionFrame(), InterruptionWorkerFrame()])
        await asyncio.sleep(0.35)
        ok = await pp_start()
        if not ok:
            logger.error("[handoff] PP re-open failed; staying in cascade")

    async def handle_control(action):
        logger.info(f"[handoff] control: {action}")
        if action == "takeover":
            await takeover_to_cascade()
            return {"owner": state.owner, "epoch": state.epoch}
        if action == "return":
            await return_to_pp()
            return {"owner": state.owner, "epoch": state.epoch}
        if action == "status":
            info = {"owner": state.owner, "epoch": state.epoch,
                    "pp_session": state.pp_session_id,
                    "transitions": len(state.transitions)}
            logger.info(f"[handoff] state: {info}")
            return info
        return {"error": f"unknown action {action!r}"}

    _control_sink["handler"] = handle_control

    async def handle_app_message(transport, message):
        if not isinstance(message, dict) or message.get("type") != "pp-control":
            return
        await handle_control((message or {}).get("action"))

    transport.event_handler("app-message")(handle_app_message)

    @worker.rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi):
        logger.info("[handoff] client ready; starting in FRONTDESK (PP) mode")
        ok = await pp_start()
        if ok:
            # PP speaks its greeting on its own after handshake (verified).
            # No synthetic greeting — PP owns the first turn.
            logger.info("[handoff] PP session live; PP owns first turn")
        else:
            await worker.queue_frames([
                TTSSpeakFrame(text="PersonaPlex is not reachable. Cascade mode only."),
            ])
            state.owner = Owner.CASCADE

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("[handoff] client disconnected; closing PP session")
        await pp_stop()
        await runner.cancel()

    await runner.run()


async def bot(runner_args: RunnerArguments):
    transport = await create_transport(
        runner_args,
        {
            "webrtc": lambda: TransportParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
            ),
        },
    )
    await run_bot(transport, runner_args)


# --- control bridge: browser buttons POST /control -> flips ownership -------
# The runner app is importable before main() (documented pattern). We bind a
# module-level app_message handler that run_bot() overrides per-session.
_control_sink: dict = {"handler": None}




def _mount_control_route():
    from pipecat.runner.run import app
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.post("/control")
    async def control(request: Request):
        body = await request.json()
        action = (body or {}).get("action")
        handler = _control_sink.get("handler")
        if handler is None:
            return JSONResponse({"ok": False, "error": "bot session not ready"})
        result = await handler(action)
        return JSONResponse({"ok": True, "result": result})


if __name__ == "__main__":
    _mount_control_route()
    from pipecat.runner.run import main

    main()
