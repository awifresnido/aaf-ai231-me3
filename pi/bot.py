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
import json
import os
import time
from contextlib import suppress

from dotenv import load_dotenv

# Optional secure env file on the Pi (chmod 600, outside the repo).
load_dotenv("/home/aldwinrpi4/.voice-agent-env", override=False)

from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
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
from pipecat.processors.frame_processor import FrameDirection
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.workers.runner import WorkerRunner
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver
from turn_timing import TurnTimingObserver

load_dotenv(override=True)

from queued_logging import configure_queued_logging

QUEUED_LOGGING = configure_queued_logging()

SPEECH_MODE = os.getenv("SPEECH_MODE", "direct")
ASR_SERVER = os.getenv("ASR_SERVER", "192.168.5.11:50051")
ASR_BACKEND = os.getenv("ASR_BACKEND", "nemotron").strip().lower()
TTS_SERVER = os.getenv("TTS_SERVER", "192.168.5.11:50052")
TTS_VOICE = os.getenv("TTS_VOICE", "0")
TTS_BACKEND = os.getenv("TTS_BACKEND", "magpie").strip().lower()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://ollama.com/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:31b")
ORCHESTRATION_MODE = os.getenv("ORCHESTRATION_MODE", "single").strip().lower()

# The private environment selects the active endpointing experiment.
VAD_STOP_SECS = float(os.getenv("VAD_STOP_SECS", "0.8"))
SMART_TURN_CPU_COUNT = int(os.getenv("SMART_TURN_CPU_COUNT", "1"))
if SMART_TURN_CPU_COUNT < 1:
    raise ValueError("SMART_TURN_CPU_COUNT must be at least 1")

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
if ORCHESTRATION_MODE == "local_vcm":
    from local_vcm import VOICE_OF_PI_GREETING
    GREETING_TEXT = VOICE_OF_PI_GREETING



def build_speech_services(*, timing_observer=None):
    """Return (stt, tts) for the configured SPEECH_MODE.

    Modes:
      direct — independently select ASR_BACKEND and TTS_BACKEND.
               Defaults are Nemotron ASR and Magpie TTS over Jetson gRPC.
               dgx_qwen2_audio ASR is VAD-segmented; dgx_qwen TTS streams PCM.
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

    if ASR_BACKEND == "dgx_qwen2_audio":
        from qwen_audio_stt import QwenAudioSTTService
        stt = QwenAudioSTTService(timing_observer=timing_observer)
        logger.info("ASR backend: DGX Qwen2-Audio, model={}", stt.model_name)
    elif ASR_BACKEND == "voxtral_mini":
        from voxtral_stt import VoxtralSTTService
        stt = VoxtralSTTService(timing_observer=timing_observer)
        logger.info("ASR backend: Jetson Voxtral Mini, model={}", stt.model_name)
    elif ASR_BACKEND == "whisper":
        from whisper_stt import WhisperSTTService
        stt = WhisperSTTService(timing_observer=timing_observer)
        logger.info("ASR backend: Jetson whisper.cpp, model={}", stt.model_name)
    elif ASR_BACKEND == "nemotron":
        stt = NvidiaSTTService(
            server=ASR_SERVER, use_ssl=False, model_function_map={},
            sample_rate=16000, audio_channel_count=1, stop_history=int(os.getenv("NEMOTRON_STOP_HISTORY_MS", "600")))
    else:
        raise ValueError("ASR_BACKEND must be nemotron, dgx_qwen2_audio, voxtral_mini or whisper")
    if TTS_BACKEND == "dgx_qwen":
        from qwen_tts import QwenTTSService
        tts = QwenTTSService(timing_observer=timing_observer)
        logger.info("TTS backend: DGX Qwen, model={}, voice={}", tts.model_name, tts.voice_name)
    elif TTS_BACKEND == "mac_qwen":
        from mac_qwen_tts import MacQwenTTSService
        tts = MacQwenTTSService(timing_observer=timing_observer)
        logger.info("TTS backend: Mac Qwen, model={}, voice={}", tts.model_name, tts.voice_name)
    elif TTS_BACKEND == "magpie":
        tts = NvidiaTTSService(
            server=TTS_SERVER, use_ssl=False, model_function_map={},
            sample_rate=22050, voice_id=TTS_VOICE)
    else:
        raise ValueError("TTS_BACKEND must be magpie, dgx_qwen or mac_qwen")
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
        self.timing_observer = None
        self._last_playback_context = None
        self._last_write_at = float("-inf")
        self._interrupt_at = 0.0
        self._interrupt_burst = -1
        self._interrupt_pending = 0.0
        # Backchannel echo gate: measured playback state (never frame events).
        self._playback_pending_s = 0.0
        self._playback_bytes_at = 0.0
        self.playback_busy_until = 0.0
        # Backchannel burst id: increments each time playback goes
        # idle->active, so the backchannel can tell "filler played, silence
        # since" from "the real answer played" without frame-event guessing.
        self._playback_burst_id = 0

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

    async def process_frame(self, frame, direction=FrameDirection.DOWNSTREAM):
        if type(frame).__name__ == "InterruptionFrame":
            now = time.monotonic()
            pending = max(0.0, self._playback_pending_s -
                          (now - self._playback_bytes_at))
            if self.timing_observer:
                self.timing_observer.record(
                    "bc_interrupt", pending_s=round(pending, 3),
                    busy_until_in_ms=round(max(0.0, self.playback_busy_until - now) * 1000),
                    burst_id=self._playback_burst_id)
            # remember for the post-interrupt drain measurement
            self._interrupt_at = now
            self._interrupt_burst = self._playback_burst_id
            self._interrupt_pending = pending
            # Hard flush: SIGKILL pacat so buffered-but-unplayed audio dies
            # with the pipe. Respawned lazily on the next write.
            if pending > 0.05 and self._proc is not None:
                if self.timing_observer:
                    self.timing_observer.record(
                        "bc_interrupt_flush", killed_pending_s=round(pending, 3))
                try:
                    self._proc.kill()
                    await self._proc.wait()
                    if self.timing_observer:
                        self.timing_observer.record(
                            "bc_flush_pacat_gone", exit_code=self._proc.returncode)
                except Exception:
                    pass
                self._proc = None
        return await super().process_frame(frame, direction)

    async def _spawn_pacat(self):
        self._proc = await asyncio.create_subprocess_exec(
            "pacat",
            "--playback",
            "--raw",
            "--format=s16le",
            f"--rate={self.sample_rate}",
            f"--channels={self._params.audio_out_channels}",
            f"--latency-msec={PACAT_LATENCY_MS}",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def write_audio_frame(self, frame) -> bool:
        if self._proc is None or self._proc.stdin is None:
            if frame.audio:
                try:
                    await self._spawn_pacat()
                except Exception as exc:
                    logger.error("pacat respawn failed: {}", exc)
                    return False
            else:
                return False
        try:
            self._proc.stdin.write(frame.audio)
            await self._proc.stdin.drain()
            now = time.monotonic()
            # Measured playback accounting: a DRAINING bucket. Each write
            # adds seconds of pending audio; wall-clock time drains it.
            # (Run 079d8d8b7f bug: a cumulative byte total made
            # playback_busy_until creep forward forever, blocking fillers.)
            n = len(frame.audio)
            rate = self.sample_rate or 24000
            channels = self._params.audio_out_channels or 1
            elapsed = now - self._playback_bytes_at
            pending = max(0.0, self._playback_pending_s - elapsed)
            if pending <= 0.001 and n > 0:
                self._playback_burst_id += 1
            pending += n / (rate * channels * 2)
            self._playback_pending_s = pending
            self._playback_bytes_at = now
            self.playback_busy_until = now + pending + 0.15
            if (self._interrupt_at and now - self._interrupt_at > 0.9
                    and (self._playback_burst_id > self._interrupt_burst or pending <= 0.001)):
                if self.timing_observer:
                    self.timing_observer.record(
                        "bc_interrupt_drain", after_interrupt_s=round(now - self._interrupt_at, 3),
                        predicted_pending_s=round(self._interrupt_pending, 3),
                        new_burst=self._playback_burst_id > self._interrupt_burst)
                self._interrupt_at = 0.0
            context_id = getattr(frame, "context_id", None)
            first = (context_id is not None and context_id != self._last_playback_context) or (context_id is None and now - self._last_write_at > 0.5)
            self._last_write_at = now
            self._last_playback_context = context_id
            if first and self.timing_observer:
                self.timing_observer.playback_write(context_id)
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


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments, *, benchmark_mode: bool = False) -> None:
    logger.info(f"Starting aaf-ai231-me3 voice agent (SPEECH_MODE={SPEECH_MODE})")
    experiment = os.getenv("VAD_EXPERIMENT", f"vad-{VAD_STOP_SECS}")
    timing = TurnTimingObserver(experiment=experiment)
    from stall_diagnostics import Diagnostics
    diagnostics = Diagnostics.from_env("pi", run=timing.run)
    timing.diagnostics = diagnostics
    from vcm_server_location import build_vcm_server
    vcm_server = build_vcm_server(os.path.dirname(os.path.abspath(__file__)), diagnostics=diagnostics)
    timing.record("configuration", vad_stop_secs=VAD_STOP_SECS, transport=TRANSPORT_MODE,
                  smart_turn_cpu_count=SMART_TURN_CPU_COUNT, orchestration_mode=ORCHESTRATION_MODE,
                  vcm_model_host=os.getenv("LOCAL_VCM_MODEL_HOST", "thinkpad") if ORCHESTRATION_MODE == "local_vcm" else None,
                  router_model=os.getenv("ROUTER_MODEL", "llama" if ORCHESTRATION_MODE == "local_vcm" else "jev") if ORCHESTRATION_MODE in {"local_vcm", "two_brain_plusjev"} else None,
                  laya_fallback_policy=os.getenv("LAYA_FALLBACK_POLICY", "clarify") if ORCHESTRATION_MODE == "local_vcm" and os.getenv("ROUTER_MODEL") == "laya" else None,
                  classifier_timeout_s=float(os.getenv("LAYA_ROUTER_TIMEOUT_SECS", "2")) if os.getenv("ROUTER_MODEL") == "laya" else None,
                  cloud_escalation=ORCHESTRATION_MODE == "two_brain_plusjev",
                  asr_backend=ASR_BACKEND if SPEECH_MODE == "direct" else SPEECH_MODE,
                  asr_model=(os.getenv("DGX_ASR_MODEL", "Qwen/Qwen2-Audio-7B-Instruct") if ASR_BACKEND == "dgx_qwen2_audio"
                             else os.getenv("VOXTRAL_MODEL", "mistralai/Voxtral-Mini-3B-2507") if ASR_BACKEND == "voxtral_mini" else None),
                  small_llm_primary_model=os.getenv("SMALL_LLM_PRIMARY_MODEL"),
                  tts_backend=TTS_BACKEND if SPEECH_MODE == "direct" else SPEECH_MODE,
                  tts_model=(os.getenv("DGX_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice") if TTS_BACKEND == "dgx_qwen"
                             else "qwen3-tts-customvoice-mlx-4bit" if TTS_BACKEND == "mac_qwen" else None),
                  tts_voice=(os.getenv("DGX_TTS_VOICE", "vivian") if TTS_BACKEND == "dgx_qwen"
                             else os.getenv("MAC_TTS_VOICE", "Aiden") if TTS_BACKEND == "mac_qwen" else TTS_VOICE),
                  diagnostics_dir=str(diagnostics.path.parent) if diagnostics else None,
                  queued_logging=QUEUED_LOGGING,
                  vcm_tool_server_host=vcm_server.host, vcm_tool_transport=vcm_server.transport,
                  vcm_state_backend=vcm_server.state_backend,
                  pulse_source=os.getenv("PULSE_SOURCE"), pulse_sink=os.getenv("PULSE_SINK"),
                  pacat_latency_ms=PACAT_LATENCY_MS if TRANSPORT_MODE == "local" else None)
    if isinstance(transport.output(), PacatAudioOutput):
        transport.output().timing_observer = timing
    latency = UserBotLatencyObserver()

    @latency.event_handler("on_latency_measured")
    async def on_latency_measured(observer, seconds):
        timing.record("native_user_bot_latency", seconds=seconds)

    # LLM tools via MCP: the voice-agent command tools server (M5). The
    # connection lives for the bot's lifetime; Pipecat closes it at teardown.
    from pipecat.services.mcp_service import MCPClient

    client_class = MCPClient
    client_options = {}
    if diagnostics:
        from profiled_mcp import ProfiledMCPClient
        client_class = ProfiledMCPClient
        client_options["diagnostics"] = diagnostics

    tools_mcp = client_class(
        server_params=vcm_server.server_params(),
        **client_options,
    )
    voice_tools = await tools_mcp.tools()
    logger.info("VCM tool server: host={}, transport={}", vcm_server.host, vcm_server.transport)
    if ORCHESTRATION_MODE == "local_vcm":
        from pipecat.adapters.schemas.tools_schema import ToolsSchema
        from orchestration import FAST_TOOLS
        voice_tools = ToolsSchema([tool for tool in voice_tools.standard_tools if tool.name in FAST_TOOLS])
    onit_registered = False
    if os.getenv("ONIT_TOOLS_ENABLED", "1").strip() == "1":
        # Optional second MCP server: the lean OnIt knowledge tools (search,
        # fetch_content). Register them for the escalation LLM so the
        # `knowledge` group has real web access. Non-fatal if it can't start.
        try:
            from mcp import StdioServerParameters
            from pipecat.adapters.schemas.tools_schema import ToolsSchema
            onit_server = StdioServerParameters(
                command=os.getenv("VENV_PY", "/home/aldwinrpi4/pipecat-quickstart/server/.venv/bin/python"),
                args=[os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "mcp_servers", "onit_tools_mcp_server.py")],
                env={"PATH": os.getenv("PATH", "/usr/bin:/bin")},
            )
            onit_mcp = client_class(server_params=onit_server, **client_options)
            onit_tools = await onit_mcp.tools()
            existing = {tool.name for tool in voice_tools.standard_tools}
            voice_tools = ToolsSchema(
                list(voice_tools.standard_tools)
                + [tool for tool in onit_tools.standard_tools if tool.name not in existing]
            )
            onit_registered = True
            logger.info("OnIt knowledge tools registered: {}", [tool.name for tool in onit_tools.standard_tools])
        except Exception as exc:
            logger.warning("OnIt knowledge tools unavailable: {}", type(exc).__name__)
    if os.getenv("WORKSPACE_TOOLS_ENABLED", "1").strip() == "1":
        # Third MCP server: the workspace tools (files, shell, github) for the
        # `workspace` group, which the router escalates to the cloud LLM.
        # Non-fatal if it can't start.
        try:
            from mcp import StdioServerParameters
            from pipecat.adapters.schemas.tools_schema import ToolsSchema
            inventory = {
                "source": "running voice agent startup configuration; not a health check",
                "harness": "Pipecat", "vad": {"model": "Silero", "host": "Pi"},
                "speech_transport": SPEECH_MODE,
                "asr": {"backend": ASR_BACKEND, "model": os.getenv("WHISPER_ASR_MODEL", "whisper-large-v3-turbo") if ASR_BACKEND == "whisper" else None,
                        "endpoint": os.getenv("WHISPER_ASR_BASE", "http://192.168.5.11:8090") if ASR_BACKEND == "whisper" else None},
                "router": {"model": os.getenv("ROUTER_MODEL", "jev"), "endpoint": os.getenv("LAYA_ROUTER_URL", "http://192.168.5.11:8083")},
                "local_llm": {"model": os.getenv("SMALL_LLM_PRIMARY_MODEL"), "endpoint": os.getenv("SMALL_LLM_PRIMARY_URL")},
                "cloud_llm": {"model": OLLAMA_MODEL} if ORCHESTRATION_MODE != "local_vcm" else None,
                "tts": {"backend": TTS_BACKEND, "model": os.getenv("DGX_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice") if TTS_BACKEND == "dgx_qwen" else None,
                        "voice": os.getenv("DGX_TTS_VOICE", "vivian") if TTS_BACKEND == "dgx_qwen" else TTS_VOICE},
                "mcp_servers": ["voice_tools", "workspace_tools"] + (["onit_tools"] if onit_registered else []),
            }
            if SPEECH_MODE == "mcp":
                inventory["mcp_servers"] += ["asr_mcp", "tts_mcp"]
            workspace_server = StdioServerParameters(
                command=os.getenv("VENV_PY", "/home/aldwinrpi4/pipecat-quickstart/server/.venv/bin/python"),
                args=[os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "mcp_servers", "workspace_tools_mcp_server.py")],
                env={"PATH": os.getenv("PATH", "/usr/bin:/bin"), "ME3_SYSTEM_INVENTORY": json.dumps(inventory),
                     **(diagnostics.server_env() if diagnostics else {})},
            )
            workspace_mcp = client_class(server_params=workspace_server, **client_options)
            workspace_tools = await workspace_mcp.tools()
            existing = {tool.name for tool in voice_tools.standard_tools}
            voice_tools = ToolsSchema(
                list(voice_tools.standard_tools)
                + [tool for tool in workspace_tools.standard_tools if tool.name not in existing]
            )
            logger.info("Workspace tools registered: {}", [tool.name for tool in workspace_tools.standard_tools])
        except Exception as exc:
            logger.warning("Workspace tools unavailable: {}", type(exc).__name__)
    logger.info(f"LLM tools registered: {[f.name for f in voice_tools.standard_tools]}")

    stt, tts = build_speech_services(timing_observer=timing)

    # Speculative Laya: classify partial audio while the user still speaks, so
    # local-tool commands skip the serial ASR->classify wait. Toggle with
    # SPECULATIVE_LAYA=0; a wrong speculation cannot fire a wrong tool (tier-2
    # grammar still validates against the final transcript).
    spec_layer = None
    spec_tap = None
    if (ORCHESTRATION_MODE == "two_brain_plusjev"
            and os.getenv("SPECULATIVE_LAYA", "1").strip() == "1"):
        try:
            from speculative_laya import SpeculativeLaya
            from spec_tap import SpecTap
            spec_layer = SpeculativeLaya(timing=timing)
            spec_tap = SpecTap(spec_layer, timing_observer=timing, stt=stt)
            logger.info("Speculative Laya enabled (min_audio_s={})", spec_layer.min_audio_s)
        except Exception as exc:
            logger.warning("Speculative Laya unavailable: {}", type(exc).__name__)
            spec_layer = None

    stop_strategy = TurnAnalyzerUserTurnStopStrategy
    stop_options = {}
    if ASR_BACKEND == "whisper" and SPEECH_MODE == "direct":
        from whisper_turn_stop import LatestWhisperTurnStopStrategy
        stop_strategy = LatestWhisperTurnStopStrategy
        stop_options = {"stt": stt, "timing": timing}
    context = LLMContext(tools=voice_tools)
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=VAD_STOP_SECS)),
            user_turn_strategies=UserTurnStrategies(stop=[
                stop_strategy(
                    turn_analyzer=LocalSmartTurnAnalyzerV3(cpu_count=SMART_TURN_CPU_COUNT), **stop_options
                )
            ]),
        ),
    )

    if ORCHESTRATION_MODE not in {"single", "two_brain_plusjev", "local_vcm"}:
        raise ValueError(f"Unknown ORCHESTRATION_MODE: {ORCHESTRATION_MODE}")
    if ORCHESTRATION_MODE == "local_vcm":
        from local_vcm import LocalVCMProcessor
        llm_stages = [LocalVCMProcessor(tools_mcp, timing_observer=timing)]
        logger.info("Local VCM trial: host={}; Jev, other model hosts, and GLM disabled",
                    llm_stages[0].model_host)
    else:
        ollama_key = os.getenv("OLLAMA_API_KEY")
        from context_management import ContextManagedLLM
        llm = ContextManagedLLM(
            timing=timing,
            history_chars=int(os.getenv("LLM_HISTORY_MAX_CHARS", "24000")),
            api_key=ollama_key,
            base_url=OLLAMA_BASE_URL,
            settings=OpenAILLMService.Settings(
                model=OLLAMA_MODEL,
                max_completion_tokens=int(os.getenv("LLM_MAX_COMPLETION_TOKENS", "4096")),
                extra={"extra_body": {"session_id": timing.run}} if "openrouter.ai" in OLLAMA_BASE_URL else {},
                system_instruction=(
                    "You are a friendly voice assistant running on a Raspberry "
                    "Pi. Keep replies short (1-3 spoken sentences), no lists or "
                    "emojis, and speak naturally. You have tools available: when "
                    "the user asks for weather, time, timers, alarms, reminders, "
                    "music, lights, thermostat, or messaging, call the "
                    "matching tool and then briefly speak its result. Never read "
                    "out code or URLs. Radio playback is not supported. When asked "
                    "which models or servers are running, call get_system_inventory "
                    "and describe its configured values without guessing; configuration "
                    "does not prove service health. Workspace tool paths are relative: "
                    "write_file requires both path and content; serve the root with path '.'. "
                    "When sending a link, use the actual URL returned by serve, not a placeholder."
                ),
            ),
        )

        llm_stages = [llm]
        if ORCHESTRATION_MODE == "two_brain_plusjev":
            from orchestration import TwoBrainRouter
            router = TwoBrainRouter(tools_mcp, timing_observer=timing)
            if spec_layer is not None:
                router.spec_layer = spec_layer
            llm_stages.insert(0, router)
            logger.info("Two-brain routing enabled: classifier={}, GLM={}", llm_stages[0].router_model, OLLAMA_MODEL)

    bc_processor = None
    if os.getenv("BACKCHANNEL", "0").strip() == "1" and TRANSPORT_MODE == "local":
        try:
            from backchannel import BackchannelProcessor
            bc_processor = BackchannelProcessor(
                timing_observer=timing, output_transport=transport.output())
            logger.info("Backchannel processor enabled")
        except Exception as exc:
            logger.warning("Backchannel processor unavailable: {}", type(exc).__name__)
            bc_processor = None

    pipeline = Pipeline([
        transport.input(),
        *( [spec_tap] if spec_layer is not None else [] ),
        stt,
        *( [bc_processor] if bc_processor is not None else [] ),
        user_aggregator,
        *llm_stages,
        tts,
        transport.output(),
        assistant_aggregator,
    ])

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        observers=[timing, latency],
        idle_timeout_secs=None if TRANSPORT_MODE == "local" else 300,
    )

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)

    @worker.rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi):
        await worker.queue_frames([TTSSpeakFrame(text=GREETING_TEXT)])

    if TRANSPORT_MODE == "local" and not benchmark_mode:
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

    if os.getenv("BC_FLUSH_TEST", "0").strip() == "1" and TRANSPORT_MODE == "local":
        async def _flush_test():
            out = transport.output()
            # wait until the greeting is ACTIVELY queued in the pacat pipe
            # (v1 waited for first write + 1 s, by which time the short
            # greeting had drained -> pending was 0 and the kill never fired)
            for _ in range(200):
                if getattr(out, "_playback_pending_s", 0.0) > 1.0:
                    break
                await asyncio.sleep(0.1)
            from pipecat.frames.frames import InterruptionFrame
            await out.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
            timing.record("bc_flush_test", stage="interrupt_pushed")
            await asyncio.sleep(2.0)
            await worker.queue_frames([TTSSpeakFrame(
                text="Flush test complete. If you hear this, respawn works.")])
            timing.record("bc_flush_test", stage="respawn_speech_queued")

        asyncio.create_task(_flush_test())
        logger.info("BC_FLUSH_TEST armed: interrupt at greeting+1s, respawn check at +3s")

    monitor = asyncio.create_task(diagnostics.monitor_loop(lambda: timing.turn)) if diagnostics else None
    activity_monitor = None
    if TRANSPORT_MODE == "local" and not benchmark_mode:
        from audio_activity import publish_activity
        activity_monitor = asyncio.create_task(publish_activity(transport.output(), bc_processor))
    try:
        await runner.run()
    except asyncio.CancelledError:
        await runner.cancel()
        raise
    finally:
        if activity_monitor:
            activity_monitor.cancel()
            with suppress(asyncio.CancelledError):
                await activity_monitor
        if monitor:
            monitor.cancel()
            with suppress(asyncio.CancelledError):
                await monitor
        if QUEUED_LOGGING:
            await logger.complete()
        if diagnostics:
            diagnostics.close()


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
