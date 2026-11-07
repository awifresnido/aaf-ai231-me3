"""Opt-in queued output for the Pi's existing DEBUG stderr log."""

import os
import sys

from loguru import logger


def configure_queued_logging(*, sink=None):
    if os.getenv("VOICE_QUEUED_LOGGING", "0") != "1":
        return False
    # Match the inspected default sink/level/format; change only queueing.
    logger.remove()
    logger.add(sys.stderr if sink is None else sink, level="DEBUG", enqueue=True)
    return True
