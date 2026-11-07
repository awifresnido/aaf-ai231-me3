# Architecture and operations

## Workload placement

| Component | Placement in the evaluated direct configuration | Responsibility |
| --- | --- | --- |
| Pipecat pipeline, Silero VAD, audio I/O | Raspberry Pi 4 | Audio capture/playback, speech boundaries, turn orchestration, interruptions |
| Whisper large-v3-turbo | Jetson Orin | Speech recognition |
| Laya router and Llama 3.2 3B | Jetson Orin | Classify intent and handle eligible local requests |
| GLM 5.3 Flash | Cloud | Complex requests and fallback where applicable |
| Qwen3-TTS Aiden | DGX | Speech synthesis served to the Pi |
| Voice, workspace and Onit MCP tools | Raspberry Pi | Tool execution and integration; state may reside on the Jetson |
| Diagnostics dashboard | Pi or connected laptop, depending on deployment | Inspect collected turn and tool events |

The Pi-hosted speech MCP servers are an **alternative proxy configuration** tested separately; they do not imply that inference moved off the Jetson or DGX. Older dated runbooks cover other ASR, router, and TTS configurations and should be read as historical experiments rather than current defaults.

## Operational lifecycle

1. Start or verify the remote model services, connectivity, and credentials, then the Pi voice and MCP services. Deployment files in [`deploy/`](../../deploy/) are environment-specific, not a universal one-command installer.
2. Capture run-scoped turn events and tool spans. The Pi commonly writes diagnostics under `/dev/shm/voice-agent-diagnostics/<run-id>/`; tmpfs data is volatile across reboot, so preserve needed evidence deliberately.
3. Inspect latency, routing, tool activity, and simulated state in the dashboard. Latency stages have distinct boundaries and may not sum to E2E; absent measurements must remain absent.
4. Run controlled benchmarks and document model versions, routing, hardware, timing definitions, sample counts, and deviations. Keep test external actions simulated when appropriate.
5. Review results and roll back failed changes using the relevant dated runbook. Do not publish recordings, transcripts, private endpoints, or credentials without review.

## Reliability and open work

The implementation includes interruption handling, a guard against dispatching while a newer Whisper segment is pending, and progress audio for slow requests. Live demo analysis records a successful link delivery and a real final-filler event, but the ASR interruption race still needs a matching live retest. Direct-socket benchmark means for E2E, ASR final, and LLM first-token latency exceeded their targets in the documented session. Progress fillers improve perceived responsiveness but must be excluded when measuring the underlying answer latency.

This is a research prototype: model availability, networking, cloud latency, and local deployment configuration affect results. Monitoring does not imply automated retraining, continuous deployment, or production-grade availability.
