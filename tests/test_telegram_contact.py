"""Verify Telegram routing without contacting Telegram or sending a message."""
import json
from pathlib import Path
import sys
from unittest.mock import patch
from urllib.parse import parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))
from mcp_servers import voice_tools_mcp_server as voice
from orchestration import explicit_route_hint, validate_arguments


def test_telegram_tool_sends_requested_link_to_configured_chat():
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return json.dumps({"ok": True, "result": {"message_id": 7}}).encode()

    args = {"to": "Telegram", "text": "https://example.com/path"}
    assert validate_arguments("send_message", args)
    assert explicit_route_hint("send a message to Telegram saying hello") == "send_message"
    with patch.object(voice, "TELEGRAM_BOT_TOKEN", "test-token"), \
         patch.object(voice, "TELEGRAM_CHAT_ID", "12345"), \
         patch.object(voice.urllib.request, "urlopen", return_value=Response()) as request:
        result = voice.send_message(**args)
    assert result["ok"] and result["to"] == "Telegram"
    assert parse_qs(request.call_args.args[0].data.decode()) == {
        "chat_id": ["12345"], "text": ["https://example.com/path"]}


def test_telegram_failure_does_not_return_secret():
    with patch.object(voice, "TELEGRAM_BOT_TOKEN", "sensitive-token"), \
         patch.object(voice, "TELEGRAM_CHAT_ID", "12345"), \
         patch.object(voice.urllib.request, "urlopen", side_effect=OSError("sensitive-token")):
        result = voice.send_message("hello", to="Telegram")
    assert result["ok"] is False
    assert "sensitive-token" not in json.dumps(result)


def test_simulated_contact_remains_simulated():
    with patch.object(voice, "_set_state"), patch.object(voice.urllib.request, "urlopen") as request:
        result = voice.send_message("hello", to="Mom")
    assert result["simulated"] is True
    request.assert_not_called()


def test_placeholder_link_is_not_reported_as_sent():
    with patch.object(voice.urllib.request, "urlopen") as request:
        result = voice.send_message("http://<device-ip>:8000/dashboard.html", to="Telegram")
    assert result["ok"] is False
    assert "placeholder" in result["spoken"]
    request.assert_not_called()
