# Contextual tool deduction assessment — 2026-11-01

The user identified the additional voice turns as a test of whether the agent
can deduce needed tools from conversational context. This assessment therefore
grades inferred intent separately from exact numeric preferences, execution
receipts, spoken claims and response reliability. It does not require every
contextual request to use an explicit command verb or tool name.

Same run **`2a664e268a`**, contextual window **turns 21–35**, approximately
**22:19:06–22:23:18 Asia/Manila**. Later activity is outside this fixed window.
This is a different task mix and not a matched second pass of the initial test.

**Finding: GLM demonstrates useful contextual tool selection, including a
multi-turn temperature inference. The overall agent remains inconsistent
because its fast conversational path lacks history, cloud responses sometimes
stall, and tool success can precede a delayed or missing spoken confirmation.**

## What it inferred

The inputs below are semantic descriptions, not a raw transcript export.

| Contextual input / situation | Selected tool and arguments | Assessment |
|---|---|---|
| Room described as dark, turn 23 | `control_lights(on)` | Appropriate inferred need. State update succeeded; first response **4.526 s**. |
| Room subsequently described as too bright, turn 24 | `control_lights(brightness, 25)` | Correct tool and direction using the room-lighting context. **25%** was selected autonomously, not stated by the user. State update succeeded; **7.477 s**, including a Jev timeout. |
| Hot-day complaint, turn 25 | Jev → Llama conversational reply; no tool | Suggested a drink/shade. Reasonable as conversation, but it did not offer to cool the room. This is a missed opportunity for a context-aware follow-up rather than proof an unsolicited thermostat change was required. **3.892 s**. |
| Preference to remain in the room after the heat complaint, turn 26 | `set_thermostat(20)` | Strongest multi-turn inference: GLM connected the prior heat discussion to room temperature. **20 C** was its chosen setpoint; the user did not specify that preference. State update succeeded. First speech **7.456 s**, final confirmation began about **15.281 s** after speech end. |
| Desire to wake at six the following morning, turn 27 | `set_alarm("6:00 AM")` | Correct inferred alarm intent and time. Receipt reported next occurrence **2026-11-02 06:00 +08:00**. **6.017 s** to speech. Actual alarm delivery remains unimplemented. |
| Preference for green room lighting, turns 28–29 | `control_lights(color, Green)` | Correct inferred tool/value. First request committed but its confirmation stalled; repetition issued the same state change again and replied in **4.968 s**. |
| Rain question followed by a phonetically corrupted repeat, turns 30–31 | `get_weather()` on the repeat | Context helped recover the weather intent despite the bad repeat. Tool returned **25 C and drizzle**; response was grounded in current conditions. **8.398 s** on repeat. This did not provide a forecast for the rest of the day. |
| Clock-time question naming Manila, turn 32 | `get_time()` | Correct result for the configured local timezone; **5.501 s**. This tool has no arbitrary-city timezone lookup parameter. |
| Music described as excessively loud, turns 33–34 | `playback_control(volume_down)` | Correct implied direction and tool. GLM saw the music fragment and loudness fragment as two consecutive user messages and combined their meaning. **5.004 s**. Tool only updated media bookkeeping; it did not reduce physical speaker volume. |
| Idiomatic lights-off request, turn 35 | `control_lights(off)` | GLM correctly interpreted the idiom. The fast path lacked validated arguments and fell through after **2.061 s**, adding avoidable delay. Overall **6.884 s**. |

The ten cloud-selected MCP calls in this window all returned `ok=true`,
including both green-light writes. That is a tool-contract observation, **not
100% intent accuracy, ten distinct completed user goals, or physical actuation
verification**. The numeric brightness and thermostat settings are plausible
choices; whether they match the user's desired comfort level is unverified.
The user explicitly wanted contextual deduction, so absence of an explicit
tool name alone is not classified as a failure.

Lighting and thermostat receipts confirm the agent's stored state. Playback
control is currently only a media-state update, and the alarm tool stores the
alarm without a delivery mechanism. Spoken claims must respect these capability
limits even when the selected tool is semantically correct.

## Why contextual behavior differs between paths

Inspection of `pi/orchestration.py` and `pi/bot.py` confirms:

1. Jev receives only `{"utterance": latest_user_text}` with its classification
   question. It receives no preceding conversation or pending workflow.
2. Accepted small talk calls `SmallModelClient.answer(text)`, which also gets
   only the latest utterance and a short reply instruction.
3. GLM receives the aggregated conversation and tool results. The heat complaint,
   prior reply and preference to remain indoors were present when it selected
   the thermostat.

Thus **the demonstrated cross-turn reasoning belongs to GLM**, not Jev's
classification or Llama's current small-talk adapter. The hot-day statement
was accepted as small talk, so it bypassed the component that can reason over
the conversation. The follow-up then reached GLM and used that history.
This is a routing/ownership limitation, not evidence that every turn needs a
large model. A context-aware decision about whether a problem/workflow is still
pending could retain fast handling for explicit routine commands while routing
contextual follow-ups consistently.

Laya's current trained criteria intentionally put complex/context-dependent or
ambiguous follow-ups in `other`. A future Laya + GLM comparison should preserve
that division: compare routing quality separately from GLM's contextual planning
and argument quality. The strict Laya-only argument grammar is not evidence
that these indirect contextual requests should be rejected by the complete agent.

## Response reliability in the contextual window

There were **11 replies with finite first-speech latency**, median
**5.501 s**, range **3.892–8.398 s**. These successful-reply statistics omit
the three long waits interrupted by repetition:

| Turn | What happened before the repeat |
|---|---|
| 21 | A hearing-check transcript reached GLM. Its call waited **15.887 s** without a spoken reply before the repeated request interrupted it. |
| 28 | First GLM call took **12.127 s** and committed green lighting at approximately **22:21:38**. The post-tool call then waited another **10.962 s** before interruption by repetition. No first speech was delivered. |
| 30 | A rain-question transcript reached GLM. It waited **19.286 s** before interruption by repetition, without speech or a weather tool call. |

The stopped processing/TTFB metrics for interrupted calls are **elapsed waits**,
not evidence that a completion or first token was delivered. In particular,
an SDK metric emitted during cancellation must not be counted as a completed
provider response. The repeated green-light request produced a second write
even though the first was already committed: delayed confirmation can make
a completed action look like a lost request.

Two additional Jev attempts timed out at about **1.203 s**, on turns 24 and 26.
The initial test had no Jev timeouts; that finding must not be generalized to
this later window. The lights-off idiom had a distinct argument-validation
fallback, not a Jev timeout. A Llama small-talk reply occurred on turn 25.

Turn 33 has partial transcript frames but no independent response. Its music
fragment and turn 34's loudness fragment were retained as separate consecutive
user messages in GLM's context, which it interpreted together. It is **not**
another example of the initial five segments with no final ASR text at all.

Combining the initial 14 replies and these eleven gives **25 timed replies**
at median **5.093 s**. That pooled number mixes command types, repeats and
successful-only outcomes. It is not a controlled comparison against the
5.468-second historical baseline and does not include the waits before retries.

## Assessment and next comparison

The contextual tool selection is promising: room conditions, preferences,
idioms and a weather follow-up produced sensible tools. The next controlled
test should use labeled short conversations, scoring these independently:

- Appropriate tool or clarification, including the required earlier context.
- Grounded arguments versus autonomous preference/default choices.
- Committed state change, with a separate check for physical capability.
- Accurate spoken confirmation, including delayed/interrupted receipts.
- First response and actual completion latency, counting repeats and no replies.

Use the same contextual conversations for Jev + GLM and Laya + GLM. For example,
hold GLM, prompts, tool inventory, storage and audio constant, and change only
the router. A routing-only checkpoint should not be credited with GLM's
reasoning, or blamed for a transcript that never arrived.

No live settings or implementation were changed for this assessment.
[Context metadata and tool receipts](../profiling/jev-glm-live-20261101/context-summary.json)
and a [later trace snapshot](../profiling/jev-glm-live-20261101/extension-capture/)
are saved without raw speech or conversational prompts.
