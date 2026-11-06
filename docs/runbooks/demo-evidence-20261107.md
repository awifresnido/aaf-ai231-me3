# ME3 demo: issues, fixes and evidence (7 November 2026)

This is evidence for the five beats in `ME3_Demo_Deck.pptx`. Times below are individual observations, not benchmark averages. The initial and retest runs are `501fc4a5eb` and `cd0cf4c88e`, respectively. The dashboard run data is local and is not included in this commit.

| Demo beat | Observed challenge | Change | Evidence and limits |
| --- | --- | --- | --- |
| 1. Hook | The request for models and MCP servers led to a process check, not a reliable model inventory. | Added `get_system_inventory`, populated from the current voice startup configuration, and instructed the agent to use it. | In the retest the inventory server call took 3.2 ms. It reports configured components, not their live health. |
| 2. List | The original spoken response described processes without listing the models. | Supply the configured inventory directly to the model. | In the retest the spoken list included Silero VAD, Whisper large-v3-turbo, Laya, Llama 3.2 3B, GLM 5.3, Qwen Aiden and the three registered MCP servers. The response began about 8.245 s after estimated speech end; this is not a sub-4-second result. |
| 3. Barge-in | The original attempted interruption arrived 3.646 s after the bot stopped, so it did not demonstrate barge-in. The retest did interrupt, but a short ASR fragment caused a premature response before the complete instruction arrived. | Hold SmartTurn completion until the latest issued Whisper segment has returned. | In the retest, 1.888 s of audio was queued when interruption was detected; the flush was initiated about 21 ms after the turn-start event. This is not acoustic stop latency. The full transcript arrived roughly 204 ms after the premature response started. The guard has regression tests; a further live test is needed to demonstrate it under the same race. |
| 4. Live MCP call | The original Telegram message contained a placeholder `http://<device-ip>` URL; the file server could also report success before it was listening and would stop with the voice service. | Validate and expose the real LAN address, check listener readiness, reuse the correct server, run it independently where systemd user services are available, and reject placeholder Telegram links. Added server-side MCP timing spans and more precise file-tool schemas. | Retest: `write_file` 725.9 ms, `serve` 45.1 ms, Telegram `send_message` 1,030 ms. The user confirmed the link worked; the page returned HTTP 200. These are individual tool durations, not end-to-end latency. The transient web service survives a voice-service restart but does not persist across a reboot. |
| 5. Slow-API recovery | After 18 s the original last filler incorrectly said the bot had been unable to respond, even though a tool was still running. | Replace it with a neutral progress message, repeat while waiting, and cancel on response or interruption. Keep the first two filler stages. | The new 4.0 s clip was transcribed as “I'm still working on your request. Thank you for your patience.” Repeat and cancellation are covered by regression tests. The live retest answered before 18 s, so it did not measure the new long-wait filler in a real slow request. |

A separate isolated cloud rehearsal required 62.71 s and six tool calls before schema improvements and 15.40 s and three successful calls afterward. These were single, stochastic runs, not a controlled benchmark or a reliable performance estimate.

The current production voice configuration uses Whisper on the Jetson and Qwen Aiden TTS on the DGX. Its registered MCP servers are voice, workspace and Onit; Pi-hosted ASR/TTS MCP proxies were tested separately. Update any older slide claims that describe other models or count all five as active in this mode.

## Validation and deployment

Pi-side regression suite: 48 passed, plus 3 subtests. Dashboard Telegram tests: 31 passed; frontend build passed. The neutral clip is tracked at `assets/backchannel/response_delayed.wav`; install it as `~/voice-agent/assets/backchannel/response_delayed.wav` on the Pi along with the updated Python files when deploying. Do not commit Telegram credentials or dashboard run data.

These rollback commands restore the backed-up Pi files and restart the voice service, in reverse deployment order:

```sh
ssh aldwinrpi4@192.168.5.12 '~/voice-agent/rollback/demo-asr-guard-20261107/rollback.sh'
ssh aldwinrpi4@192.168.5.12 '~/voice-agent/rollback/demo-fixes-20261107/rollback.sh'
```

The rollbacks do not remove the independently running demo HTTP service or Telegram credentials. The backup locations are specific to this Pi deployment.
