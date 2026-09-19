# Windows bridge teammate handoff

Own OS observation and execution: UI Automation first, direct Windows APIs next,
mouse/keyboard and screenshots last. Prefer stable UIA/runtime IDs scoped to a
window/process generation; never reuse an ID for a different element. Keep all OS
imports here. Core, UI, and the mock bridge work without Windows.

Start Core, then use `python run.py mock-platform` as the reference bridge client. The
bridge connects to `ws://127.0.0.1:8765/v1/platform`, authenticates with its separate
local token and receives one ToolCall at a time. Return ToolResult with matching
request_id/task_id/call_id. Use the shared schema, not copied models. See
`bridge_contract.py`, `../../docs/contracts.md` and `../../shared/tools.json`.
The ToolCall owner field is in the tool catalog: implement only owner=platform.

Implementation order:

1. get_system_state and get_ui_state via UIA; return normalized UIElement and full
   StateDelta. Mark password/secure fields sensitive. Do not include their value.
2. open_app and safe settings APIs; invoke_ui direct uses UIA Invoke/Select/Toggle.
3. set_ui_value, scroll and visible demonstration mode. Visible mode may animate
   the pointer but must verify the same semantic target before activation.
4. Region/full screenshots on explicit calls only; encoded image in ToolResult.
5. Other tools as supported; return structured unsupported_tool errors otherwise.

Classification metadata is a security boundary: action_kind=navigation ONLY for
known navigation operations, never arbitrary buttons, page-provided labels or
submit links. Unknown targets must be unknown. Core conservatively confirms
unknown typing/clicking. Independently validate bounds, enabled/visible state,
revision (including ToolCall.expected_revision), allowlisted operation parameters, lock/sleep state and OS permissions.
Increment revision for semantic/context changes (including navigation/focus) and
geometry changes; coordinate-only changes do not cause Core to re-embed text.
On sleep/resume increment sleep_epoch. Return full=true snapshots or atomic deltas
with removed_ids. Reconnecting with reset revisions starts a new session/task.

`run_approved_action` allows only set_volume/set_brightness with integer 0..100.
Map those to direct APIs, never concatenate shell. `propose_command` is Core-only
and never executes shell in this build. open_url/file/app must reject unsupported
schemes, executable content and unsafe launch arguments or classify them for
additional authorization; initial Core policy already requires consent for paths
and URLs. Do not infer safe execution from a tool name alone.

Cancellation arrives on the same socket while a call is running; keep the receive
loop independent, cancel queued operations, and abort safely where possible. Never
replay a mutating call after timeout/disconnect. A timed-out operation may already
have happened: observe before retrying. Bridge is trusted local code, not a sandbox.
