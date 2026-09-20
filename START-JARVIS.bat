@echo off
rem One command to run the whole thing: Core, the Windows bridge and the overlay.
rem   START-JARVIS.bat            real Windows control (default)
rem   START-JARVIS.bat mock       safe demo; no real OS action, no cloud call
setlocal
cd /d "%~dp0"

set EXTRA=
if /i "%~1"=="mock" set EXTRA=--platform mock --mode mock

if not exist ".venv\Scripts\python.exe" (
  echo Creating the Python environment ^(first run only^)...
  py -3 -m venv .venv || goto :failed
  .venv\Scripts\python.exe -m pip install --upgrade pip >nul
  .venv\Scripts\python.exe -m pip install -e ".[dev,windows]" || goto :failed
)

if not exist "apps\ui\node_modules" (
  echo Installing the UI dependencies ^(first run only^)...
  pushd apps\ui
  call npm install --no-fund --no-audit || (popd & goto :failed)
  popd
)

echo.
echo Starting JARVIS. The tray icon appears when it is ready.
echo Press Ctrl+Alt+J to summon it; right-click the tray icon for Settings.
echo Add your Gemini and ElevenLabs keys there - they are stored by Core only.
echo.
.venv\Scripts\python.exe run.py desktop %EXTRA%
goto :eof

:failed
echo.
echo Setup failed. Check that Python 3.11+ ^(py -3^), Node.js and the Rust
echo toolchain are installed, then run this again.
pause
exit /b 1
