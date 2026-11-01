"""Verify traces across real MCP stdio/SQLite, without touching live state."""

import asyncio
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import suppress
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))
from stall_diagnostics import Diagnostics, ProfiledConnection
from profiled_mcp import ProfiledMCPClient
from mcp import StdioServerParameters


def read_events(folder):
    return [json.loads(line) for path in Path(folder).rglob("*.jsonl")
            for line in path.read_text().splitlines()]


class SQLiteDiagnosticsTests(unittest.TestCase):
    def test_sql_results_and_private_values_are_preserved_without_logging_them(self):
        with tempfile.TemporaryDirectory() as folder:
            trace = Diagnostics("test", run="sqlite-test", directory=folder)
            with trace.call("a" * 32):
                db = sqlite3.connect(":memory:", factory=partial(ProfiledConnection, diagnostics=trace))
                db.execute("CREATE TABLE notes(note TEXT)")
                db.execute("INSERT INTO notes VALUES (?)", ("private reminder value",))
                db.commit()
                self.assertEqual(db.execute("SELECT note FROM notes").fetchall(), [("private reminder value",)])
                db.close()
            trace.close()
            events = read_events(folder)
            ends = [e for e in events if e["event"] == "span_end"]
            self.assertTrue({"sqlite_connect", "sqlite_execute", "sqlite_fetchall", "sqlite_commit", "sqlite_close"}
                            <= {e["phase"] for e in ends})
            self.assertTrue(all(e["call_id"] == "a" * 32 for e in ends))
            self.assertNotIn("private reminder value", json.dumps(events))
            self.assertNotIn("CREATE TABLE", json.dumps(events))

    def test_locked_database_error_is_traced_and_propagated(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "db.sqlite")
            first = sqlite3.connect(path)
            first.execute("CREATE TABLE notes(note TEXT)")
            first.commit()
            first.execute("BEGIN IMMEDIATE")
            trace = Diagnostics("test", run="locked-test", directory=folder)
            second = sqlite3.connect(path, timeout=0.01, factory=partial(ProfiledConnection, diagnostics=trace))
            with self.assertRaises(sqlite3.OperationalError):
                second.execute("INSERT INTO notes VALUES (?)", ("private",))
            second.close()
            first.rollback()
            first.close()
            trace.close()
            failures = [e for e in read_events(folder) if e.get("error") == "OperationalError"]
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["phase"], "sqlite_execute")


class AsyncDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_event_loop_block_is_visible_without_normal_logging(self):
        with tempfile.TemporaryDirectory() as folder:
            trace = Diagnostics("test", run="loop-test", directory=folder)
            task = asyncio.create_task(trace.monitor_loop(lambda: 7))
            await asyncio.sleep(0.02)
            time.sleep(0.18)  # Deliberately block a loop that is waiting 0.1 s.
            await asyncio.sleep(0.02)
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            trace.close()
            lags = [e for e in read_events(folder) if e["event"] == "event_loop_lag"]
            self.assertTrue(lags)
            self.assertEqual(lags[0]["turn"], 7)
            self.assertGreaterEqual(lags[0]["lag_ms"], 50)

    async def test_real_stdio_correlates_client_server_sqlite_without_schema_or_result_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            trace = Diagnostics("pi", run="rpc-test", directory=folder)
            server = Path(__file__).resolve().parents[1] / "pi" / "mcp_servers" / "voice_tools_mcp_server.py"
            env = {**trace.server_env(), "VOICE_TOOLS_DATA": str(Path(folder) / "state"), "VCM_STATE_BACKEND": "local_sqlite"}
            async with ProfiledMCPClient(diagnostics=trace,
                server_params=StdioServerParameters(command=sys.executable, args=[str(server)], env=env)) as client:
                schema = await client.tools()
                self.assertEqual(len(schema.standard_tools), 13)
                self.assertNotIn("play_radio", [tool.name for tool in schema.standard_tools])
                result = json.loads(await client._call_tool_text("control_lights", {"action": "on"}))
                self.assertEqual(result["spoken"], "Lights on.")
                self.assertEqual(set(result), {"ok", "spoken", "lights"})
            trace.close()
            ends = [e for e in read_events(folder) if e["event"] == "span_end"]
            total = next(e for e in ends if e["phase"] == "mcp_client_total")
            correlated = [e for e in ends if e["call_id"] == total["call_id"]]
            self.assertTrue({"mcp_client_total", "mcp_open_session", "mcp_rpc", "mcp_server_call",
                             "tool_execute", "sqlite_connect", "sqlite_execute", "sqlite_commit"}
                            <= {e["phase"] for e in correlated})
            self.assertEqual(len([e for e in correlated if e["phase"] == "tool_execute"]), 1)
