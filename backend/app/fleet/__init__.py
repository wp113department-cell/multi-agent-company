"""Fleet OS — infrastructure layer for registry-driven agent orchestration.

Day 0 components:
  capability_registry.py  — what each agent can do (static contracts)
  agent_registry.py       — live state of each agent instance (idle/running/sleep)
  fleet_manager.py        — dispatch via registry lookup, not hardcoded names
  audit_log.py            — immutable record of mutating actions + approvals
  metrics.py              — per-run observability with trace_id
  fleet_events.py         — Fleet OS typed event overlay (backward-compatible)
  tool_manifest.py        — governance manifest for every tool
"""
