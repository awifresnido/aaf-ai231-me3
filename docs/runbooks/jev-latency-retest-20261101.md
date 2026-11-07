# Jev latency during the JV801P retest

Source: Pi `me3-local-audio.log`, 2026-11-01, 10:16:23–10:22:41
Asia/Manila. Thirteen inference turns were observed after the latest local
restart. No configuration or service changes were made for this assessment.

## What the measurements mean

`jev=` is client wall-clock time awaiting Jev, including connection and network
time; it does not isolate the provider's model inference. Total latency is
Pipecat turn inference to the first generated TTS audio, not physical speech
end to audible speaker output. The log does not provide a controlled comparison
of identical utterances with Jev enabled and disabled.

## Successful decisions

Seven decisions completed in 0.288–0.462 s, median 0.333 s. Five selected a
fast tool or small-talk path; two deliberately went to GLM for messaging.

| Request | Jev | Other work before TTS | Magpie TTFA | Turn to first audio |
|---|---:|---|---:|---:|
| Current time | 0.290 s | MCP 0.009 s | 0.815 s | 1.105 s |
| List reminders | 0.353 s | MCP 0.007 s | 0.928 s | 1.276 s |
| Set thermostat to 25 C | 0.462 s | Llama extraction 1.978 s; MCP 0.038 s | 0.890 s | 3.371 s |
| Current weather | 0.314 s | MCP 2.611 s | 0.882 s | 3.803 s |
| “Can you hear my voice?” | 0.288 s | Llama reply 1.830 s | 1.161 s | 3.275 s |

Stage metrics use separate measurement boundaries, so they are approximate
components rather than a sum guaranteed to equal total latency. The small-talk
reply incorrectly described itself as a text-only assistant; its prompt needs
the actual voice-agent persona.

## Timeouts and fallback cost

Six of thirteen decisions timed out (46%). Five elapsed about 1.204–1.205 s
before GLM fallback; the first took 2.245 s despite the configured 1.2 s
deadline. Async cancellation and event-loop scheduling can exceed a requested
timeout; these logs do not establish the cause of that first overrun.

| Recognized request | Time before GLM request | Turn to first audio | Additional bottleneck |
|---|---:|---:|---|
| Garbled initial speech | 2.245 s | 8.793 s | GLM clarification |
| Turn lights on | 1.205 s | 9.020 s | Two GLM calls; MCP only 0.016 s |
| Garbled red-lights request | 1.204 s | 6.808 s | GLM clarification |
| Red-lights follow-up | 1.205 s | 23.560 s | GLM first token 18.298 s |
| Brightness 80% | 1.204 s | 19.667 s | MCP 11.239 s |
| Alarm at 8 AM | 1.204 s | 17.798 s | GLM first token 13.684 s |

Jev adds a small direct cost on a successful decision, and its selected fast
route avoids GLM planning and response calls. A timeout adds its own wait and
also loses that route advantage. The latter effect is large for the explicit
lights and brightness requests in this retest. MCP and GLM waits remain
independent sources of delay.

Five successful fast/small-talk turns had median total latency 3.275 s
(1.105–3.803 s). Eight GLM turns had median 8.907 s (5.737–23.560 s). These
groups contain different requests and must not be presented as a causal speedup
attributable solely to Jev.

## Recommended next work

1. Let strict deterministic parsing handle explicit, complete basic commands
   before Jev. Use Jev for requests requiring semantic routing, while retaining
   GLM for ambiguity and complex tasks. The existing explicit-reminder route
   already demonstrates this structure.
2. Record connection/prewarm, request, confidence, timeout, and cancellation
   stages separately. A startup preconnection timeout also appears at 10:16:05;
   the log cannot distinguish provider delay from network/connection reuse.
3. Profile MCP server execution separately from the stdio round trip; the
   11.239 s brightness call should not be attributed to Jev.
4. Run a controlled replay of the same utterances before and after the routing
   change, including warm requests and requests after an idle interval.
