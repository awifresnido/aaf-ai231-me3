import json
import os
from pathlib import Path
import signal
import socket
import sys
import urllib.request

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))
from mcp_servers import workspace_tools_mcp_server as workspace


def test_inventory_uses_configured_values(monkeypatch):
    expected = {"vad": {"model": "Silero"}, "mcp_servers": ["voice_tools", "workspace_tools"]}
    monkeypatch.setenv("ME3_SYSTEM_INVENTORY", json.dumps(expected))
    result = workspace.get_system_inventory()
    assert result["ok"] and result["inventory"] == expected


def test_serve_real_url_and_reuse(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setenv("WORKSPACE_SYSTEMD", "0")
    monkeypatch.setattr(workspace, "_cluster_address", lambda: "192.168.5.12")
    (tmp_path / "demo.html").write_text("hello", encoding="utf-8")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    result = workspace.serve(port=port)
    assert result["ok"], result
    try:
        assert result["url"] == f"http://192.168.5.12:{port}/"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/demo.html", timeout=2) as response:
            assert response.read() == b"hello"
        again = workspace.serve(port=port)
        assert again["ok"] and again["reused"] and again["pid"] == result["pid"]
    finally:
        os.kill(result["pid"], signal.SIGTERM)
        os.waitpid(result["pid"], 0)


def test_serve_rejects_unrelated_listener(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(workspace, "_cluster_address", lambda: "192.168.5.12")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        result = workspace.serve(port=listener.getsockname()[1])
    assert result["ok"] is False
    assert "already in use" in result["spoken"]


@pytest.mark.asyncio
async def test_workspace_mcp_records_tool_spans_without_file_content(tmp_path):
    root = tmp_path / "work"
    trace = tmp_path / "trace"
    script = Path(__file__).resolve().parents[1] / "pi/mcp_servers/workspace_tools_mcp_server.py"
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "WORKSPACE_ROOT": str(root),
           "VOICE_DIAGNOSTICS": "1", "VOICE_DIAGNOSTICS_RUN": "demo-test", "VOICE_DIAGNOSTICS_DIR": str(trace)}
    params = StdioServerParameters(command=sys.executable, args=[str(script)], env=env)
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            assert set(tools["write_file"].input_schema["required"]) == {"path", "content"}
            result = await session.call_tool("write_file", {"path": "demo.html", "content": "private-test-content"})
            assert not result.is_error
            response = result.structured_content or json.loads(result.content[0].text)
            assert response["path"] == "demo.html"
            import asyncio
            await asyncio.sleep(.15)
    lines = "".join(p.read_text() for p in (trace / "demo-test").glob("mcp-*.jsonl"))
    events = [json.loads(line) for line in lines.splitlines()]
    phases = [x["event"] for x in events if x.get("phase") == "mcp_server_call" and x.get("tool") == "write_file"]
    assert phases == ["span_start", "span_end"]
    assert "private-test-content" not in lines
