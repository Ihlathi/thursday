"""Trusted development launcher for Core, one platform bridge and the Tauri UI."""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROVIDER_KEYS = ("GEMINI_API_KEY", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID")


def load_env_file(path: Path, base: dict[str, str]) -> list[str]:
    """Seed the launcher's own environment from .env, without overriding a real
    environment variable. Core still never reads files like this itself; keys
    saved from the tray live in .agent-data/settings.json instead."""
    loaded: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return loaded
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if not name or not value or name in base:
            continue
        base[name] = value
        loaded.append(name)
    return loaded


def _without(environment: dict[str, str], *names: str) -> dict[str, str]:
    result = environment.copy()
    for name in names:
        result.pop(name, None)
    return result


def child_environments(
    base: dict[str, str], ui_token: str, platform_token: str, port: int
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Return least-privilege environments for Core, bridge and UI."""
    core = base | {
        "AGENT_UI_TOKEN": ui_token,
        "AGENT_PLATFORM_TOKEN": platform_token,
        "AGENT_DATA_DIR": str(REPO_ROOT / ".agent-data"),
    }
    platform = _without(base, "AGENT_UI_TOKEN", *PROVIDER_KEYS) | {
        "AGENT_PLATFORM_TOKEN": platform_token,
    }
    ui = _without(base, "AGENT_PLATFORM_TOKEN", *PROVIDER_KEYS) | {
        "AGENT_UI_TOKEN": ui_token,
        "AGENT_UI_URL": f"ws://127.0.0.1:{port}/v1/ui",
    }
    return core, platform, ui


def _wait_for_port(process: subprocess.Popen, port: int, timeout: float = 12) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Core exited with status {process.returncode} before becoming ready.")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"Core did not start on port {port} within {timeout:g} seconds.")


def _stop(processes: list[subprocess.Popen]) -> None:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    for process in reversed(processes):
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def _package_manager() -> str:
    for name in ("npm", "npm.cmd", "pnpm", "pnpm.cmd"):
        executable = shutil.which(name)
        if executable:
            return executable
    raise RuntimeError("npm or pnpm is required to start the Tauri desktop UI.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the complete desktop accessibility agent")
    parser.add_argument("--mode", choices=("mock", "gemini"), default=None,
                        help="Pin the provider; omit to follow the keys saved in Settings")
    parser.add_argument("--platform", choices=("windows", "mock"), default="windows")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.platform == "windows" and sys.platform != "win32":
        parser.error("The Windows bridge can only run on Windows; use --platform mock elsewhere.")

    ui_token = secrets.token_urlsafe(32)
    platform_token = secrets.token_urlsafe(32)
    base = os.environ.copy()
    loaded = load_env_file(REPO_ROOT / ".env", base)
    if loaded:
        print("Seeded from .env: " + ", ".join(loaded), flush=True)
    core_environment, platform_environment, ui_environment = child_environments(
        base, ui_token, platform_token, args.port
    )

    python = sys.executable
    launcher = str(REPO_ROOT / "run.py")
    processes: list[subprocess.Popen] = []
    try:
        serve_command = [python, launcher, "serve", "--port", str(args.port)]
        if args.mode:
            serve_command += ["--mode", args.mode]
        core = subprocess.Popen(
            serve_command,
            cwd=REPO_ROOT,
            env=core_environment,
        )
        processes.append(core)
        _wait_for_port(core, args.port)

        platform_command = "windows-platform" if args.platform == "windows" else "mock-platform"
        platform = subprocess.Popen(
            [
                python,
                launcher,
                platform_command,
                "--url",
                f"ws://127.0.0.1:{args.port}/v1/platform",
            ],
            cwd=REPO_ROOT,
            env=platform_environment,
        )
        processes.append(platform)

        package_manager = _package_manager()
        print("Starting JARVIS. Press Ctrl+Alt+J to open it, or use the tray icon.", flush=True)
        ui = subprocess.Popen(
            [package_manager, "run", "tauri", "dev"],
            cwd=REPO_ROOT / "apps" / "ui",
            env=ui_environment,
        )
        processes.append(ui)
        exit_code = ui.wait()
        if exit_code:
            raise RuntimeError(f"The desktop UI exited with status {exit_code}.")
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError) as error:
        parser.error(str(error))
    finally:
        _stop(processes)


if __name__ == "__main__":
    main()
