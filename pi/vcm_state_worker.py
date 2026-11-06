"""Private JSON-lines SQLite worker on Jetson NVMe. This is not an MCP server."""

from contextlib import nullcontext
import json
import os
import re
import sys

from stall_diagnostics import Diagnostics
from vcm_state import SQLiteStateStore, MAX_MESSAGE


def main():
    os.umask(0o077)
    trace = Diagnostics.from_env("state")
    store = SQLiteStateStore(os.environ["VOICE_TOOLS_DATA"], diagnostics=trace)
    try:
        ready = store.health()
        if trace:
            trace.emit("state_worker_configuration", state_host="jetson", **ready)
        print(json.dumps(ready, separators=(",", ":")), flush=True)
        while True:
            line = sys.stdin.buffer.readline(MAX_MESSAGE + 1)
            if not line:
                break
            if len(line) > MAX_MESSAGE or not line.endswith(b"\n"):
                raise ValueError("Oversized or incomplete storage request")
            request_id = None
            try:
                request = json.loads(line)
                if not isinstance(request, dict) or set(request) != {"request_id", "operation", "arguments", "call_id"}:
                    raise ValueError("Invalid storage request fields")
                request_id = request["request_id"]
                if not isinstance(request_id, str) or not re.fullmatch(r"[0-9a-f]{32}", request_id):
                    raise ValueError("Invalid storage request ID")
                call_id = request["call_id"] or request_id
                if not isinstance(call_id, str) or not re.fullmatch(r"[0-9a-f]{32}", call_id):
                    raise ValueError("Invalid trace correlation ID")
                scope = trace.call(call_id) if trace else nullcontext()
                with scope:
                    span = trace.span("state_worker_call", operation=request["operation"], request_id=request_id) if trace else nullcontext()
                    with span:
                        result = store.dispatch(request["operation"], request["arguments"], request_id=request_id)
                response = {"request_id": request_id, "ok": True, "result": result}
            except Exception as exc:
                response = {"request_id": request_id, "ok": False, "error": type(exc).__name__}
            # No success receipt exists until dispatch has returned from commit.
            encoded = json.dumps(response, separators=(",", ":"), allow_nan=False)
            if len(encoded.encode()) > MAX_MESSAGE:
                raise ValueError("Storage response exceeds protocol bound")
            print(encoded, flush=True)
            if trace:
                trace.emit("state_worker_status", dropped=trace.dropped, write_errors=trace.write_errors)
    finally:
        store.close()
        if trace:
            trace.close()


if __name__ == "__main__":
    main()
