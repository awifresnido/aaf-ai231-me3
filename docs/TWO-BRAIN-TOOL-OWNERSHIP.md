# Tool ownership for the next two-brain refactor

User clarification, 2026-11-01: VCM commands belong to the small-model path;
complex tasks belong to GLM. Do not advertise the entire tool catalog to both
models or send every command through both. Radio is excluded from future
designs, and `play_radio` has been removed from the server and router.

Status: design for the next refactor. The current deployed pipeline still
advertises all remaining MCP tools to GLM and can fall back there after a Jev
timeout. Successful fast routes already bypass GLM; the Llama client receives
only a selected extraction schema, not the complete MCP catalog.

## Intended behavior

- A validated tool registry assigns an owner to each capability. Jev selects
  the worker/intent. It does not execute tools or transfer ownership merely
  because a request times out.
- The VCM worker uses ThinkPad Llama 3.2 3B, with the VPS Llama as host
  failover. Deterministic parsing supplies complete explicit arguments when
  possible; Llama resolves bounded VCM intent/arguments when needed. The
  worker receives only its allowed tool schemas, validates proposals, and
  returns the tool's spoken result without an extra GLM call.
- The GLM worker handles reasoning and complex workflows using its scoped
  capabilities. A mixed plan involving VCM actions delegates them to the
  VCM worker rather than giving GLM raw ownership of every VCM tool.
- One shared executor enforces the registry, validates arguments, records
  receipts, and performs each action. Model-generated text never constitutes
  evidence that an action happened.
- A Jev timeout on an otherwise recognizable VCM command sends it to the
  VCM worker. Missing information produces clarification. Escalation to GLM
  is an explicit decision before execution, with the reason recorded.

Initial VCM scope is the current ten routine capabilities: local time,
current weather, timers, alarms, reminder creation/listing, lights,
thermostat, music search, and playback control. Radio is absent. Messaging,
email, and calls currently require separate capability/workflow validation;
their placement is a policy decision, not a claim that these tool names
always require reasoning. Calls are a stub and messaging is unconfigured in
the current installation.

## Execution receipts and interruptions

Each request/action records pending, issued, completed, failed, or uncertain
state and the actual result. Cancelling speech or model generation must not
erase completed actions. A repeated request related to an interrupted
confirmation checks that receipt before executing again. An explicit request
for another action remains a new request. Once execution is issued, do not
reroute/retry it through another model without resolving its outcome.

## Implementation and acceptance sequence

1. Introduce the ownership registry and shared executor/receipt interface.
2. Separate the small worker's VCM schemas from GLM's tools. Give GLM a
   bounded delegation interface for VCM actions needed in complex plans.
3. Replace unconditional Jev-failure-to-GLM behavior with owner-aware handling.
4. Test single VCM requests, semantic variants, Jev timeout, host failover,
   true complex/mixed requests, malformed arguments, and interruptions before
   and after tool completion. Verify one executor invocation per action.
5. Deploy as a separately labelled trial while keeping the current VAD,
   Smart Turn, and echo-cancellation settings fixed.

Log requested owner, selected tool subset, Jev/worker timing, escalation
reason, execution receipt, and spoken-confirmation timing. Compare identical
utterances with the current checkpoint before claiming a latency gain.
