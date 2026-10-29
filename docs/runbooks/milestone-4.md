# Milestone 4: MCP in the loop (Option A behind a switch)

Status: working (verified live 2026-10-29, user-tested).

## Design

MCP is the control plane, not the audio transport. Two thin MCP servers
(stdio subprocesses) wrap the same Jetson endpoints the direct path uses:

- `mcp_servers/asr_mcp_server.py` — tool `transcribe(audio_wav_b64)`:
  offline Riva recognize against Jetson :50051 (one VAD-bounded utterance).
- `mcp_servers/tts_mcp_server.py` — tool `synthesize(text)`:
  offline Riva synthesize against Jetson :50052 (one sentence at a time).

`mcp_pipeline.py` bridges them into Pipecat:
- `MCPSTTService(SegmentedSTTService)` — Pipecat does VAD-bounded buffering
  and hands a WAV segment per utterance; we forward via MCP.
- `MCPTTSService(TTSService)` — called per sentence; returns WAV PCM.

`bot.py` switch: `SPEECH_MODE=direct|mcp` (direct is default/streaming).

## Measured (live session, 2026-10-29)

- ASR roundtrip per utterance: 117-358 ms (server-side ASR 61-332 ms).
- TTS roundtrip per sentence: 0.85 s ("That's right.") to 3.98 s (long
  sentence); scales with sentence length, non-streaming by design.
- Direct-mode TTS TTFA baseline: ~0.9 s.
- Multi-turn context and barge-in ("Stop.") work in MCP mode.

## Key finding: MCP TTS sounds SMOOTHER than direct streaming

User-reported and structurally explained:
- Direct mode streams per sentence via SynthesizeOnline; the first chunk of
  each fresh stream has an imperfect onset (codec decoder starts cold
  mid-prosody) — the "cut at sentence start" reported earlier.
- MCP mode synthesizes the whole sentence offline before sending, so the
  prosody envelope is complete and natural at onset.
- Raw one-shot synthesis was verified clean earlier (tts_probe2/3), which
  supports this: the defect was streaming onset, not audio content.

Trade-off: MCP mode trades ~1-2.5 s extra first-audio latency for better
voice quality. Benchmark skeleton (M6) should record both modes.

## Gotchas hit

- mcp SDK is 2.x: `FastMCP` renamed to `MCPServer` (mcp.server.mcpserver);
  run with `server.run("stdio")`.
- Inserting a FrameProcessor between tts and transport.output() in 1.13
  drops TTS audio silently (see milestone-3.md) — MCP processors replace
  the Nvidia services rather than wrapping the pipeline.

## Extensibility

Adding tools = adding @server.tool() functions in a server file (each
server is an independent subprocess). When LLM tool calling lands (M5),
Pipecat's MCPClient registers these same tools with the LLM.
