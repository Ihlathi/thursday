# Verification record — 2026-09-20

Tested locally with Python 3.14.7; supported minimum is Python 3.11.

- `python -m pytest -q`: **51 passed**. One upstream google-genai warning about a
  Python typing alias scheduled for removal in Python 3.17; no test failures.
- `python run.py demo --mode mock`: completed the retrieval/direct invocation demo.
- `python run.py stack`: completed the authenticated real WebSocket vertical slice.
- Separate `serve --mode mock`, `mock-platform`, and `mock-ui` processes completed
  the same task over authenticated WebSockets on a test port.
- `npm run build` from `apps/ui`: TypeScript and the production frontend build
  passed (Vite 8.3.0); npm reported no known dependency vulnerabilities.
- The UI was visually checked at a narrow viewport after responsive fixes. Its
  dialog, connection state, form controls and reconnect guidance are exposed in
  the accessibility tree.
- `cargo fmt --all --check` and `cargo metadata --locked --no-deps` passed using
  a temporary Rust toolchain. `cargo check --locked` reached compilation but this
  host has no Visual Studio C++ Build Tools/Windows SDK, so it stopped at the
  missing `link.exe` prerequisite rather than compiling the native shell.
- `python platform/windows/bridge.py --self-check` passed all real read-only
  probes: UIA, lock state, foreground window, normalized snapshot and structured
  audio/battery/brightness/network state.
- `git diff --check`: passed; changed paths and common secret patterns checked.

Coverage: strict shared contracts and fixtures, catalog/schema consistency, policy
context and bounded allowlist, confirmation task/hash binding/replay/expiry/denial,
cancellation during confirmation and voice, approved vs stale UI actions, working
TTL, SQLite persistence/promotion, semantic UI search, explicit opt-in task/context notes, coordinate-only index reuse,
deltas and sensitive element exclusion, offline multi-step loop, missing keys,
provider timeouts, vision escalation, unsolicited image rejection and exact capture scope, real Gemini
SDK multimodal part construction and thought/function ID preservation, mocked
ElevenLabs HTTP contracts, socket authentication/origin rejection, task replay and
socket cancellation.

No live Gemini or ElevenLabs requests were made: API keys/voice ID were not configured.
Native Tauri compilation still requires Visual Studio C++ Build Tools and the
Windows SDK on this host. Hardware microphone/playback and mutating desktop actions
were not exercised; the bridge self-check is deliberately read-only. The mock
desktop performs no OS actions.

This host marks editable-install path files hidden; the repo-local run.py launcher
avoids that environmental issue. Initial test fixtures and a tool argument naming
collision were fixed before the passing run.
