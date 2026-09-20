"""Simulated mouse/keyboard -- the last execution tier before screenshots.

Used for the catalog's explicitly coordinate-based tools (move_mouse, click,
type_text, press_key) and for `invoke_ui` in `visible` mode, where the pointer
is animated so the user can see what is being operated. Visible mode still
re-verifies the same semantic target immediately before activation; the pointer
movement is presentation, never the thing that decides what gets clicked.
"""

from __future__ import annotations

from .errors import backend_unavailable

try:
    import uiautomation as auto
except ImportError:  # pragma: no cover - Windows only
    auto = None

_MODIFIERS = {
    "ctrl": "Ctrl", "control": "Ctrl",
    "alt": "Alt",
    "shift": "Shift",
    "win": "Win", "windows": "Win", "super": "Win", "cmd": "Win",
}

_NAMED_KEYS = {
    "enter": "Enter", "return": "Enter",
    "tab": "Tab",
    "esc": "Esc", "escape": "Esc",
    "space": "Space",
    "delete": "Delete", "del": "Delete",
    "backspace": "Backspace",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "home": "Home", "end": "End",
    "pageup": "PageUp", "pagedown": "PageDown",
    "insert": "Insert",
    **{f"f{i}": f"F{i}" for i in range(1, 13)},
}


def _require():
    if auto is None:
        raise backend_unavailable("uiautomation is not installed (Windows-only bridge)")
    return auto


def to_send_keys(key: str) -> str:
    """Translates "ctrl+shift+s" / "Enter" into uiautomation's SendKeys syntax."""
    parts = [p.strip() for p in (key or "").replace("-", "+").split("+") if p.strip()]
    if not parts:
        raise backend_unavailable("Empty key sequence")
    *modifiers, last = parts
    rendered = _NAMED_KEYS.get(last.lower())
    rendered = f"{{{rendered}}}" if rendered else last
    if not modifiers:
        return rendered
    prefix = "".join(f"{{{_MODIFIERS.get(m.lower(), m)}}}" for m in modifiers)
    return f"{prefix}({rendered})"


def move_mouse(x: int, y: int) -> None:
    _require().SetCursorPos(int(x), int(y))


def glide_to(x: int, y: int, seconds: float = 0.35) -> None:
    """Animated pointer move for visible demonstration mode."""
    api = _require()
    try:
        api.MoveTo(int(x), int(y), moveSpeed=1.0, waitTime=seconds)
    except Exception:  # noqa: BLE001 - fall back to an instant move
        api.SetCursorPos(int(x), int(y))


def click(x: int, y: int) -> None:
    _require().Click(int(x), int(y))


def type_text(text: str) -> None:
    # Literal text: escape uiautomation's special characters so user content is
    # never reinterpreted as a key sequence.
    api = _require()
    api.SendKeys(_escape_literal(text), waitTime=0)


def press_key(key: str) -> None:
    api = _require()
    api.SendKeys(to_send_keys(key), waitTime=0)


def _escape_literal(text: str) -> str:
    out = []
    for ch in text:
        if ch in "{}()+^%~":
            out.append("{" + ch + "}")
        else:
            out.append(ch)
    return "".join(out)
