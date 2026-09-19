# Verification record — 2026-09-19

Tested locally with Python 3.14.7; supported minimum is Python 3.11.

- `python -m pytest -q`: **24 passed**. One upstream google-genai warning about a
  Python typing alias scheduled for removal in Python 3.17; no test failures.
- `python run.py demo --mode mock`: completed the retrieval/direct invocation demo.
- `python run.py stack`: completed the authenticated real WebSocket vertical slice.
- Separate `serve --mode mock`, `mock-platform`, and `mock-ui` processes completed
  the same task over authenticated WebSockets on a test port.
- `npm run build` from `apps/ui`: production frontend build passed (Vite 6.4.3).
- `git diff --cached --check`: passed; staged paths and common secret patterns checked.

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
Native Tauri compilation, actual Windows UI Automation, hardware microphone/playback,
and real desktop action safety require teammate integration testing. The UI frontend
build does not verify the native Tauri shell. The mock desktop performs no OS actions.

This host marks editable-install path files hidden; the repo-local run.py launcher
avoids that environmental issue. Initial test fixtures and a tool argument naming
collision were fixed before the passing run.
