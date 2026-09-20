# Windows bridge — implementation notes

Implements the handoff in `README.md` and the `WindowsBridge` protocol in
`bridge_contract.py`. `README.md` is the spec; this file records what is built,
what is deliberately refused, and where the seams are.

## Running it

```powershell
pip install -r platform/windows/requirements.txt     # or: pip install -e ".[windows]"

python platform/windows/bridge.py --self-check       # read-only probe, no Core needed
python run.py                                        # terminal 1: Core
python run.py windows-platform                       # terminal 2: this bridge
```

`--self-check` confirms UIA/WMI/pycaw actually work on the machine before Core
is involved. It reads only: nothing is clicked, typed or changed.

`AGENT_PLATFORM_TOKEN` must be set, same as `mocks/platform.py`.

## Layout

```
platform/windows/
  bridge.py            process entry: WebSocket client, COM worker thread, cancellation
  winbridge/
    executor.py         WindowsBridge: ToolCall -> ToolResult for all 17 platform tools
    session.py           world model: element IDs, revision, sleep_epoch, StateDelta
    guards.py             URL/path/app/setting allowlists  (no Windows imports)
    classify.py            action_kind + sensitive derivation (no Windows imports)
    errors.py               structured error codes
    uia.py                   UI Automation: snapshot, relocate, invoke/set/scroll
    system_api.py             WMI brightness, Core Audio volume/mute, battery, network
    rawinput.py                simulated mouse/keyboard, visible-mode pointer glide
    capture.py                  screenshots fitted to the protocol's base64 budget
    launcher.py                  app/URL/file/folder launching from validated input
tests/test_windows_bridge.py   26 tests, no Windows required
```

`guards.py`, `classify.py` and `session.py` have no Windows imports on purpose —
they hold the security and identity logic, which is the part most worth testing,
and they run in CI on any OS.

## Tool coverage

All 17 `owner=platform` tools are implemented. Core-owned tools (`search_ui`,
`inspect_ui`, `ask_user`, `request_confirmation`, `complete_task`,
`propose_command`) return `unsupported_tool` rather than executing.

| Tool | Mechanism |
|---|---|
| `get_system_state` | foreground window via UIA + lock probe; machine detail (brightness, audio incl. per-app sessions, battery, network) in `data.machine` |
| `get_ui_state` | UIA tree walk → full `StateDelta` snapshot |
| `invoke_ui` | UIA Invoke/Toggle/Select/Expand pattern; `visible` mode glides the pointer first |
| `set_ui_value` | UIA ValuePattern |
| `scroll` | UIA ScrollPattern, falling back to wheel events |
| `move_mouse`, `click`, `type_text`, `press_key` | simulated input (SendInput via `uiautomation`) |
| `inspect_screen`, `inspect_region` | `mss` capture, downscaled to fit the base64 cap |
| `open_app` | fixed allowlist → System32 executable (argv is exactly `[exe]`) or a bridge-owned protocol URI |
| `open_url` | http/https only → default browser |
| `open_file`, `open_folder` | validated path → shell association |
| `set_setting` | allowlist: brightness / volume / mute → direct APIs |
| `run_approved_action` | `set_volume` / `set_brightness`, integer 0..100 → direct APIs |

`data` is used as the protocol's extension object to carry machine detail that
`SystemState` has no fields for — that is what makes "why isn't my sound
working" answerable without a screenshot: the default endpoint's mute/volume and
every per-app session come back as structured data.

## Decisions worth knowing

**Ordering inside a mutating call.** Refuse core-owned/unknown tools → validate
the ToolCall against the shared schema (arguments included) → refuse if the
workstation is locked → re-locate the target in the live tree and re-observe it
→ check `expected_revision` → execute once → re-snapshot and return an
authoritative delta. The revision check happens immediately before execution,
never earlier, and re-location happens even in `visible` mode *after* the
pointer moves, since the screen can change during the trip.

**Element identity.** IDs come from the UIA RuntimeId where one exists, prefixed
with a generation counter that advances whenever the snapshot root (process +
window) changes. A RuntimeId that Windows later recycles therefore cannot
collide with an ID Core still holds. Elements are re-found by RuntimeId first,
then the recorded child-index path verified by name+role, then a bounded
name+role search — and the call is refused rather than acting on a weaker match.

**`action_kind` is conservative by construction.** It is derived only from
trusted UIA semantics (control type, `IsPassword`), never from an element's
display name, which any app or page can set. The practical consequence: nothing
is ever classified `navigation`, `submit` or `delete`, so Core confirms those.
That is intended. If per-app trusted semantics are added later (e.g. a known
browser's toolbar Back button by AutomationId), `classify.action_kind` is the
single place to extend, and it should stay driven by chrome-level facts rather
than page content.

**Sensitive values never leave the machine.** Password fields (`IsPassword`) and
fields whose names match secret-ish hints are marked `sensitive`, and their
values are absent from `description` entirely — not masked, not truncated.
Non-sensitive editable fields do include a short value preview, which is what
lets Core answer "what's in the search box" without a capture. `set_ui_value`
never echoes the written value back, since it may be a secret typed into a field
that isn't flagged.

**No arbitrary execution path exists.** `open_app` resolves a friendly name
through a fixed allowlist to either a System32 executable launched with no
arguments, or a protocol URI this module owns. Shells and interpreters
(`powershell`, `cmd`, `wt`, `python`) are absent from that allowlist
deliberately. `open_file` refuses executable and script extensions, UNC paths,
NTFS alternate data streams and the Windows directory. `set_setting` accepts
only brightness/volume/mute. Nothing concatenates a command string.

**Threading.** Every UIA call runs on one worker thread that owns the COM
apartment, so COM is never touched from two threads and the receive loop stays
free to process a `cancel` while a call is in flight.

**Cancellation.** A cancel flag is checked immediately before the committing
step; queued asyncio tasks are cancelled. A call already inside a COM operation
runs to completion — no rollback is claimed, and the bridge never replays a
mutating call after a timeout or disconnect.

**Session lifetime.** A fresh `Session` (revision + ID generation) is created per
connection, so a bridge restart cannot hand Core IDs minted against an older
view of the desktop.

## Testing

```powershell
python -m pytest tests/test_windows_bridge.py -q     # 26 tests, runs on any OS
```

Fake adapters stand in for UIA/WMI/pycaw, and every ToolResult is validated
against the repository's real `shared/protocol.schema.json`. Covered: schema
conformance, stale-revision refusal, target-drift refusal, locked-workstation
refusal, cancellation, ID stability across snapshots, generation change on
window change, conservative classification, sensitive-value suppression, and
each launch/settings allowlist.

What these tests cannot cover is the adapter layer itself — whether UIA really
returns what we expect from a given app. `bridge.py --self-check` is the probe
for that, and it needs real Windows.

## Known gaps

- **Brightness on external monitors.** WMI reaches the built-in/driver-backed
  display; monitors on DDC/CI need a different path and currently return a clear
  `backend_unavailable` rather than silently doing nothing.
- **`sleep_epoch` increments on a lock→unlock transition**, not on true
  suspend/resume, which would need `WM_POWERBROADCAST` and a message window.
- **Lock detection is conservative**: any failure to open the input desktop reads
  as locked, so the bridge refuses to act rather than acting blind. (This is also
  why the whole bridge refuses mutations when run off-Windows.)
- **Snapshots are full, not incremental.** The contract allows either;
  `removed_ids`-style atomic deltas would cut payload size if tree walks become
  a bottleneck. Element count is capped at 300 (`session.MAX_ELEMENTS`), depth at
  6 (`uia.MAX_DEPTH`).
- **In-page browser structure comes from UIA only.** Chromium exposes its
  accessibility tree natively to UIA, which is enough for links/buttons/fields.
  A Chrome DevTools Protocol path would give richer in-page structure but needs
  the browser launched with `--remote-debugging-port`, and there is no
  browser-specific tool in `shared/tools.json` to carry it, so it is not wired
  in. That would be a contract change first, not a bridge change.
