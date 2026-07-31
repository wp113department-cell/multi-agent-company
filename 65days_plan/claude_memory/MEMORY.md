# Claude memory index — copied from `~/.claude/projects/.../memory/` on the original Windows
# machine, 2026-07-31 (Day 34), for cross-machine continuity. These are point-in-time notes from
# earlier sessions on this project, predating and overlapping with the 65-day gap-closure plan in
# this same folder. `IMPLEMENTATION_PROGRESS.md` and `answers.md` are the live, authoritative,
# continuously-updated status — treat these memory files as background/history, not current state.

- [Verify empirically, not by assumption](feedback_verify_empirically.md) — check real system state (docker ps, etc.) after side-effecting tests, don't assume isolation.
- [tools.py hardening state](project_tools_py_hardening.md) — what's fixed vs. knowingly still open in multi-agent-company's agent tool handlers.
- [MASTER_AGENT_v2.md status](project_master_agent_v2_status.md) — multi-agent-company's full upgrade spec is 100% implemented/tested as of 2026-07-30 (this predates and precedes the 65-day gap-closure plan in this folder).
- [Safe scope over literal spec](feedback_safe_scope_over_literal_spec.md) — when a spec's literal ask is unsafe, document why and ship the real safe subset instead.
