"""Tool Discovery — Day 10.

A thin index over the two registries that already exist: `tool_manifest.py`
(tool -> risk/permission data) and `capability_registry.py` (agent -> tools it
uses). This module does not re-scan agent source files; every fact it reports
is derived from those two registries plus a small in-process overlay for
runtime tool registration.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from app.fleet.capability_registry import get_capability_registry
from app.fleet.tool_manifest import TOOL_MANIFEST, is_high_risk


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    permission_level: (
        str  # ToolManifestEntry.risk_level, or "unknown" if not in the manifest
    )
    permissions: list[str] = field(default_factory=list)
    handler_path: str = (
        "app.agents.tools"  # best-effort — nearly every tool handler lives here
    )


def _spec_from_manifest(tool_name: str) -> ToolSpec | None:
    entry = TOOL_MANIFEST.get(tool_name)
    if entry is None:
        return None
    return ToolSpec(
        name=tool_name,
        description=entry.purpose,
        permission_level=entry.risk_level,
        permissions=list(entry.permissions),
    )


class ToolDiscovery:
    """Thread-safe in-process tool discovery index."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._overlay: dict[str, ToolSpec] = {}

    def register_tool(self, spec: ToolSpec) -> None:
        """Add a runtime-discovered tool. Appends to an in-process overlay —
        never mutates the static TOOL_MANIFEST."""
        with self._lock:
            self._overlay[spec.name] = spec

    def _resolve(self, tool_name: str) -> ToolSpec:
        with self._lock:
            overlay_spec = self._overlay.get(tool_name)
        if overlay_spec is not None:
            return overlay_spec
        spec = _spec_from_manifest(tool_name)
        if spec is not None:
            return spec
        return ToolSpec(name=tool_name, description="", permission_level="unknown")

    def discover_tools(self, capability: str) -> list[ToolSpec]:
        """Union of .tools across every AgentCapability tagged with `capability`."""
        reg = get_capability_registry()
        tool_names: set[str] = set()
        for cap in reg.all():
            if capability in cap.capabilities:
                tool_names.update(cap.tools)
        return [self._resolve(name) for name in sorted(tool_names)]

    def check_compatibility(self, tool_name: str, agent_name: str) -> bool:
        """Is `tool_name` declared in `agent_name`'s own capability contract?

        Mirrors tool_manifest.verify_agent_contract()'s "declared vs used" rule
        rather than inventing a new risk-tier-matching scheme: a tool is
        compatible with an agent only if that agent's AgentCapability.tools
        actually lists it.
        """
        reg = get_capability_registry()
        cap = reg.get(agent_name)
        if cap is None:
            return False
        with self._lock:
            if tool_name in self._overlay:
                return tool_name in cap.tools
        return tool_name in cap.tools

    def check_availability(self, tool_name: str) -> bool:
        """Best-effort static check: is there a known spec for this tool?

        This does NOT probe a live handler — building a handler requires a
        repo_path and can have side effects. It only confirms the tool is
        documented (manifest or runtime overlay) or exists as a top-level
        callable in app.agents.tools.
        """
        with self._lock:
            if tool_name in self._overlay:
                return True
        if tool_name in TOOL_MANIFEST:
            return True
        import app.agents.tools as _tools_mod

        return callable(getattr(_tools_mod, tool_name, None))

    def is_high_risk(self, tool_name: str) -> bool:
        with self._lock:
            overlay_spec = self._overlay.get(tool_name)
        if overlay_spec is not None:
            return overlay_spec.permission_level == "high"
        return is_high_risk(tool_name)

    def filter_runtime_tools(
        self,
        agent_name: str,
        static_tools: list[dict[str, Any]],
        tool_handlers: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Narrow `static_tools` to what can actually run for `agent_name` right now.

        Two independent checks; a tool is kept only if both pass:

        1. Availability — `tool["name"]` is a real key in `tool_handlers`. This
           is the zero-false-negative signal: every real caller of
           run_agent_graph() builds `tool_handlers` to include every tool it
           passes, including each agent's own locally-defined `submit_*`
           closure (those are never in TOOL_MANIFEST or top-level
           app.agents.tools callables, so check_availability() would wrongly
           drop them — do not use it here).
        2. Contract drift — if the tool is high-risk (tool_manifest.is_high_risk),
           it must also appear in this agent's own registered
           `AgentCapability.tools`. Non-high-risk tools, and agents with no
           registered capability entry (unregistered agent_name), are not
           narrowed by this check — it only catches a high-risk tool that
           slipped into an agent's static list without being declared in its
           capability contract.

        Never adds a tool absent from `static_tools`. Preserves input order.
        """
        cap = get_capability_registry().get(agent_name)
        declared = set(cap.tools) if cap is not None else None
        kept: list[dict[str, Any]] = []
        for tool in static_tools:
            name = tool.get("name", "")
            if name not in tool_handlers:
                continue
            if (
                self.is_high_risk(name)
                and declared is not None
                and name not in declared
            ):
                continue
            kept.append(tool)
        return kept


_discovery_singleton: ToolDiscovery | None = None
_singleton_lock = threading.Lock()


def get_tool_discovery() -> ToolDiscovery:
    global _discovery_singleton
    with _singleton_lock:
        if _discovery_singleton is None:
            _discovery_singleton = ToolDiscovery()
        return _discovery_singleton


def discover_tools(capability: str) -> list[ToolSpec]:
    return get_tool_discovery().discover_tools(capability)


def check_compatibility(tool_name: str, agent_name: str) -> bool:
    return get_tool_discovery().check_compatibility(tool_name, agent_name)


def check_availability(tool_name: str) -> bool:
    return get_tool_discovery().check_availability(tool_name)


def register_tool(spec: ToolSpec) -> None:
    get_tool_discovery().register_tool(spec)


def filter_runtime_tools(
    agent_name: str,
    static_tools: list[dict[str, Any]],
    tool_handlers: dict[str, Any],
) -> list[dict[str, Any]]:
    return get_tool_discovery().filter_runtime_tools(
        agent_name, static_tools, tool_handlers
    )
