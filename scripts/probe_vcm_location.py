"""Real MCP placement preflight on disposable state, without model or audio."""

import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time


async def main(args):
    sys.path.insert(0, str(args.project))
    from loguru import logger
    from profiled_mcp import ProfiledMCPClient
    from stall_diagnostics import Diagnostics
    from vcm_server_location import build_vcm_server, JETSON_ROOT
    logger.remove()
    logger.add(sys.stderr, enqueue=True)
    trace = Diagnostics("pi", run=args.run, directory=args.output_dir)
    requests = [("control_lights", {"action": "on"}),
                ("control_lights", {"action": "color", "value": "Green"}),
                ("set_thermostat", {"degrees": 26}),
                ("control_lights", {"action": "off"})]
    if args.exercise_state:
        requests.extend([("add_reminder", {"text": "synthetic storage preflight"}),
                         ("list_reminders", {}), ("set_timer", {"duration_s": 60}),
                         ("set_alarm", {"time_str": "09:00 PM"})])
    local = tempfile.TemporaryDirectory(prefix="voice-vcm-preflight-", dir=args.state_root) if args.host == "pi" else None
    env = {"VCM_TOOL_SERVER_HOST": args.host, "VENV_PY": sys.executable, "VCM_STATE_BACKEND": args.state_backend}
    if local:
        env["VOICE_TOOLS_DATA"] = local.name
        env["VCM_JETSON_DATA_DIR"] = JETSON_ROOT + "/state/preflight/" + args.run
    else:
        env["VCM_JETSON_DATA_DIR"] = JETSON_ROOT + "/state/preflight/" + args.run
    try:
        spec = build_vcm_server(args.project, diagnostics=trace, environ=env)
        async with ProfiledMCPClient(diagnostics=trace, server_params=spec.server_params()) as client:
            tools = await client.tools()
            names = sorted(tool.name for tool in tools.standard_tools)
            assert len(names) == 13 and "play_radio" not in names
            print(json.dumps({"host": args.host, "run": args.run, "tools": names}), flush=True)
            for index, (name, arguments) in enumerate(requests):
                if index:
                    await asyncio.sleep(args.interval_secs)
                started = time.monotonic()
                result = json.loads(await client._call_tool_text(name, arguments))
                assert result.get("ok"), "Tool call failed"
                if name == "list_reminders" and args.exercise_state:
                    assert "synthetic storage preflight" in result["reminders"]
                print(json.dumps({"host": args.host, "tool": name, "ok": result["ok"],
                                  "elapsed_ms": (time.monotonic() - started) * 1000}), flush=True)
    finally:
        await logger.complete()
        trace.close()
        if local:
            local.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=["pi", "jetson"], required=True)
    parser.add_argument("--state-backend", choices=["local_sqlite", "jetson_sqlite"], default="jetson_sqlite")
    parser.add_argument("--exercise-state", action="store_true", help="Also exercise reminder read/write, timer, and alarm persistence")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, default=Path("/home/aldwinrpi4/voice-agent-tools"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--interval-secs", type=float, default=5)
    args = parser.parse_args()
    if not 0 <= args.interval_secs <= 15:
        parser.error("Use an interval between 0 and 15 seconds")
    asyncio.run(main(args))
