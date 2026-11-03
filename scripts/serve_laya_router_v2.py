"""Serve laya_v2 (9-group router) on the Jetson with FP16 CUDA, v2 contract.

Bind 0.0.0.0 so the Pi reaches it directly over the LAN (same as llama :8084 /
whisper :8090). A rejected turn returns route=None / accepted=False — the caller
escalates; there is no ``other`` label in the v2 schema.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))
from laya_contract_v2 import CONTRACT, QUESTIONS, TEMPERATURE, gate, verify_artifacts  # noqa: E402


def load(checkpoint, threads):
    checkpoint = checkpoint.resolve()
    verify_artifacts(checkpoint)
    # The Orin's 8 GB is shared with llama.cpp (3B, 2.7 GB) + whisper.cpp (turbo,
    # 1.9 GB). fp32 CUDA needs ~1.7 GB and only sometimes allocates — silently
    # falling back to CPU (~2.5 s) which trips the Pi's 2 s classifier timeout.
    # fp16 halves that footprint so CUDA allocation is reliable and ~10x faster.
    os.environ["LAYA_PRECISION"] = "fp16"
    os.environ["LAYA_CUDA_AMP"] = "fp16"
    import torch  # noqa: E402
    torch.set_num_threads(threads)
    torch.set_num_interop_threads(1)
    spec = importlib.util.spec_from_file_location("jetson_v2_router", checkpoint / "use_router_v2.py")
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    started = time.monotonic()
    agent = loader.load_router()
    load_s = time.monotonic() - started
    param = next(agent.model.parameters())
    device = param.device.type
    ptype = str(param.dtype).replace("torch.", "")
    if agent.temperature != TEMPERATURE or getattr(agent, "temperature_by_options", None):
        raise ValueError("External Laya calibration was not installed")
    warmups = []
    for _ in range(3):
        s = time.monotonic()
        gate(agent.predict("what time is it", QUESTIONS)["answers"]["route"])
        warmups.append(time.monotonic() - s)
    with (checkpoint / "model.safetensors").open("rb") as weights:
        model_sha256 = hashlib.file_digest(weights, "sha256").hexdigest()
    return agent, {"contract": CONTRACT, "device": device, "weights_dtype": ptype,
                   "host_role": "jetson", "checkpoint": str(checkpoint),
                   "threads": threads, "load_s": load_s, "warmup_s": warmups,
                   "model_sha256": model_sha256, "torch_version": torch.__version__}


def serve(agent, metadata, host, port):
    busy = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        timeout = 5

        def log_message(self, *_):
            pass

        def send_json(self, status, payload):
            body = json.dumps(payload, allow_nan=False).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

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
    parser.add_argument("--checkpoint", type=Path, default=Path.home() / "models/laya/laya_v2")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8083)
    parser.add_argument("--threads", type=int, default=6)
    args = parser.parse_args()
    if not 1 <= args.threads <= 6:
        parser.error("threads must be between 1 and 6")
    agent, metadata = load(args.checkpoint, args.threads)
    serve(agent, metadata, args.host, args.port)
