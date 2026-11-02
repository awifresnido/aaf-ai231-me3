"""Serve the Jetson checkpoint's FP16 CUDA loader using the pinned HTTP contract.

This is a text classifier, not an MCP server. No package/model downloads or
tool execution occur. The existing ThinkPad CPU service is left unchanged.
"""

import argparse
import hashlib
import importlib.metadata
import importlib.util
import os
from pathlib import Path
import time

from serve_laya_router import serve
from laya_contract import CONTRACT, QUESTIONS, TEMPERATURE, gate, verify_artifacts


def assert_cuda_fp16(agent, torch):
    parameter = next(agent.model.parameters())
    if (parameter.device.type != "cuda" or parameter.dtype != torch.float16
            or not agent.amp_enabled or agent.dtype != torch.float16):
        raise ValueError("Jetson trial requires CUDA FP16 weights and autocast")


class CudaRouter:
    def __init__(self, agent, torch):
        self.agent, self.torch = agent, torch

    def predict(self, text, questions):
        if questions != QUESTIONS:
            raise ValueError("Jetson trial requires the exact trained question")
        assert_cuda_fp16(self.agent, self.torch)
        self.torch.cuda.synchronize()
        result = self.agent.predict(text, questions)
        self.torch.cuda.synchronize()
        assert_cuda_fp16(self.agent, self.torch)
        return result


def load(checkpoint, threads):
    checkpoint = checkpoint.resolve()
    verify_artifacts(checkpoint)
    os.environ["LAYA_PRECISION"] = "fp16"
    os.environ["LAYA_CUDA_AMP"] = "fp16"
    import torch
    if not torch.cuda.is_available():
        raise ValueError("Jetson CUDA is unavailable")
    torch.set_num_threads(threads)
    torch.set_num_interop_threads(1)
    spec = importlib.util.spec_from_file_location("jetson_checkpoint_router", checkpoint / "use_router.py")
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    started = time.monotonic()
    agent = loader.load_router()
    torch.cuda.synchronize()
    load_s = time.monotonic() - started
    assert_cuda_fp16(agent, torch)
    if agent.temperature != TEMPERATURE or agent.temperature_by_options:
        raise ValueError("External Laya calibration was not installed")
    router = CudaRouter(agent, torch)
    warmups = []
    for _ in range(3):
        started = time.monotonic()
        gate(router.predict("what time is it", QUESTIONS)["answers"]["route"])
        warmups.append(time.monotonic() - started)
    with (checkpoint / "model.safetensors").open("rb") as weights:
        model_sha256 = hashlib.file_digest(weights, "sha256").hexdigest()
    return router, {"contract": CONTRACT, "device": "cuda", "host_role": "jetson",
                    "weights_dtype": "float16", "autocast_dtype": "float16",
                    "checkpoint": str(checkpoint), "threads": threads,
                    "load_s": load_s, "warmup_s": warmups,
                    "model_sha256": model_sha256,
                    "torch_version": torch.__version__,
                    "laya_version": importlib.metadata.version("laya"),
                    "cuda_allocated_bytes": torch.cuda.memory_allocated(),
                    "cuda_reserved_bytes": torch.cuda.memory_reserved()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=Path.home() / "models/laya/laya_v1")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.threads <= 6:
        parser.error("threads must be between 1 and 6")
    router, metadata = load(args.checkpoint, args.threads)
    serve(router, metadata, args.host, args.port)
