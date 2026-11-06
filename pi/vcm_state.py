"""VCM persistence: local SQLite or a persistent, restricted SSH state worker.

The worker speaks a private JSON-lines storage protocol, not MCP. Writes
return only after FULL commit. Request receipts share the write transaction
so a repeated request ID cannot create a second reminder/timer/alarm.
"""

from contextlib import nullcontext
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import sqlite3
import subprocess
import threading
import time
import uuid

from stall_diagnostics import CALL_ID, ProfiledConnection


PROTOCOL = "voice-state-v1"
MAX_MESSAGE = 1024 * 1024
SCHEMA = [
    "CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, created_ms REAL NOT NULL, done INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS device_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS timers (id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT NOT NULL, ends_at REAL NOT NULL, fired INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS alarms (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS state_requests (request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL)",
]
FIELDS = {
    "get_state": ({"key"}, set()), "set_state": ({"key", "value"}, set()),
    "patch_state": ({"key", "changes", "defaults"}, {"require_existing"}),
    "add_timer": ({"label", "ends_at"}, set()), "add_alarm": ({"time_str"}, set()),
    "add_reminder": ({"text", "created_ms"}, set()), "list_reminders": (set(), set()),
}
WRITE_OPS = set(FIELDS) - {"get_state", "list_reminders"}


def validate_request(operation, arguments, request_id):
    if not isinstance(operation, str) or operation not in FIELDS or not isinstance(arguments, dict):
        raise ValueError("Unknown state operation")
    required, optional = FIELDS[operation]
    if not required <= arguments.keys() or not arguments.keys() <= required | optional:
        raise ValueError("Invalid state operation fields")
    if not isinstance(request_id, str) or not re.fullmatch(r"[0-9a-f]{32}", request_id):
        raise ValueError("Invalid state request ID")
    for key in {"key", "label", "time_str", "text"} & arguments.keys():
        if not isinstance(arguments[key], str):
            raise ValueError("Invalid state string")
    for key in {"value", "changes", "defaults"} & arguments.keys():
        if not isinstance(arguments[key], dict):
            raise ValueError("Invalid state object")
    for key in {"ends_at", "created_ms"} & arguments.keys():
        if type(arguments[key]) not in {int, float}:
            raise ValueError("Invalid state timestamp")
    if "require_existing" in arguments and type(arguments["require_existing"]) is not bool:
        raise ValueError("Invalid state patch condition")
    encoded = json.dumps([operation, arguments], sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode()) > MAX_MESSAGE // 2:
        raise ValueError("State request too large")
    return hashlib.sha256(encoded.encode()).hexdigest()


class SQLiteStateStore:
    def __init__(self, data_dir, *, diagnostics=None):
        self.path = Path(data_dir) / "state.db"
        self.diagnostics = diagnostics

    def _connect(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        options = {"factory": partial(ProfiledConnection, diagnostics=self.diagnostics)} if self.diagnostics else {}
        db = sqlite3.connect(str(self.path), check_same_thread=False, **options)
        try:
            db.execute("PRAGMA synchronous=FULL")
            for sql in SCHEMA:
                db.execute(sql)
            db.commit()
            return db
        except BaseException:
            db.close()
            raise

    def health(self):
        db = self._connect()
        try:
            return {"protocol": PROTOCOL, "ready": True, "sqlite_version": sqlite3.sqlite_version,
                    "journal_mode": db.execute("PRAGMA journal_mode").fetchone()[0],
                    "synchronous": db.execute("PRAGMA synchronous").fetchone()[0]}
        finally:
            db.close()

    def dispatch(self, operation, arguments, *, request_id=None):
        request_id = request_id or uuid.uuid4().hex
        fingerprint = validate_request(operation, arguments, request_id)
        db = self._connect()
        try:
            if operation in WRITE_OPS:
                db.execute("BEGIN IMMEDIATE")
                previous = db.execute("SELECT fingerprint, result FROM state_requests WHERE request_id=?", (request_id,)).fetchone()
                if previous:
                    if previous[0] != fingerprint:
                        raise ValueError("State request ID reused for a different operation")
                    result = json.loads(previous[1])
                    db.rollback()
                    return result
            result = self._execute(db, operation, arguments)
            if operation in WRITE_OPS:
                db.execute("INSERT INTO state_requests(request_id,fingerprint,result) VALUES (?,?,?)",
                           (request_id, fingerprint, json.dumps(result, separators=(",", ":"))))
                db.commit()
            return result
        finally:
            db.close()  # Also rolls back an uncommitted failed write.

    @staticmethod
    def _execute(db, operation, arguments):
        def get(key):
            row = db.execute("SELECT value FROM device_state WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None

        def put(key, value):
            db.execute("INSERT INTO device_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, json.dumps(value)))

        if operation == "get_state":
            return get(arguments["key"])
        if operation == "set_state":
            put(arguments["key"], arguments["value"])
        elif operation == "patch_state":
            value = get(arguments["key"])
            if not value and arguments.get("require_existing"):
                return None
            value = value or dict(arguments["defaults"])
            value.update(arguments["changes"])
            put(arguments["key"], value)
            return value
        elif operation == "add_timer":
            db.execute("INSERT INTO timers(label,ends_at) VALUES (?,?)", (arguments["label"], arguments["ends_at"]))
        elif operation == "add_alarm":
            db.execute("INSERT INTO alarms(time,enabled) VALUES (?,1)", (arguments["time_str"],))
        elif operation == "add_reminder":
            db.execute("INSERT INTO reminders(text,created_ms) VALUES (?,?)", (arguments["text"], arguments["created_ms"]))
        elif operation == "list_reminders":
            return [list(row) for row in db.execute("SELECT id,text FROM reminders WHERE done=0 ORDER BY id DESC").fetchall()]
        return None

    def close(self):
        pass


class StateUnavailable(RuntimeError):
    """No confirmed receipt; a transmitted write may already have committed."""


class JetsonStateStore:
    def __init__(self, *, diagnostics=None, environ=None, command=None):
        self.diagnostics = diagnostics
        self.environ = os.environ if environ is None else environ
        self.command = command
        self.timeout = float(self.environ.get("VCM_STATE_TIMEOUT_SECS", "8"))
        if not 0 < self.timeout <= 30:
            raise ValueError("VCM_STATE_TIMEOUT_SECS must be in (0,30]")
        self._lock = threading.Lock()
        self._process = None
        self._buffer = b""

    @staticmethod
    def _wait(fd, event, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("State worker timed out")
        with selectors.DefaultSelector() as selector:
            selector.register(fd, event)
            if not selector.select(remaining):
                raise TimeoutError("State worker timed out")

    def _receive(self, deadline):
        while b"\n" not in self._buffer:
            self._wait(self._process.stdout.fileno(), selectors.EVENT_READ, deadline)
            block = os.read(self._process.stdout.fileno(), 65536)
            if not block:
                raise EOFError("State worker disconnected")
            self._buffer += block
            if len(self._buffer) > MAX_MESSAGE:
                raise ValueError("State response too large")
        line, self._buffer = self._buffer.split(b"\n", 1)
        return json.loads(line)

    def start(self):
        with self._lock:
            try:
                return self._start(time.monotonic() + self.timeout)
            except (OSError, ValueError, TimeoutError, EOFError) as exc:
                self._discard()
                raise StateUnavailable("Jetson state worker unavailable") from exc

    def _start(self, deadline):
        if self._process is None:
            from vcm_server_location import build_state_worker
            spec = build_state_worker(diagnostics=self.diagnostics, environ=self.environ)
            command = self.command or [spec.command, *spec.args]
            self._process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
            os.set_blocking(self._process.stdin.fileno(), False)
            os.set_blocking(self._process.stdout.fileno(), False)
            ready = self._receive(deadline)
            if (not isinstance(ready, dict) or ready.get("protocol") != PROTOCOL or
                    ready.get("ready") is not True or ready.get("synchronous") != 2):
                raise ValueError("Invalid durable state-worker handshake")
            self._ready = ready
        return self._ready

    def dispatch(self, operation, arguments, *, request_id=None):
        request_id = request_id or uuid.uuid4().hex
        validate_request(operation, arguments, request_id)
        payload = json.dumps({"request_id": request_id, "operation": operation, "arguments": arguments,
                              "call_id": CALL_ID.get()}, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        scope = self.diagnostics.span("state_rpc", operation=operation, request_id=request_id) if self.diagnostics else nullcontext()
        deadline = time.monotonic() + self.timeout
        if not self._lock.acquire(timeout=self.timeout):
            raise StateUnavailable("State worker busy; request was not sent")
        try:
            with scope:
                return self._dispatch(payload, request_id, deadline)
        finally:
            self._lock.release()

    def _dispatch(self, payload, request_id, deadline):
        try:
            self._start(deadline)
            sent = 0
            while sent < len(payload):
                self._wait(self._process.stdin.fileno(), selectors.EVENT_WRITE, deadline)
                count = os.write(self._process.stdin.fileno(), payload[sent:])
                if not count:
                    raise EOFError("State worker input closed")
                sent += count
            response = self._receive(deadline)
            if not isinstance(response, dict) or response.get("request_id") != request_id or response.get("ok") is not True:
                raise ValueError("State worker did not confirm the operation")
            return response["result"]
        except (OSError, KeyError, ValueError, TimeoutError, EOFError) as exc:
            self._discard()
            # Never retry a write or silently use a local SQLite file.
            raise StateUnavailable("State operation not confirmed; outcome may be unknown") from exc

    def _discard(self):
        process, self._process = self._process, None
        self._buffer = b""
        if process:
            process.stdin.close()
            process.stdout.close()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

    def close(self):
        with self._lock:
            self._discard()


def state_store_from_env(*, diagnostics=None):
    backend = os.getenv("VCM_STATE_BACKEND", "jetson_sqlite").strip().lower()
    if backend == "jetson_sqlite":
        return JetsonStateStore(diagnostics=diagnostics)
    if backend == "local_sqlite":
        return SQLiteStateStore(os.getenv("VOICE_TOOLS_DATA", str(Path.home() / "voice-agent-tools")), diagnostics=diagnostics)
    raise ValueError("VCM_STATE_BACKEND must be local_sqlite or jetson_sqlite")
