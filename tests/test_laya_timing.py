"""Keep classifier/argument/fallback timings separate from total decision time."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

path = Path(__file__).resolve().parents[1] / "scripts/summarize_voice_trial.py"
spec = importlib.util.spec_from_file_location("laya_voice_summary", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LayaTimingTests(unittest.TestCase):
    def test_classifier_and_arguments_remain_separate_nested_measurements(self):
        data = [("local_decision", {"model_s": .82, "tool": "control_lights"}),
                ("laya_classification", {"classifier_s": .8}),
                ("laya_arguments", {"extraction_s": .001}),
                ("route_local_tool", {}), ("native_user_bot_latency", {"seconds": 2.6})]
        with tempfile.TemporaryDirectory() as folder:
            events = [{"component": "pi", "event": "turn_event", "turn": 1,
                       "timing_event": name, "fields": fields, "mono_ns": i, "at": i}
                      for i, (name, fields) in enumerate(data)]
            Path(folder, "pi.jsonl").write_text("\n".join(json.dumps(e) for e in events))
            report = module.summarize(Path(folder), [(1, 1)])
        self.assertEqual(report["combined"]["classifier_s"]["median"], .8)
        self.assertEqual(report["combined"]["argument_extraction_s"]["median"], .001)
        self.assertEqual(report["combined"]["model_s"]["median"], .82)
        self.assertIsNone(report["combined"]["model_fallback_s"]["median"])
