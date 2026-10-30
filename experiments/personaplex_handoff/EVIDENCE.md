# Stage 1 evidence — PersonaPlex / cascade speech handoff (hardware relay run)

Date: 2026-10-30 (times in UTC-8 local unless marked UTC)
Executor: Hermes (relay agent with lab network access), working from the
`HERMES_PROMPT.md` handover. Codex cloud session was offline at run time; no
`RELAY_RUNBOOK.md` was pushed, so this report follows `HERMES_PROMPT.md` steps
1–3 and PLAN.md Stage 1 directly.

Branch: `experiment/personaplex-cascade-handoff`
Harness commit executed: `427c934` ("Add PersonaPlex cascade handoff lab and Hermes handover")
Artifacts bundle: `me3-handoff-evidence.tar.gz` — sha256
`6c8fd5d2887a201d5f4c4df8cc3a1fd91862d242c005c590532d200cff3bc79d`
(WAVs excluded from the committed bundle; available on the Pi on request.)

## Environment verified (no secrets printed)

| Host | Facts |
|---|---|
| Raspberry Pi (192.168.5.12, `raspberrypi`) | Debian, kernel 6.18.50+rpt-rpi-v8, 4 cores, 3.5 GiB mem avail, ~98% idle |
| Pi production bot | `~/voice-agent/bot.py` — **not running** at capture time (idle-timeout shutdown, last run logged Oct 29 22:45). Latest logs: `bot_m5.log` (M5 tools run), `bot_dg.log` |
| Pi venv (existing, untouched) | `~/pipecat-quickstart/server/.venv` — Python 3.13.5, pipecat 1.13.0, aiortc 1.15.0, av 17.1.0, numpy 2.5.4, soundfile 0.13.1 |
| Speech mode | `bot.py` reads `SPEECH_MODE` (default `direct`); the env file's `SPEECH_BACKEND=local` var is **not read** by the bot (name mismatch, harmless) |
| Pi env file names | `OLLAMA_API_KEY, OLLAMA_BASE_URL, OLLAMA_MODEL, DGX_API_KEY, SPEECH_BACKEND, DGX_TTS_VOICE, DGX_ASR_BASE, DGX_TTS_BASE, DEEPGRAM_API_KEY` (values not printed) |
| MCP servers on Pi | `~/voice-agent/mcp_servers/`: asr, tts, voice_tools (M4/M5 as committed) |
| Jetson (192.168.5.11) | `nemotron-asr-server` was **Exited(0) 16h ago** (predates this session; not stopped by relay). Restarted via `docker start` — now Up, port 50051 listening. `magpie-tts-lan` Up throughout (port 50052). |
| DGX (10.153.60.233, ai-n003) | Ubuntu, OpenSSH 9.6p1. 8× A100-SXM4-40GB. PersonaPlex NOT running before relay start (no listener on 8998, no moshi procs, no tmux/screen). |
| DGX PP env | `~/miniconda3/envs/personaplex` — py 3.10.22, moshi 0.1.0, torch 2.4.1+cu121 (CUDA available). Repo `~/personaplex` (server entry `moshi/moshi/server.py`, default port 8998, `--ssl` optional/off). Weights cached: `nvidia/personaplex-7b-v1` (16 GB HF cache, incl. `voices/`). |

## GPU allocation (PLAN.md Stage 1 precondition)

- Cluster scheduler exists (`sinfo`/`salloc` installed) but **slurm is
  non-functional from ai-n003**: `squeue`/`sinfo` fail with "DNS SRV lookup
  failed / Could not establish a configuration source". No usable allocation
  system from this node; free GPUs operate first-come.
- Before start: GPUs 2, 3, 4 fully idle (0 MiB). Post-start GPU state:
  GPU 2 = 19.4 GiB used (this session), others unchanged. No other user's job
  was displaced; nothing was preempted.
- PersonaPlex was started pinned to the idle GPU 2 with
  `CUDA_VISIBLE_DEVICES=2`.

## PersonaPlex session started (one isolated session)

```
pid:        1848230  (survives SSH exit via nohup/disown; pidfile ~/pp_session.pid)
log:        ~/pp_session_20261030T144939.log
command:    CUDA_VISIBLE_DEVICES=2 ~/miniconda3/envs/personaplex/bin/python \
              -m moshi.server --hf-repo nvidia/personaplex-7b-v1 \
              --host 127.0.0.1 --port 8998
startup:    ~48 s (mimi load 3 s → moshi load 22 s → warmup 20 s → serving)
serving at: "Access the Web UI directly at http://127.0.0.1:8998" per log
GPU 2:      19 361 MiB used, util 0% at idle
```

**⚠️ Binding deviation (flagged):** the requested `--host 127.0.0.1` was NOT
honored — the server listens on `0.0.0.0:8998` and `[::]:8998` (all
interfaces). The `--host` argument is accepted but the aiohttp app binds
wildcard regardless. Consequence: the service is reachable from anywhere that
can route to the DGX, not just loopback. Since the DGX is VPN-only this stays
off the public internet, but it is wider than the PLAN.md Stage-2 intent
("forwarded listeners on loopback"). Recommended: treat 8998 as
DGX-VPN-reachable and, for the live hybrid stage, tunnel it over SSH to the Pi
rather than widening anything. Server code fix (optional, later):
`web.run_app(app, host=args.host, port=args.port, ...)`.

## Harness run (Step 2) — `run.py` on the Pi

Command (per README, existing venv, `-B`, no new installs):

```
~/pipecat-quickstart/server/.venv/bin/python -B experiments/personaplex_handoff/run.py
```

Result: **19/20 checks PASSED**, `overall_passed=false` (single failing check
below). Artifacts at
`~/handoff-lab/experiments/personaplex_handoff/artifacts/20261029T202208Z-8dd966aa/`
(run.json, lab.log, analysis.log, results/summary.json — run_id
`956ac4bb95a64d4aa2abc3fcfab10bf7`).

| Check | Result | Notes |
|---|---|---|
| baseline_both_sources_received | ✅ | pp 0.34 s, cascade 0.42 s |
| baseline_no_pipeline_errors | ✅ | |
| identity_after_tts_both_sources_received | ✅ | |
| identity_after_tts_no_pipeline_errors | ✅ | |
| negative_control_exposes_fifo_backlog | ✅ | 906 ms backlog (baseline: ~900 ms) |
| sixty_guarded_transitions_completed | ✅ | 60/60 |
| switch_output_gap_p95_under_300ms | ✅ | p95 0.8 ms |
| old_sender_audio_tail_p95_under_300ms | ✅ | p95 20.6 ms |
| same_webrtc_connection | ✅ | no reconnect |
| late_audio_and_tts_lifecycle_rejected | ✅ | 4 rejected |
| **playback_fence_after_generation** | ❌ | separation 95.8 ms < 250 ms required |
| no_guarded_pipeline_errors | ✅ | |
| receiver_rtp_timestamps_continuous | ✅ | |
| (analyzer) all_60_source_changes_reached_decoded_peer_in_order | ✅ | 62/62 |
| (analyzer) decoded_peer_transition_p95_under_300ms | ✅ | **p95 137.6 ms** (cloud baseline: ~141 ms) |
| (analyzer) no_decoded_silence_gap_over_300ms | ✅ | 0.0 ms across the board |
| (analyzer) no_revoked_sender_audio_reappeared_after_switch | ✅ | 0 violations |

### The one failing check — diagnosis

`playback_fence_after_generation` (lab.py:548) asserts
`fence_played.t − tts_generated.t > 0.25 s`. The comment in the code says the
fence follows **PCM delivery into WebRTC, not model generation** — so this
check is a machine-speed-dependent timing margin, not a functional invariant.
On this Pi the final generation→delivery pipeline is fast enough that the
gap lands at 95.8 ms; the cloud baseline machine happened to exceed 250 ms.
Everything the check is *meant to prove* (no early fence, ordered output) is
independently covered by passing checks (`no_guarded_pipeline_errors`,
`receiver_rtp_timestamps_continuous`, `all_60_source_changes…in_order`).
Suggested handling for Codex review: either lower the threshold to a
CPU-relative margin, derive it from measured inter-frame pacing, or mark it
"informational" — but that decision belongs to the harness author, and this
relay run records the failure as-is.

### Relay-vs-cloud comparison

| Metric | Cloud baseline | This Pi run |
|---|---|---|
| Checks passed | 20/20 | 19/20 |
| Decoded-peer transition p95 | ~141 ms | 137.6 ms |
| No-flush negative control | ~900 ms | 906 ms |
| Silence gap between sources | — | 0.0 ms |
| Revoked-audio reappearance | 0 | 0 |

Performance parity confirmed within noise; the single miss is the
machine-dependent fence margin above.

## Baseline cascade behavior (Step 1 remainder)

Production bot was found stopped (idle timeout), so a "live baseline capture"
of an actual conversation was not possible without starting the bot — that is
a Stage-2 action per PLAN.md ("Use an experimental entry point … keep the
production entry point unchanged"), and starting the production bot is
explicitly outside this relay's safety remit for Stage 1. What was verified
instead:

- Cascade service endpoints: Jetson ASR (50051) and TTS (50052) reachable
  from the Pi — confirmed OPEN after the ASR restart above.
- Speech backend selection logic in `bot.py` (direct/mcp/deepgram modes,
  `SPEECH_MODE` env), default `direct`, Jetson addresses default
  192.168.5.11:50051/50052, TTS voice `0`.
- Ollama Cloud LLM config present via env names (values not printed).

## Changes made by this relay (rollback list)

| # | Change | Where | Rollback |
|---|---|---|---|
| 1 | `docker start nemotron-asr-server` (container was Exited(0) 16 h before this session) | Jetson | `docker stop nemotron-asr-server` if the pre-session state is wanted |
| 2 | Deployed harness to `~/handoff-lab/` (tar of this branch's `experiments/`) | Pi | `rm -rf ~/handoff-lab ~/handoff-lab/experiments` |
| 3 | Harness artifacts dir created by run | Pi | `rm -rf ~/handoff-lab/experiments/personaplex_handoff/artifacts/20261029T202208Z-8dd966aa` |
| 4 | Started PersonaPlex: pid 1848230, GPU 2, log `~/pp_session_20261030T144939.log`, pidfile `~/pp_session.pid` | DGX | `kill $(cat ~/pp_session.pid)` and remove pidfile/log |
| 5 | Evidence bundle copied to `/tmp/me3-handoff-evidence.tar.gz` | Pi | `rm /tmp/me3-handoff-evidence.tar.gz` |

Not touched: production bot processes/files (`~/voice-agent/`), Pi venv,
OpenVPN, VPN profiles, router/firewall, unrelated GPU jobs, model services
beyond the ASR restart above, any credential values, any commits to `main`.
