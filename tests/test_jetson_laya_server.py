"""Reject silent CPU/precision changes and synchronize CUDA classifier timing."""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from serve_jetson_laya_router import CudaRouter, assert_cuda_fp16
from laya_contract import QUESTIONS


class JetsonRouterTests(unittest.TestCase):
    def runtime(self):
        parameter = SimpleNamespace(device=SimpleNamespace(type="cuda"), dtype="fp16")
        torch = SimpleNamespace(float16="fp16", cuda=SimpleNamespace(synchronize=Mock()))
        agent = SimpleNamespace(model=SimpleNamespace(parameters=lambda: iter([parameter])),
                                amp_enabled=True, dtype="fp16", predict=Mock(return_value={"ok": True}))
        return parameter, torch, agent

    def test_synchronize_before_and_after_prediction(self):
        _, torch, agent = self.runtime()
        events = []
        torch.cuda.synchronize.side_effect = lambda: events.append("sync")
        agent.predict.side_effect = lambda *args: events.append("predict") or {"ok": True}
        self.assertEqual(CudaRouter(agent, torch).predict("time", QUESTIONS), {"ok": True})
        self.assertEqual(events, ["sync", "predict", "sync"])

    def test_reject_cpu_or_wrong_precision(self):
        for setting in ["cpu", "fp32_weights", "bf16_autocast", "autocast_off"]:
            with self.subTest(setting=setting):
                parameter, torch, agent = self.runtime()
                if setting == "cpu": parameter.device.type = "cpu"
                if setting == "fp32_weights": parameter.dtype = "fp32"
                if setting == "bf16_autocast": agent.dtype = "bf16"
                if setting == "autocast_off": agent.amp_enabled = False
                with self.assertRaises(ValueError): assert_cuda_fp16(agent, torch)

    def test_reject_runtime_cpu_fallback(self):
        parameter, torch, agent = self.runtime()
        def fallback(*args):
            parameter.device.type = "cpu"
            return {"ok": True}
        agent.predict.side_effect = fallback
        with self.assertRaises(ValueError): CudaRouter(agent, torch).predict("time", QUESTIONS)

    def test_reject_changed_question_before_inference(self):
        _, torch, agent = self.runtime()
        with self.assertRaises(ValueError): CudaRouter(agent, torch).predict("time", {})
        agent.predict.assert_not_called()
