from types import SimpleNamespace
from unittest.mock import Mock

from backend import control


def test_local_dashboard_restarts_pi_without_ssh(monkeypatch):
    monkeypatch.setattr(control, "LOCAL_CONTROL", True)
    monkeypatch.setattr(control, "newest_run_id", Mock(side_effect=["old", "new"]))
    run = Mock(return_value=SimpleNamespace(returncode=0, stderr="", stdout=""))
    monkeypatch.setattr(control.subprocess, "run", run)
    monkeypatch.setattr(control, "_run_ssh", Mock(side_effect=AssertionError("unexpected SSH")))
    assert control.restart_bot() == "new"
    assert run.call_args.args[0] == ["systemctl", "--user", "restart", control.SERVICE]


def test_local_dashboard_finds_latest_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "LOCAL_CONTROL", True)
    monkeypatch.setattr(control, "REMOTE_DIR", str(tmp_path))
    run = tmp_path / "run123"
    run.mkdir()
    (run / "pi-1.jsonl").write_text("{}\n")
    assert control.newest_run_id() == "run123"


def test_save_copies_live_diagnostics_to_persistent_directory(tmp_path, monkeypatch):
    live = tmp_path / "live"
    saved = tmp_path / "persistent" / "saved"
    run = live / "run123"
    run.mkdir(parents=True)
    (run / "pi-1.jsonl").write_text("{}\n")
    monkeypatch.setattr(control, "DATA_DIR", live)
    monkeypatch.setattr(control, "SAVED_DIR", saved)
    assert control.save_run("run123") == str(saved / "run123")
    assert (saved / "run123" / "pi-1.jsonl").read_text() == "{}\n"
