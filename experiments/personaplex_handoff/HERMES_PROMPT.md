# Copy this prompt into the Hermes session

You are implementing and testing the ME3 PersonaPlex/cascade speech-handoff
experiment. You have local access to the ThinkPad, Raspberry Pi, Jetson Orin
Nano, and DGX through the existing VPN. Codex cannot directly reach that network;
we will relay your reports, logs, and recordings back for analysis.

Repository: `awifresnido/aaf-ai231-me3`
Branch: `experiment/personaplex-cascade-handoff`
Handover folder: `experiments/personaplex_handoff/`

Fetch this branch and inspect the existing checkout status before switching.
Preserve local changes and commits; do not reset, clean, force-push, or overwrite
the deployed bot. Use the existing checkout where practical. Read this folder's
README.md and PLAN.md, then inspect lab.py, analyze_receiver.py, and run.py.

## Goal

Verify that Pipecat on the Pi can switch audible speech smoothly in both
directions between PersonaPlex on DGX and the existing cascade, while retaining
one ThinkPad WebRTC connection. PersonaPlex handles casual conversation; the
cascade handles task reasoning/MCP and speaks its own answers using existing
TTS. Prioritize timing, interruption, stale-audio prevention, and context on
return. Start with explicit switching controls; automatic routing is later work.

## Current evidence and constraints

The cloud reference used real Pipecat 1.13.0, SmallWebRTC/Opus, and two local
aiortc peers, with synthetic model audio. It passed 20 checks and 60 handoffs.
The original decoded-peer transition p95 was about 141 ms; an unflushed negative
control incurred about 900 ms of backlog. See reference/cloud-baseline.json for
the committed verification result. None of these measurements validates live
PersonaPlex, Jetson, a ThinkPad browser, physical audio, or context restoration.

Public output.send_audio() worked for PersonaPlex-style PCM. Interruption
acknowledgement used output.on_after_process_frame for the exact frame ID.
Revocation guarded PCM and TTS start/stop/text context frames. A correctly
forwarding processor after TTS did not drop audio in this harness, so the
earlier Pi bug needs application-specific regression testing. Standard
SmallWebRTC backpressure did not require private queue-clearing modifications.

## Work through the plan

1. Record actual commits, Python/Pipecat/codec versions, active speech mode,
   startup commands, and baseline cascade behavior without exposing secrets.
   Inspect the existing Pi venv; do not install test requirements into it.

2. Run the harness on the Pi using its existing compatible interpreter:

   ```bash
   ~/pipecat-quickstart/server/.venv/bin/python -B experiments/personaplex_handoff/run.py
   ```

   Return its fresh run.json, results/summary.json, logs, recordings, and CPU/load
   observations. If dependencies are incompatible, use a separate environment or
   diagnose the exact blocker. Preserve failing evidence and assertions.

3. Verify PersonaPlex independently over the current trusted VPN route. Previous
   inventory reported an existing install but no running server; recheck it.
   Obtain a permitted GPU allocation under the server's normal policy before
   starting one isolated session. Preserve unrelated GPU jobs and model services.

4. Continue with PLAN.md's staged live implementation after the transport checks
   pass: live PersonaPlex audio through one Pipecat output, manual takeover,
   fixed TTS text, Ollama, a read-only MCP tool, return to PersonaPlex, then
   interruption and recovery tests. Implement experimental modules and a
   separate entry point/port 7861; keep the production entry point unchanged.

5. Keep the current VPN and LAN routes. Cloud access, a bastion, a new VPN client,
   and Tailscale enrollment are not prerequisites for this relay workflow.
   Use verified loopback SSH forwards if the Pi cannot directly reach DGX.

6. Finish with the live ThinkPad microphone/speaker path, 30 prepared switches in
   each direction and 10 scripted task exchanges, including interruptions and
   a task-referencing follow-up after return. Separate backend wait, switching,
   session restoration, and browser playback timing. Record subjective voice
   changes separately from transport artifacts.

Continue independent work through diagnosed failures; do not stop at installing
dependencies or starting a process. If an external prerequisite blocks progress,
finish unaffected work and report the precise requirement. Do not claim full
end-to-end success from synthetic tests or server logs alone.

## Return and commit

Return a concise report with executed scenarios, versions, exact commands,
passed/failed/unrun checks, metrics, recordings, diagnosis, and remaining
blockers. Package generated evidence from the ignored artifacts directory for
relay rather than committing it. Use existing secret bindings and never print
credential values. Do not send messages/email as test side effects.

Commit the experimental implementation and updated documentation to this branch
and push normally. Do not merge into main. Include rollback instructions for
only the processes and files introduced by this experiment. Do not stop or
restart the existing production bot, unrelated GPU jobs, or VPN connection.
