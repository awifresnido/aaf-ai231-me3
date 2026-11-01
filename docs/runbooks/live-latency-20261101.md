# JV801P spoken test, 2026-11-01

The subsequent retest focused on Jev overhead and timeout behavior:
`docs/runbooks/jev-latency-retest-20261101.md`.

Source: Pi `me3-local-audio.log`, 10:06:40–10:13:00 Asia/Manila,
running the routing version from commit `78b1aa3`. The Pi-local agent remained
active after its previous five-minute idle limit.

Times below measure Pipecat turn inference to first generated TTS audio.
They exclude acoustic speech-end detection and physical speaker onset.
PulseAudio routes microphone and playback to the JV801P; the user has confirmed
clear speakerphone output.

| Request as recognized / inferred | Route | First audio delay | Result |
|---|---|---:|---|
| Current time | Fast | 1.59 s | Correct; Jev 0.69 s, MCP 0.012 s. |
| “Remained me to study” | GLM | 13.62 s | Jev selected reminder but confidence gate rejected it; GLM added it. |
| “an alarm” | GLM | 7.15 s | Asked for a time; no time was present in the recognized text. |
| “Can you stuff the music grade now” | GLM | 22.33 s | GLM invoked `play_music`; this may be a misheard stop request and is a correctness concern. |
| Ask what music is playing | GLM | 11.03 s | Answered from earlier conversation. |
| Turn lights on and set blue | GLM | 12.02 s | Two sequential light calls and three GLM requests. |
| Adjust brightness to 70 percent | Fast | 2.37 s | Correct; Jev 0.59 s, MCP 0.87 s. |
| “Also set” temperature to 20 C | GLM | 6.40 s | Incorrectly flagged as multiple actions because of leading “also.” |
| Call default contact | GLM | 14.06 s | Called the existing stateful stub; no carrier call is implemented. |
| Reminders for water, study, exercise | GLM | 16.97 s | Added water/exercise; study was already present. Recognition was fragmented. |
| Current weather | Fast | 3.32 s | Correct; Jev 0.81 s, MCP 1.47 s. |
| Unclear music-control request | GLM | 6.40 s | Asked whether to pause, skip, or stop. |
| “stop it completely” follow-up | GLM | 22.29 s | Correct stop action, but MCP alone waited 9.27 s. |

Fast-route median was 2.37 s across three turns. GLM-route median was
12.82 s across ten turns, ranging from 6.40 to 22.33 s. This is a small,
mixed workload sample rather than a controlled model comparison. No Jev
timeouts or repeated `get_time` calls appeared in this session. Llama small
talk and flexible extraction were not exercised by these successful fast turns.

## Findings and next work

- The fast route is useful when ASR delivers the needed words and the parser
  has explicit arguments. Lowering the confidence threshold globally would
  risk executing commands from uncertain transcripts.
- The leading “also” routing bug is fixed after this test. A regression test
  checks that a single thermostat command stays fast; existing tests retain
  GLM routing for actual combined commands. Fallback logs now include Jev
  confidence for further diagnosis.
- Context-dependent follow-ups such as “stop it completely” need a grounded
  pending-action state. Sending them through a full GLM tool loop adds delay.
- MCP latency varies independently of intent complexity: simple local state
  calls ranged from milliseconds to 9.27 s. Instrument server-side SQLite
  execution separately from the client's stdio round trip next.
- ASR substitutions remain consequential: “remind” became “remained,” and
  the apparent stop request became “stuff.” Prefer clarification when a noisy
  transcript would cause an action contrary to its likely intent.
- The current music tools return metadata and update stored state; they do
  not launch a music audio player. Spoken playback claims do not establish
  actual music playback. Calls likewise remain a stub.
- GLM successfully handled the combined commands, but sequential tool/model
  cycles dominated their latency. Bounded plans for validated combinations
  are a later improvement after single-command routing is reliable.
