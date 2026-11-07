"""Run real MCP state tools against a disposable database, with no model/audio."""

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
    from mcp import StdioServerParameters
    from profiled_mcp import ProfiledMCPClient
    from stall_diagnostics import Diagnostics
    logger.remove()
    logger.add(sys.stderr, level="DEBUG", enqueue=True)
    trace = Diagnostics("pi", run="mcp-storage-probe", directory=args.output_dir)
    server = args.project / "mcp_servers" / "voice_tools_mcp_server.py"
    with tempfile.TemporaryDirectory(prefix="voice-mcp-storage-probe-", dir=args.state_root) as state:
        env = {**trace.server_env(), "VOICE_TOOLS_DATA": state, "VCM_STATE_BACKEND": "local_sqlite"}
        try:
            async with ProfiledMCPClient(diagnostics=trace, server_params=StdioServerParameters(
                command=sys.executable, args=[str(server)], env=env)) as client:
                await client.tools()
                requests = [("control_lights", {"action": "on"}),
                            ("control_lights", {"action": "color", "value": "Green"}),
                            ("set_thermostat", {"degrees": 21}),
                            ("control_lights", {"action": "off"})]
                for index, (tool, values) in enumerate(requests):
                    if index:
                        await asyncio.sleep(args.interval_secs)
                    started = time.monotonic()
                    result = json.loads(await client._call_tool_text(tool, values))
                    assert result.get("ok"), "Synthetic MCP tool failed"
                    print(json.dumps({"case": "mcp_temporary_database", "tool": tool,
                                      "elapsed_ms": (time.monotonic() - started) * 1000,
                                      "ok": result["ok"]}), flush=True)
        finally:
            await logger.complete()
            trace.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", required=True, type=Path)
    p.add_argument("--state-root", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--interval-secs", type=float, default=10)
    args = p.parse_args()
    if not 0 <= args.interval_secs <= 15:
        p.error("Interval must be 0–15 seconds")
    asyncio.run(main(args))
