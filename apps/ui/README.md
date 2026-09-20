# JARVIS desktop UI

The Tauri 2 overlay is the human-facing client for the protocol in
`../../shared/protocol.schema.json`. It uses Tauri's native WebSocket plugin so
the Core connection does not inherit a development-server browser origin.

## Start for development

Set `AGENT_UI_TOKEN` to the same private token configured for Core, then run:

```powershell
npm install
npm run tauri dev
```

Core must be listening on `ws://127.0.0.1:8765/v1/ui`. A different loopback port
may be selected with `AGENT_UI_URL=ws://127.0.0.1:<port>/v1/ui`. The native shell
rejects non-loopback URLs and tokens outside the protocol's 32–256 character
range. The token is read from the process environment, used for the hello frame,
and is never written to source, a URL, local storage, logs, or the visible UI.

Use `Ctrl+Alt+J` to open or close the overlay and `Ctrl+Alt+Shift+J` to quit.
Escape also closes it. While closed, the transparent full-screen window ignores
mouse input. While open, it is focusable and keyboard navigable.

## Implemented protocol behavior

- typed requests and complete-recording voice requests (WebM/Ogg, maximum 2 MB)
- optional spoken MP3 responses
- correlated task status and bounded activity history
- exact confirmation action, consequence, risk, expiry and opaque response fields
- `user_reply` for `awaiting_input`, distinct from a new request
- local recording/playback stop followed by protocol cancellation
- stale/other-task event rejection, terminal-state handling and reconnect UI
- no API keys in the UI process; provider credentials remain in Core

The visual layer supports keyboard focus indicators, live status announcements,
reduced motion, forced colors and responsive sizing. The browser-only Vite preview
renders the interface but deliberately does not connect to Core; native Tauri is
required for the trusted local socket.

## Verification

```powershell
npm run build
npm run tauri info
```

`npm run build` checks TypeScript and creates the production frontend. Native
compilation additionally requires Rust, Cargo, Visual Studio Build Tools and the
Windows SDK, as reported by `tauri info`.
