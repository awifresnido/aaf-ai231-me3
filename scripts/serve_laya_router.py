"""Resident, serialized HTTP classifier on ThinkPad; never an MCP server.

Run with /home/aldlinux/ai/laya-env/bin/python. Bind to loopback and use the
separate Pi SSH reverse tunnel. No model downloads, package changes, or tools.
"""

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))
from laya_contract import CONTRACT, QUESTIONS, TEMPERATURE, gate, verify_artifacts


def load(checkpoint, threads):
    calibration = verify_artifacts(checkpoint)
    import torch
    torch.set_num_threads(threads)
    torch.set_num_interop_threads(1)
    import laya
    started = time.monotonic()
    agent = laya.load(str(checkpoint), device="cpu", calibration=str(calibration))
    if agent.temperature != TEMPERATURE or agent.temperature_by_options:
        raise ValueError("External Laya calibration was not installed")
    load_s = time.monotonic() - started
    started = time.monotonic()
    gate(agent.predict("what time is it", QUESTIONS)["answers"]["route"])
    warmup_s = time.monotonic() - started
    with (checkpoint / "model.safetensors").open("rb") as weights:
        model_sha256 = hashlib.file_digest(weights, "sha256").hexdigest()
    return agent, {"contract": CONTRACT, "device": "cpu", "threads": threads,
                   "load_s": load_s, "warmup_s": warmup_s,
                   "model_sha256": model_sha256}


def serve(agent, metadata, host, port):
    busy = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        timeout = 5

        def log_message(self, *_):
            pass  # Do not retain transcripts or HTTP request details.

        def send_json(self, status, payload):
            body = json.dumps(payload, allow_nan=False).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # A lost classifier response cannot issue a tool.

        def do_GET(self):
            self.send_json(200 if self.path == "/health" else 404,
                           {"ready": True, **metadata} if self.path == "/health" else {})

        def do_POST(self):
            if self.path != "/classify":
                self.send_json(404, {})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 8192:
                    raise ValueError("Invalid body size")
                body = json.loads(self.rfile.read(size))
                if (not isinstance(body, dict) or set(body) != {"text"}
                        or not isinstance(body["text"], str)
                        or not 0 < len(body["text"].strip()) <= 1000):
                    raise ValueError("Invalid transcript")
            except (ValueError, TypeError, OSError):
                self.send_json(400, {"error": "invalid_request"})
                return
            if not busy.acquire(blocking=False):
                self.send_json(503, {"error": "busy"})
                return
            try:
                started = time.monotonic()
                decision = gate(agent.predict(body["text"], QUESTIONS)["answers"]["route"])
                self.send_json(200, {**decision, "contract": CONTRACT,
                                     "classifier_s": time.monotonic() - started})
            except Exception:
                self.send_json(503, {"error": "classification_failed"})
            finally:
                busy.release()

    server = ThreadingHTTPServer((host, port), Handler)
    print(json.dumps({"listening": f"{host}:{port}", **metadata}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=Path("/home/aldlinux/ai/laya_v1"))
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.threads <= 6:
        parser.error("threads must be between 1 and 6")
    agent, metadata = load(args.checkpoint, args.threads)
    serve(agent, metadata, "127.0.0.1", args.port)
