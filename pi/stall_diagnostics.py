"""Opt-in metadata traces written by a background thread, separately from logs."""

import asyncio
import contextvars
import itertools
import json
import os
import queue
import re
import resource
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


CALL_ID = contextvars.ContextVar("voice_profile_call_id", default=None)
META_KEY = "voice_profile_call_id"


class Diagnostics:
    def __init__(self, component, *, run, directory):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run):
            raise ValueError("Invalid diagnostic run ID")
        self.run = run
        self.component = component
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        folder = self.directory / run
        folder.mkdir(mode=0o700, exist_ok=True)
        self.path = folder / f"{component}-{os.getpid()}.jsonl"
        # Open before starting the worker so configuration errors fail visibly.
        self._file = os.fdopen(os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a", buffering=1)
        self._queue = queue.Queue(maxsize=8192)
        self._ids = itertools.count()
        self.dropped = 0
        self.write_errors = 0
        self._closed = False
        self._thread = threading.Thread(target=self._write, daemon=True, name="voice-diagnostics")
        self._thread.start()
        self.emit("diagnostics_started")

    @classmethod
    def from_env(cls, component, *, run=None):
        if os.getenv("VOICE_DIAGNOSTICS", "0") != "1":
            return None
        return cls(component, run=run or os.getenv("VOICE_DIAGNOSTICS_RUN") or uuid.uuid4().hex[:10],
                   directory=os.getenv("VOICE_DIAGNOSTICS_DIR", "/dev/shm/voice-agent-diagnostics"))

    def server_env(self):
        return {"VOICE_DIAGNOSTICS": "1", "VOICE_DIAGNOSTICS_RUN": self.run,
                "VOICE_DIAGNOSTICS_DIR": str(self.directory)}

    def emit(self, event, **fields):
        if self._closed:
            return
        item = {"event": event, "run": self.run, "component": self.component,
                "pid": os.getpid(), "at": time.time(), "mono_ns": time.monotonic_ns(),
                "call_id": CALL_ID.get(), **fields}
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            self.dropped += 1

    def _write(self):
        while True:
            item = self._queue.get()
            if item is None:
                break
            try:
                self._file.write(json.dumps(item, separators=(",", ":")) + "\n")
            except (OSError, TypeError, ValueError):
                self.write_errors += 1
        self._file.close()

    def close(self):
        if self._closed:
            return
        self.emit("diagnostics_stopped", dropped=self.dropped, write_errors=self.write_errors)
        self._closed = True
        # Shutdown runs outside the measured path. Never wait indefinitely.
        try:
            self._queue.put(None, timeout=1)
        except queue.Full:
            return
        self._thread.join(timeout=2)

    @contextmanager
    def call(self, call_id):
        token = CALL_ID.set(call_id)
        try:
            yield
        finally:
            CALL_ID.reset(token)

    @contextmanager
    def span(self, phase, **fields):
        span_id = f"{os.getpid()}-{next(self._ids)}"
        started = time.monotonic_ns()
        usage = resource.getrusage(resource.RUSAGE_SELF)
        self.emit("span_start", phase=phase, span_id=span_id, **fields)
        error = None
        try:
            yield
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            ended = time.monotonic_ns()
            after = resource.getrusage(resource.RUSAGE_SELF)
            self.emit("span_end", phase=phase, span_id=span_id,
                      elapsed_ms=(ended - started) / 1e6,
                      process_cpu_ms=((after.ru_utime + after.ru_stime) - (usage.ru_utime + usage.ru_stime)) * 1000,
                      voluntary_switches=after.ru_nvcsw - usage.ru_nvcsw,
                      involuntary_switches=after.ru_nivcsw - usage.ru_nivcsw,
                      input_blocks=after.ru_inblock - usage.ru_inblock,
                      output_blocks=after.ru_oublock - usage.ru_oublock,
                      major_faults=after.ru_majflt - usage.ru_majflt,
                      error=error, **fields)

    async def monitor_loop(self, get_turn=lambda: None):
        loop = asyncio.get_running_loop()
        heartbeat = loop.time()
        maximum = 0.0
        while True:
            expected = loop.time() + 0.1
            await asyncio.sleep(0.1)
            now = loop.time()
            lag_ms = max(0.0, (now - expected) * 1000)
            maximum = max(maximum, lag_ms)
            if lag_ms >= 50:
                self.emit("event_loop_lag", lag_ms=lag_ms, turn=get_turn())
            if now - heartbeat >= 5:
                usage = resource.getrusage(resource.RUSAGE_SELF)
                self.emit("loop_heartbeat", max_lag_ms=maximum, turn=get_turn(),
                          dropped=self.dropped, write_errors=self.write_errors,
                          process_cpu_s=usage.ru_utime + usage.ru_stime,
                          input_blocks=usage.ru_inblock, output_blocks=usage.ru_oublock,
                          major_faults=usage.ru_majflt, max_rss_kb=usage.ru_maxrss)
                heartbeat, maximum = now, 0.0


class ProfiledCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=()):
        # Only the SQL verb is recorded; no SQL text or parameter values.
        verb = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else "EMPTY"
        with self.connection.diagnostics.span("sqlite_execute", operation=verb):
            return super().execute(sql, parameters)

    def fetchone(self):
        with self.connection.diagnostics.span("sqlite_fetchone"):
            return super().fetchone()

    def fetchall(self):
        with self.connection.diagnostics.span("sqlite_fetchall"):
            return super().fetchall()


class ProfiledConnection(sqlite3.Connection):
    def __init__(self, *args, diagnostics, **kwargs):
        self.diagnostics = diagnostics
        with diagnostics.span("sqlite_connect"):
            super().__init__(*args, **kwargs)

    def execute(self, sql, parameters=()):
        return self.cursor(factory=ProfiledCursor).execute(sql, parameters)

    def commit(self):
        with self.diagnostics.span("sqlite_commit"):
            return super().commit()

    def close(self):
        with self.diagnostics.span("sqlite_close"):
            return super().close()
