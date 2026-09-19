# Team workflow

- Core owner: Python service, providers, policy, memory, tests. Run `pytest -q` and
  `python run.py stack` before changing protocol behavior.
- UI owner: `apps/ui/`, accessibility, capture/playback and human confirmations.
  Use mock AgentEvents before connecting to Core.
- Windows owner: `platform/windows/`, normalized UIA snapshots and direct tools.
  Use the Python mock bridge and shared fixtures as wire examples.
- Shared changes: propose schema + catalog + fixture + test changes in one PR;
  coordinate field/version changes with both teammate owners before merging.

Clone the shared private repository once published. Each teammate creates a short
feature branch (`git switch -c ui/voice`, `windows/uia`, `core/memory`), commits only
owned changes, pushes and opens a PR. Keep main runnable. Pull/rebase before merging;
never force-push main. Keys stay in Core process environment, never commits or UI.
Do not add screenshots/recordings, .env, tokens, SQLite data or debug logs to Git.

The mock stack needs no API key, OS SDK, Rust or Windows machine. A full Windows
end-to-end test is a later integration milestone once the bridge and UI are built.
