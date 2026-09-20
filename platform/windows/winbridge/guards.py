"""Independent validation of every launch/settings parameter.

The bridge never trusts a tool name, a model-supplied string or UI text to mean
an operation is safe (`../README.md`). Nothing here concatenates a shell
command: apps resolve through a fixed allowlist to a real executable path or a
registered protocol handler, and settings resolve to direct APIs.

This module deliberately has no Windows imports so it can be unit-tested on any
OS -- the security boundary is the part that most needs tests.
"""

from __future__ import annotations

import os
from pathlib import PurePath, PureWindowsPath
from urllib.parse import urlparse

from .errors import BridgeError

# Only schemes that cannot, by themselves, execute local content.
ALLOWED_URL_SCHEMES = ("http", "https")

# Extensions that execute (directly or via a script host) when opened by shell
# association. open_file refuses these outright rather than classifying them.
EXECUTABLE_SUFFIXES = {
    ".exe", ".com", ".scr", ".pif", ".bat", ".cmd", ".msi", ".msp", ".msc",
    ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".hta",
    ".cpl", ".reg", ".lnk", ".url", ".jar", ".appref-ms", ".gadget", ".inf",
    ".dll", ".sys", ".add", ".application",
}

# Friendly name -> launch spec. `exe` entries resolve inside %SystemRoot%\System32
# only; `uri` entries are fixed, bridge-authored protocol strings, never user text.
# A shell/terminal is intentionally absent: this build has no arbitrary command
# execution path, and `propose_command` stays Core-only and non-executing.
APP_ALLOWLIST: dict[str, dict[str, str]] = {
    "notepad": {"kind": "exe", "target": "notepad.exe"},
    "calculator": {"kind": "uri", "target": "calculator:"},
    "calc": {"kind": "uri", "target": "calculator:"},
    "settings": {"kind": "uri", "target": "ms-settings:"},
    "file explorer": {"kind": "exe", "target": "explorer.exe"},
    "explorer": {"kind": "exe", "target": "explorer.exe"},
    "files": {"kind": "exe", "target": "explorer.exe"},
    "paint": {"kind": "exe", "target": "mspaint.exe"},
    "snipping tool": {"kind": "uri", "target": "ms-screenclip:"},
    "camera": {"kind": "uri", "target": "microsoft.windows.camera:"},
    "edge": {"kind": "uri", "target": "microsoft-edge:"},
    "microsoft edge": {"kind": "uri", "target": "microsoft-edge:"},
    "magnifier": {"kind": "exe", "target": "magnify.exe"},
    "narrator": {"kind": "exe", "target": "narrator.exe"},
    "on-screen keyboard": {"kind": "exe", "target": "osk.exe"},
}

# set_setting is SECURITY_SENSITIVE in the catalog, so the bridge accepts only
# settings it can map to a direct API with a validated value.
SETTING_SPECS: dict[str, dict] = {
    "brightness": {"type": "int", "min": 0, "max": 100},
    "volume": {"type": "int", "min": 0, "max": 100},
    "mute": {"type": "bool"},
}


def validate_url(url: str) -> str:
    """Accepts only http/https with a real host and no embedded credentials."""
    candidate = (url or "").strip()
    if not candidate or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in candidate):
        raise BridgeError("unsafe_url", "URL is empty or contains control characters")

    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in ALLOWED_URL_SCHEMES:
        raise BridgeError(
            "unsafe_url",
            f"Only {'/'.join(ALLOWED_URL_SCHEMES)} URLs may be opened; refused scheme '{parsed.scheme or 'none'}'",
        )
    if not parsed.netloc:
        raise BridgeError("unsafe_url", "URL has no host")
    if "@" in parsed.netloc:
        raise BridgeError("unsafe_url", "URL embeds credentials")
    return candidate


def _windows_path_checks(raw: str) -> None:
    if not raw or any(ord(ch) < 0x20 for ch in raw):
        raise BridgeError("unsafe_path", "Path is empty or contains control characters")
    win = PureWindowsPath(raw)
    # UNC (\\server\share) reaches off-machine; this bridge is local-only.
    if raw.startswith("\\\\") or raw.startswith("//"):
        raise BridgeError("unsafe_path", "UNC network paths are not allowed")
    # "file.txt:stream" selects an NTFS alternate data stream.
    tail = win.name
    if ":" in tail:
        raise BridgeError("unsafe_path", "Alternate data streams are not allowed")


def _reject_system_locations(resolved: PurePath) -> None:
    system_root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT")
    if not system_root:
        return
    try:
        root = PureWindowsPath(system_root).as_posix().lower()
        target = PureWindowsPath(str(resolved)).as_posix().lower()
    except Exception:  # noqa: BLE001 - best-effort comparison only
        return
    if target == root or target.startswith(root.rstrip("/") + "/"):
        raise BridgeError("unsafe_path", "Paths inside the Windows system directory are not allowed")


def validate_file_path(raw: str, *, exists=os.path.exists, isfile=os.path.isfile, realpath=os.path.realpath) -> str:
    """Resolves a file path and refuses executable/script content and system locations.

    Filesystem probes are injected so this stays testable off-Windows.
    """
    _windows_path_checks(raw)
    resolved = realpath(os.path.expandvars(os.path.expanduser(raw)))
    if not exists(resolved):
        raise BridgeError("unsafe_path", "Path does not exist")
    if not isfile(resolved):
        raise BridgeError("unsafe_path", "Path is not a file")
    if PureWindowsPath(resolved).suffix.lower() in EXECUTABLE_SUFFIXES:
        raise BridgeError("unsafe_path", "Refusing to open executable or script content")
    _reject_system_locations(PureWindowsPath(resolved))
    return resolved


def validate_folder_path(raw: str, *, exists=os.path.exists, isdir=os.path.isdir, realpath=os.path.realpath) -> str:
    _windows_path_checks(raw)
    resolved = realpath(os.path.expandvars(os.path.expanduser(raw)))
    if not exists(resolved):
        raise BridgeError("unsafe_path", "Path does not exist")
    if not isdir(resolved):
        raise BridgeError("unsafe_path", "Path is not a folder")
    _reject_system_locations(PureWindowsPath(resolved))
    return resolved


def resolve_app(name: str) -> dict[str, str]:
    """Maps a friendly app name to a fixed launch spec, or refuses.

    Anything outside the allowlist is an explicit `unsupported_app` error --
    never a best-effort attempt to run the string the model supplied.
    """
    key = (name or "").strip().lower()
    spec = APP_ALLOWLIST.get(key)
    if spec is None:
        raise BridgeError(
            "unsupported_app",
            f"'{name}' is not in the bridge's launch allowlist",
        )
    return dict(spec)


def validate_setting(setting: str, value) -> tuple[str, object]:
    """Validates a set_setting pair against the allowlist and coerces the value."""
    key = (setting or "").strip().lower()
    spec = SETTING_SPECS.get(key)
    if spec is None:
        raise BridgeError("unsupported_setting", f"Setting '{setting}' is not supported by this bridge")

    if spec["type"] == "bool":
        if not isinstance(value, bool):
            raise BridgeError("invalid_arguments", f"Setting '{key}' expects a boolean")
        return key, value

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BridgeError("invalid_arguments", f"Setting '{key}' expects a number")
    number = int(value)
    if number != value or not (spec["min"] <= number <= spec["max"]):
        raise BridgeError(
            "invalid_arguments",
            f"Setting '{key}' expects an integer between {spec['min']} and {spec['max']}",
        )
    return key, number
