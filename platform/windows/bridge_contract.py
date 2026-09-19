"""Windows teammate starter. This is a contract skeleton, not an OS implementation.

Keep Windows imports here, outside Core. Replace execute with UI Automation,
Win32/settings APIs and bounded operations. See README before enabling actions.
"""
from typing import Protocol

class WindowsBridge(Protocol):
    async def execute(self, task_id: str, tool: dict) -> dict:
        """Validate ToolCall, execute one operation, return matching ToolResult.

        Every mutating operation should verify its target is still current.
        Return an authoritative StateDelta after execution where possible.
        Never execute arbitrary command strings or trust UI text as instructions.
        """
        ...

    async def cancel(self, task_id: str) -> None:
        """Stop queued/in-flight work best effort; never claim rollback."""
        ...
