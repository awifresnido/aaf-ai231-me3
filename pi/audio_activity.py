"""Publish minimal live speech activity for the local dashboard."""

import asyncio
import json
import os
import time


async def publish_activity(output, backchannel, *, path="/dev/shm/me3-audio-activity.json", interval=0.25):
    temporary = f"{path}.{os.getpid()}.tmp"
    try:
        while True:
            now = time.monotonic()
            payload = {
                "updated_at": time.time(),
                "user_speaking": bool(backchannel._user_speaking) if backchannel is not None else None,
                "bot_speaking": bool(getattr(output, "playback_busy_until", 0.0) > now),
            }
            try:
                with open(temporary, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, separators=(",", ":"))
                os.replace(temporary, path)
            except OSError:
                pass  # A dashboard failure must never interrupt speech.
            await asyncio.sleep(interval)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
