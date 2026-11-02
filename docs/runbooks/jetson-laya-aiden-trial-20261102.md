# Jetson CUDA Laya + DGX Aiden trial — 2026-11-02

User requested the Jetson checkpoint **`~/models/laya/laya_v1/`** instead of Jev,
with TTS voice **Aiden**, retaining the other pipeline settings. Activated
**11:54:18 Asia/Manila**, run **`016c1ab953`**, Pi PID **17735**. Pipeline ready
**11:54:32**, greeting first playback **11:54:48**. Startup has no captured
errors; greeting first PCM **0.169 s**. Human voice trial completed.

## Completed live latency and performance

Human measurement window **11:58:50–12:06:29 Manila**, turns **4–33**: 30
speech-start events, **27 timed replies**, and three segments with no final
ASR (**15–17**). Greeting and untimed exchanges **0–3** are excluded. The
first two startup transcripts resemble fragments of the greeting; self-hearing
is a possibility, not established user intent. The introduction exchange also
lacks native timing. First included turn 4 is a partial hearing check.

Direct set **4–20** has 14 replies, hearing check **21** is a transition, and
context set **22–33** has 12 replies. Boundaries are inferred from content.

| Measurement | Jetson Laya + Aiden median | Jev + Aiden median | Current P95 |
|---|---:|---:|---:|
| Direct speech end to software response | **3.259 s** | 1.477 s | 27.041 s |
| Context speech end to software response | **3.980 s** | 4.960 s | 6.828 s |
| All human speech end to software response | **3.448 s** | 2.559 s | 15.762 s |
| Pi classifier client wait | **0.132 s** | 0.283 s | 0.146 s |
| Jetson synchronized classifier server time | **0.118 s** | unavailable | 0.131 s |
| Qwen first PCM, all successful human requests | **0.168 s** | 0.165 s | 1.426 s |
| Qwen complete request, all successful human requests | **0.649 s** | 0.616 s | 6.346 s |

Native response time and earliest playback agree within a few milliseconds;
earliest playback median is **3.446 s**. P95 is nearest rank on small samples.
These are software-onset measurements, not independent acoustic onset.

All **25 human classifications** completed without timeout/failure (28
including startup). Actual server inference/gating ranged **0.090–0.132 s**;
Pi wait **0.103–0.153 s**. Median client overhead outside the server was
**14.6 ms**. Relative to CPU Laya + Qwen run `147f31abef`, median server time
fell **0.748 → 0.118 s** (about **6.3× faster**). Pi client wait was about
**53% lower** than the Jev + Aiden sample, **0.283 → 0.132 s**.

This compute improvement did not translate into uniformly faster responses.
Of 27 replies, **22 reached GLM**, two used local small talk and only **three
used fast tools**. Eight argument checks yielded five rejections after accepted
classification: light-color wording (6, 12), a time question with a leading
affirmative (19), Manila time (30), and the lights-off rephrase (33). Some
rejections are deliberate scope checks; ordinary light-color phrasing remains
an existing guard-coverage limitation. Thermostat twenty and direct weather
classified as `other`. Placement/precision did not repair these behaviors.

Fast tools were lights on **1.170 s**, reminder **1.073 s** (classifier bypass),
and music catalog **2.189 s**. Their median **1.170 s** has only three samples.
GLM reply median was **3.787 s**. Contextual median was lower than Jev's sample,
but wording, state, clarification turns and external waits differed; no causal
accuracy or full-pipeline speedup is established by these aggregate medians.

### Long waits, missed speech and correctness

- Compound red-light/volume-up turn **13** took **15.762 s**. GLM generations
  took **1.408 / 13.253 s** around roughly **40 / 43 ms** tool calls. Laya
  server **0.099 s**, first Qwen PCM **0.164 s**. The large wait was downstream.
- Current weather turn **14** took **27.041 s** after classifying `other`.
  GLM generations took **6.794 / 14.947 s**, weather MCP **4.123 s**, Laya
  server **0.103 s**, Qwen first PCM **0.161 s**. GLM and the external weather
  path dominate this outlier.
- All **41 human TTS requests completed**, with no captured TTS failure,
  cancellation or late-context recreation warning. First-PCM waits still
  reached **1.744 s** (18), **1.426 s** (19), and about **1.565 s** (23).
  Full request tails reached **12.007 s** (18), **8.173 s** (19), and
  **6.346 s** (26). First response onset can precede completion substantially;
  full request timings include server/network and generator backpressure.
- Three speech segments lacked final ASR (15–17). Other transcripts distorted
  the brightness complaint and lights-off idiom, prompting clarification and
  repetition. The data does not establish that GPU contention caused this.
- The message-body follow-up (9) became small talk and promised to pass along
  a greeting without calling `send_message`. The heat complaint (25) also went
  to small talk; the room-specific continuation (26) reached the thermostat.
- Brightness consent (24) invoked **40%**, then corrected to **10%**, while
  acknowledging the initial increase. Response onset does not establish
  correct action completion. No audio-based ground-truth accuracy was measured.

### Jetson resource outcome

**228 tegrastats samples**, at two-second intervals during the human window:

- Reported RAM **5,381–5,395 MB of 7,485 MB**, median **5,387 MB** (about
  **5.26 GiB used of 7.31 GiB**, using binary conversion of those counts).
  Postflight `/proc/meminfo` had **1,999,340 KiB available**, about **1.91 GiB**.
- Reported swap stayed **785 MB** throughout the sampled window.
- Aggregate GPU load median **6%**, P95/max **99%**; 38 of 228 samples were
  at least 90%. GPU temperature **53.34–54.13°C**. This includes ASR and other
  GPU activity; it is not isolated Laya utilization. Short peaks can fall
  between samples.
- Laya stayed ready on CUDA with the same PID and **zero classifier restarts**;
  both Riva containers were still running. The resource capture was stopped
  after the test; the classifier and voice bot remain selected and active.

This run supports hosting FP16 Laya beside the active Jetson ASR pipeline
with **DGX TTS**, without observed swap growth or classifier restarts. It does
not establish headroom for an additional actively generating Jetson TTS or LLM.

Saved [summary](../profiling/jetson-laya-aiden-trial-20261102/benchmark-summary.json),
[per-turn timings](../profiling/jetson-laya-aiden-trial-20261102/per-turn-timings.md),
metadata-only timing/resource samples and postflight health alongside them.
Raw speech log and Pi/MCP trace capture stay outside the repo under
`/tmp/jetson-laya-aiden-live-016c1ab953*`. No runtime/source settings changed
during analysis; no test-suite rerun was needed.

## Follow-up routing diagnosis

The 22 human GLM referrals break down into **16 explicit `other` predictions**,
**five accepted tool classifications rejected by argument grounding**, and
**one compound bypass**. None of the 25 human classifications fell below the
0.50 probability / 0.05 gap thresholds. Treating all referrals as classifier
mistakes, or lowering thresholds to solve them, would misdiagnose the run.

A post-trial classifier-only replay confirmed a model miss on clean text:
`Set the room temperature to twenty degrees` still predicted `other` (0.8234).
Weather predictions were sensitive to formatting:

| Synthetic text | Prediction | Top score |
|---|---|---:|
| `what is the weather today` | `other` | 0.5024 |
| `What is the weather today` | `get_weather` | 0.8460 |
| `what is the weather today?` | `get_weather` | 0.9840 |
| `What is the weather today?` | `get_weather` | 0.9751 |

These scores are model confidence outputs, not measured accuracy. The replay
demonstrates inadequate robustness to ASR-style capitalization/punctuation;
no normalization, thresholds or weights were changed. `Set the light color
to green` and `Yes, what time is it?` still predicted the correct tool in the
same replay; their live fallback is an integration grammar issue.

Several `other` decisions are expected: messaging and compound commands are
outside the fast-tool scope, while ambiguous replies, room complaints and
noisy transcripts can require GLM's conversation history. Laya receives only
the latest user utterance. The message-body follow-up also shows why pending
conversation state needs separate handling before small-talk classification.
Prioritize supported-command guard coverage, pending-action handling and an
ASR-style labeled replay before deciding on further fine-tuning. Expanding
training/evaluation with case, punctuation and phrasing variants is supported
by the observed weather failure. No overall accuracy rate is established.

[Routing diagnosis and synthetic replay](../profiling/jetson-laya-aiden-trial-20261102/routing-diagnosis.json)
were captured without tool execution or speaker playback.

## Placement and unchanged configuration

- Laya loads **`/home/aldwin/models/laya/laya_v1`** on Jetson **CUDA**, with
  **FP16 weights and FP16 autocast**, through that checkpoint's `use_router.py`.
- Resident classifier **`http://192.168.5.11:8082`**, direct Pi-to-Jetson LAN;
  there is no ThinkPad hop for Laya inference. This HTTP classifier is not an
  MCP server. Pi hosts all existing MCP servers.
- `ROUTER_MODEL=laya` remains inside **`two_brain_plusjev`**. Jev is not
  instantiated. Laya `other`, rejection, unsupported grounded arguments and
  failures retain the existing GLM escalation path. Small talk still uses the
  existing ThinkPad Llama; secondary small-model URL remains blank.
- TTS stays DGX **Qwen3-TTS-12Hz-1.7B-CustomVoice**, port **8001** via the
  existing Pi **18001** SSH forward, now explicitly requesting **Aiden**.
- Jetson Nemotron ASR, Jetson SQLite/NVMe worker and state directory, Pi MCP,
  GLM settings, speakerphone/AEC and volume, VAD 0.3 s, Smart Turn two threads,
  pacat 150 ms, diagnostics and queued logging are preserved. No Riva container
  was stopped or reconfigured. Conversation resets; durable state is retained.

Only four private environment entries changed:

```text
DGX_TTS_VOICE=aiden
ROUTER_MODEL=laya
LAYA_ROUTER_URL=http://192.168.5.11:8082
VAD_EXPERIMENT=jetson-laya-glm-qwen-aiden-20261102
```

Existing **two-second Laya deadline**, **0.50 / 0.05** gate, exact trained
question and separate argument grounding/validation remain unchanged. No
argument-guard or contextual follow-up fixes are bundled into this trial.
Pi bot/router source hashes match the previous test; no Pi source deployment
was necessary.

## Artifact, CUDA and readiness verification

The Jetson model SHA-256 matches the ThinkPad checkpoint exactly:
`89948232efe015ca9ac260ef2160829b2d7b715005e5ed4115d9ae68d59649e6`.
Question, calibration and model-config hashes match the pinned integration
artifacts. The README still says 2.58, but the verified external payload uses
**`[1.9951245784759521, 1.0, 1.0]`**. External calibration is installed and
checked at startup. Laya's calibration identity warning refers to the original
training directory; artifact hashes and applied temperatures were verified.

Jetson provides **torch 2.15.0+cu132**, **Laya 0.4.21**, and CUDA Orin. Stored
tensors are F16. The checkpoint loader casts the resident model to FP16 and
sets FP16 autocast. New `serve_jetson_laya_router.py` wraps that supplied
loader and reuses the existing serialized HTTP contract. It rejects CPU or
precision fallback, synchronizes CUDA before/after inference, verifies the
trained questions/calibration, and warms three calls before serving. It logs
no transcripts and executes no tools.

**96 regression tests passed on Pi in 8.750 seconds**, including four new
checks for CUDA synchronization, wrong precision, runtime CPU fallback and
changed questions. No dependencies were installed and no checkpoint files
were modified.

Eight synthetic CPU/CUDA comparisons produced **zero argmax flips**, **zero
acceptance flips**, maximum probability difference **0.0025**. Their median
server durations were **0.711 s CPU / 0.093 s CUDA**. This is a precision and
contract smoke test, not a new accuracy evaluation or live latency benchmark.

Actual Pi adapter preflights measured **0.090–0.123 s** server and
**0.096–0.130 s** Pi wait across five synthetic utterances. A concurrent Aiden
request and classifier call produced first PCM **0.161 s**, classifier server
**0.126 s**, Pi wait **0.134 s**, without speaker playback or tool execution.
The explicit twenty-five-degree thermostat phrase still classified as `other`;
GPU placement does not fix that existing model behavior.

Model startup reported **864,480,256 CUDA allocated bytes** (about 824 MiB)
and **964,689,920 reserved bytes**. These allocator numbers are not total
process/system consumption. Before load, MemAvailable was about **3,583 MiB**;
after warm-up a sample showed about **1,980 MiB**, with Riva containers still
running and swap usage about 800 MiB. Full ASR/CUDA overlap remains to be
evaluated during the human trial; the prior capacity report described a
different FP32 loader and speech workload.

## Capture and comparison

Main Pi log: `/home/aldwinrpi4/voice-agent/me3-local-audio.log`, startup byte
**6082480**. Select `TURN_TIMING` run **`016c1ab953`**. Greeting turn 0 is
excluded from human statistics. Pi/MCP traces are in
`/dev/shm/voice-agent-diagnostics/016c1ab953/`; matching worker traces are on
Jetson.

Record `classifier_result.classifier_s` (Pi wait), `server_classifier_s`
(synchronized Jetson inference/gate duration), client overhead, argument
validity, downstream routes/tools/GLM, Qwen first PCM/full request and earliest
playback/native response. Keep missing ASR, repeated commands, interruptions
and failures separate. Software playback timing is not acoustic onset.

Jetson `voice-agent-jetson-laya-metrics.service` samples tegrastats every two
seconds into **`/tmp/jetson-laya-tegrastats-20261102.log`**, bounded to one hour.
Use the live run timestamps to correlate GPU, RAM and swap with latency. This
is metadata-only resource monitoring, not audio recording. Stop the metrics
unit after capture; leave the classifier available while this selection is active.

Compare primarily with Jev + Aiden **`f0c87b3a33`**, which used the same TTS
voice: direct **1.477 s**, context **4.960 s**, successful Jev client wait
**0.283 s**. Also compare the CPU Laya + Vivian run **`147f31abef`** for
classifier placement, accounting for the speaker difference. Command mix,
state and route/argument policies prevent claiming an exactly matched causal
comparison. Repeat direct and contextual sets and assess tool correctness.

## Service lifecycle and rollback

Classifier files are under **`/home/aldwin/voice-agent-laya-trial/`** on Jetson;
model files stay at their supplied path. The classifier was started as a
**transient, unenabled user unit**:

```sh
systemd-run --user --unit=voice-agent-jetson-laya --property=Type=simple \
  --property=Restart=no --property=UMask=0077 --setenv=HF_HUB_OFFLINE=1 \
  --setenv=TOKENIZERS_PARALLELISM=false /usr/bin/python3 \
  /home/aldwin/voice-agent-laya-trial/scripts/serve_jetson_laya_router.py \
  --checkpoint /home/aldwin/models/laya/laya_v1 \
  --host 192.168.5.11 --port 8082 --threads 2
```

It needs restarting after a Jetson reboot; verify `/health` from Pi before
restarting the voice bot. The existing DGX TTS reverse SSH forward also remains
temporary. The ThinkPad CPU Laya service is preserved as a rollback option.

Private Pi backup, mode 600:
`/home/aldwinrpi4/voice-agent-backups/jetson-laya-aiden-20261102-115418/voice-agent-env.before`.
Restoring it to `~/.voice-agent-env` and restarting `me3-local-audio.service`
returns to **Jev + Ryan**. To retain Aiden with Jev instead, explicitly select
`ROUTER_MODEL=jev` and the corresponding experiment marker. Restore routing
before stopping the unused Jetson classifier to release its resources. Stop
only the new Laya/metrics units, leaving Riva and the state worker untouched.

[Activation and validation artifacts](../profiling/jetson-laya-aiden-trial-20261102/)
contain no credentials or raw user speech. New implementation/documentation
changes remain uncommitted for review.
