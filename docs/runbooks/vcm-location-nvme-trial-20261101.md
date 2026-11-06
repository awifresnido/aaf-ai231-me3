# Select Pi or Jetson/NVMe for the VCM MCP server

Update: the latest [Pi-MCP/Jetson-storage split](pi-mcp-jetson-state-trial-20261101.md)
keeps the VCM MCP server on Pi and uses a non-MCP SQLite worker on Jetson.
Pi mode now defaults to that worker. This document records the earlier
full-server placement trial; its initial state-selection semantics below
are historical unless `VCM_STATE_BACKEND=local_sqlite` is explicitly selected.

The project default remains **all MCP servers on the Pi**. Setting
`VCM_TOOL_SERVER_HOST=jetson` is an explicit experimental exception: the
VCM MCP process and its SQLite state execute on the Jetson. Pi audio,
endpointing, orchestration, and the MCP client remain on the Pi. Speech
service selection is independent and was not changed for this experiment.

The implementation is on `two-brain-plusjev`, uncommitted after checkpoint
`81cbbb8`. The initial full-Jetson trial used run ID `625b1e52a7`; experiment:
`vcm-jetson-nvme-20261101`. A restart creates a fresh run ID.
The [two-test results](vcm-nvme-results-20261101.md) show a combined median
response latency of 5.185 s and NVMe commit median 2.456 ms; model inference
now dominates. Startup self-hearing and command-validation issues remain.

## Placement and configuration

Edit the Pi's private `/home/aldwinrpi4/.voice-agent-env`, then restart
`systemctl --user restart me3-local-audio.service`.

| Setting | Meaning / deployed value |
|---|---|
| `VCM_TOOL_SERVER_HOST` | `pi` by default; `jetson` explicitly selects remote VCM |
| `VCM_JETSON_SSH_TARGET` | `aldwin@192.168.5.11` |
| `VCM_JETSON_SSH_KEY` | `/home/aldwinrpi4/.ssh/id_ed25519_vcm_jetson` |
| `VCM_JETSON_KNOWN_HOSTS` | `/home/aldwinrpi4/.ssh/known_hosts_vcm_jetson` |
| `VCM_JETSON_DATA_DIR` | Current trial: `/home/aldwin/voice-agent-vcm/state/trials/nvme-20261101` |
| `VAD_EXPERIMENT` | Label each run to match the selected host |

For the Pi option, `VOICE_TOOLS_DATA` retains its existing meaning and
defaults to `/home/aldwinrpi4/voice-agent-tools`. For Jetson, the default
data directory is `/home/aldwin/voice-agent-vcm/state`; the current trial
explicitly uses the separate directory above. The launcher confines remote
state paths beneath the Jetson deployment's `state/` root.

The connection uses persistent SSH stdio for the bot's lifetime, without a
new MCP TCP listener. A dedicated Pi-generated key is authorized on Jetson
with `restrict` and a forced command:

```text
/home/aldwin/voice-agent-vcm/.venv/bin/python /home/aldwin/voice-agent-vcm/pi/vcm_server_location.py --serve
```

The forced entry point accepts a bounded encoded request containing only
the state directory, diagnostic run ID, and optional timezone/weather
settings. It validates paths and fields before executing the fixed server.
SSH uses batch mode, a pinned host key, explicit identity selection,
connection timeout, and keepalives. It does not silently fall back to Pi
state if Jetson is unavailable. Bot/model credentials are not forwarded.

Jetson deployment files:

- `pi/vcm_server_location.py`
- `pi/stall_diagnostics.py`
- `pi/mcp_servers/voice_tools_mcp_server.py`
- `.venv/` installed from `deploy/jetson/vcm-requirements.txt`

The isolated environment uses MCP 2.3.0 and Pydantic 2.14.1, matching the Pi.
No Jetson GPU/audio dependencies or ASR/TTS containers were modified. The
remote process starts when the Pi opens its MCP connection and exits with
that connection; no separate Jetson systemd service is needed. The selected
Pi bot service is enabled at boot. Jetson mode also requires Jetson SSH to
be reachable; startup failure follows the existing Pi service restart policy.

## State preservation

A consistent SQLite backup was taken with the live Pi database opened
read-only. The snapshot was transferred privately to the trial directory;
integrity, byte hash, and mode 600 were verified. No state contents were
added to this repository. The trial retains DELETE/FULL synchronization.

The two locations now have **separate state histories**. New trial reminders,
timers, alarms, and device changes stay on Jetson. Returning to Pi uses its
original database. Do not copy either database over the other or merge state
automatically. A permanent migration needs an explicit state handover.

The private environment and previous deployed source files were backed up
under `/home/aldwinrpi4/voice-agent-backups/vcm-location-20261101/` with
restricted permissions. These private backups are outside the repository.

## Validation and preflight measurements

All **46 regression tests passed on the Pi**: the previous 37 plus nine
placement/request-validation/cross-host-clock tests. The existing real-stdio
test still passes with 13 backend tools and no radio tool. Local VCM mode
continues to expose its existing ten-tool subset to the small-model path.

Four actual MCP write calls were executed per host with five-second gaps
on separate disposable state. This includes Pi-to-Jetson SSH transport and
normal MCP handling, without a model, speech, or live state changes.

| Measurement | Pi local stdio | Jetson NVMe over SSH stdio |
|---|---:|---:|
| Median complete MCP call | 262.88 ms | 19.90 ms |
| Longest MCP call | 1,110.68 ms | 29.01 ms |
| Median summed SQLite commit spans per call | 188.67 ms | 2.91 ms |
| Longest summed SQLite commit spans | 1,097.00 ms | 6.36 ms |

The first call includes schema creation. Remote RPC time outside the server
handler was 6.04–7.67 ms, including transport/protocol/client overhead;
it is not a pure network round-trip measurement. Both captures contain four
matched client/server call IDs, no unfinished spans, no dropped events, and
no diagnostic write errors. This small preflight is not an end-to-end
spoken-response comparison.

Diagnostics now attach a boot-specific monotonic clock domain and namespace
span IDs by that domain. The summarizer retains one-way breakdowns only
within the same clock domain. Across hosts it subtracts **durations**, RPC
minus server handling, rather than subtracting unrelated monotonic clocks.
No wall-clock synchronization assumption is needed for that calculation.

Evidence: [preflight captures and summaries](../profiling/vcm-location-preflight-20261101/).
`scripts/probe_vcm_location.py` exercises the actual configured launcher on
disposable state. The earlier [storage activity diagnosis](storage-activity-diagnosis-20261101.md)
contains the untraced storage comparison and root-cause evidence.

## Voice trial and analysis

The live startup verified local speakerphone streams on the paired echo
canceller, PCM 100%, ThinkPad model health, remote VCM diagnostics on Jetson,
and successful greeting playback. Settings remain ThinkPad-only local VCM,
Jev/GLM/VPS fallback disabled, VAD stop 0.3 seconds, Smart Turn two threads,
queued logging enabled, pacat 150 ms.

Use one command at a time, waiting for the reply: time; lights on; lights
green; thermostat 26 degrees; lights blue; lights off; weather. Repeat the
lights cycle twice. Note unexpected speech during silence or wrong actions,
then report completion. Some startup turns may lack a speech-end marker;
retain them in evidence but exclude them from speech-end latency statistics.

For analysis, collect the **same run ID** from both hosts:

```text
Pi:     /dev/shm/voice-agent-diagnostics/<run>/pi-*.jsonl
Jetson: /dev/shm/voice-agent-diagnostics/<run>/mcp-*.jsonl
```

Combine their metadata files in one local capture directory and run
`scripts/summarize_stall_diagnostics.py`. Report speech-end to first playback,
endpoint/context readiness, model, MCP/server/SQLite, TTS, missing markers,
intent errors, echo, and incomplete calls separately. First playback write
precedes actual sound by output buffering; keep the native latency metric
alongside it. Compare with the earlier queued-logging voice trial, while
accounting for different utterances and sample sizes. A matched Pi rerun
with the same prompt sequence would strengthen the comparison.

## Return to Pi

Set `VCM_TOOL_SERVER_HOST=pi` and restore an appropriate `VAD_EXPERIMENT`
label in the private environment; restart `me3-local-audio.service`.
Verify the new configuration event says `vcm_tool_server_host=pi` and
`vcm_tool_transport=local_stdio`. The original Pi database is still present.
With the new default storage split, Pi MCP still uses the Jetson state file.
Returning to the original Pi database additionally requires an explicit
`VCM_STATE_BACKEND=local_sqlite`. Keep the Jetson trial state for review;
no reverse synchronization occurs.
