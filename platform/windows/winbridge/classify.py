"""Classification metadata -- a security boundary, not a convenience field.

`../README.md`: "action_kind=navigation ONLY for known navigation operations,
never arbitrary buttons, page-provided labels or submit links. Unknown targets
must be unknown." So this module derives classification *only* from trusted UIA
adapter semantics (control type, IsPassword), never from an element's display
name, which any page or app can set to anything.

Consequence of that rule as implemented here: nothing is ever classified
`navigation`, `submit` or `delete` from a generic control, so Core conservatively
confirms those. That is the intended, safe default -- see IMPLEMENTATION.md for
the extension point if trusted per-app semantics are added later.
"""

from __future__ import annotations

# UIA control types whose editability is a trusted structural fact.
EDITABLE_ROLES = {
    "EditControl",
    "DocumentControl",
    "ComboBoxControl",
    "SpinnerControl",
}

# Name hints only ever *raise* sensitivity, never lower it, and never grant a
# more permissive action_kind. A page lying in this direction can only make the
# bridge more cautious.
SENSITIVE_NAME_HINTS = (
    "password", "passcode", "passphrase", "pin", "cvv", "cvc", "security code",
    "ssn", "social security", "credit card", "card number", "account number",
    "secret", "api key", "token", "otp", "one-time code", "verification code",
)

MAX_DESCRIPTION = 2048
MAX_VALUE_PREVIEW = 120


def is_sensitive(role: str, name: str, is_password: bool) -> bool:
    if is_password:
        return True
    haystack = (name or "").lower()
    return any(hint in haystack for hint in SENSITIVE_NAME_HINTS)


def action_kind(role: str, is_password: bool, sensitive: bool) -> str:
    """Returns one of the schema's action_kind values, conservatively."""
    if is_password:
        return "security"
    if role in EDITABLE_ROLES:
        # Editability comes from the UIA control type, which the app's
        # accessibility provider supplies -- not from on-screen text.
        return "security" if sensitive else "edit"
    return "unknown"


def describe(role: str, value: str | None, sensitive: bool, help_text: str = "") -> str:
    """Builds UIElement.description without ever leaking a secure value.

    A non-sensitive editable control includes a short preview of its current
    value, which is what lets Core answer "what's in the search box" without a
    screenshot. Sensitive controls contribute no value at all -- not truncated,
    not masked, simply absent.
    """
    parts: list[str] = [_role_phrase(role)]
    if help_text:
        parts.append(help_text.strip())
    if value and not sensitive:
        preview = " ".join(value.split())
        if len(preview) > MAX_VALUE_PREVIEW:
            preview = preview[: MAX_VALUE_PREVIEW - 1] + "…"
        if preview:
            parts.append(f"currently: {preview}")
    elif sensitive:
        parts.append("value hidden (sensitive field)")
    return " — ".join(p for p in parts if p)[:MAX_DESCRIPTION]


def _role_phrase(role: str) -> str:
    if not role:
        return "control"
    trimmed = role[:-7] if role.endswith("Control") else role
    spaced = "".join(f" {ch.lower()}" if ch.isupper() and i else ch.lower() for i, ch in enumerate(trimmed))
    return spaced.strip() or "control"
