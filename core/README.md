# Python Core

Use the repository root instructions. `python run.py demo --mode mock` works without
Tauri, Windows or API keys; `python run.py serve --mode gemini` accepts UI and bridge
connections. The repo-local launcher also avoids environments that suppress Python
editable-install .pth files. `pip install -e '.[dev]'` remains the dependency setup.

Modules: contracts loads shared schemas; providers isolates Gemini/ElevenLabs;
engine runs tasks; policy owns authorization; memory owns conversation preferences;
world owns structured desktop state and ephemeral search; transport/server own IPC.
The Core is OS independent. Add platform behavior to an adapter, not this package.

Schema discovery defaults to the monorepo `shared/` directory. AGENT_SHARED_DIR may
point to that same contract directory in packaged deployments. This hackathon repo
is run from source; a standalone wheel with bundled schemas is not a release target.
