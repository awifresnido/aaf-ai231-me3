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
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.workers.runner import WorkerRunner

load_dotenv(override=True)

SPEECH_MODE = os.getenv("SPEECH_MODE", "direct")
ASR_SERVER = os.getenv("ASR_SERVER", "192.168.5.11:50051")
TTS_SERVER = os.getenv("TTS_SERVER", "192.168.5.11:50052")
TTS_VOICE = os.getenv("TTS_VOICE", "0")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://ollama.com/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:31b")

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

GREETING_TEXT = (
    "Hello. This is the Raspberry Pi voice agent, "
    "connected to Ollama Cloud. Say something and I will answer."
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


def build_local_transport() -> BaseTransport:
    """Build a LocalAudioTransport bound to the Pi's own sound card."""
    import pyaudio
    from pipecat.transports.local.audio import (
        LocalAudioTransport,
        LocalAudioTransportParams,
    )

    probe = pyaudio.PyAudio()
    try:
        in_idx = _resolve_audio_device(probe, AUDIO_INPUT_DEVICE, want_input=True)
        out_idx = _resolve_audio_device(probe, AUDIO_OUTPUT_DEVICE, want_input=False)
        logger.info(f"Local audio input  [{in_idx}] {probe.get_device_info_by_index(in_idx)['name']}")
        logger.info(f"Local audio output [{out_idx}] {probe.get_device_info_by_index(out_idx)['name']}")
    finally:
        probe.terminate()

    return LocalAudioTransport(
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

    pipeline = Pipeline([
        transport.input(),
        stt,
        user_aggregator,
        llm,
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
