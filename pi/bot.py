"""aaf-ai231-me3 — Pi-side voice agent (Milestone 2 target).

Cascaded pipeline on the Raspberry Pi:
  browser (ThinkPad) --WebRTC--> Pi: Silero VAD (local) -> Nemotron ASR (Jetson)
  -> Ollama Cloud LLM -> Magpie TTS (Jetson) -> browser speaker

Run on the Pi:
  ~/pipecat-quickstart/server/.venv/bin/python bot.py -t webrtc --host 0.0.0.0 --port 7860
Then from the ThinkPad:
  ssh -L 7860:localhost:7860 aldwinrpi4@192.168.5.12
and open http://localhost:7860 in the browser.

Env (chmod 600 file outside the repo; never commit):
  OLLAMA_API_KEY   Ollama Cloud key (bearer)
  OLLAMA_BASE_URL  default https://ollama.com/v1
  OLLAMA_MODEL     default gemma4:31b
  ASR_SERVER       default 192.168.5.11:50051
  TTS_SERVER       default 192.168.5.11:50052
  TTS_VOICE        default 0 (speaker index; named voices vary per container build)
"""

import os

from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame, TTSSpeakFrame
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

ASR_SERVER = os.getenv("ASR_SERVER", "192.168.5.11:50051")
TTS_SERVER = os.getenv("TTS_SERVER", "192.168.5.11:50052")
TTS_VOICE = os.getenv("TTS_VOICE", "0")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://ollama.com/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:31b")

SYSTEM_PROMPT = (
    "You are a helpful voice assistant running on a Raspberry Pi. Your answers are "
    "spoken aloud: keep them short and conversational, no markdown, lists, or emoji. "
    "If you don't know something, say so plainly."
)

# Pi-local VAD policy: 0.7 s silence ends the turn (see Phase 0 memo 0.5).
# The Jetson ASR final remains the backstop.
VAD_STOP_SECS = float(os.getenv("VAD_STOP_SECS", "0.7"))


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments) -> None:
    logger.info("Starting aaf-ai231-me3 voice agent")

    stt = NvidiaSTTService(
        server=ASR_SERVER,
        use_ssl=False,
        model_function_map={},
        sample_rate=16000,
        audio_channel_count=1,
        stop_history=-1,
        stop_history_eou=-1,
    )

    tts = NvidiaTTSService(
        server=TTS_SERVER,
        use_ssl=False,
        model_function_map={},
        sample_rate=22050,
        voice_id=TTS_VOICE,
    )

    llm = OpenAILLMService(
        api_key=os.getenv("OLLAMA_API_KEY"),
        base_url=OLLAMA_BASE_URL,
        settings=OpenAILLMService.Settings(
            model=OLLAMA_MODEL,
            system_instruction=SYSTEM_PROMPT,
        ),
    )

    context = LLMContext()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=VAD_STOP_SECS))
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        observers=[],
    )

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)

    @worker.rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi):
        if os.getenv("OLLAMA_API_KEY"):
            context.add_message(
                {"role": "developer", "content": "Greet the user briefly, then wait."}
            )
            await worker.queue_frames([LLMRunFrame()])
        else:
            # Milestone 1 (audio-path) smoke test: fixed speech out, no LLM needed.
            await worker.queue_frames(
                [
                    TTSSpeakFrame(
                        text="Hello. This is the Raspberry Pi voice agent. "
                        "Speech out is working. Please say something after the tone."
                    )
                ]
            )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected")

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
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


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
