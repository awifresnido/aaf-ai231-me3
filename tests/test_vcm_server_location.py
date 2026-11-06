"""Placement isolation, restricted SSH requests, and multi-host timings."""

import base64
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pi"))
from vcm_server_location import build_vcm_server, build_state_worker, decode_remote_request, JETSON_ROOT

spec = importlib.util.spec_from_file_location("stall_summary", ROOT / "scripts" / "summarize_stall_diagnostics.py")
summary_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary_module)


def request(value):
    return "voice-agent-vcm " + base64.urlsafe_b64encode(json.dumps(value).encode()).decode()


class PlacementTests(unittest.TestCase):
    def test_default_stays_on_pi_without_forwarding_bot_credentials(self):
        spec = build_vcm_server("/project", environ={"OLLAMA_API_KEY": "private", "JEV_API_KEY": "private"})
        self.assertEqual((spec.host, spec.transport), ("pi", "local_stdio"))
        self.assertEqual(spec.state_backend, "jetson_sqlite")
        self.assertEqual(spec.args, ["/project/mcp_servers/voice_tools_mcp_server.py"])
        self.assertNotIn("private", json.dumps(spec.env))

    def test_jetson_is_pinned_ssh_with_allowlisted_settings_and_matching_run(self):
        spec = build_vcm_server("/project", environ={"VCM_TOOL_SERVER_HOST": "jetson", "OLLAMA_API_KEY": "private",
            "VOICE_TOOLS_TZ": "Asia/Manila"}, diagnostics=SimpleNamespace(run="voice-test"))
        self.assertEqual((spec.command, spec.host, spec.transport), ("ssh", "jetson", "ssh_stdio"))
        self.assertIn("StrictHostKeyChecking=yes", spec.args)
        self.assertIn("BatchMode=yes", spec.args)
        self.assertEqual(spec.env, {})
        result = decode_remote_request(spec.args[-1], state_root=Path(JETSON_ROOT) / "state")
        self.assertEqual(result["VOICE_DIAGNOSTICS_RUN"], "voice-test")
        self.assertEqual(result["VOICE_TOOLS_TZ"], "Asia/Manila")
        self.assertEqual(result["VOICE_TOOLS_DATA"], JETSON_ROOT + "/state")
        self.assertEqual(result["VCM_STATE_BACKEND"], "local_sqlite")
        self.assertNotIn("private", json.dumps(result))

    def test_unknown_location_and_option_injection_fail_without_local_fallback(self):
        for env in [{"VCM_TOOL_SERVER_HOST": "auto"}, {"VCM_TOOL_SERVER_HOST": "jetson", "VCM_JETSON_SSH_TARGET": "-oProxyCommand=x@host"},
                    {"VCM_TOOL_SERVER_HOST": "jetson", "VCM_JETSON_SSH_KEY": "relative"}]:
            with self.subTest(env=env), self.assertRaises(ValueError):
                build_vcm_server("/project", environ=env)

    def test_local_state_override_and_diagnostics_reach_only_local_process(self):
        diag = SimpleNamespace(server_env=lambda: {"VOICE_DIAGNOSTICS": "1", "VOICE_DIAGNOSTICS_RUN": "local-run"})
        spec = build_vcm_server("/project", environ={"VOICE_TOOLS_DATA": "/custom/state"}, diagnostics=diag)
        self.assertEqual(spec.env["VOICE_TOOLS_DATA"], "/custom/state")
        self.assertEqual(spec.env["VOICE_DIAGNOSTICS_RUN"], "local-run")

    def test_remote_state_cannot_escape_root_including_through_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "state"
            root.mkdir()
            (root / "escape").symlink_to(Path(folder), target_is_directory=True)
            for path in [str(root / ".." / "outside"), str(root / "escape" / "outside"), "relative"]:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    decode_remote_request(request({"data_dir": path, "settings": {}, "diagnostics_run": None}), state_root=root)

    def test_remote_rejects_shell_commands_credential_settings_and_bad_run_ids(self):
        base = {"data_dir": JETSON_ROOT + "/state", "settings": {}, "diagnostics_run": None}
        for value in [{**base, "executable": "/bin/sh"}, {**base, "settings": {"SMTP_PASSWORD": "private"}},
                      {**base, "diagnostics_run": "../../elsewhere"}, {**base, "settings": {"WEATHER_LAT": 42}}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                decode_remote_request(request(value), state_root=JETSON_ROOT + "/state")
        for command in ["sh -c id", "voice-agent-vcm invalid?", "voice-agent-vcm " + "x" * 8193]:
            with self.subTest(command=command[:30]), self.assertRaises(ValueError):
                decode_remote_request(command, state_root=JETSON_ROOT + "/state")

    def test_diagnostics_disabled_is_explicit_on_remote(self):
        spec = build_vcm_server("/project", environ={"VCM_TOOL_SERVER_HOST": "jetson"})
        decoded = decode_remote_request(spec.args[-1], state_root=JETSON_ROOT + "/state")
        self.assertEqual(decoded["VOICE_DIAGNOSTICS"], "0")
        self.assertNotIn("VOICE_DIAGNOSTICS_RUN", decoded)

    def test_pi_storage_connection_overrides_are_forwarded_without_bot_keys(self):
        spec = build_vcm_server("/project", environ={"VCM_JETSON_DATA_DIR": JETSON_ROOT + "/state/trial",
            "VCM_STATE_TIMEOUT_SECS": "4", "VCM_JETSON_SSH_KEY": "/custom/key", "OLLAMA_API_KEY": "private"})
        self.assertEqual(spec.env["VCM_JETSON_SSH_KEY"], "/custom/key")
        self.assertEqual(spec.env["VCM_STATE_TIMEOUT_SECS"], "4")
        self.assertNotIn("OLLAMA_API_KEY", spec.env)
        local = build_vcm_server("/project", environ={"VCM_STATE_BACKEND": "local_sqlite"})
        self.assertEqual(local.state_backend, "local_sqlite")

    def test_state_worker_request_selects_only_the_storage_entry_point(self):
        spec = build_state_worker(environ={})
        self.assertTrue(spec.args[-1].startswith("voice-agent-state "))
        decoded = decode_remote_request(spec.args[-1], state_root=JETSON_ROOT + "/state", kind="voice-agent-state")
        self.assertEqual(decoded["VCM_STATE_BACKEND"], "local_sqlite")
        with self.assertRaises(ValueError):
            decode_remote_request(spec.args[-1], state_root=JETSON_ROOT + "/state")


class CrossHostTimingTests(unittest.TestCase):
    def summarize(self, cross_host):
        rows = []
        for ident, phase, start, duration, component, clock in [
            ("pi:total", "mcp_client_total", 0, 21, "pi", "pi-boot"),
            ("pi:rpc", "mcp_rpc", 1, 20, "pi", "pi-boot"),
            ("jet:server", "mcp_server_call", 999999 if cross_host else 3, 5, "mcp", "jetson-boot" if cross_host else "pi-boot")]:
            fields = {"run": "test", "component": component, "clock_domain": clock,
                      "span_id": ident, "call_id": "call", "phase": phase, "tool": "control_lights"}
            rows.append({**fields, "event": "span_start", "mono_ns": int(start * 1e6)})
            rows.append({**fields, "event": "span_end", "mono_ns": int((start + duration) * 1e6), "elapsed_ms": duration})
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "trace.jsonl").write_text("\n".join(json.dumps(x) for x in rows))
            return summary_module.summarize(folder)["calls"][0]

    def test_remote_clock_offset_never_becomes_transport_latency(self):
        result = self.summarize(True)
        self.assertFalse(result["same_clock_domain"])
        self.assertNotIn("rpc_to_server_entry_ms", result)
        self.assertNotIn("server_exit_to_rpc_return_ms", result)
        self.assertEqual(result["rpc_outside_server_ms"], 15)

    def test_local_same_clock_breakdown_remains_available(self):
        result = self.summarize(False)
        self.assertTrue(result["same_clock_domain"])
        self.assertEqual(result["rpc_to_server_entry_ms"], 2)
        self.assertEqual(result["server_exit_to_rpc_return_ms"], 13)


if __name__ == "__main__":
    unittest.main()
