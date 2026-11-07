# Demo evidence runs — diagnostics JSONL

Raw turn-by-turn diagnostics for the demo evidence in
`docs/runbooks/demo-evidence-20261107.md` (challenge → fix → measurement per beat).

| Run | What it was |
|---|---|
| `501fc4a5eb` | Initial demo run (pre-fixes): placeholder Telegram URL, late barge-in, wrong 18 s filler |
| `cd0cf4c88e` | Retest after fixes: `get_system_inventory` 3.2 ms, `write_file` 725.9 ms, `serve` 45.1 ms, `send_message` 1,030 ms, HTTP 200 confirmed |
| `bb4c872892` | Latest dashboard-revision run: edit HTML, re-serve, progress fillers (0.352 s / 8.0 s / 18 s stages) |

Files per run: `pi-<pid>.jsonl` (turn events, `native_user_bot_latency`, VAD/ASR timings)
and `mcp-<pid>.jsonl` (MCP tool-call spans, `span_start`/`span_end`).

These runs were captured on the Pi under `/dev/shm/voice-agent-diagnostics/`
(volatile) and archived here on 2026-11-07. They are individual observations,
not benchmark averages.
