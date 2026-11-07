"""Matched text-only comparison, never executes tools or records live speech.

Run on Pi with its existing venv, --env-file pointing to the private config.
Jev queries are explicitly opt-in through --jev. Failures stay in denominators.
This authored challenge set is not an independent statistical accuracy estimate.
"""

import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))
from laya_contract import CONTRACT, QUESTIONS, gate
from laya_router import grounded_arguments


def stats(values):
    ordered = sorted(values)
    return {"count": len(values), "p50_s": statistics.median(values),
            "p95_s": ordered[math.ceil(len(ordered) * .95) - 1]} if values else {"count": 0}


async def compare(args):
    cases = json.loads(args.cases.read_text())
    engines = ["laya", "jev"] if args.jev else ["laya"]
    if args.env_file:
        from dotenv import dotenv_values
        config = dotenv_values(args.env_file)
    else:
        config = os.environ
    key = config.get("TYPESAFE_API_KEY")
    if args.jev and not key:
        raise SystemExit("Jev comparison requires TYPESAFE_API_KEY in private config")
    rows = []
    async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
        health = (await client.get(args.url + "/health")).json()
        if health.get("contract") != CONTRACT:
            raise ValueError("Unverified classifier service")
        for index, case in enumerate(cases):
            # Alternate order to reduce a fixed ordering effect.
            for engine in engines if index % 2 == 0 else list(reversed(engines)):
                row = {"case": index, "engine": engine, "expected_route": case["route"],
                       "expected_tool": case["route"] if case["arguments"] is not None else "reply"}
                started = time.monotonic()
                try:
                    if engine == "laya":
                        response = await client.post(args.url + "/classify", json={"text": case["text"]})
                        response.raise_for_status()
                        payload = response.json()
                        if payload.get("contract") != CONTRACT:
                            raise ValueError("Laya contract mismatch")
                        data = {"choice": payload["raw_choice"], "probabilities": payload["probabilities"]}
                        tau, gap = .5, .05
                    else:
                        response = await client.post("https://api.typesafe.ai/v1/systemone",
                            headers={"Authorization": "Bearer " + key},
                            json={"model": "jev-1.14.0", "state": case["text"], "questions": QUESTIONS})
                        response.raise_for_status()
                        data = response.json()["answers"]["route"]
                        tau, gap = .9, .2
                    elapsed = time.monotonic() - started
                    routed = gate(data, tau=tau, gap=gap)
                    parsed = grounded_arguments(routed["route"], case["text"])
                    proposed = routed["route"] if parsed is not None else "reply"
                    row.update(seconds=elapsed, raw_choice=routed["raw_choice"],
                               route_correct=routed["raw_choice"] == case["route"],
                               accepted=routed["accepted"], tool=proposed, arguments=parsed,
                               wrong_accepted_tool=(routed["accepted"] and routed["route"] not in {"other", "small_talk"}
                                                    and routed["route"] != case["route"]),
                               action_exact=(proposed == row["expected_tool"]
                                             and (parsed == case["arguments"] if parsed is not None else True)))
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    row.update(seconds=time.monotonic() - started, error=type(exc).__name__,
                               route_correct=False, action_exact=False)
                rows.append(row)
            print(json.dumps({"completed_cases": index + 1, "total": len(cases)}), flush=True)
    report = {"kind": "authored_text_challenge_not_voice_or_holdout", "health": health,
              "gates": {"laya": [.5, .05], "jev": [.9, .2]}, "summary": {}, "rows": rows}
    for engine in engines:
        selected = [r for r in rows if r["engine"] == engine]
        report["summary"][engine] = {
            "items": len(selected), "errors": sum("error" in r for r in selected),
            "route_accuracy": sum(r["route_correct"] for r in selected) / len(selected),
            "action_exact_accuracy": sum(r["action_exact"] for r in selected) / len(selected),
            "wrong_accepted_tool_count": sum(r.get("wrong_accepted_tool", False) for r in selected),
            "wrong_grounded_tool_count": sum(r.get("tool", "reply") != "reply" and not r["action_exact"] for r in selected),
            "successful_latency": stats([r["seconds"] for r in selected if "error" not in r]),
            "all_attempt_latency": stats([r["seconds"] for r in selected]),
        }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).resolve().parents[1] / "tests/fixtures/laya_challenge.json")
    parser.add_argument("--url", default="http://127.0.0.1:18082")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--jev", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(compare(parser.parse_args()))
