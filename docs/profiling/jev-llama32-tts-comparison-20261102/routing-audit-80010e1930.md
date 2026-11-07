# Routing audit — run `80010e1930` (Mac streaming TTS, PCM 60 %)

Timing was already summarised; this note answers "did the speech go to the right
brain, and which tools does each brain actually have".

## Latency (unchanged TTS, different routing mix)

| measurement | `23dff71cba` (Mac stream) | `80010e1930` (Mac stream, PCM 60 %) |
|---|---:|---:|
| End-to-end median | 3.669 s | 4.064 s |
| End-to-end p95 / max | 6.903 / 7.551 s | 8.414 / 9.245 s |
| TTS first audio median | 0.327 s | **0.321 s** |
| TTS completion median | 3.292 s | 2.591 s |
| ASR transcript median | 0.441 s | 0.427 s |
| Jev classification median | 0.283 s | 0.286 s |
| Routes GLM / tool / smalltalk | 23 / 6 / 0 | 28 / 4 / 0 |

TTS first audio did not move — PCM volume is not on the latency path. The
end-to-end regression is entirely route mix: fast-tool turns averaged
**1.47 s** (n = 4) against **4.95 s** (n = 26) for GLM turns.

## Route audit, turn by turn

Executed by the fast path (Jev gate: p ≥ 0.90 and gap ≥ 0.20):

| turn | choice | p | gap | result |
|---|---:|---:|---:|---|
| 6 | control_lights | 0.99 | 0.98 | `control_lights` ✓ |
| 7 | set_thermostat | 0.98 | 0.96 | `set_thermostat` ✓ |
| 8 | (explicit reminder hint) | — | — | `add_reminder` ✓ (classifier bypassed) |
| 13 | get_time | 1.00 | 1.00 | `get_time` ✓ |

Rejected by the gate and sent to GLM:

| turn | choice | p | gap | why |
|---|---:|---:|---:|---|
| 1 | small_talk | 0.97 | 0.94 | **accepted**, but the small model returned nothing → GLM |
| 17 | small_talk | 0.92 | 0.86 | **accepted**, same empty answer → GLM |
| 2, 3, 21 | small_talk | 0.88 / 0.89 / 0.78 | — | below 0.90 |
| 15, 16, 22 | control_lights | 0.41 / 0.62 / 0.69 | 0.09 / 0.25 / 0.42 | below 0.90 |
| 24 | get_time | 0.63 | 0.26 | below 0.90 |
| 14 | (multiple actions) | — | — | two commands in one utterance → GLM by design |
| 18 | set_alarm | — | — | `TimeoutError` — extraction needs the small model |

ASR was the upstream cause of most low confidences: *"During underlights."*
→ lights, *"Turn on delights"* → lights, *"place some music"* → play music.

## Root cause: the local small model was not running

`SMALL_LLM_PRIMARY_URL=http://192.168.5.11:8084` (Jetson, Llama 3.2 3B Q4_K_M,
`llama.cpp --ngl 99`, a *transient* service). At audit time:

```
Jetson: nothing listening on 8084
Pi:     curl http://192.168.5.11:8084/v1/models -> unreachable
```

Consequences in this run: `SmallModelClient.answer()` returned empty for both
gate-accepted smalltalk turns, and `extract()` timed out for `set_alarm`, so
**26 of 30 turns were answered by GLM**. The last run with working smalltalk
routing was `7373bf308b` (2 route_smalltalk events).

Nothing was misrouted *to* the small model: it never produced a spoken reply.

## Tools per brain

**Large model — GLM 5.3 Flash (OpenRouter `z-ai/glm-5.3-flash`)**, 13 tools
registered at startup:

```
play_music, playback_control, get_weather, get_time, set_timer, set_alarm,
add_reminder, list_reminders, set_thermostat, control_lights, send_message,
send_email, place_call
```

**Small model — Llama 3.2 3B (Jetson :8084)**: no tool execution at all. Two
jobs only:

1. `answer(text)` — conversational reply for `small_talk` (emitted as a
   `TTSSpeakFrame`, bypassing GLM).
2. `extract(tool, text)` — argument extraction for the 10 `FAST_TOOLS`:
   `get_time, get_weather, list_reminders, add_reminder, set_thermostat,
   control_lights, set_timer, set_alarm, playback_control, play_music`.
   `send_message`, `send_email`, `place_call` are GLM-only.

The Jev classifier chooses among those 10 plus `small_talk`; anything else
(`other`) goes to GLM.

## About the "I don't have that ability" replies

They came from **GLM**, not the small model, and were accurate: no tool exists
for documents or code execution, and the system prompt forbids reading code.

```
22:52:57  "I don't have any saved PDF files with me. I can create reminders,
           messages, or send emails, but not handle documents..."
22:53:11  "I can't run or test code myself — I don't have a code execution tool.
           I'm limited to things like music, weather, lights, timers, messaging."
```

That is a capability gap, not a routing error. What *is* a routing miss is
smalltalk and alarm extraction silently degrading to the cloud model because
:8084 was down.

## Fixes, in order of value

1. Restart the Jetson Llama 3.2 3B on `:8084` and make it a persistent unit
   rather than transient (it has now vanished twice on stop/reboot).
2. Tighten ASR for command phrasing, or add phrase hints — most gate rejections
   trace to garbled transcripts, not to Jev.
3. Consider a per-tool gate (lights/time can tolerate p ≥ 0.60 with a
   confirmation) instead of one global 0.90.
4. Decide whether non-VCM asks (documents, code, web) get tools; otherwise the
   refusal is correct and the tool list should be stated as the limit in the
   prompt.
