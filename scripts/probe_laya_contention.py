"""Model-only sequential/concurrent ThinkPad probe; never issues tool calls."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))


async def main(args):
    from dotenv import dotenv_values
    from local_vcm import LocalVCMClient
    config = dotenv_values(args.env_file)
    os.environ.update({k: v for k, v in config.items() if k.startswith("SMALL_LLM_PRIMARY_") and v is not None})
    os.environ["LOCAL_VCM_MODEL_HOST"] = "thinkpad"
    model = LocalVCMClient()
    rows = []
    texts = ["What time is it now?", "Turn on the lights", "Set the lights to blue",
             "Set the thermostat to twenty six degrees", "Remind me to Review Laya Results"]
    async with httpx.AsyncClient(timeout=12, trust_env=False) as router:
        async def measure(engine, text, phase):
            started = time.monotonic()
            row = {"engine": engine, "phase": phase, "case": texts.index(text)}
            try:
                if engine == "laya":
                    response = await router.post(args.url + "/classify", json={"text": text})
                    response.raise_for_status()
                    row["route"] = response.json()["route"]
                else:
                    context = SimpleNamespace(get_messages=lambda: [{"role": "user", "content": text}])
                    decision = await model.decide(context)
                    if not isinstance(decision, dict):
                        raise ValueError("No model decision")
                    row["route"] = decision.get("tool")
            except (httpx.HTTPError, ValueError) as exc:
                row["error"] = type(exc).__name__
            row["seconds"] = time.monotonic() - started
            rows.append(row)
            print(json.dumps(row), flush=True)
        try:
            for text in texts:
                await measure("laya", text, "sequential")
                await measure("llama", text, "sequential")
            for text in texts:
                await asyncio.gather(measure("laya", text, "concurrent"), measure("llama", text, "concurrent"))
        finally:
            await model.close()
    args.output.write_text(json.dumps({"kind": "model_only_not_voice", "rows": rows}, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:18082")
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
