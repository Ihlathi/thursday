"""Windows platform bridge implementation.

Implements the `WindowsBridge` protocol in `../bridge_contract.py`: receives one
ToolCall at a time from Core over the loopback WebSocket, executes exactly one
OS operation, and returns a matching ToolResult plus an authoritative StateDelta.

Mechanism order, per `../README.md`: UI Automation first, direct Windows APIs
next, mouse/keyboard and screenshots last. All Windows-specific imports live in
this package so Core, the UI and the mock bridge keep working without Windows.
"""

__all__ = ["executor", "session", "guards", "classify", "errors"]
