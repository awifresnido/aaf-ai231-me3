"""Durability, replay, transaction and failure tests for the storage split."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pi"))
from vcm_state import SQLiteStateStore, JetsonStateStore, StateUnavailable


class SQLiteStoreTests(unittest.TestCase):
    def test_existing_schema_data_survives_and_all_entities_persist(self):
        with tempfile.TemporaryDirectory() as folder:
            db = sqlite3.connect(Path(folder) / "state.db")
            db.execute("CREATE TABLE device_state(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            db.execute("INSERT INTO device_state VALUES ('lights',?)", (json.dumps({"color": "Red"}),))
            db.commit(); db.close()
            store = SQLiteStateStore(folder)
            self.assertEqual(store.health()["synchronous"], 2)
            self.assertEqual(store.dispatch("get_state", {"key": "lights"}), {"color": "Red"})
            store.dispatch("add_reminder", {"text": "test note", "created_ms": 1000})
            store.dispatch("add_timer", {"label": "60s", "ends_at": 12345})
            store.dispatch("add_alarm", {"time_str": "09:00 PM"})
            self.assertEqual(SQLiteStateStore(folder).dispatch("list_reminders", {}), [[1, "test note"]])
            db = sqlite3.connect(Path(folder) / "state.db")
            try:
                self.assertEqual(db.execute("SELECT label,ends_at FROM timers").fetchall(), [("60s", 12345)])
                self.assertEqual(db.execute("SELECT time,enabled FROM alarms").fetchall(), [("09:00 PM", 1)])
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            finally:
                db.close()

    def test_durable_request_replay_never_duplicates_inserts_and_rejects_conflicting_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            for operation, args, table in [
                ("add_reminder", {"text": "test", "created_ms": 1}, "reminders"),
                ("add_timer", {"label": "1s", "ends_at": 1}, "timers"),
                ("add_alarm", {"time_str": "09:00 PM"}, "alarms")]:
                request_id = uuid.uuid4().hex
                SQLiteStateStore(folder).dispatch(operation, args, request_id=request_id)
                SQLiteStateStore(folder).dispatch(operation, args, request_id=request_id)
                with sqlite3.connect(Path(folder) / "state.db") as db:
                    self.assertEqual(db.execute("SELECT count(*) FROM " + table).fetchone(), (1,))
                with self.assertRaises(ValueError):
                    SQLiteStateStore(folder).dispatch("set_state", {"key": "other", "value": {}}, request_id=request_id)

    def test_concurrent_patches_preserve_other_fields_and_return_committed_state(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStateStore(folder)
            store.dispatch("set_state", {"key": "lights", "value": {"power": False}})
            def patch_state(change):
                return SQLiteStateStore(folder).dispatch("patch_state", {"key": "lights", "changes": change, "defaults": {}})
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(patch_state, [{"color": "Blue"}, {"brightness": "50"}]))
            self.assertEqual(store.dispatch("get_state", {"key": "lights"}),
                             {"power": False, "color": "Blue", "brightness": "50"})
            self.assertIsNone(store.dispatch("patch_state", {"key": "missing", "changes": {"status": "pause"},
                                                             "defaults": {}, "require_existing": True}))

    def test_commit_failure_rolls_back_both_change_and_success_receipt(self):
        class FailingCommit(sqlite3.Connection):
            def commit(self):
                if self.in_transaction:
                    raise sqlite3.OperationalError("Synthetic durable flush failure")
                return super().commit()
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStateStore(folder)
            original = sqlite3.connect
            def connect(*args, **kwargs):
                return original(*args, factory=FailingCommit, **kwargs)
            with patch("vcm_state.sqlite3.connect", connect), self.assertRaises(sqlite3.OperationalError):
                store.dispatch("add_reminder", {"text": "must not persist", "created_ms": 1})
            with original(Path(folder) / "state.db") as db:
                self.assertEqual(db.execute("SELECT count(*) FROM reminders").fetchone(), (0,))
                self.assertEqual(db.execute("SELECT count(*) FROM state_requests").fetchone(), (0,))

    def test_bad_requests_cannot_execute_sql_or_create_a_database(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStateStore(Path(folder) / "unused")
            for operation, args in [("execute", {"sql": "DROP TABLE reminders"}),
                                    ("set_state", {"key": "x", "value": [], "extra": 1}),
                                    ("add_timer", {"label": "x", "ends_at": float("nan")})]:
                with self.subTest(operation=operation), self.assertRaises(ValueError):
                    store.dispatch(operation, args)
            self.assertFalse(store.path.exists())


class WorkerTransportTests(unittest.TestCase):
    def client(self, folder, code=None, timeout="2"):
        command = [sys.executable, str(ROOT / "pi" / "vcm_state_worker.py")]
        if code is not None:
            path = Path(folder) / "fake-worker.py"
            path.write_text(code)
            command = [sys.executable, str(path)]
        return JetsonStateStore(command=command, environ={"VCM_STATE_TIMEOUT_SECS": timeout})

    def test_real_worker_persists_and_reuses_one_process(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                "VOICE_TOOLS_DATA": folder, "VOICE_DIAGNOSTICS": "0"}):
            client = self.client(folder)
            try:
                self.assertEqual(client.start()["synchronous"], 2)
                pid = client._process.pid
                client.dispatch("add_reminder", {"text": "worker test", "created_ms": 1})
                self.assertEqual(client.dispatch("list_reminders", {}), [[1, "worker test"]])
                self.assertEqual(client._process.pid, pid)
            finally:
                client.close()
            self.assertEqual(SQLiteStateStore(folder).dispatch("list_reminders", {}), [[1, "worker test"]])

    def test_reply_loss_after_commit_is_uncertain_and_not_automatically_retried(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                "VOICE_TOOLS_DATA": folder, "VOICE_DIAGNOSTICS": "0"}):
            code = "\n".join([
                "import sys,json,os", "sys.path.insert(0," + repr(str(ROOT / "pi")) + ")",
                "from vcm_state import SQLiteStateStore", "s=SQLiteStateStore(os.environ['VOICE_TOOLS_DATA'])",
                "print(json.dumps(s.health()),flush=True)", "r=json.loads(sys.stdin.readline())",
                "s.dispatch(r['operation'],r['arguments'],request_id=r['request_id'])",
                "# Exit without returning the already-committed receipt.",
            ])
            client = self.client(folder, code)
            request_id = uuid.uuid4().hex
            args = {"text": "one insert despite lost reply", "created_ms": 1}
            try:
                with self.assertRaises(StateUnavailable):
                    client.dispatch("add_reminder", args, request_id=request_id)
                self.assertIsNone(client._process)
            finally:
                client.close()
            store = SQLiteStateStore(folder)
            self.assertEqual(len(store.dispatch("list_reminders", {})), 1)
            store.dispatch("add_reminder", args, request_id=request_id)
            self.assertEqual(len(store.dispatch("list_reminders", {})), 1)

    def test_timeout_does_not_claim_success_or_fall_back_to_local_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            code = "\n".join(["import json,sys,time",
                "print(json.dumps({'protocol':'voice-state-v1','ready':True,'synchronous':2}),flush=True)",
                "sys.stdin.readline()", "time.sleep(10)"])
            client = self.client(folder, code, timeout="0.2")
            try:
                with self.assertRaises(StateUnavailable):
                    client.dispatch("add_reminder", {"text": "uncertain", "created_ms": 1})
                self.assertFalse((Path(folder) / "state.db").exists())
                self.assertIsNone(client._process)
            finally:
                client.close()

    def test_non_durable_handshake_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            client = self.client(folder, "import json;print(json.dumps({'protocol':'voice-state-v1','ready':True,'synchronous':0}),flush=True)")
            try:
                with self.assertRaises(StateUnavailable):
                    client.start()
            finally:
                client.close()


if __name__ == "__main__":
    unittest.main()
