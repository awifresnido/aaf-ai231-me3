# Live implementation and validation plan

## Objective and boundaries

Determine whether speech can hand off smoothly in both directions between
PersonaPlex on the DGX and the working ME3 cascade, managed by Pipecat on the Pi.
Keep a single ThinkPad browser WebRTC connection and audio output. The cascade
owns the wording and TTS of task answers; PersonaPlex handles casual conversation.

The code in this folder currently validates the local transport mechanics with
synthetic audio. The following hardware stages remain to be implemented and run.
Use explicit developer controls first. Automatic semantic routing and forced
PersonaPlex text-token speech are later experiments.

## Stage 1: reproduce and preserve the baseline

- Record exact commits, Python/framework/codec versions, speech backend, and
  startup commands without secret values.
- Verify the working cascade, interruption, and a read-only MCP tool.
- Run `run.py` on the Pi and return its fresh artifacts and CPU/load observations.
- Verify PersonaPlex independently from the ThinkPad. If it is not running,
  establish the permitted GPU allocation before starting one isolated session.
  Free GPU memory alone does not establish that a shared GPU is allocated to us.
- Start with a headset, then repeat the successful configuration with normal
  speakers and microphone. Preserve the current bot, model jobs, and recordings.

Use an experimental entry point such as `pi/bot_handoff.py`, port 7861, separate
logs, and existing environment-variable bindings. Keep `pi/bot.py` and its
production process unchanged. Keep one verified speech backend fixed initially;
compare Deepgram and Jetson direct mode in separate runs if both are available.

## Stage 2: add one continuous PersonaPlex audio path

Create a session-managed PersonaPlex client, an input audio tee, a handoff
controller, and a source-aware output adapter. Reuse existing cascade service
construction and MCP tools. Prefer new experimental modules in this folder
over broad refactoring of the working bot.

```text
ThinkPad microphone -> Pipecat input -> microphone tee
  -> continuous 24 kHz PersonaPlex path on DGX -> PCM via send_audio()
  -> existing ASR -> aggregator -> gated LLM/MCP -> existing TTS
Both producers -> one Pipecat output -> ThinkPad speaker
```

Inspect the actual deployed PersonaPlex server rather than assuming an SDK API.
Its reference protocol uses a startup handshake, framed Opus audio, and generated
assistant text. That text is not the user's ASR transcript. Maintain the shadow
ASR path for user text. Handle sample-rate conversion as a continuous stream,
including partial codec frames. Bound and measure input/output queue age; do not
accumulate muted audio for replay. Open and close tasks with the bot session.

Use the existing VPN/LAN routes, or managed SSH forwards where needed. Hermes's
VPN route need not exist on the Pi. If bridging through the ThinkPad, keep
forwarded listeners on loopback and verify each hop. Preserve certificate and
SSH host verification; an SSH tunnel can carry a loopback `ws://` service.

Disable the cascade's initial greeting in hybrid mode so only one component
greets. Confirm that the chosen Pipecat output has completed startup before
submitting PersonaPlex audio.

## Stage 3: implement explicit speech ownership

Keep controller state separate from audible ownership:

```text
state: FRONTDESK -> TAKING_OVER -> CASCADE_WORKING -> CASCADE_SPEAKING
                 -> RETURNING -> FRONTDESK
       RECOVERING on errors
owner: PERSONAPLEX | CASCADE | NONE
```

Track `session_id`, `handoff_id`, `owner_epoch`, `cascade_request_id`,
`personaplex_session_id`, and `tts_context_id`. Capture each request's epoch
when it starts. Do not stamp a late response with whatever epoch is current.

For interrupting takeover:

1. Close admission for the old source and increment the epoch.
2. Cancel obsolete generation as appropriate and queue the interruption.
3. Await processing of that exact interruption at the output.
4. Grant the new owner and admit its audio and matching lifecycle frames.

Use a manual session control/button or explicit developer command for ownership.
Test prepared clips first, then fixed text through the real TTS, then Ollama,
then a read-only MCP tool such as `get_time` or `list_reminders`.
Do not use messaging, email, or real reminders/timers as initial test actions.

Compare finish-then-switch against interrupt-then-switch. Preserve the known
TTS-to-output adjacency at first, while separately testing any proposed merge.
Do not add private queue-clearing code unless evidence shows standard
interruption leaves unacceptable stale output. Keep RTP timing continuous.

## Stage 4: make return context consistent

A speech-output mute alone does not synchronize model histories. PersonaPlex
can generate unheard speech internally while the cascade answers.

For the first implementation, close the old PersonaPlex session on takeover.
After the backend result is available, build a short prompt containing recent
conversation and task outcome, then open a new PersonaPlex session. The stock
server does not expose a general mid-session tool-result/context-update API.

Start sequentially. Once reliable, prepare the new session while cascade speech
is playing. Wait for its handshake, keep it silent and without conversational
input until activation, and verify that behavior against the deployed server.
Do not assume concurrent sessions are supported. Test repeated greetings and
first-response delays after reconnection.

Return only after a correlated final output fence for the whole cascade answer,
not after LLM completion or an intermediate sentence's stop event. Record both
sender consumption and browser delivery/playback; they are different boundaries.
If the answer is interrupted, invalidate any prepared session whose prompt
assumes the complete answer was heard.

Keep a shared history of user transcripts, delivered assistant speech, tool
results, pending requests, and interruptions. Record approximate or partial
delivery honestly. The backend must know what PersonaPlex said, and the new
PersonaPlex session must know the completed task result.

## Stage 5: interruptions and recovery

Keep microphone capture active. Separate full-duplex frontdesk behavior from
the cascade aggregator's normal VAD interruption policy; do not indiscriminately
cut every PersonaPlex backchannel. Preserve established cascade barge-in.

Test explicit stop, corrected requests, short acknowledgments, speech during
return, delayed results, backend timeout, DGX disconnect, and browser disconnect.
Stopping audio does not undo a completed tool action. Superseded results must
not become audible later. Revoke output before cleanup and return to a defined
usable mode; preserve the original bot as a separate fallback launch command.

## Evidence and acceptance

First run at least 30 prepared transitions in each direction, then 10 scripted
live task exchanges. Include a follow-up that refers to the cascade result
after returning to PersonaPlex. Log the exact scenario, source, epoch, request,
context IDs, and outcome.

| Measurement | Initial experimental target |
| --- | --- |
| Competing speech ownership | Zero overlapping grants |
| Revoked answer replay | Zero occurrences |
| Prepared-audio switching gap | p95 <= 300 ms |
| Explicit stop residual speech | p95 <= 300 ms |
| Handoff-induced lost first/last words | Zero in scripted listening tests |
| Browser connection | No reconnect for ownership switches |
| Return context | Correct task-referencing follow-up |
| Resource behavior | No steadily growing queue or unreleased session |

These are targets, not a reason to disable assertions or relabel failed runs.
Report distributions and failures if the hardware misses them. Measure backend
waiting (`task accepted -> first audio available`) separately from output
switching (`incoming audio available -> played`). Record PersonaPlex session
restoration separately too. Tone-based cloud timing is not physical playback.

Events should include request, revoke, output flush processed, last outgoing
audio, incoming audio available/submitted, final playback fence, PersonaPlex
handshake, grant, and stale-frame rejection. Use per-host monotonic times and
correlated IDs. Do not subtract monotonic clocks from different machines.
Capture receiver/browser evidence and listen for clicks, clipping, timing,
loudness changes, competing answers, and the intentional voice change.

Deliver a report, reproducible commands, versions, scenario counts, summary
metrics, logs, and recordings as an ignored artifact bundle. Keep passed,
failed, unrun, and externally blocked checks distinct. Commit experimental
code/docs only; never keys, auth tokens, VPN profiles, secret values, or raw
recordings. Push this experiment branch without merging it into `main`.
