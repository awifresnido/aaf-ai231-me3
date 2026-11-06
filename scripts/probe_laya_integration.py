"""Real classifier/controller/Pi MCP/Jetson worker test on disposable state.

No microphone, ASR, TTS, or live database access. Use the existing Pi venv.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))


async def main(args):
    from dotenv import dotenv_values
    from loguru import logger
    from local_vcm import LocalVCMProcessor
    from laya_router import LayaDecisionClient
    from pipecat.frames.frames import LLMContextFrame, TTSSpeakFrame
    from pipecat.processors.frame_processor import FrameDirection
    from profiled_mcp import ProfiledMCPClient
    from stall_diagnostics import Diagnostics
    from turn_timing import TurnTimingObserver
    from vcm_server_location import build_vcm_server, JETSON_ROOT

    config = dotenv_values(args.env_file)
    allowed = {k: v for k, v in config.items() if v is not None and (
        k.startswith("SMALL_LLM_PRIMARY_") or k in {
            "VCM_JETSON_SSH_TARGET", "VCM_JETSON_SSH_KEY", "VCM_JETSON_KNOWN_HOSTS"})}
    run = "laya-preflight-" + uuid.uuid4().hex[:10]
    os.environ.update(allowed, ROUTER_MODEL="laya", LOCAL_VCM_MODEL_HOST="thinkpad",
                      LAYA_ROUTER_URL=args.url, LAYA_FALLBACK_POLICY="clarify")
    logger.remove()
    logger.add(sys.stderr, enqueue=True)
    trace = Diagnostics("pi", run=run, directory="/dev/shm/voice-agent-diagnostics")
    timing = TurnTimingObserver(experiment="laya-disposable-preflight")
    timing.run = run
    timing.diagnostics = trace
    rows = []
    with tempfile.TemporaryDirectory(prefix="laya-state-") as folder:
        spec = build_vcm_server(Path(__file__).resolve().parents[1] / "pi", diagnostics=trace, environ={
            **allowed, "VCM_TOOL_SERVER_HOST": "pi", "VCM_STATE_BACKEND": "jetson_sqlite",
            "VENV_PY": sys.executable, "VOICE_TOOLS_DATA": folder,
            "VCM_JETSON_DATA_DIR": JETSON_ROOT + "/state/preflight/" + run})
        model = LayaDecisionClient(timing_observer=timing)
        try:
            async with ProfiledMCPClient(diagnostics=trace, server_params=spec.server_params()) as client:
                await client.tools()
                calls = []

                async def call(tool, arguments):
                    calls.append(tool)
                    return await client._call_tool_text(tool, arguments)

                processor = LocalVCMProcessor(SimpleNamespace(_call_tool_text=call), model=model, timing_observer=timing)
                speech = []

                async def capture(frame, *_):
                    if isinstance(frame, TTSSpeakFrame):
                        speech.append(frame.text)

                processor.push_frame = capture
                cases = [
                    ("Turn on the lights", "control_lights"),
                    ("Set the lights to blue", "control_lights"),
                    ("Set the thermostat to 26 degrees Celsius", "set_thermostat"),
                    ("Remind me to Review Laya Results", "add_reminder"),
                    ("List my reminders", "list_reminders"),
                    ("Set a five minute timer", "set_timer"),
                    ("Set an alarm for nine PM", "set_alarm"),
                    ("Can you hear my voice?", None),
                    ("Set the thermostat", None),
                    ("Turn the lights green and lower the volume", None),
                    ("What is the weather in Cebu?", None),
                    ("Do not turn on the lights", None),
                ]
                for turn, (text, expected) in enumerate(cases, 1):
                    timing.turn = turn
                    messages = [{"role": "user", "content": text}]
                    context = SimpleNamespace(get_messages=lambda: messages, add_message=messages.append)
                    frame = LLMContextFrame(context=context)
                    before = len(calls)
                    started = time.monotonic()
                    await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
                    # Including a repeated context must not duplicate a write.
                    await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
                    actual = calls[before:]
                    passed = actual == ([expected] if expected else [])
                    rows.append({"turn": turn, "expected_tool": expected, "calls": actual,
                                 "seconds": time.monotonic() - started, "passed": passed})
                    print(json.dumps(rows[-1]), flush=True)
                    if not passed:
                        raise AssertionError(f"Unexpected tool outcome on case {turn}")
                if len(speech) != len(cases):
                    raise AssertionError("Expected exactly one spoken receipt per test context")
        finally:
            await model.close()
            await logger.complete()
            trace.close()
    args.output.write_text(json.dumps({"kind": "disposable_text_integration_not_voice", "run": run,
                                       "trace_dir": str(trace.path.parent), "rows": rows}, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:18082")
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
