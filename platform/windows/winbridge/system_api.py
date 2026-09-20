"""Direct Windows APIs -- the tier above UI Automation for machine state.

Brightness goes through WMI's `root\\wmi` monitor classes and audio through
Core Audio/WASAPI (pycaw). Neither touches a settings window, so
`run_approved_action` and `set_setting` complete without disturbing whatever the
user is doing. Nothing here builds a shell string.

Hardware specifics (which monitors exist, which endpoint is default, which apps
have sessions) are always discovered at call time so the bridge behaves the same
on any Windows 11 machine.
"""

from __future__ import annotations

from ctypes import POINTER, cast
from typing import Any

from .errors import backend_unavailable

try:
    import wmi
except ImportError:  # pragma: no cover - Windows only
    wmi = None

try:
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
except ImportError:  # pragma: no cover - Windows only
    AudioUtilities = None
    IAudioEndpointVolume = None
    CLSCTX_ALL = None

_wmi_root = None
_wmi_cimv2 = None


def _namespace(name: str):
    global _wmi_root, _wmi_cimv2
    if wmi is None:
        raise backend_unavailable("The 'WMI' package is not installed (Windows-only bridge)")
    if name == "wmi":
        if _wmi_root is None:
            _wmi_root = wmi.WMI(namespace="root\\wmi")
        return _wmi_root
    if _wmi_cimv2 is None:
        _wmi_cimv2 = wmi.WMI()
    return _wmi_cimv2


# ---------------------------------------------------------------- brightness


def get_brightness() -> dict[str, Any]:
    try:
        monitors = _namespace("wmi").WmiMonitorBrightness()
    except Exception as exc:  # noqa: BLE001
        raise backend_unavailable(f"Brightness is not readable on this system: {exc}") from exc
    if not monitors:
        raise backend_unavailable(
            "No WMI-controllable display found. External monitors on DDC/CI are not reachable this way."
        )
    levels = [{"instance": m.InstanceName, "level": int(m.CurrentBrightness)} for m in monitors]
    return {"level": levels[0]["level"], "monitors": levels}


def set_brightness(level: int) -> None:
    level = max(0, min(100, int(level)))
    try:
        methods = _namespace("wmi").WmiMonitorBrightnessMethods()
    except Exception as exc:  # noqa: BLE001
        raise backend_unavailable(f"Brightness is not settable on this system: {exc}") from exc
    if not methods:
        raise backend_unavailable("No WMI-controllable display found for brightness control")
    for method in methods:
        method.WmiSetBrightness(Timeout=1, Brightness=level)


# ---------------------------------------------------------------- audio


def _endpoint_volume():
    if AudioUtilities is None:
        raise backend_unavailable("The 'pycaw' package is not installed (Windows-only bridge)")
    try:
        speakers = AudioUtilities.GetSpeakers()
        raw = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(raw, POINTER(IAudioEndpointVolume))
    except Exception as exc:  # noqa: BLE001
        raise backend_unavailable(f"Default audio endpoint is unavailable: {exc}") from exc


def get_audio() -> dict[str, Any]:
    """Default endpoint plus per-app sessions -- enough to explain 'no sound'."""
    volume = _endpoint_volume()
    state: dict[str, Any] = {
        "default_device": {
            "muted": bool(volume.GetMute()),
            "volume_percent": round(volume.GetMasterVolumeLevelScalar() * 100),
        },
        "app_sessions": [],
    }
    try:
        for session in AudioUtilities.GetAllSessions():
            if session.Process is None:
                continue
            simple = session.SimpleAudioVolume
            state["app_sessions"].append({
                "app": session.Process.name(),
                "muted": bool(simple.GetMute()),
                "volume_percent": round(simple.GetMasterVolume() * 100),
            })
    except Exception:  # noqa: BLE001
        # Session enumeration is best-effort detail; the default endpoint
        # reading above is what callers depend on.
        pass
    return state


def set_volume(level: int) -> None:
    volume = _endpoint_volume()
    volume.SetMasterVolumeLevelScalar(max(0.0, min(1.0, int(level) / 100)), None)


def set_mute(muted: bool) -> None:
    volume = _endpoint_volume()
    volume.SetMute(1 if muted else 0, None)


# ---------------------------------------------------------------- misc state


def get_battery() -> dict[str, Any]:
    try:
        batteries = _namespace("cimv2").Win32_Battery()
    except Exception as exc:  # noqa: BLE001
        raise backend_unavailable(f"Battery state is not readable: {exc}") from exc
    if not batteries:
        return {"present": False}
    battery = batteries[0]
    return {
        "present": True,
        "percent": getattr(battery, "EstimatedChargeRemaining", None),
        "status_code": getattr(battery, "BatteryStatus", None),
    }


def get_network() -> dict[str, Any]:
    try:
        adapters = _namespace("cimv2").Win32_NetworkAdapter(NetEnabled=True)
    except Exception as exc:  # noqa: BLE001
        raise backend_unavailable(f"Network state is not readable: {exc}") from exc
    connected = [a.Name for a in adapters if getattr(a, "NetConnectionStatus", None) == 2]
    return {"connected": bool(connected), "connected_adapters": connected}


def machine_state() -> dict[str, Any]:
    """Best-effort bundle for get_system_state's extension `data` object.

    Each probe degrades independently: a desktop with no battery, or a machine
    whose display ignores WMI brightness, still returns everything else.
    """
    state: dict[str, Any] = {}
    for key, probe in (
        ("brightness", get_brightness),
        ("audio", get_audio),
        ("battery", get_battery),
        ("network", get_network),
    ):
        try:
            state[key] = probe()
        except Exception as exc:  # noqa: BLE001
            state[key] = {"unavailable": str(exc)[:200]}
    return state
