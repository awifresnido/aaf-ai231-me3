import json
from unittest.mock import patch

from backend import ingest


def test_cache_reloads_live_tool_events_and_reuses_unchanged_runs(tmp_path):
    run = tmp_path / "live"
    run.mkdir()
    log = run / "mcp-1.jsonl"
    log.write_text("")
    with patch.object(ingest, "_parse_run", wraps=ingest._parse_run) as parse:
        assert ingest.list_runs(str(tmp_path))[0].tool_spans == []
        assert ingest.load_run("live", str(tmp_path)).tool_spans == []
        assert parse.call_count == 1
        events = [
            {"event": "span_start", "phase": "mcp_server_call", "span_id": "1",
             "tool": "set_timer", "at": 100, "arguments": {"duration_s": 60}},
            {"event": "span_end", "span_id": "1", "at": 100.1,
             "result": {"ok": True, "ends_at": 160}},
        ]
        with log.open("a") as stream:
            for event in events:
                stream.write(json.dumps(event) + "\n")
        refreshed = ingest.load_run("live", str(tmp_path))
        assert refreshed.detail()["devices"]["final"]["timers"] == [
            {"label": "60s", "ends_at": 160}]
        assert parse.call_count == 2


def test_load_run_rejects_parent_paths(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        ingest.load_run("..", str(tmp_path))
