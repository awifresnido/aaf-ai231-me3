# Jev + Jetson Voxtral Mini trial — 2026-11-02

Activated **15:01:24 Asia/Manila**, run **`7a50558fa3`**, experiment
`jev-voxtral-jetson-asr-small-qwen3-aiden-20261102`. Human trial completed.
Voxtral replaces Qwen2-Audio in **both ASR and small-model roles**. Jev
1.14.0, GLM `z-ai/glm-5.3-flash`, Qwen3 Aiden TTS, Pi MCP, Jetson SQLite,
speakerphone/AEC, VAD 0.3 s, SmartTurn two threads and audio buffering remain
selected. Both Voxtral roles share one Jetson inference slot.

## Serving configuration

Jetson endpoint `http://192.168.5.11:8083`, model alias
`mistralai/Voxtral-Mini-3B-2507`. Existing local model files:

- `/home/aldwin/models/llm/voxtral/Voxtral-Mini-3B-2507-Q4_K_M.gguf`
- `/home/aldwin/models/llm/voxtral/mmproj-Voxtral-Mini-3B-2507-Q8_0.gguf`

Transient user service **`voice-agent-voxtral-native.service`** runs the
existing llama.cpp build 11824, commit `36cbf415f`. The service name records
an earlier probe; the active adapter uses **audio-first instruct chat**,
not native transcription tokens or `/v1/audio/transcriptions`.

Reproduction command, after copying `deploy/jetson/voxtral-chat.jinja` to
`/home/aldwin/voice-agent-voxtral-trial/voxtral-chat.jinja`:

```sh
/home/aldwin/models/src/llama.cpp/build/bin/llama-server \
  -m /home/aldwin/models/llm/voxtral/Voxtral-Mini-3B-2507-Q4_K_M.gguf \
  --mmproj /home/aldwin/models/llm/voxtral/mmproj-Voxtral-Mini-3B-2507-Q8_0.gguf \
  --host 192.168.5.11 --port 8083 --alias mistralai/Voxtral-Mini-3B-2507 \
  -c 4096 -np 1 -b 512 -ub 128 -ngl 99 -fa on -ctk q8_0 -ctv q8_0 \
  -t 2 -tb 2 --jinja \
  --chat-template-file /home/aldwin/voice-agent-voxtral-trial/voxtral-chat.jinja
```

The GGUF's embedded template injected an unrelated Devstral coding prompt.
It is overridden. The adapter verifies `/props` audio support, the served
template's normalized SHA256
`3faa7f0b8d012e01c58769d7ca81a8a87719acc57b59588afbfa47cee0e66dec`, and
`/v1/models` identity before starting. Media precedes the transcription
instruction. Text-first requests and native-token transcription probes
produced refusals or answers with these weights/runtime and were rejected.
An initial system instruction for small-model requests is merged into the
first user message because this Voxtral template has no separate system role.

[Official model capabilities](https://huggingface.co/mistralai/Voxtral-Mini-3B-2507)
include audio transcription, audio understanding and text conversation.
The specific quantized serving path still requires live evaluation.

## Checks and limits

All **113 regression tests passed** on the Pi, including the existing Qwen,
Laya, router and TTS checks and eight new Voxtral adapter/template checks.
Actual adapter checks using synthetic Aiden audio returned:

| Request | Result | Client time |
|---|---|---:|
| ASR: What time is it? | Exact transcript | 2.076 s |
| ASR: Turn on the lights. | Exact transcript | 2.094 s |
| Small reply: Hello. | Hello! | 0.310 s |
| Thermostat argument extraction | No result by deadline; GLM fallback retained | 2.507 s |

Earlier probes sometimes omitted an article or the word “degrees”; two exact
outputs are not an accuracy estimate. A real-time synthetic VAD → SmartTurn →
Voxtral → Jev probe delivered transcription and routing. Jev selected `other`
at confidence 0.720 in 0.988 s and forwarded context to GLM. The probe lacked a
GLM sink and consequently timed out waiting for a fast-tool reply. It proves
pipeline delivery, not fast-tool acceptance or end-to-end spoken completion.
No physical tools were executed during the synthetic probes.

ASR uses the existing segmented-service lifecycle, 16 kHz mono WAV,
35-second cap and 15-second HTTP timeout. Metadata records per-segment queue
wait, HTTP duration, failures, and speech-end-to-transcript latency. Small
calls retain the 2.5-second deadline and separate argument validation; Jev
retains its 1.2-second deadline and acceptance thresholds. Existing GLM
escalation policy remains selected. No DGX key is sent to the Jetson endpoint.

Live greeting first PCM **0.163 s**, complete HTTP **0.903 s**; playback
succeeded. These are startup TTS measurements, not human end-to-end latency.
Trial metadata and synthetic evidence are in
`docs/profiling/jev-voxtral-trial-20261102/`. User speech logs remain private.

## Resources and rollback

Stopped unused **`voice-agent-jetson-laya.service`** before loading Voxtral.
Both Riva containers and the Jetson SQLite worker remain available. No model
download or package installation was needed. Voxtral service memory was
3.72 GB (peak 3.88 GB), zero restarts. Before human testing, Jetson available
RAM was about **700 MiB**, swap **575 MiB**, GPU idle, temperature about 53 C.
Capacity is tight; live resource capture is necessary to distinguish model
compute from memory pressure. These snapshots do not establish concurrent
pipeline capacity or a speed improvement over Qwen2/Nemotron.

`voice-agent-voxtral-metrics.service` captured tegrastats every two seconds to
`/tmp/voxtral-tegrastats-20261102.log` on Jetson and was stopped after the
trial. Pi log starts at byte **7451797** in
`/home/aldwinrpi4/voice-agent/me3-local-audio.log`; diagnostics are under
`/dev/shm/voice-agent-diagnostics/7a50558fa3`.

Private pre-switch environment and source backups:
`/home/aldwinrpi4/voice-agent-backups/jev-voxtral-20261102-150120/`.
Restore `private-env` to `/home/aldwinrpi4/.voice-agent-env`, restore backed-up
`bot.py` and `qwen_audio_stt.py` to `/home/aldwinrpi4/voice-agent/`, and restart
`me3-local-audio.service` to return to Jev + Qwen2-Audio + Aiden. The extra
Voxtral module is unused under that configuration. Stop the Voxtral and
metrics services when deselecting them. Restart Jetson Laya only when needed
for a Laya trial. All implementation changes remain uncommitted.

## Completed human trial

Trial turns 1–29 include two setup turns. Direct commands were inferred as
turns 3–14, transition/checks as 15–16, and contextual requests as 17–29.
These boundaries differ from the previous Qwen2 run, so comparisons are
observational. Turn 11 inherited a second transcript from turn 10 and has no
independent speech-end/E2E value. There were 28 measured first spoken onsets
overall, 26 in turns 3–29.

| Measurement | Direct | Context | Turns 3–29 |
|---|---:|---:|---:|
| E2E speech end to bot onset, median | **4.153 s** (11) | **5.968 s** (13) | **5.156 s** (26) |
| E2E p95, nearest rank | 6.434 s | 7.537 s | **7.208 s** |
| Voxtral ASR HTTP, median | 2.134 s (12) | 2.344 s (14) | **2.263 s** (28 requests) |
| Speech end to transcript, median | 2.441 s | 2.651 s | **2.605 s** |
| Jev successful call, median | 0.288 s | 0.299 s | **0.290 s** |
| Qwen3 first PCM, median | 0.165 s | 0.165 s | **0.164 s** |

Of 27 routing outcomes in turns 3–29, **seven** used fast tools, **19** used
GLM, and **one** used Voxtral for a short smalltalk reply (0.685 s). Six
fast-tool turns with independent E2E measurements had median **2.915 s**;
19 GLM turns had median **5.669 s**. All 30 Voxtral ASR requests in the whole
run completed without an HTTP failure. Two Jev calls reached the 1.2-second
deadline and fell back to GLM. The longest measured response was **7.537 s**
(turn 25); no TTS first-audio stall like the previous Qwen2 run occurred.

The Voxtral server logged 31 model tasks (30 ASR, one smalltalk). Median
prompt evaluation was **1.583 s**, decoding **0.539 s**, and total server
time **2.057 s**. This is the principal fixed ASR cost. Pi HTTP ASR median
**2.221 s** includes roughly 0.16 s beyond the server median, though tasks
were not individually paired. ASR starts after VAD closure. Speech-end to
transcript adds the 0.3 s VAD confirmation and transport/processing overhead.
Fast MCP calls were generally short; the Pi's 18 MCP client spans had median
**0.028 s**, with a **1.351 s** maximum for an external tool. GLM adds remote
generation and sometimes multiple sentence/TTS cycles. Qwen3 first PCM stayed
around 0.16 s; complete TTS requests had median **0.635 s** and maximum
**1.782 s**.

Compared with Jev + DGX Qwen2-Audio + Aiden, the overall median rose from
**4.494 to 5.156 s** (+0.662 s), while median ASR HTTP rose from **0.744 to
2.263 s** (+1.519 s). Direct replies were 4.153 versus 4.433 s, while
context replies were 5.968 versus 4.502 s. The mix of routes and utterances
changed, and Qwen2 had a 29.884-second TTS outlier. Earlier Jev + Nemotron +
Llama + Aiden overall median was **2.559 s** (23 replies), with a different
speech and route mix.

Transcript quality remains a material issue. Private utterance history
contains answer-like or altered ASR outputs: a music request became “I can't
play music directly ...”, a multiplication request became “132 times 11 is
1452”, a Jane Austen query became an encyclopedia-style statement, and a PDF
request became “I don't have a saved PDF file.” Turn 3 was truncated to “Turn
the lights”, and a reminder lost its requested action. This can change Jev's
route and GLM's answer; without original audio recordings, exact word error
rate and intent accuracy cannot be quantified. Several contextual requests
were recognized but went to GLM under Jev's confidence/argument gate. The
small-model role was exercised once, so its broader accuracy is unmeasured.

Jetson tegrastats had **252** samples: RAM median **6852/7485 MB**, p95
**7031 MB**; swap median **615 MB**, stable near 617 MB; GPU median idle but
p95 **99%**, temperature at most **55.75 C**. Post-trial available RAM was
about **308 MiB**. The model service stayed active with **zero restarts**,
current memory **3.82 GB** and peak **3.88 GB**. There was no crash or ongoing
swap growth; remaining headroom is narrow. The metadata summary and per-turn
timings are in the trial profile folder.
