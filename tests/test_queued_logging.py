"""A blocked log sink must not run on the voice event loop."""

import asyncio
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))
from queued_logging import configure_queued_logging


class QueuedLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_writer_does_not_block_loop_and_flush_preserves_records(self):
        entered = threading.Event()
        release = threading.Event()
        threads = []
        records = []

        def sink(message):
            threads.append(threading.get_ident())
            entered.set()
            if not release.wait(timeout=2):
                return
            records.append(message.record)

        try:
            with patch.dict(os.environ, {"VOICE_QUEUED_LOGGING": "1"}):
                self.assertTrue(configure_queued_logging(sink=sink))
            logger.debug("first profile record")
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            # The writer is still blocked, yet another record and loop work run.
            logger.info("second profile record")
            await asyncio.sleep(0.02)
            self.assertFalse(release.is_set())
            self.assertNotEqual(threads[0], threading.get_ident())
            release.set()
            await logger.complete()
            self.assertEqual([r["message"] for r in records],
                             ["first profile record", "second profile record"])
            self.assertEqual([r["level"].name for r in records], ["DEBUG", "INFO"])
        finally:
            release.set()
            await logger.complete()
            logger.remove()
            logger.add(sys.stderr, level="DEBUG")

    async def test_disabled_mode_keeps_existing_handlers(self):
        with patch.dict(os.environ, {"VOICE_QUEUED_LOGGING": "0"}):
            with patch.object(logger, "remove") as remove, patch.object(logger, "add") as add:
                self.assertFalse(configure_queued_logging())
                remove.assert_not_called()
                add.assert_not_called()
