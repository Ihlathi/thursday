"""UI Automation adapter -- the bridge's primary observation and execution path.

Produces plain `Observation` records for the session's world model and re-finds
live controls before every mutation. Re-finding matters: UIA trees can be
rebuilt between calls even when the screen looks unchanged, so a cached COM
reference is not evidence that the target is still what Core decided to act on.
`relocate` therefore re-walks and matches on RuntimeId first, then the recorded
child-index path, then name+role -- and refuses rather than guessing.

All COM work must happen on the single worker thread that called `com_init`.
"""

from __future__ import annotations

import ctypes
import os
from typing import Any, Optional

from .errors import BridgeError, backend_unavailable, element_not_found
from .session import Observation

try:
    import comtypes
    import uiautomation as auto
except ImportError:  # pragma: no cover - importable only on Windows with deps
    comtypes = None
    auto = None

MAX_DEPTH = 6
MAX_NODES = 300
RELOCATE_MAX_NODES = 2000


def available() -> bool:
    return auto is not None


def com_init() -> None:
    """Called once on the worker thread that owns every UIA call."""
    if comtypes is not None:
        comtypes.CoInitialize()


def _require():
    if auto is None:
        raise backend_unavailable("uiautomation/comtypes are not installed (Windows-only bridge)")
    return auto


# ---------------------------------------------------------------- system probes


def is_locked() -> bool:
    """True when the interactive desktop can't be opened, which is the locked case.

    Heuristic but conservative: any failure here reads as "locked", so the
    bridge refuses to act rather than acting blind.
    """
    try:
        user32 = ctypes.windll.user32
        handle = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
        if not handle:
            return True
        user32.CloseDesktop(handle)
        return False
    except Exception:  # noqa: BLE001
        return True


def process_name(pid: int) -> str:
    """Image name for a pid via Win32, avoiding a WMI round-trip per call."""
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            size = ctypes.c_uint32(512)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return os.path.basename(buffer.value)
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        pass
    return ""


def active_window() -> tuple[int, str, str]:
    """Returns (pid, window_title, app_name) for the foreground window."""
    api = _require()
    try:
        top = api.GetForegroundControl()
    except Exception as exc:  # noqa: BLE001
        raise backend_unavailable(f"Could not read the foreground window: {exc}") from exc
    if top is None:
        raise backend_unavailable("No foreground window is available")
    pid = int(getattr(top, "ProcessId", 0) or 0)
    return pid, (top.Name or "unknown"), (process_name(pid) or "unknown")


# ---------------------------------------------------------------- snapshot


def _runtime_id(control) -> Optional[tuple[int, ...]]:
    try:
        raw = control.GetRuntimeId()
        if raw:
            return tuple(int(part) for part in raw)
    except Exception:  # noqa: BLE001
        pass
    return None


def _value_of(control) -> Optional[str]:
    try:
        pattern = control.GetValuePattern()
        if pattern is not None:
            return pattern.Value
    except Exception:  # noqa: BLE001
        pass
    return None


def _is_password(control) -> bool:
    try:
        return bool(getattr(control, "IsPassword", False))
    except Exception:  # noqa: BLE001
        return False


def _bounds_of(control) -> dict[str, float]:
    try:
        rect = control.BoundingRectangle
        if rect is not None:
            width, height = rect.width(), rect.height()
            return {"x": float(rect.left), "y": float(rect.top), "width": float(max(0, width)), "height": float(max(0, height))}
    except Exception:  # noqa: BLE001
        pass
    return {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}


def _observe(control, path: list[int], parent_index: Optional[int]) -> Observation:
    role = ""
    try:
        role = control.ControlTypeName or ""
    except Exception:  # noqa: BLE001
        pass

    enabled, offscreen = True, False
    try:
        enabled = bool(control.IsEnabled)
    except Exception:  # noqa: BLE001
        pass
    try:
        offscreen = bool(control.IsOffscreen)
    except Exception:  # noqa: BLE001
        pass

    bounds = _bounds_of(control)
    is_password = _is_password(control)
    return Observation(
        role=role or "control",
        name=(getattr(control, "Name", "") or ""),
        bounds=bounds,
        enabled=enabled,
        visible=(not offscreen) and bounds["width"] > 0 and bounds["height"] > 0,
        pid=int(getattr(control, "ProcessId", 0) or 0),
        path=list(path),
        runtime_id=_runtime_id(control),
        automation_id=(getattr(control, "AutomationId", "") or ""),
        help_text=(getattr(control, "HelpText", "") or "")[:200],
        is_password=is_password,
        # Value is captured here but `classify.describe` decides whether any of
        # it may be emitted; sensitive controls contribute none of it.
        value=None if is_password else _value_of(control),
        parent_index=parent_index,
        children_indices=[],
    )


def snapshot(max_depth: int = MAX_DEPTH, max_nodes: int = MAX_NODES) -> tuple[list[Observation], tuple[int, str]]:
    """Walks the foreground window and returns (observations, root_key)."""
    api = _require()
    try:
        root = api.GetForegroundControl()
    except Exception as exc:  # noqa: BLE001
        raise backend_unavailable(f"Could not read the foreground window: {exc}") from exc
    if root is None:
        raise backend_unavailable("No foreground window is available")

    observations: list[Observation] = []
    root_key = (int(getattr(root, "ProcessId", 0) or 0), root.Name or "")

    def walk(control, depth: int, path: list[int], parent_index: Optional[int]) -> None:
        if len(observations) >= max_nodes:
            return
        index = len(observations)
        observations.append(_observe(control, path, parent_index))
        if depth >= max_depth:
            return
        try:
            children = control.GetChildren()
        except Exception:  # noqa: BLE001
            children = []
        for position, child in enumerate(children):
            if len(observations) >= max_nodes:
                return
            observations[index].children_indices.append(len(observations))
            walk(child, depth + 1, path + [position], index)

    walk(root, 0, [], None)
    return observations, root_key


# ---------------------------------------------------------------- relocation


def relocate(observation: Observation):
    """Re-finds the live control for a previously observed element, or refuses.

    Tried in order of how much the match proves: RuntimeId (identity), the
    recorded child-index path verified by name+role, then a bounded name+role
    search. Anything less certain raises rather than acting on a guess.
    """
    api = _require()
    try:
        root = api.GetForegroundControl()
    except Exception as exc:  # noqa: BLE001
        raise backend_unavailable(f"Could not read the foreground window: {exc}") from exc
    if root is None:
        raise backend_unavailable("No foreground window is available")

    if observation.runtime_id:
        found = _find_by_runtime_id(root, observation.runtime_id)
        if found is not None:
            return found

    walker = root
    for position in observation.path:
        try:
            children = walker.GetChildren()
        except Exception:  # noqa: BLE001
            children = []
        if position >= len(children):
            walker = None
            break
        walker = children[position]
    if walker is not None and _matches(walker, observation):
        return walker

    found = _find_by_identity(root, observation)
    if found is not None:
        return found
    raise element_not_found(observation.name or observation.role)


def _matches(control, observation: Observation) -> bool:
    try:
        return (control.Name or "") == observation.name and (control.ControlTypeName or "") == observation.role
    except Exception:  # noqa: BLE001
        return False


def _find_by_runtime_id(root, runtime_id: tuple[int, ...]):
    visited = 0

    def walk(control):
        nonlocal visited
        if visited >= RELOCATE_MAX_NODES:
            return None
        visited += 1
        if _runtime_id(control) == runtime_id:
            return control
        try:
            children = control.GetChildren()
        except Exception:  # noqa: BLE001
            return None
        for child in children:
            hit = walk(child)
            if hit is not None:
                return hit
        return None

    return walk(root)


def _find_by_identity(root, observation: Observation):
    visited = 0

    def walk(control):
        nonlocal visited
        if visited >= RELOCATE_MAX_NODES:
            return None
        visited += 1
        if _matches(control, observation):
            if observation.automation_id:
                if (getattr(control, "AutomationId", "") or "") != observation.automation_id:
                    pass  # same name+role but a different automation id: keep looking
                else:
                    return control
            else:
                return control
        try:
            children = control.GetChildren()
        except Exception:  # noqa: BLE001
            return None
        for child in children:
            hit = walk(child)
            if hit is not None:
                return hit
        return None

    return walk(root)


def observe_control(control, observation: Observation) -> Observation:
    """Re-observes a relocated control so checks run against live state, not cache."""
    return _observe(control, observation.path, observation.parent_index)


# ---------------------------------------------------------------- execution


def invoke(control) -> str:
    """Activates via a UIA control pattern. Returns the pattern used."""
    try:
        pattern = control.GetInvokePattern()
        if pattern is not None:
            pattern.Invoke()
            return "invoke"
    except Exception:  # noqa: BLE001
        pass
    try:
        pattern = control.GetTogglePattern()
        if pattern is not None:
            pattern.Toggle()
            return "toggle"
    except Exception:  # noqa: BLE001
        pass
    try:
        pattern = control.GetSelectionItemPattern()
        if pattern is not None:
            pattern.Select()
            return "select"
    except Exception:  # noqa: BLE001
        pass
    try:
        pattern = control.GetExpandCollapsePattern()
        if pattern is not None:
            pattern.Expand()
            return "expand"
    except Exception:  # noqa: BLE001
        pass
    raise BridgeError(
        "no_supported_pattern",
        "This control exposes no Invoke/Toggle/Select/Expand pattern",
        retryable=False,
    )


def set_value(control, value: str) -> None:
    try:
        pattern = control.GetValuePattern()
    except Exception:  # noqa: BLE001
        pattern = None
    if pattern is None:
        raise BridgeError("no_supported_pattern", "This control exposes no settable value", retryable=False)
    pattern.SetValue(value)


def scroll(control, direction: str, amount: int) -> None:
    api = _require()
    try:
        pattern = control.GetScrollPattern() if control is not None else None
    except Exception:  # noqa: BLE001
        pattern = None

    if pattern is None:
        target = control if control is not None else api.GetForegroundControl()
        if target is None:
            raise backend_unavailable("Nothing available to scroll")
        times = max(1, int(amount))
        if direction == "down":
            target.WheelDown(wheelTimes=times)
        elif direction == "up":
            target.WheelUp(wheelTimes=times)
        else:
            raise BridgeError("no_supported_pattern", f"No scroll pattern for direction '{direction}'", retryable=False)
        return

    none_amount = api.ScrollAmount.NoAmount
    increment = api.ScrollAmount.LargeIncrement
    decrement = api.ScrollAmount.LargeDecrement
    for _ in range(max(1, int(amount))):
        if direction == "down":
            pattern.Scroll(none_amount, increment)
        elif direction == "up":
            pattern.Scroll(none_amount, decrement)
        elif direction == "right":
            pattern.Scroll(increment, none_amount)
        elif direction == "left":
            pattern.Scroll(decrement, none_amount)
        else:
            raise BridgeError("invalid_arguments", f"Unknown scroll direction '{direction}'", retryable=False)


def center_of(control) -> tuple[int, int]:
    bounds = _bounds_of(control)
    return (
        int(bounds["x"] + bounds["width"] / 2),
        int(bounds["y"] + bounds["height"] / 2),
    )


def virtual_screen_bounds() -> dict[str, float]:
    """Union of all displays, used to bounds-check caller-supplied coordinates."""
    try:
        metrics = ctypes.windll.user32.GetSystemMetrics
        return {
            "x": float(metrics(76)),       # SM_XVIRTUALSCREEN
            "y": float(metrics(77)),        # SM_YVIRTUALSCREEN
            "width": float(metrics(78)),     # SM_CXVIRTUALSCREEN
            "height": float(metrics(79)),     # SM_CYVIRTUALSCREEN
        }
    except Exception as exc:  # noqa: BLE001
        raise backend_unavailable(f"Could not read display metrics: {exc}") from exc
