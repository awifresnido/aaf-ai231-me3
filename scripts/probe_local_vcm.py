"""Probe the selected VCM model host without executing tools or speaking audio."""

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))
from local_vcm import LocalVCMClient


async def main():
    client = LocalVCMClient()
    cases = [
        ("What time is it now?", "get_time", {}),
        ("Turn on the lights", "control_lights", {"action": "on", "value": ""}),
        ("Set the room temperature to twenty eight degrees", "set_thermostat", {"degrees": 28}),
        ("Set a five minute timer", "set_timer", {"duration_s": 300}),
        ("Set the lights to blue", "control_lights", {"action": "color", "value": "Blue"}),
        ("What is the weather today?", "get_weather", {}),
        ("Set the lights to eighty percent brightness", "control_lights", {"action": "brightness", "value": "80"}),
        ("Set an alarm for nine PM", "set_alarm", {"time_str": "09:00 PM"}),
        ("Remind me to study", "add_reminder", {"text": "study"}),
        ("List my reminders", "list_reminders", {}),
        ("Stop the music", "playback_control", {"action": "stop"}),
        ("Play some jazz music", "play_music", {"query": "jazz"}),
        ("Send a message to my contact", "reply", None),
        ("Play the radio", "reply", None),
    ]
    failures = 0
    try:
        for text, tool, args in cases:
            started = time.monotonic()
            context = SimpleNamespace(get_messages=lambda: [{"role": "user", "content": text}])
            error = None
            try:
                decision = await asyncio.wait_for(client.decide(context), client.timeout)
            except (TimeoutError, ValueError) as exc:
                decision = None
                error = type(exc).__name__
            actual = decision.get("arguments") if decision else None
            if tool in {"add_reminder", "play_music"} and isinstance(actual, dict):
                actual = {key: value.casefold() if isinstance(value, str) else value
                          for key, value in actual.items()}
            passed = bool(decision and decision.get("tool") == tool
                          and (args is None or actual == args))
            print(json.dumps({"model_host": client.model_host, "utterance": text, "seconds": round(time.monotonic() - started, 3),
                              "decision": decision, "passed": passed, "error": error}), flush=True)
            if not passed:
                failures += 1
        if failures:
            raise AssertionError(f"{failures} local model decisions failed")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
