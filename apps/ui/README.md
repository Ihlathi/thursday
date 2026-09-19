# UI teammate handoff (Tauri 2)

Own the accessible conversational UI, microphone capture, playback, focus/keyboard
navigation, meaningful status announcements, confirmation display, and cancellation.
Core owns reasoning, provider credentials, transcription, synthesis and policy.

The scaffold previews real-shaped mock AgentEvents with `npm install && npm run dev`.
`npm run build` builds the frontend. With Rust and OS Tauri prerequisites installed,
`npm run tauri dev` opens the desktop shell. Native builds are teammate work.

Use `../../shared/protocol.schema.json` as the source of truth. Fixtures live in
`../../mocks/agent-events.json`; do not invent parallel interfaces. See
`../../docs/contracts.md` for WebSocket authentication, examples and lifecycle.

For real IPC, have the native shell obtain the *local UI token* through a trusted
launcher/private file and connect to `ws://127.0.0.1:8765/v1/ui`. Never put tokens in
URLs, source, localStorage or a public web page. The current Python server rejects
ordinary browser origins; the Vite page is a mock preview. The native shell should
proxy WebSockets without an Origin, or use the explicitly permitted packaged Tauri
origin. Do not broaden origins to make a public webpage control the machine.

Render confirmation action + consequence + expiry with explicit Approve/Deny
buttons. Return all three opaque binding values unchanged. Stop audio immediately
on local cancel, then send Cancel; await terminal cancelled/error/completed event.
Send UserReply for awaiting_input; it is not a new UserRequest. Ignore old-task
messages and never manufacture completion. API keys belong only in Core.

Voice v1 is a complete recording (base64 WAV/WebM/Ogg/MP3, decoded <=2 MB), not live
streaming. Offer push-to-talk, a recording timer and typed fallback. TTS is complete
base64 MP3. Screen/audio cloud disclosure belongs in onboarding and consent UI.
