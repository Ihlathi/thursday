# Shipping this at the hackathon

Written for the last few hours before judging. Two questions: what do we hand
someone, and what do we do on stage.

## What we ship

**A built app plus a launcher, not an installer.** The UI is a real Tauri
release binary (`apps/ui/src-tauri/target/release/jarvis.exe`, single native
executable, no dev server, starts in about a second). Core and the Windows
bridge stay as Python running from the repo's `.venv`. `START-JARVIS.bat` ties
them together, and `run.py desktop` picks the release binary automatically
whenever it exists, falling back to `tauri dev` while we are still editing the
interface.

```
START-JARVIS.bat          real control, live provider if a key is saved
START-JARVIS.bat mock     offline: no OS action, no cloud call
```

That is the whole install story: clone, double-click, tray icon appears.

### Why not a single .exe

Bundling Core and the bridge into one executable means PyInstaller over
`comtypes`, `uiautomation`, `pycaw` and `wmi`. Those generate COM type-library
caches at runtime and are the classic PyInstaller failure — it either works in
twenty minutes or eats the rest of the night, and we would find out which at
4 a.m. The release UI binary gets us most of the polish (no console windows, no
Vite banner, instant start) for a ten-minute compile we can verify.

Keep the one-file bundle as the first task after the hackathon:
`pyinstaller --onefile` for Core, a second for the bridge, both declared as
Tauri `externalBin` sidecars, then `npm run tauri build --bundles nsis` emits a
genuine Windows installer. The code is already arranged for it — Core and the
bridge are separate processes talking over a documented socket, so they become
sidecars without touching the protocol.

### Judge-proof checklist

* Build the release binary and **run it once from a cold start** before judging.
  A build that has never been launched is not a build.
* Save the Gemini key through the settings pane on the demo machine, so the
  first thing judges see is not a configuration error.
* Know the machine: the bridge reads the real desktop, so rehearse on the laptop
  that will be on the table, not a different one.
* `START-JARVIS.bat mock` is the fallback if the venue network dies. It is
  honest — the UI says "mock, no cloud calls" — and everything except the
  reasoning is still real.

## The demo

Five minutes, in this order. The point is not that it talks; it is that it
*acts*, and that it stops when told to.

1. **Cold start.** Double-click the launcher. Tray icon appears. Nothing else
   on screen — that is the pitch: it lives out of the way.
2. **Settings (30 seconds).** Right-click the tray → Settings. Paste the Gemini
   key. The pane says "Saved. Live Gemini is active." Say the line: *the UI
   process is never given the key — it asks Core to store it and is only told
   whether one exists.* Judges notice when a team has thought about this.
3. **Ask it something about the machine.** Ctrl+Alt+J, then "what window am I
   in and what's my battery?" It answers from UI Automation and WMI — no
   screenshot, no pixel guessing. Point at the activity list showing
   `get_system_state`.
4. **Make it do something.** "Set my volume to 30 percent." The volume changes.
   This is the moment the demo lands.
5. **Then tell it no.** Ask for something consequential, and *deny* the
   confirmation. It stops, says so, and does not look for another route. The
   policy layer is independent of the model and the model's own risk opinion is
   never trusted — that is the strongest thing we built, and it only reads as
   strong if a judge watches it refuse.
6. **If asked about accessibility**, the overlay is keyboard-driven, reports
   status through `aria-live`, respects `prefers-reduced-motion`, and every
   confirmation states the action, consequence, risk and expiry in words.

Things to say out loud, because they are true and unusual:

* Direct APIs and accessibility first; screenshots are last, require consent,
  and cannot be taken until cheaper observation has been tried.
* The model gets one tool per turn and must observe the result before acting
  again; it cannot claim success without evidence.
* Arbitrary shell execution is reviewed and refused by construction.

Things not to claim: it is a prototype, UIA behaviour varies per application,
voice is recorded-then-sent rather than streaming, and macOS does not exist yet.
Saying so first is better than a judge finding it.
