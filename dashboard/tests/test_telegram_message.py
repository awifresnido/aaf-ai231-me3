from backend.devices import reconstruct


def test_successful_telegram_message_appears_as_sent():
    result = reconstruct([{"tool": "send_message", "at": 10, "duration_s": 0.1,
                           "arguments": {"to": "Telegram", "text": "https://example.com"},
                           "result": {"ok": True, "to": "Telegram", "text": "https://example.com"}}])
    assert result["final"]["message"] == {"status": "sent", "to": "Telegram",
                                             "text": "https://example.com", "at": 10}
