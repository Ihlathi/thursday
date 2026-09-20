"""World model: stable element identity, revisions, and StateDelta assembly.

Holds the bridge's authoritative view of the desktop between ToolCalls. Core
addresses elements by the IDs minted here, so identity rules matter:

* An ID is derived from the UIA RuntimeId when one exists, which is unique per
  live element, and is prefixed with a generation counter. The generation
  advances whenever the snapshot root (process + window) changes, so a RuntimeId
  that Windows later recycles for a different element can never collide with an
  ID Core is still holding -- "never reuse an ID for a different element".
* Revision increments on any observed semantic or geometry change, so Core's
  `expected_revision` check is meaningful. Older deltas are ignored by Core.

Deliberately free of Windows imports: the adapter feeds it plain observations,
which keeps identity and revision logic testable on any OS.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional

from . import classify
from .errors import BridgeError, element_not_found, stale_target

# Payload bound well under the schema's 2000-element ceiling: a deep tree is
# rarely useful to Core and always expensive to embed.
MAX_ELEMENTS = 300


@dataclass
class Observation:
    """One control as the OS adapter saw it. Plain data, no COM handles."""

    role: str
    name: str
    bounds: dict[str, float]
    enabled: bool
    visible: bool
    pid: int = 0
    path: list[int] = field(default_factory=list)
    runtime_id: Optional[tuple[int, ...]] = None
    automation_id: str = ""
    help_text: str = ""
    is_password: bool = False
    value: Optional[str] = None
    parent_index: Optional[int] = None
    children_indices: list[int] = field(default_factory=list)


@dataclass
class Registered:
    """What the bridge keeps so it can re-find and re-verify an element later."""

    element_id: str
    ui_element: dict[str, Any]
    observation: Observation
    generation: int


class Session:
    def __init__(self) -> None:
        self.revision = 0
        self.sleep_epoch = 0
        self.generation = 0
        self.locked = False
        self.active_app = "unknown"
        self.active_window = "unknown"
        self.elements: dict[str, Registered] = {}
        self._root_key: Optional[tuple[int, str]] = None

    # ---------------------------------------------------------------- state

    def system_state(self) -> dict[str, Any]:
        # active_app/active_window are minLength:1 in the schema, so they never
        # fall through as empty strings.
        return {
            "active_app": self.active_app or "unknown",
            "active_window": self.active_window or "unknown",
            "locked": self.locked,
            "sleep_epoch": self.sleep_epoch,
            "revision": self.revision,
        }

    def note_lock_state(self, locked: bool) -> None:
        """Tracks lock transitions; a lock->unlock transition counts as a resume."""
        if locked != self.locked:
            if self.locked and not locked:
                self.sleep_epoch += 1
            self.locked = locked
            self._bump()

    def note_system(self, active_app: str, active_window: str) -> None:
        if active_app != self.active_app or active_window != self.active_window:
            self.active_app = active_app or "unknown"
            self.active_window = active_window or "unknown"
            # Focus/context change is a semantic change per the contract.
            self._bump()

    def _bump(self) -> None:
        self.revision += 1

    def validate_revision(self, expected: Optional[int]) -> None:
        """Checked immediately before every mutating execution, never earlier."""
        if expected is not None and expected != self.revision:
            raise stale_target(
                f"Desktop revision is {self.revision}, call expected {expected}"
            )

    # ---------------------------------------------------------------- identity

    def _element_id(self, observation: Observation) -> str:
        if observation.runtime_id:
            suffix = "-".join(str(int(part)) for part in observation.runtime_id)
            candidate = f"g{self.generation}-rt-{suffix}"
            if len(candidate) <= 100:
                return candidate
        seed = "|".join([
            str(observation.pid),
            ",".join(str(i) for i in observation.path),
            observation.role,
            observation.name,
            observation.automation_id,
        ])
        digest = hashlib.sha1(seed.encode("utf-8", "replace")).hexdigest()[:20]
        return f"g{self.generation}-h-{digest}"

    # ---------------------------------------------------------------- snapshot

    def ingest(self, observations: list[Observation], root_key: tuple[int, str]) -> dict[str, Any]:
        """Registers a fresh snapshot and returns a full StateDelta.

        Full snapshots (rather than incremental upserts) are used deliberately:
        the contract permits either, element counts here are capped well below
        the schema ceiling, and a full replace cannot drift out of sync the way
        a missed removal can.
        """
        if root_key != self._root_key:
            # New window/process: start a fresh ID generation so no previously
            # issued ID can ever be reinterpreted against the new tree.
            self.generation += 1
            self._root_key = root_key
            self.elements = {}

        trimmed = observations[:MAX_ELEMENTS]
        ids = [self._element_id(obs) for obs in trimmed]

        registry: dict[str, Registered] = {}
        ui_elements: list[dict[str, Any]] = []
        for index, (obs, element_id) in enumerate(zip(trimmed, ids)):
            if element_id in registry:
                continue  # identical runtime id seen twice; keep the first
            ui_element = self._to_ui_element(element_id, obs, ids, index)
            registry[element_id] = Registered(element_id, ui_element, obs, self.generation)
            ui_elements.append(ui_element)

        if self._changed(registry):
            self._bump()
        self.elements = registry

        return {
            "revision": self.revision,
            "system": self.system_state(),
            "elements": ui_elements,
            "full": True,
        }

    def system_delta(self) -> dict[str, Any]:
        """Revision + system only, for reads that don't re-walk the UI tree."""
        return {"revision": self.revision, "system": self.system_state()}

    def _changed(self, registry: dict[str, Registered]) -> bool:
        if set(registry) != set(self.elements):
            return True
        for element_id, entry in registry.items():
            if entry.ui_element != self.elements[element_id].ui_element:
                return True
        return False

    def _to_ui_element(
        self, element_id: str, obs: Observation, ids: list[str], index: int
    ) -> dict[str, Any]:
        sensitive = classify.is_sensitive(obs.role, obs.name, obs.is_password)
        parent = ids[obs.parent_index] if obs.parent_index is not None and obs.parent_index < len(ids) else None
        children = [ids[i] for i in obs.children_indices if i < len(ids)]
        return {
            "id": element_id,
            "role": obs.role or "control",
            "name": (obs.name or "")[:1024],
            "description": classify.describe(obs.role, obs.value, sensitive, obs.help_text),
            "bounds": {
                "x": float(obs.bounds.get("x", 0)),
                "y": float(obs.bounds.get("y", 0)),
                "width": max(0.0, float(obs.bounds.get("width", 0))),
                "height": max(0.0, float(obs.bounds.get("height", 0))),
            },
            "enabled": bool(obs.enabled),
            "visible": bool(obs.visible),
            "parent": parent if parent != element_id else None,
            "children": [c for c in children if c != element_id][:2000],
            # Everything this bridge emits comes from the accessibility tree;
            # screenshots are returned as images, never as synthesized elements.
            "source": "accessibility",
            "confidence": 1.0,
            "sensitive": sensitive,
            "action_kind": classify.action_kind(obs.role, obs.is_password, sensitive),
        }

    # ---------------------------------------------------------------- lookup

    def get(self, element_id: str) -> Registered:
        entry = self.elements.get(element_id)
        if entry is None:
            raise element_not_found(element_id)
        if entry.generation != self.generation:
            raise stale_target("Element belongs to a previous window generation")
        return entry

    def require_actionable(self, entry: Registered) -> None:
        """Bounds/enabled/visible are re-checked from the live re-read, not cached trust."""
        ui = entry.ui_element
        if not ui["enabled"]:
            raise BridgeError("element_disabled", f"Element {ui['id']} is disabled", retryable=False)
        if not ui["visible"]:
            raise BridgeError("element_not_visible", f"Element {ui['id']} is not visible", retryable=False)
        bounds = ui["bounds"]
        if bounds["width"] <= 0 or bounds["height"] <= 0:
            raise BridgeError("element_not_visible", f"Element {ui['id']} has empty bounds", retryable=False)
