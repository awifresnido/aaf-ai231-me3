# Two-brain live latency check, 2026-10-31

Source: Pi `two-brain-webrtc.log`, user session 22:22:47–22:28:30 Asia/Manila.
The measurements below run from Pipecat's user-turn inference trigger to
Magpie's first generated audio. They exclude speech capture, browser playback,
and physical speaker onset. There were too few turns for reliable percentiles.

| Request | Route | Turn trigger to first audio | Main observation |
|---|---|---:|---|
| Time | Fast, then duplicate GLM | 11.36 s | Fast TTS was interrupted by a late transcript; GLM repeated `get_time` and the answer. |
| Lights blue | Fast | 3.24 s | Router 2.25 s, including a 1.90 s MCP call; TTS first audio 1.01 s. |
| Play music | GLM | 14.82 s | Two GLM calls around a 2.06 s MCP call. |
| Thermostat 17 C | Fast | 5.94 s | Router 5.01 s, including a 3.00 s MCP call; TTS first audio 0.92 s. |
| Reminder to study | GLM | 27.36 s | An interrupted turn and a second GLM request delayed the answer. |
| Call and reminder | GLM | 18.39 s | Two tool calls before TTS. |
| Helen Keller | GLM | 7.72 s | GLM generated a two-sentence answer. |
| Music | GLM | 14.50 s | Two GLM calls around a 2.12 s MCP call. |
| Stop music, then lowest temperature | Overlapping GLM turns | 103.97 s from first turn; 73.21 s from second | Jev timed out twice at its 1.2 s deadline. GLM first-token delays reached 24.86 s and 30.27 s, then both tools ran before one combined answer. |

The median of the first eight turn-to-audio measurements was 12.93 s (range
3.24–27.36 s). The last two turns overlapped and are excluded from that
calculation. Magpie first-audio time was generally 0.8–1.0 s. Nemotron's last
transcript chunk usually preceded turn inference by about 1–3 s. These figures
are software timestamps, not acoustic end-to-end latency.

## Findings

1. The biggest variable delay is the GLM route. Multiple model calls around
   tools and growing context coincide with longer waits; provider-side timing
   is still needed to isolate the cause of the 24–30 s first-token delays.
   The last two turns show the severe tail when requests overlap.
2. The fast path helps, but local MCP calls for lights and thermostat took
   1.9 and 3.0 s even though their tool bodies only update SQLite state.
   Measure Pi scheduling and MCP round trips separately before changing the
   executor.
3. A late transcription reopened the time request after the fast path had
   started TTS. It interrupted the first answer, sent a duplicate request to
   GLM, and called `get_time` again. Fix turn deduplication and late-final
   handling before using fast execution for consequential actions.
4. Jev timed out on two later utterances. Its 1.2 s deadline bounded that
   delay, but sent both turns to the much slower GLM path. Log classifier
   timing and result separately before changing the deadline.
5. Music control, reminders, and multi-action requests still take the GLM
   path. Add only validated, single-action commands to the fast path, with
   clear fallbacks for ambiguous speech.

## Audio path

The measured session used WebRTC, so capture and playback were on the
ThinkPad browser. The Pi default PulseAudio source and sink both identify the
JOUNIVO JV801P. After this session, the WebRTC bot was stopped and
`me3-local-audio.service` was started with `TRANSPORT_MODE=local`, PCM at 100%,
and `pacat` playback. Its recording stream is attached to the JV801P source;
`pacat` is attached to the JV801P sink. The greeting reached Magpie TTS and
the Pi sink; audible output from the physical speakerphone requires a
listening check. The Jetson ASR and TTS containers were running during the
inspection.

The first Pi-local speakerphone turns show that the device is recording and
the two-brain path is active. Lights on took 1.19 s from turn trigger to
first generated audio (0.34 s fast route, 0.86 s Magpie). Lights off took
5.35 s because the MCP call alone took 4.23 s. An alarm request took 14.55 s,
and its follow-up took 36.46 s through GLM. Magpie first audio remained
roughly 0.7–1.2 s. These are still software timings; they do not establish
audible onset or sound quality from the speakerphone.
