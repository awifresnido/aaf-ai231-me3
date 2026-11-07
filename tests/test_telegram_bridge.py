import base64
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))
from telegram_bridge import (ALLOWED_READ, ALLOWED_VOICE, Bridge, Journal,
                             authorized_message, github_repo, read_github)


def update(ident=1, chat=123, sender=123, **extra):
    return {"update_id": ident, "message": {"chat": {"id": chat, "type": "private"},
            "from": {"id": sender, "is_bot": False}, "text": "set a timer", **extra}}


def test_private_owner_only_and_forwarded_messages_are_rejected():
    assert authorized_message(update(), "123") == "set a timer"
    assert authorized_message(update(chat=124), "123") is None
    assert authorized_message(update(sender=124), "123") is None
    assert authorized_message(update(forward_origin={"type": "user"}), "123") is None
    assert "bash" not in ALLOWED_READ | ALLOWED_VOICE


@pytest.mark.parametrize("url", ["http://github.com/user/repo", "https://github.com.evil/user/repo",
                                  "https://github.com/user/repo/issues", "https://github.com@evil/user/repo"])
def test_only_github_repository_root_links_are_accepted(url):
    with pytest.raises(ValueError):
        github_repo(url)


@pytest.mark.asyncio
async def test_github_readme_is_read_as_data():
    def response(req):
        if req.url.path.endswith("/readme"):
            return httpx.Response(200, json={"encoding": "base64", "content": base64.b64encode(b"# Demo").decode()})
        return httpx.Response(200, json={"full_name": "owner/repo", "description": "demo", "html_url": "https://github.com/owner/repo"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        result = await read_github("https://github.com/owner/repo", client)
    assert result["readme"] == "# Demo"


@pytest.mark.asyncio
async def test_update_is_not_executed_twice(tmp_path):
    journal = Journal(tmp_path / "journal.sqlite")
    bridge = Bridge("test", "123", None, None, "test", journal)
    bridge.answer = AsyncMock(return_value="Done")
    bridge.api = AsyncMock()
    await bridge.process(update())
    await bridge.process(update())
    bridge.answer.assert_awaited_once()
    bridge.api.assert_awaited_once()
    journal.db.close()


@pytest.mark.asyncio
async def test_untrusted_content_cannot_trigger_unrequested_device_action(tmp_path):
    journal = Journal(tmp_path / "journal.sqlite")
    bridge = Bridge("test", "123", None, None, "test", journal)
    session = SimpleNamespace(call_tool=AsyncMock())
    bridge.sessions["control_lights"] = session
    result = await bridge.tool("control_lights", {"action": "on"}, "Summarize this repository")
    assert result["ok"] is False
    session.call_tool.assert_not_awaited()
    journal.db.close()
