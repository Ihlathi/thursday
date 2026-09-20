# JARVIS UI integration — Protocol v1.0

This Tauri application connects to the existing Core contract in `../../docs/contracts.md`
and `../../shared/protocol.schema.json`. No Core or platform protocol changes are needed.

## Run with teammates

1. Start Core at `ws://127.0.0.1:8765/v1/ui` and the Windows bridge (or mock platform), as described in the root README.
2. Set the same private `AGENT_UI_TOKEN` in the shell launching this app, then run `npm run tauri dev` from `apps/ui`. Never commit tokens. Provider keys belong only to Core.
3. In the JARVIS tray menu choose **Open Assistant**, then **Connect to assistant**.
4. Submit a typed request. Follow-up questions accept replies in the same box. Consequential actions display the exact action, consequence, risk, and expiration; only an explicit button click sends approval. **Stop** cancels the task and immediately stops local playback and cursor effects.

The native WebSocket client sends no browser Origin, so development and packaged builds both meet Core's origin rules. It authenticates first and never places the token in a URL or frontend state. One app connection is shared by the Assistant UI. Disconnect invalidates the local task; reconnect is manual and never replays actions.

## Ownership and presentation

Core owns task/action execution and policy. The Windows bridge owns real OS input. Incoming correlated AgentEvents drive the existing summon/dismiss renderer via the internal `jarvis-agent-status` event. The Assistant window owns text input, exact confirmations, follow-up replies, cancellation, and optional returned MP3 playback. Protocol debug messages never trigger desktop actions.

Current protocol v1.0 does not send cursor path/click coordinates to UI. Therefore the UI does not fake or duplicate bridge movement. Existing Ctrl+Alt+M/T/C/A visual demos remain development-only; Ctrl+Alt+J toggles the overlay. Coordinate-synchronized production trails need a coordinated protocol addition with the Core/Windows owners. Microphone recording is not implemented yet; typed requests work without voice credentials.

Settings still tune the same Canvas renderer live. Closing Assistant or Settings hides that window; Quit JARVIS exits the app.

## Validation

Run `npm run build` and `cargo check --manifest-path src-tauri/Cargo.toml`. Use Core's mock provider and mock platform for integration testing without OS actions or provider charges. Do not run the terminal mock UI at the same time: Core permits one UI connection.
`nRun `node tests/core-integration.cjs` for UI message-flow checks against the shared message definitions (no Core process or credentials needed).
