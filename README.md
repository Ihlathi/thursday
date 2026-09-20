# Adaptive Computer Accessibility Agent

A hackathon monorepo for operating and troubleshooting Windows through natural
intent. It includes a Python Core, a Tauri 2 accessibility overlay and a Windows
UI Automation bridge. macOS is future work. Prefer direct APIs and accessibility
over screenshot/mouse control.

## Quick start — offline, no API keys

Python 3.11+; commands run from repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python run.py demo --mode mock
python run.py stack
pytest -q
```

On Windows PowerShell use `py -3 -m venv .venv` and
`.venv\Scripts\Activate.ps1` instead of the first two commands.

For the integrated Windows desktop in development, install the Python Windows
extra plus the UI dependencies and use the trusted launcher:

```powershell
python -m pip install -e ".[dev,windows]"
cd apps\ui; npm install; cd ..\..
python run.py desktop --mode gemini
```

The launcher creates fresh private UI/platform tokens, gives each child only the
credentials it needs, starts Core and the Windows bridge, and opens the Tauri UI.
Use `Ctrl+Alt+J` to show it. Use `--mode mock --platform mock` for a safe UI demo
that performs no real OS or cloud actions.

`demo` runs Core against an in-process fake desktop. `mocks.stack` starts real local
WebSockets with Core, mock platform and mock UI, authenticates both roles, executes
several tool steps and prints correlated events. Both show “stuff I bought recently”
retrieving and opening “Returns & Orders.” Mock output is labeled; no real OS action
or cloud call occurs. Non-interactive harnesses deny confirmations.

## Separate processes for teammates

Create two distinct private random tokens (for example, `python -c "import secrets;
print(secrets.token_urlsafe(32))"` twice). Set them in the Core environment; give only
the appropriate local token to each client. Do not commit tokens or put them in URLs.

```sh
export AGENT_UI_TOKEN='<first-generated-token>'
export AGENT_PLATFORM_TOKEN='<second-generated-token>'
python run.py serve --mode mock
# Terminal 2: set AGENT_PLATFORM_TOKEN to the same bridge token
python run.py mock-platform
# Terminal 3: set AGENT_UI_TOKEN to the same UI token
python run.py mock-ui 'show me the stuff I bought recently' --interactive
```

Core: `ws://127.0.0.1:8765/v1/ui` and `/v1/platform`. The UI harness prints events;
`--interactive` enables deliberate yes/no confirmations. Configure `.env.example`
values in your launcher/shell; Core does not auto-load .env files.

For live reasoning, set GEMINI_API_KEY only in Core and use `--mode gemini`.
The verified default is `gemini-3.8-flash`, configurable via GEMINI_MODEL. Optional
ElevenLabs STT/TTS needs its key and voice ID. No live provider claim is made by the
offline tests. See [provider setup](docs/providers.md).

## Layout and handoffs

| Directory | Responsibility |
|---|---|
| `core/agent/` | Model loop, policy, context, memory, providers and transport |
| `shared/` | Canonical protocol schemas and tool catalog |
| `apps/ui/` | Tauri 2 accessible overlay and authenticated Core client |
| `platform/windows/` | Windows UIA/direct-API bridge and safety guards |
| `platform/macos/` | Future adapter placeholder |
| `mocks/` | Independent fake platform, UI harness and socket stack |
| `tests/` | Focused offline unit/provider/contract/WebSocket tests |
| `docs/` | Architecture, contracts, provider setup and team workflow |

Read [architecture](docs/architecture.md), [wire contracts](docs/contracts.md),
[team workflow](docs/team.md), [UI handoff](apps/ui/README.md), and
[Windows handoff](platform/windows/README.md).

## Honest boundaries

The integrated Windows build remains a prototype. The native bridge uses real
Windows operations, but UIA behavior varies by application and requires hands-on
testing on the target machine. Voice uses complete recordings rather than live
streaming, and macOS remains future work. The local vector baseline is
feature hashing with a small synonym map, not a pretrained embedding model. Memory
promotion covers explicit accessibility preferences and opt-in task/context notes. Arbitrary
shell commands are review-only; execution is disabled. Local auth protects against
untrusted clients, not malware with the same user privileges. Desktop actions can
race state changes: the real bridge must revalidate targets when dispatching.

`requirements-verified.txt` records the directly tested Python dependency versions.
The root `run.py` launcher avoids dependence on editable-install path files, including
macOS environments that mark those files hidden. This repository runs from source.
