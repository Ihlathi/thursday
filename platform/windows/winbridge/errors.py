"""Structured bridge errors.

Every failure Core sees is a schema-valid Error `{code, message, retryable}`.
Codes match `^[A-Za-z0-9_-]{1,100}$`. Unsupported work returns an explicit
error rather than fake success, per `docs/contracts.md`.
"""

from __future__ import annotations


class BridgeError(Exception):
    """Carries a Core-visible error code. Message must not embed UI text verbatim."""

    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def as_error(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


def unsupported_tool(name: str) -> BridgeError:
    # Name is echoed for debuggability; it is constrained by the shared enum.
    return BridgeError("unsupported_tool", f"Tool not supported by the Windows bridge: {name}")


def stale_target(detail: str = "Desktop revision changed") -> BridgeError:
    return BridgeError("stale_target", detail, retryable=False)


def element_not_found(element_id: str) -> BridgeError:
    return BridgeError("element_not_found", f"Element {element_id} is no longer present", retryable=False)


def backend_unavailable(detail: str) -> BridgeError:
    return BridgeError("backend_unavailable", detail, retryable=False)


def cancelled() -> BridgeError:
    return BridgeError("cancelled", "Operation cancelled before execution", retryable=False)


def session_locked() -> BridgeError:
    return BridgeError("session_locked", "The workstation is locked; refusing to act", retryable=True)
