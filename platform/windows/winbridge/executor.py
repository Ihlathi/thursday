"""WindowsBridge implementation -- one ToolCall in, one ToolResult out.

Implements the Protocol in `../bridge_contract.py`. The ordering inside every
mutating call is the part that matters and is deliberate:

    1. refuse core-owned and unknown tools (never fake success)
    2. validate the ToolCall against the shared schema, arguments included
    3. refuse while the workstation is locked
    4. re-locate the target from the live tree and re-observe it
    5. check `expected_revision` immediately before execution, not earlier
    6. execute exactly one operation
    7. re-snapshot and return an authoritative StateDelta

Steps 4 and 5 are what stop a call that Core authorised against one screen from
landing on a different one. Adapters are injected so the whole flow can be
tested without Windows.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from agent.contracts import validate_def

from . import classify, guards
from .errors import BridgeError, backend_unavailable, cancelled, session_locked, unsupported_tool
from .session import Session

# Owned by Core per docs/contracts.md; the bridge must never execute them.
CORE_OWNED = {
    "search_ui", "inspect_ui", "ask_user",
    "request_confirmation", "complete_task", "propose_command",
}

# Operations after which the UI plausibly changed, so the bridge re-walks the
# tree to return an authoritative snapshot rather than a guess.
RESNAPSHOT_AFTER = {
    "open_app", "open_url", "open_file", "open_folder", "invoke_ui",
    "set_ui_value", "scroll", "click", "type_text", "press_key",
}

SETTLE_SECONDS = 0.25


@dataclass
class Adapters:
    """Injection seam: real Windows modules in production, fakes in tests."""

    uia: Any
    system: Any
    rawinput: Any
    capture: Any
    launcher: Any


def default_adapters() -> Adapters:
    from . import capture as capture_module
    from . import launcher as launcher_module
    from . import rawinput as rawinput_module
    from . import system_api as system_module
    from . import uia as uia_module

    return Adapters(
        uia=uia_module,
        system=system_module,
        rawinput=rawinput_module,
        capture=capture_module,
        launcher=launcher_module,
    )


class WindowsBridge:
    def __init__(
        self,
        adapters: Optional[Adapters] = None,
        session: Optional[Session] = None,
        runner: Optional[Callable] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.adapters = adapters or default_adapters()
        self.session = session or Session()
        self._runner = runner
        self._sleep = sleep
        self._cancelled: set[str] = set()

    # ---------------------------------------------------------------- protocol

    async def execute(self, task_id: str, tool: dict) -> dict:
        if self._runner is not None:
            return await self._runner(lambda: self.execute_sync(task_id, tool))
        return self.execute_sync(task_id, tool)

    async def cancel(self, task_id: str) -> None:
        """Best effort only: a call already inside a COM operation runs to completion."""
        self._cancelled.add(task_id)

    def clear_task(self, task_id: str) -> None:
        self._cancelled.discard(task_id)

    # ---------------------------------------------------------------- dispatch

    def execute_sync(self, task_id: str, tool: dict) -> dict:
        call_id = tool.get("call_id", "unknown")
        try:
            validate_def("ToolCall", tool)
        except Exception as exc:  # noqa: BLE001 - jsonschema error shape varies
            return self._failure(call_id, BridgeError(
                "invalid_arguments", f"ToolCall failed shared-schema validation: {str(exc)[:300]}"
            ))

        call_id = tool["call_id"]
        name = tool["name"]
        arguments = tool.get("arguments", {})
        expected_revision = tool.get("expected_revision")

        if name in CORE_OWNED:
            return self._failure(call_id, BridgeError(
                "unsupported_tool", f"{name} is Core-owned; the bridge does not execute it"
            ))

        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return self._failure(call_id, unsupported_tool(name))

        try:
            if task_id in self._cancelled:
                raise cancelled()
            self._refresh_system()
            mutating = name not in ("get_system_state", "get_ui_state", "inspect_screen", "inspect_region")
            if mutating and self.session.locked:
                raise session_locked()
            result = handler(task_id, arguments, expected_revision)
        except BridgeError as exc:
            return self._failure(call_id, exc)
        except Exception as exc:  # noqa: BLE001 - never leak a raw traceback to Core
            return self._failure(call_id, BridgeError(
                "bridge_error", f"{type(exc).__name__}: {str(exc)[:300]}", retryable=False
            ))

        payload: dict[str, Any] = {"call_id": call_id, "ok": True, "data": result.get("data", {})}
        if "delta" in result:
            payload["delta"] = result["delta"]
        if "image" in result:
            payload["image"] = result["image"]
        return validate_def("ToolResult", payload)

    def _failure(self, call_id: str, error: BridgeError) -> dict:
        return validate_def("ToolResult", {
            "call_id": call_id,
            "ok": False,
            "error": error.as_error(),
        })

    # ---------------------------------------------------------------- helpers

    def _refresh_system(self) -> None:
        """Updates lock state and foreground context before anything else runs."""
        try:
            self.session.note_lock_state(bool(self.adapters.uia.is_locked()))
        except Exception:  # noqa: BLE001 - treat probe failure as unknown, not unlocked
            pass
        if self.session.locked:
            return
        try:
            _, window_title, app_name = self.adapters.uia.active_window()
            self.session.note_system(app_name, window_title)
        except BridgeError:
            pass

    def _snapshot_delta(self) -> dict:
        observations, root_key = self.adapters.uia.snapshot()
        return self.session.ingest(observations, root_key)

    def _after_mutation(self, name: str) -> dict:
        if name in RESNAPSHOT_AFTER:
            self._sleep(SETTLE_SECONDS)
            self._refresh_system()
            try:
                return self._snapshot_delta()
            except BridgeError:
                pass
        self.session._bump()
        return self.session.system_delta()

    def _resolve_live(self, element_id: str):
        """Re-locates and re-observes a target, then re-checks it is actionable."""
        entry = self.session.get(element_id)
        control = self.adapters.uia.relocate(entry.observation)
        fresh = self.adapters.uia.observe_control(control, entry.observation)

        if fresh.role != entry.observation.role or fresh.name != entry.observation.name:
            raise BridgeError(
                "stale_target",
                f"Element {element_id} no longer matches the control Core selected",
                retryable=False,
            )
        entry.observation = fresh
        entry.ui_element = dict(entry.ui_element)
        entry.ui_element.update({
            "enabled": bool(fresh.enabled),
            "visible": bool(fresh.visible),
            "bounds": dict(fresh.bounds),
        })
        self.session.require_actionable(entry)
        return control, entry, fresh

    def _check_bounds(self, x: float, y: float) -> None:
        screen = self.adapters.uia.virtual_screen_bounds()
        if not (screen["x"] <= x <= screen["x"] + screen["width"]):
            raise BridgeError("out_of_bounds", "x coordinate is outside the visible desktop")
        if not (screen["y"] <= y <= screen["y"] + screen["height"]):
            raise BridgeError("out_of_bounds", "y coordinate is outside the visible desktop")

    def _guard_cancelled(self, task_id: str) -> None:
        """Last check before an irreversible step; after this the call is committed."""
        if task_id in self._cancelled:
            raise cancelled()

    # ---------------------------------------------------------------- read tools

    def _tool_get_system_state(self, task_id, arguments, expected_revision) -> dict:
        try:
            machine = self.adapters.system.machine_state()
        except Exception as exc:  # noqa: BLE001
            machine = {"unavailable": str(exc)[:200]}
        return {"data": {"machine": machine}, "delta": self.session.system_delta()}

    def _tool_get_ui_state(self, task_id, arguments, expected_revision) -> dict:
        delta = self._snapshot_delta()
        return {"data": {"element_count": len(delta.get("elements", []))}, "delta": delta}

    def _tool_inspect_screen(self, task_id, arguments, expected_revision) -> dict:
        image = self.adapters.capture.capture(None)
        return {"data": {"scope": "screen"}, "image": image, "delta": self.session.system_delta()}

    def _tool_inspect_region(self, task_id, arguments, expected_revision) -> dict:
        bounds = arguments["bounds"]
        self._check_bounds(bounds["x"], bounds["y"])
        image = self.adapters.capture.capture(bounds)
        return {"data": {"scope": "region"}, "image": image, "delta": self.session.system_delta()}

    # ---------------------------------------------------------------- UI tools

    def _tool_invoke_ui(self, task_id, arguments, expected_revision) -> dict:
        element_id, mode = arguments["id"], arguments["mode"]
        control, entry, fresh = self._resolve_live(element_id)

        if mode == "visible":
            # Animate the pointer for the user, then re-verify the *same*
            # semantic target before activating: the pointer trip is
            # presentation, and the screen may have moved during it.
            x, y = self.adapters.uia.center_of(control)
            self._check_bounds(x, y)
            self.adapters.rawinput.glide_to(x, y)
            control, entry, fresh = self._resolve_live(element_id)

        self.session.validate_revision(expected_revision)
        self._guard_cancelled(task_id)
        pattern = self.adapters.uia.invoke(control)
        return {
            "data": {"invoked": element_id, "pattern": pattern, "mode": mode},
            "delta": self._after_mutation("invoke_ui"),
        }

    def _tool_set_ui_value(self, task_id, arguments, expected_revision) -> dict:
        element_id, value = arguments["id"], arguments["value"]
        control, entry, fresh = self._resolve_live(element_id)
        self.session.validate_revision(expected_revision)
        self._guard_cancelled(task_id)
        self.adapters.uia.set_value(control, value)
        # The written value is never echoed back: it may be a secret even when
        # the field itself isn't flagged sensitive.
        return {
            "data": {"element": element_id, "value_length": len(value),
                      "sensitive": bool(entry.ui_element.get("sensitive"))},
            "delta": self._after_mutation("set_ui_value"),
        }

    def _tool_scroll(self, task_id, arguments, expected_revision) -> dict:
        direction, amount = arguments["direction"], int(arguments["amount"])
        self.session.validate_revision(expected_revision)
        self._guard_cancelled(task_id)
        self.adapters.uia.scroll(None, direction, amount)
        return {"data": {"direction": direction, "amount": amount}, "delta": self._after_mutation("scroll")}

    # ---------------------------------------------------------------- raw input

    def _tool_move_mouse(self, task_id, arguments, expected_revision) -> dict:
        x, y = arguments["x"], arguments["y"]
        self._check_bounds(x, y)
        self.session.validate_revision(expected_revision)
        self._guard_cancelled(task_id)
        self.adapters.rawinput.move_mouse(int(x), int(y))
        # Pointer position alone changes no UI semantics, so no re-snapshot.
        return {"data": {"x": x, "y": y}, "delta": self.session.system_delta()}

    def _tool_click(self, task_id, arguments, expected_revision) -> dict:
        x, y = arguments["x"], arguments["y"]
        self._check_bounds(x, y)
        self.session.validate_revision(expected_revision)
        self._guard_cancelled(task_id)
        self.adapters.rawinput.click(int(x), int(y))
        return {"data": {"x": x, "y": y}, "delta": self._after_mutation("click")}

    def _tool_type_text(self, task_id, arguments, expected_revision) -> dict:
        text = arguments["text"]
        self.session.validate_revision(expected_revision)
        self._guard_cancelled(task_id)
        self.adapters.rawinput.type_text(text)
        return {"data": {"length": len(text)}, "delta": self._after_mutation("type_text")}

    def _tool_press_key(self, task_id, arguments, expected_revision) -> dict:
        key = arguments["key"]
        self.session.validate_revision(expected_revision)
        self._guard_cancelled(task_id)
        self.adapters.rawinput.press_key(key)
        return {"data": {"key": key}, "delta": self._after_mutation("press_key")}

    # ---------------------------------------------------------------- launching

    def _tool_open_app(self, task_id, arguments, expected_revision) -> dict:
        spec = guards.resolve_app(arguments["name"])
        self.session.validate_revision(expected_revision)
        self._guard_cancelled(task_id)
        launched = self.adapters.launcher.open_app(spec)
        return {"data": {"app": arguments["name"], "launched": launched},
                "delta": self._after_mutation("open_app")}

    def _tool_open_url(self, task_id, arguments, expected_revision) -> dict:
        url = guards.validate_url(arguments["url"])
        self.session.validate_revision(expected_revision)
        self._guard_cancelled(task_id)
        self.adapters.launcher.open_url(url)
        return {"data": {"url": url}, "delta": self._after_mutation("open_url")}

    def _tool_open_file(self, task_id, arguments, expected_revision) -> dict:
        path = guards.validate_file_path(arguments["path"])
        self.session.validate_revision(expected_revision)
        self._guard_cancelled(task_id)
        self.adapters.launcher.open_path(path)
        return {"data": {"path": path}, "delta": self._after_mutation("open_file")}

    def _tool_open_folder(self, task_id, arguments, expected_revision) -> dict:
        path = guards.validate_folder_path(arguments["path"])
        self.session.validate_revision(expected_revision)
        self._guard_cancelled(task_id)
        self.adapters.launcher.open_path(path)
        return {"data": {"path": path}, "delta": self._after_mutation("open_folder")}

    # ---------------------------------------------------------------- settings

    def _tool_set_setting(self, task_id, arguments, expected_revision) -> dict:
        setting, value = guards.validate_setting(arguments["setting"], arguments["value"])
        self.session.validate_revision(expected_revision)
        self._guard_cancelled(task_id)
        self._apply_setting(setting, value)
        return {"data": {"setting": setting, "value": value}, "delta": self._after_mutation("set_setting")}

    def _tool_run_approved_action(self, task_id, arguments, expected_revision) -> dict:
        action = arguments["action"]
        value = int(arguments["args"]["value"])
        if action not in ("set_volume", "set_brightness"):
            raise BridgeError("unsupported_action", f"{action} is not an approved action")
        if not 0 <= value <= 100:
            raise BridgeError("invalid_arguments", "Approved actions take an integer 0..100")
        self.session.validate_revision(expected_revision)
        self._guard_cancelled(task_id)
        # Mapped to direct APIs; there is no shell path here by construction.
        self._apply_setting("volume" if action == "set_volume" else "brightness", value)
        return {"data": {"action": action, "value": value}, "delta": self._after_mutation("run_approved_action")}

    def _apply_setting(self, setting: str, value) -> None:
        if setting == "brightness":
            self.adapters.system.set_brightness(int(value))
        elif setting == "volume":
            self.adapters.system.set_volume(int(value))
        elif setting == "mute":
            self.adapters.system.set_mute(bool(value))
        else:  # pragma: no cover - guards.validate_setting already filtered
            raise BridgeError("unsupported_setting", f"Setting '{setting}' is not supported")
