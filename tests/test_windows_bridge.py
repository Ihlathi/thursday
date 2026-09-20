"""Windows bridge tests that run anywhere.

The bridge's Windows adapters need Windows, but its contract behaviour -- schema
conformance, revision/staleness checks, ID identity, and the launch/settings
allowlists -- does not, and those are the parts worth regression-testing. Fake
adapters stand in for UIA/WMI/pycaw, while ToolResults are validated against the
repository's real `shared/protocol.schema.json`.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "core"))
sys.path.insert(0, str(REPO_ROOT / "platform" / "windows"))

from agent.contracts import validate_def  # noqa: E402
from winbridge import classify, guards  # noqa: E402
from winbridge.errors import BridgeError, backend_unavailable, element_not_found  # noqa: E402
from winbridge.executor import Adapters, WindowsBridge  # noqa: E402
from winbridge.session import Observation, Session  # noqa: E402


# ---------------------------------------------------------------- fakes


class FakeControl:
    def __init__(self, observation):
        self.observation = observation


class FakeUia:
    def __init__(self, observations=None, locked=False):
        self.observations = observations if observations is not None else [_button()]
        self.locked = locked
        self.invoked = []
        self.values = []
        self.scrolls = []
        self.drift = None  # set to an Observation to simulate the tree changing

    def is_locked(self):
        return self.locked

    def active_window(self):
        return 4242, "Untitled - Notepad", "notepad.exe"

    def snapshot(self):
        return list(self.observations), (4242, "Untitled - Notepad")

    def relocate(self, observation):
        for candidate in self.observations:
            if candidate.runtime_id == observation.runtime_id:
                return FakeControl(candidate)
        raise element_not_found(observation.name)

    def observe_control(self, control, observation):
        return self.drift or control.observation

    def invoke(self, control):
        self.invoked.append(control.observation.name)
        return "invoke"

    def set_value(self, control, value):
        self.values.append((control.observation.name, value))

    def scroll(self, control, direction, amount):
        self.scrolls.append((direction, amount))

    def center_of(self, control):
        bounds = control.observation.bounds
        return int(bounds["x"] + bounds["width"] / 2), int(bounds["y"] + bounds["height"] / 2)

    def virtual_screen_bounds(self):
        return {"x": 0.0, "y": 0.0, "width": 1920.0, "height": 1080.0}


class FakeSystem:
    def __init__(self):
        self.brightness = 50
        self.volume = 30
        self.muted = False

    def machine_state(self):
        return {"brightness": {"level": self.brightness}, "audio": {"default_device": {"muted": self.muted}}}

    def set_brightness(self, level):
        self.brightness = level

    def set_volume(self, level):
        self.volume = level

    def set_mute(self, muted):
        self.muted = muted


class FakeRawInput:
    def __init__(self):
        self.calls = []

    def move_mouse(self, x, y):
        self.calls.append(("move", x, y))

    def glide_to(self, x, y, seconds=0.35):
        self.calls.append(("glide", x, y))

    def click(self, x, y):
        self.calls.append(("click", x, y))

    def type_text(self, text):
        self.calls.append(("type", text))

    def press_key(self, key):
        self.calls.append(("key", key))


class FakeCapture:
    def capture(self, bounds=None):
        image = {"mime_type": "image/png", "data": "aGk=", "scope": "region" if bounds else "screen"}
        if bounds:
            image["bounds"] = {k: float(bounds[k]) for k in ("x", "y", "width", "height")}
        return image


class FakeLauncher:
    def __init__(self):
        self.opened = []

    def open_app(self, spec):
        self.opened.append(("app", spec["target"]))
        return spec["target"]

    def open_url(self, url):
        self.opened.append(("url", url))

    def open_path(self, path):
        self.opened.append(("path", path))


def _button(name="Save", runtime_id=(7, 1), role="ButtonControl"):
    return Observation(
        role=role, name=name,
        bounds={"x": 10, "y": 20, "width": 100, "height": 30},
        enabled=True, visible=True, pid=4242, path=[0],
        runtime_id=runtime_id, automation_id="saveBtn",
    )


def _edit(name="Search", value="hello", is_password=False):
    return Observation(
        role="EditControl", name=name,
        bounds={"x": 0, "y": 0, "width": 200, "height": 24},
        enabled=True, visible=True, pid=4242, path=[1],
        runtime_id=(7, 2), value=value, is_password=is_password,
    )


def build(observations=None, locked=False):
    uia = FakeUia(observations, locked)
    adapters = Adapters(uia=uia, system=FakeSystem(), rawinput=FakeRawInput(),
                        capture=FakeCapture(), launcher=FakeLauncher())
    bridge = WindowsBridge(adapters=adapters, sleep=lambda _: None)
    return bridge, adapters


def call(tool_name, call_id="c1", /, **arguments):
    # Positional-only so a tool argument literally called "name" (open_app)
    # doesn't collide with this helper's own parameter.
    return {"call_id": call_id, "name": tool_name, "arguments": arguments}


# ---------------------------------------------------------------- guards


def test_url_scheme_allowlist():
    assert guards.validate_url("https://example.com/orders")
    for bad in ("javascript:alert(1)", "file:///C:/Windows/System32/cmd.exe",
                "data:text/html,<h1>x", "ms-settings:", "https://user:pw@example.com"):
        with pytest.raises(BridgeError) as excinfo:
            guards.validate_url(bad)
        assert excinfo.value.code == "unsafe_url"


def test_file_path_rejects_executables_and_unc():
    probes = {"exists": lambda p: True, "isfile": lambda p: True, "realpath": lambda p: p}
    assert guards.validate_file_path(r"C:\Users\x\notes.txt", **probes)
    with pytest.raises(BridgeError):
        guards.validate_file_path(r"C:\Users\x\payload.exe", **probes)
    with pytest.raises(BridgeError):
        guards.validate_file_path(r"\\server\share\file.txt", **probes)
    with pytest.raises(BridgeError):
        guards.validate_file_path(r"C:\Users\x\notes.txt:hidden", **probes)


def test_app_allowlist_refuses_shells():
    assert guards.resolve_app("Notepad")["kind"] == "exe"
    for denied in ("powershell", "cmd", "wt", "python", ""):
        with pytest.raises(BridgeError) as excinfo:
            guards.resolve_app(denied)
        assert excinfo.value.code == "unsupported_app"


def test_setting_allowlist_and_ranges():
    assert guards.validate_setting("brightness", 40) == ("brightness", 40)
    assert guards.validate_setting("mute", True) == ("mute", True)
    for setting, value in (("brightness", 400), ("brightness", "40"), ("mute", 1), ("registry", "x")):
        with pytest.raises(BridgeError):
            guards.validate_setting(setting, value)


# ---------------------------------------------------------------- classification


def test_classification_is_conservative():
    # A button never becomes "navigation" just because of what it is called.
    assert classify.action_kind("ButtonControl", False, False) == "unknown"
    assert classify.action_kind("ButtonControl", False, False) != "navigation"
    assert classify.action_kind("EditControl", False, False) == "edit"
    assert classify.action_kind("EditControl", True, True) == "security"


def test_sensitive_values_never_appear_in_description():
    secret = classify.describe("EditControl", "hunter2", sensitive=True)
    assert "hunter2" not in secret
    assert "sensitive" in secret
    shown = classify.describe("EditControl", "laptop stand", sensitive=False)
    assert "laptop stand" in shown


def test_name_hints_raise_sensitivity():
    assert classify.is_sensitive("EditControl", "Card number", False) is True
    assert classify.is_sensitive("EditControl", "Search", False) is False


# ---------------------------------------------------------------- session


def test_ids_are_stable_and_schema_valid():
    session = Session()
    delta = session.ingest([_button(), _edit()], (4242, "Untitled - Notepad"))
    first_ids = [e["id"] for e in delta["elements"]]
    for element in delta["elements"]:
        validate_def("UIElement", element)
    validate_def("StateDelta", delta)

    again = session.ingest([_button(), _edit()], (4242, "Untitled - Notepad"))
    assert [e["id"] for e in again["elements"]] == first_ids
    # Nothing changed, so the revision must not move.
    assert again["revision"] == delta["revision"]


def test_new_window_starts_a_new_id_generation():
    session = Session()
    first = session.ingest([_button()], (4242, "Notepad"))
    second = session.ingest([_button()], (99, "Calculator"))
    assert first["elements"][0]["id"] != second["elements"][0]["id"]
    assert second["revision"] > first["revision"]


def test_revision_moves_when_semantics_change():
    session = Session()
    before = session.ingest([_button(name="Save")], (4242, "Notepad"))
    after = session.ingest([_button(name="Save as…")], (4242, "Notepad"))
    assert after["revision"] > before["revision"]


# ---------------------------------------------------------------- executor


def test_reads_produce_valid_tool_results():
    bridge, _ = build()
    for name in ("get_system_state", "get_ui_state", "inspect_screen"):
        result = bridge.execute_sync("t1", call(name))
        assert result["ok"] is True, result
        validate_def("ToolResult", result)
    region = bridge.execute_sync("t1", call("inspect_region", bounds={"x": 0, "y": 0, "width": 10, "height": 10}))
    assert region["image"]["scope"] == "region"


def test_core_owned_and_unknown_tools_are_refused():
    bridge, _ = build()
    for name in ("search_ui", "ask_user", "complete_task", "propose_command"):
        result = bridge.execute_sync("t1", {"call_id": "c1", "name": name, "arguments": {"query": "x"}
                                            if name == "search_ui" else {"message": "x"} if name in ("ask_user", "complete_task")
                                            else {"command": "x", "reason": "y"}})
        assert result["ok"] is False
        assert result["error"]["code"] == "unsupported_tool"


def test_invoke_requires_a_known_element():
    bridge, _ = build()
    result = bridge.execute_sync("t1", call("invoke_ui", id="g1-rt-nope", mode="direct"))
    assert result["ok"] is False
    assert result["error"]["code"] == "element_not_found"


def test_invoke_happy_path_and_delta():
    bridge, adapters = build()
    snapshot = bridge.execute_sync("t1", call("get_ui_state"))
    element_id = snapshot["delta"]["elements"][0]["id"]

    result = bridge.execute_sync("t1", call("invoke_ui", id=element_id, mode="direct"))
    assert result["ok"] is True, result
    assert adapters.uia.invoked == ["Save"]
    validate_def("ToolResult", result)
    assert result["delta"]["revision"] >= snapshot["delta"]["revision"]


def test_stale_expected_revision_blocks_execution():
    bridge, adapters = build()
    snapshot = bridge.execute_sync("t1", call("get_ui_state"))
    element_id = snapshot["delta"]["elements"][0]["id"]

    tool = call("invoke_ui", id=element_id, mode="direct")
    tool["expected_revision"] = snapshot["delta"]["revision"] + 5
    result = bridge.execute_sync("t1", tool)
    assert result["ok"] is False
    assert result["error"]["code"] == "stale_target"
    assert adapters.uia.invoked == []


def test_target_drift_blocks_execution():
    bridge, adapters = build()
    snapshot = bridge.execute_sync("t1", call("get_ui_state"))
    element_id = snapshot["delta"]["elements"][0]["id"]
    # Same runtime id, different control behind it.
    adapters.uia.drift = _button(name="Delete everything")

    result = bridge.execute_sync("t1", call("invoke_ui", id=element_id, mode="direct"))
    assert result["ok"] is False
    assert result["error"]["code"] == "stale_target"
    assert adapters.uia.invoked == []


def test_locked_workstation_blocks_mutations_but_not_reads():
    bridge, adapters = build(locked=True)
    assert bridge.execute_sync("t1", call("get_system_state"))["ok"] is True

    result = bridge.execute_sync("t1", call("press_key", key="Enter"))
    assert result["ok"] is False
    assert result["error"]["code"] == "session_locked"
    assert adapters.rawinput.calls == []


def test_cancel_prevents_a_queued_mutation():
    import asyncio

    bridge, adapters = build()
    asyncio.run(bridge.cancel("t9"))
    result = bridge.execute_sync("t9", call("press_key", key="Enter"))
    assert result["ok"] is False
    assert result["error"]["code"] == "cancelled"
    assert adapters.rawinput.calls == []


def test_visible_mode_reverifies_before_activating():
    bridge, adapters = build()
    snapshot = bridge.execute_sync("t1", call("get_ui_state"))
    element_id = snapshot["delta"]["elements"][0]["id"]

    result = bridge.execute_sync("t1", call("invoke_ui", id=element_id, mode="visible"))
    assert result["ok"] is True
    assert ("glide", 60, 35) in adapters.rawinput.calls
    assert adapters.uia.invoked == ["Save"]


def test_set_ui_value_does_not_echo_the_value():
    bridge, adapters = build([_edit()])
    snapshot = bridge.execute_sync("t1", call("get_ui_state"))
    element_id = snapshot["delta"]["elements"][0]["id"]

    result = bridge.execute_sync("t1", call("set_ui_value", id=element_id, value="my-secret-token"))
    assert result["ok"] is True
    assert "my-secret-token" not in str(result)
    assert adapters.uia.values == [("Search", "my-secret-token")]


def test_password_field_is_marked_sensitive_without_value():
    bridge, _ = build([_edit(name="Password", value="hunter2", is_password=True)])
    snapshot = bridge.execute_sync("t1", call("get_ui_state"))
    element = snapshot["delta"]["elements"][0]
    assert element["sensitive"] is True
    assert element["action_kind"] == "security"
    assert "hunter2" not in str(snapshot)


def test_launch_guards_apply_through_the_executor():
    bridge, adapters = build()
    bad_url = bridge.execute_sync("t1", call("open_url", url="javascript:alert(1)"))
    assert bad_url["error"]["code"] == "unsafe_url"

    bad_app = bridge.execute_sync("t1", call("open_app", name="powershell"))
    assert bad_app["error"]["code"] == "unsupported_app"

    good = bridge.execute_sync("t1", call("open_url", url="https://example.com"))
    assert good["ok"] is True
    assert adapters.launcher.opened == [("url", "https://example.com")]


def test_run_approved_action_maps_to_direct_apis():
    bridge, adapters = build()
    result = bridge.execute_sync("t1", call("run_approved_action", action="set_brightness", args={"value": 80}))
    assert result["ok"] is True
    assert adapters.system.brightness == 80

    result = bridge.execute_sync("t1", call("run_approved_action", action="set_volume", args={"value": 10}))
    assert result["ok"] is True
    assert adapters.system.volume == 10


def test_schema_rejects_out_of_range_arguments():
    bridge, adapters = build()
    result = bridge.execute_sync("t1", call("scroll", direction="down", amount=99))
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_arguments"
    assert adapters.uia.scrolls == []


def test_coordinates_must_be_on_screen():
    bridge, adapters = build()
    result = bridge.execute_sync("t1", call("click", x=99999, y=10))
    assert result["ok"] is False
    assert result["error"]["code"] == "out_of_bounds"
    assert adapters.rawinput.calls == []


def test_adapter_failures_surface_as_structured_errors():
    bridge, adapters = build()

    def boom(*_args, **_kwargs):
        raise backend_unavailable("WMI is not responding")

    adapters.system.set_brightness = boom
    result = bridge.execute_sync("t1", call("run_approved_action", action="set_brightness", args={"value": 10}))
    assert result["ok"] is False
    assert result["error"]["code"] == "backend_unavailable"
    validate_def("ToolResult", result)
