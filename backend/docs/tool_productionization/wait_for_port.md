# Tool #207 — `wait_for_port` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `wait_for_port_h` inside
`make_chat_handlers()`. Exclusively a `CHAT_TOOLS` entry (membership
count confirmed = 1); grepped all other agent files — none reference
`"wait_for_port"` in their own `allowed_tools`.

## Problems found

Two findings.

1. **`host` was a completely unrestricted, LLM-controlled TCP
   connect-probe target — a real network-reconnaissance / blind-SSRF-
   adjacent primitive.** Deliberately scoped **narrower** than the
   full `_ssrf_denial_reason()` guard `fetch_url`/`check_url_status`
   use (tool #126): this tool's own stated purpose is checking whether
   a just-started LOCAL dev server's port is open (`host` defaults to
   `"localhost"`) — applying the full SSRF denylist (which also
   rejects loopback and private RFC1918 ranges) would break the tool's
   entire legitimate use case, since local/private-network port checks
   ARE the intended capability, not a bug. What has NO legitimate use
   case for this tool, ever, is probing the cloud instance-metadata /
   link-local range (`169.254.0.0/16` IPv4, `fe80::/10` IPv6) — the
   range every major cloud provider's instance-metadata service
   occupies, used in real-world SSRF attacks to steal instance
   credentials. Proved live: `169.254.169.254` correctly resolves to
   a link-local address and `127.0.0.1`/`localhost` correctly do not.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#202/#203/#204/#206.**
   `wait_for_port` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` had NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: wait_for_port"`.

## Changes made

Extracted into `app/tools/execution/wait_for_port.py`
(`WAIT_FOR_PORT_TOOL`, `wait_for_port_handler`): a new
`_link_local_denial_reason()` helper (using the same
`ipaddress.ip_address(...).is_link_local` primitive
`_ssrf_denial_reason()` itself uses for this one specific check)
rejects only link-local-resolving hosts before the connect loop
starts, closing finding #1 without breaking the tool's real
localhost/private-network use case. A new `chat_agent.py`
`_execute_tool()` dispatch delegates to this same shared handler,
closing finding #2. The connect/retry/timeout loop itself is preserved
verbatim.

## Tests

`tool_inventory.json` correctly lists 0 pre-existing test files for
this tool, confirmed by grep — a genuine, closed coverage gap.

New file `tests/test_wait_for_port_hardening.py`, 10 tests: schema
check, `CHAT_TOOLS` single-registration check, cloud-metadata-blocked
proof on all 3 real access paths, proof a real localhost open port is
still correctly detected (confirming the narrower guard doesn't break
the tool's actual purpose), proof the dispatch no longer returns
"Unknown tool", and legitimate-usage regression using real, live
sockets (not mocks) — a real closed port timing out, a real port that
opens mid-wait being correctly detected.

## Regression

This tool's own new hardening tests (10/10 pass). Also ran a broader
chat_agent regression sweep
(`test_audit_q_batch10_chat_agent_dispatch.py`,
`test_batch11_chat_agent_bash_sandbox.py`,
`test_batch11_chat_agent_policy_chokepoint.py`,
`test_gap16_chat_agent_verification_gate.py`) — **19 passed**, 0
failed.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.chat_agent` and `app.agents.tools` (both clean), a `ruff
check` on all touched files (clean), a `CHAT_TOOLS`
duplicate-registration check (clean), and
`tests/test_final_session.py` tool-count regression tests (25/25
pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Two real findings (an unrestricted network-recon/
metadata-probing primitive and a completely non-functional
interactive-chat dispatch) identified and fixed with a deliberately
narrow, purpose-preserving guard rather than a blanket copy of an
unrelated tool's stricter policy. No functionality lost — real
localhost port-waiting (the tool's actual purpose) verified working
end-to-end with live sockets on both real access paths. Tool-specific
and broader chat_agent regression tests clean. Agent alignment
verified: PASS (`chat_agent.py`'s dispatch and `make_chat_handlers()`'s
handler both now route through the one shared, link-local-guarded
implementation).
