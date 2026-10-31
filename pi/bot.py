"""aaf-ai231-me3 — Pi-side voice agent (M4: MCP speech mode).

Cascaded pipeline on the Raspberry Pi:
  browser (ThinkPad) --WebRTC--> Pi: Silero VAD -> Nemotron ASR (Jetson)
  -> Ollama Cloud LLM -> Magpie TTS (Jetson) -> browser speaker

Audio transports (TRANSPORT_MODE):
  webrtc (default) — the ThinkPad browser carries mic + speaker over WebRTC.
  local — the Pi's own audio hardware. Mic and speaker attach to the Pi, so
    no browser is involved. Defaults to the PulseAudio "pulse" device, i.e.
    whatever the system default sink/source is (on the lab Pi that is the
    JOUNIVO JV801P USB speakerphone). Pin a specific device with
    AUDIO_INPUT_DEVICE / AUDIO_OUTPUT_DEVICE (name substring or "index:N").

Speech backends:
  SPEECH_MODE=direct (default) — NvidiaSTTService/NvidiaTTSService talk to
    the Jetson gRPC containers straight. Streaming ASR partials, TTS TTFA
    ~0.9s.
  SPEECH_MODE=mcp — the same Jetson endpoints reached through two local MCP
    servers (stdio) as per-utterance / per-sentence tool calls. No streaming
    ASR partials; TTS first audio waits for full sentence synthesis. This is
    the Option A benchmark path.

Run on the Pi:
  # browser (ThinkPad) mic + speaker
  ~/pipecat-quickstart/server/.venv/bin/python bot.py -t webrtc --host 0.0.0.0 --port 7860
  # Pi-local mic + speaker (USB speakerphone)
  TRANSPORT_MODE=local ~/pipecat-quickstart/server/.venv/bin/python bot.py
Env: OLLAMA_API_KEY etc. in ~/.voice-agent-env (chmod 600, outside the repo).
"""
import asyncio
import os

from dotenv import load_dotenv

# Optional secure env file on the Pi (chmod 600, outside the repo).
load_dotenv("/home/aldwinrpi4/.voice-agent-env", override=False)

from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.nvidia.stt import NvidiaSTTService
from pipecat.services.nvidia.tts import NvidiaTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.workers.runner import WorkerRunner

load_dotenv(override=True)

SPEECH_MODE = os.getenv("SPEECH_MODE", "direct")
ASR_SERVER = os.getenv("ASR_SERVER", "192.168.5.11:50051")
TTS_SERVER = os.getenv("TTS_SERVER", "192.168.5.11:50052")
TTS_VOICE = os.getenv("TTS_VOICE", "0")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://ollama.com/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:31b")
ORCHESTRATION_MODE = os.getenv("ORCHESTRATION_MODE", "single").strip().lower()

# Pi-local VAD policy: with the Jetson ASR container at stop_history_eou_ms=320,
# finals arrive ~0.6s after speech end. 0.8s VAD silence lets the final land
# inside the turn.
VAD_STOP_SECS = float(os.getenv("VAD_STOP_SECS", "0.8"))

# Audio transport: "webrtc" (browser on the ThinkPad) or "local" (the Pi's own
# sound card). Device specs are matched against PyAudio device names; use
# "index:N" to pin a raw PyAudio index, or a substring such as "JOUNIVO".
TRANSPORT_MODE = os.getenv("TRANSPORT_MODE", "webrtc").strip().lower()
AUDIO_INPUT_DEVICE = os.getenv("AUDIO_INPUT_DEVICE", "pulse")
AUDIO_OUTPUT_DEVICE = os.getenv("AUDIO_OUTPUT_DEVICE", "pulse")

# Backend used for Pi-local playback:
#   pacat   (default) — stream PCM to the OS player; it owns buffering and
#                       plays cleanly on USB speakerphones.
#   pyaudio — Pipecat's built-in PyAudio writer. On the lab Pi this starves
#             the sink (audible stutter / near-silence) even though the same
#             bytes play fine through paplay, hence not the default.
AUDIO_OUTPUT_IMPL = os.getenv("AUDIO_OUTPUT_IMPL", "pacat").strip().lower()
# pacat target buffer; absorbs pipeline jitter on a Pi 4.
PACAT_LATENCY_MS = int(os.getenv("PACAT_LATENCY_MS", "150"))

GREETING_TEXT = (
    "Hello. This is your Raspberry Pi voice agent. "
    "Say something and I will answer."
)


def build_speech_services():
    """Return (stt, tts) for the configured SPEECH_MODE.

    Modes:
      direct — Jetson Nemotron ASR + Magpie TTS over gRPC (streaming).
      mcp    — same Jetson endpoints through local MCP servers (offline,
               per-utterance/per-sentence; smoother onsets, higher latency).
      deepgram — Deepgram cloud STT + TTS over WebSockets (streaming, needs
               DEEPGRAM_API_KEY).
    """
    if SPEECH_MODE == "mcp":
        from mcp_pipeline import MCPSTTService, MCPTTSService
        logger.info("Speech mode: MCP (per-utterance ASR, per-sentence TTS via MCP servers)")
        stt = MCPSTTService()
        tts = MCPTTSService(sample_rate=22050)
        return stt, tts

    if SPEECH_MODE == "deepgram":
        from pipecat.services.deepgram.stt import DeepgramSTTService
        from pipecat.services.deepgram.tts import DeepgramTTSService
        api_key = os.getenv("DEEPGRAM_API_KEY", "")
        if not api_key:
            raise RuntimeError("SPEECH_MODE=deepgram requires DEEPGRAM_API_KEY in ~/.voice-agent-env")
        logger.info("Speech mode: Deepgram (cloud streaming STT+TTS)")
        stt = DeepgramSTTService(api_key=api_key, sample_rate=16000)
        tts = DeepgramTTSService(
            api_key=api_key,
            settings=DeepgramTTSService.Settings(
                voice=os.getenv("DEEPGRAM_TTS_VOICE", "aura-2-thalia-en"),
            ),
        )
        return stt, tts

    logger.info("Speech mode: direct (Jetson Riva gRPC streaming)")
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
    return stt, tts


def _resolve_audio_device(py_audio, spec: str, want_input: bool) -> int:
    """Resolve a device spec ("index:N" or a name substring) to a PyAudio index.

    PyAudio/ALSA indices shift when USB devices are replugged or cards
    renumber, so a name match is preferred over a hard-coded index. The
    "pulse" device is the PulseAudio bridge: it always exists while the daemon
    runs and follows the system default sink/source, which is what routes
    audio to the USB speakerphone.
    """
    spec = str(spec).strip()
    if spec.lower().startswith("index:"):
        return int(spec.split(":", 1)[1])
    if spec.isdigit():
        return int(spec)

    want = spec.lower()
    candidates = []
    for i in range(py_audio.get_device_count()):
        info = py_audio.get_device_info_by_index(i)
        usable = (
            info["maxInputChannels"] > 0 if want_input else info["maxOutputChannels"] > 0
        )
        candidates.append(f"{i}:{info['name']}")
        if usable and want in info["name"].lower():
            return i

    raise RuntimeError(
        f"No {'input' if want_input else 'output'} audio device matches {spec!r}. "
        f"Available: {', '.join(candidates)}"
    )


class PacatAudioOutput(BaseOutputTransport):
    """Playbot output that pipes PCM to `pacat` instead of PyAudio.

    Pipecat's LocalAudioOutputTransport writes 10ms chunks from the event loop
    through PyAudio; on this Pi that leaves the sink starved (measured: the
    same audio played through paplay is continuous, through PyAudio it is
    fragmented). Handing the bytes to pacat puts buffering in the OS player,
    which is exactly the path that is verified audible on the JV801P.
    """

    _params: "LocalAudioTransportParams"

    def __init__(self, py_audio, params):
        super().__init__(params)
        self._proc = None

    async def setup(self, setup):
        # Run BaseOutputTransport.setup for resampler/chunking init, but do NOT
        # open a PyAudio stream: pacat owns playback.
        await BaseOutputTransport.setup(self, setup)
        self._proc = await asyncio.create_subprocess_exec(
            "pacat",
            "--playback",
            "--raw",
            f"--format=s16le",
            f"--rate={self.sample_rate}",
            f"--channels={self._params.audio_out_channels}",
            f"--latency-msec={PACAT_LATENCY_MS}",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        logger.info(
            f"Local audio output via pacat: {self.sample_rate} Hz, "
            f"{self._params.audio_out_channels} ch, latency {PACAT_LATENCY_MS} ms"
        )

    async def start(self, frame):
        await BaseOutputTransport.start(self, frame)
        await self.set_transport_ready(frame)

    async def write_audio_frame(self, frame) -> bool:
        if self._proc is None or self._proc.stdin is None:
            return False
        try:
            self._proc.stdin.write(frame.audio)
            await self._proc.stdin.drain()
            return True
        except (BrokenPipeError, ConnectionResetError):
            logger.error("pacat pipe closed; playback stopped")
            self._proc = None
            return False

    async def cleanup(self):
        try:
            await BaseOutputTransport.cleanup(self)
        finally:
            if self._proc is not None:
                try:
                    self._proc.stdin.close()
                    await self._proc.wait()
                except Exception:
                    pass
                self._proc = None


def build_local_transport() -> BaseTransport:
    """Build a LocalAudioTransport bound to the Pi's own sound card."""
    import pyaudio
    from pipecat.transports.local.audio import (
        LocalAudioTransport,
        LocalAudioTransportParams,
    )

    if AUDIO_OUTPUT_IMPL == "pacat":
        # Defined here because the local transport classes import pyaudio,
        # which only exists on the Pi (and only after our hand-built install).
        class LocalPacatTransport(LocalAudioTransport):
            """LocalAudioTransport with the PyAudio writer swapped for pacat."""

            def output(self):
                if not self._output:
                    self._output = PacatAudioOutput(self._pyaudio, self._params)
                return self._output

        cls = LocalPacatTransport
    else:
        cls = LocalAudioTransport

    probe = pyaudio.PyAudio()
    try:
        in_idx = _resolve_audio_device(probe, AUDIO_INPUT_DEVICE, want_input=True)
        out_idx = _resolve_audio_device(probe, AUDIO_OUTPUT_DEVICE, want_input=False)
        logger.info(f"Local audio input  [{in_idx}] {probe.get_device_info_by_index(in_idx)['name']}")
        logger.info(f"Local audio output [{out_idx}] {probe.get_device_info_by_index(out_idx)['name']}")
    finally:
        probe.terminate()

    return cls(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            input_device_index=in_idx,
            output_device_index=out_idx,
        )
    )


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments) -> None:
    logger.info(f"Starting aaf-ai231-me3 voice agent (SPEECH_MODE={SPEECH_MODE})")

    ollama_key = os.getenv("OLLAMA_API_KEY")
    llm = OpenAILLMService(
        api_key=ollama_key,
        base_url=OLLAMA_BASE_URL,
        settings=OpenAILLMService.Settings(
            model=OLLAMA_MODEL,
            system_instruction=(
                "You are a friendly voice assistant running on a Raspberry "
                "Pi. Keep replies short (1-3 spoken sentences), no lists or "
                "emojis, and speak naturally. You have tools available: when "
                "the user asks for weather, time, timers, alarms, reminders, "
                "music, radio, lights, thermostat, or messaging, call the "
                "matching tool and then briefly speak its result. Never read "
                "out code or URLs."
            ),
        ),
    )

    # LLM tools via MCP: the voice-agent command tools server (M5). The
    # connection lives for the bot's lifetime; Pipecat closes it at teardown.
    from pipecat.services.mcp_service import MCPClient
    from mcp import StdioServerParameters

    tools_mcp = MCPClient(
        server_params=StdioServerParameters(
            command=os.getenv("VENV_PY", "/home/aldwinrpi4/pipecat-quickstart/server/.venv/bin/python"),
            args=[os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_servers", "voice_tools_mcp_server.py")],
        )
    )
    voice_tools = await tools_mcp.tools()
    logger.info(f"LLM tools registered: {[f.name for f in voice_tools.standard_tools]}")

    stt, tts = build_speech_services()

    context = LLMContext(tools=voice_tools)
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=VAD_STOP_SECS))
        ),
    )

    if ORCHESTRATION_MODE not in {"single", "two_brain_plusjev"}:
        raise ValueError(f"Unknown ORCHESTRATION_MODE: {ORCHESTRATION_MODE}")
    llm_stages = [llm]
    if ORCHESTRATION_MODE == "two_brain_plusjev":
        from orchestration import TwoBrainRouter
        llm_stages.insert(0, TwoBrainRouter(tools_mcp))
        logger.info("Two-brain-plus-Jev routing enabled")

    pipeline = Pipeline([
        transport.input(),
        stt,
        user_aggregator,
        *llm_stages,
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

    @worker.rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi):
        await worker.queue_frames([TTSSpeakFrame(text=GREETING_TEXT)])

    if TRANSPORT_MODE == "local":
        # Local audio has no RTVI client, so on_client_ready never fires.
        # Queue the greeting ourselves once the output stream is actually open.
        async def _local_greeting():
            out = transport.output()
            for _ in range(75):
                if getattr(out, "_out_stream", None) is not None:
                    break
                await asyncio.sleep(0.2)
            await asyncio.sleep(0.3)
            await worker.queue_frames([TTSSpeakFrame(text=GREETING_TEXT)])

        asyncio.create_task(_local_greeting())

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected")

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await runner.cancel()

    await runner.run()


async def bot(runner_args: RunnerArguments):
    if TRANSPORT_MODE == "local":
        # Pi-local hardware: no browser, no signalling, no WebRTC peer.
        transport = build_local_transport()
    else:
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


if __name__ == "__main__":
    if TRANSPORT_MODE == "local":
        # Bypass the development runner: it exists to serve a browser client,
        # and local audio needs neither the HTTP port nor the signalling layer.
        local_args = RunnerArguments()
        local_args.handle_sigint = True
        asyncio.run(bot(local_args))
    else:
        from pipecat.runner.run import main

        main()
