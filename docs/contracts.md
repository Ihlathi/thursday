# Protocol v1.0

Canonical files: `shared/protocol.schema.json` (Draft 2020-12) and `shared/tools.json`.
Python loads those files directly; its ToolCall validation also validates arguments
per tool. `$defs` exposes reusable UserRequest, AgentEvent, ConfirmationRequest /
Response, ToolCall / Result, UIElement, SystemState, StateDelta, Cancel, Error, Audio,
Image and UserReply. All named shapes reject extra fields; data/metadata are
extension objects. Breaking changes require coordinated version bump and fixtures.

Core listens on IPv4 loopback port 8765. UI: `/v1/ui`; bridge: `/v1/platform`.
Both clients send a hello text frame first:

```json
{"version":"1.0","type":"hello","request_id":"hello1","payload":{"role":"ui","token":"<at-least-32-characters-private-token>"}}
```

Core responds hello_ack with the same request_id and role. Browser origins are
rejected except packaged Tauri `tauri://localhost` / `http://tauri.localhost`; native
clients send no Origin. Tokens are separate per role. Never put a token in a URL.
UI requests carry client-generated unique task_id and request_id:

```json
{"version":"1.0","type":"user_request","task_id":"task1","request_id":"req1","payload":{"text":"show me the stuff I bought recently","speak":false}}
```

AgentEvents correlate to the original request and task. Statuses: listening,
thinking, acting, speaking, confirmation_required, awaiting_input, completed,
cancelled, error, debug. Exactly one terminal task status is intended. Envelope
errors indicate invalid/busy/duplicate messages and do not themselves end a task.
Task IDs cannot be reused during the server lifetime. Debug metadata includes
provider mode, retrieved counts/element IDs, actual image metadata, model tool names,
policy outcomes and result status. No tool arguments/context dumps in debug events.

ConfirmationRequest arrives inside AgentEvent.confirmation. Render its exact action,
consequence, risk and expiry. Reply with `type=confirmation_response`, same task ID,
and payload `{confirmation_id,call_id,action_hash,approved}` copied exactly. A false
response, timeout, wrong session/task/hash, expired or replayed token never executes.
Use explicit consent, never auto-approve because the model says it is safe.

For `awaiting_input`, metadata.reply_to identifies a pending question. Send
`type=user_reply` and payload `{reply_to,text}` with same task ID. For cancellation
send `type=cancel`, payload `{reason:"User cancelled"}`. UI immediately stops local
recording/playback. Core aborts awaits and sends cancel to the bridge. In-flight OS
operations are best effort; no rollback guarantee.

## Voice and images

UserRequest carries exactly one of text or audio, optionally speak. Audio:
`{mime_type:"audio/wav",encoding:"base64",data:"..."}`. WAV, MP3, WebM and Ogg are
accepted, decoded max 2 MB; JSON frames max 3 MB. A full recording per request, not
streaming. ElevenLabs transcribes in Core; typed fallback needs no voice key.
Speaking events carry base64 audio/mpeg. Voice failure leaves text completion.
Image ToolResult carries PNG/JPEG, base64 <=2 MB, scope region/screen and optional
bounds. Only approved capture calls may supply images. Do not save recordings or
screenshots to long-term memory. Cloud provider retention follows the account's
terms; this prototype cannot promise zero provider retention.

## Bridge calls and world deltas

Core sends `type=tool_call`, payload `{call_id,name,arguments,expected_revision?}`. Bridge returns
`type=tool_result`, same request_id/task_id/call_id, payload `{call_id,ok,data?,delta?,
image?,error?}`. Failed results require `{code,message,retryable}`. For UI mutations, expected_revision is set by Core, included in the confirmation
hash, and must be checked by the bridge immediately before execution. Late replies after
cancel/timeout are ignored. Bridge must not execute core-owned tools. Catalog tool
parameters are also the Gemini function declarations, so schema edits affect both.

StateDelta has monotonic revision, optional system, elements, removed_ids, full.
full=true replaces the element set; otherwise upsert and remove by stable ID.
Each UIElement carries role/name/description/bounds/enabled/visible/parent/children/
source/confidence/sensitive/action_kind. Do not leak secure element values. UIA/API
classification must come from trusted adapter semantics, not arbitrary page text.
Revision changes on any relevant state change. Older deltas are ignored. A bridge
restart should cancel the active task and start a fresh session.

Core-owned tools: search_ui, inspect_ui, ask_user, request_confirmation,
complete_task, propose_command. All others in tools.json belong to the platform.
Core search_ui hides retrieval and may ask the platform for a UI snapshot. Core
refreshes targets before invocation and after mutations. Unsupported bridge tools
return unsupported_tool, not fake success. `mocks/platform.py` is explicitly fake.

## Settings (UI ↔ Core)

Provider credentials belong to Core. The UI may ask what is configured and may
hand Core a new value, but never receives a stored secret back.

* `settings_get` — payload `{}`. Core answers with `settings_state`.
* `settings_update` — a partial update. A present, non-empty string sets a
  field; an empty string clears it back to whatever Core's environment provides;
  an absent field is left alone, so a blank key box never erases a stored key.
  `model_mode` is `mock` or `gemini`. `clear_all: true` forgets everything.
* `settings_state` — Core's answer to both. Secrets appear only as
  `<name>_set` and `<name>_from_environment` booleans; non-secret fields
  (model name, voice ID) carry their value. `model_mode` is what Core will
  actually use — it reports `mock` whenever `gemini` is requested without a key
  available — while `requested_mode` is what was chosen. `saved` is true when
  the message answers an update.

None of these carry a `task_id`. Values are capped at 512 characters and an
oversized or malformed update is answered with `error/settings_rejected`.
