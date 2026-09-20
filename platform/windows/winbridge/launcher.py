"""Launching apps, URLs, files and folders -- always from validated input.

Every entry point here receives a value that `guards` has already accepted, and
launches it without building a command line: allowlisted executables run from
%SystemRoot%\\System32 with no arguments, protocol URIs are fixed strings this
module owns, and files/folders go through the shell association API rather than
any interpreter. There is no code path that executes a caller-supplied string.
"""

from __future__ import annotations

import os
import subprocess
import webbrowser

from .errors import BridgeError, backend_unavailable


def open_app(spec: dict[str, str]) -> str:
    """Launches an allowlisted app. `spec` comes from guards.resolve_app."""
    kind, target = spec.get("kind"), spec.get("target", "")
    if kind == "exe":
        path = _system32(target)
        # No arguments are ever appended: argv is exactly [executable].
        subprocess.Popen([path], shell=False, close_fds=True)
        return path
    if kind == "uri":
        _startfile(target)
        return target
    raise BridgeError("unsupported_app", "Unrecognised launch specification", retryable=False)


def open_url(url: str) -> None:
    """Opens a guards-validated http/https URL in the user's default browser."""
    if not webbrowser.open(url, new=2):
        raise backend_unavailable("No browser is available to open the URL")


def open_path(path: str) -> None:
    """Opens a guards-validated file or folder via its shell association."""
    _startfile(path)


def _system32(executable: str) -> str:
    root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT") or "C:\\Windows"
    path = os.path.join(root, "System32", executable)
    if not os.path.isfile(path):
        raise BridgeError("unsupported_app", f"{executable} is not present on this system", retryable=False)
    return path


def _startfile(target: str) -> None:
    starter = getattr(os, "startfile", None)
    if starter is None:  # pragma: no cover - non-Windows
        raise backend_unavailable("Shell association launching is only available on Windows")
    try:
        starter(target)
    except OSError as exc:
        raise backend_unavailable(f"Windows refused to open the target: {exc}") from exc
