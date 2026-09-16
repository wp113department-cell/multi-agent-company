"""wait_for_port tool — tool_enhance.md productionization pass, tool
#207 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: wait_for_port
Old path: app/agents/tools.py (`_WAIT_FOR_PORT_TOOL` schema dict,
    `wait_for_port_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/execution/wait_for_port.py (this file) —
    `WAIT_FOR_PORT_TOOL`, `wait_for_port_handler`.
Affected agents: exclusively a `CHAT_TOOLS` entry (confirmed:
    `CHAT_TOOLS` membership count is 1); grepped all other agent
    files, none reference `"wait_for_port"` in their own
    `allowed_tools` — interactive chat is the only real consumer.
Affected modules: app/agents/tools.py (`wait_for_port_h` delegates to
    the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "wait_for_port" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: `tool_inventory.json` correctly lists 0 pre-existing
    test files for this tool, confirmed by grep. New tests added: see
    tests/test_wait_for_port_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/wait_for_port.md.
---------------------------------------------------------------------------

Two findings.

1. **`host` was a completely unrestricted, LLM-controlled TCP
   connect-probe target — a real network-reconnaissance / blind-SSRF-
   adjacent primitive, scoped deliberately narrower than the full
   `_ssrf_denial_reason()` guard `fetch_url`/`check_url_status` use
   (tool #126).** This tool's OWN stated purpose is checking whether a
   just-started LOCAL dev server's port is open (`host` defaults to
   `"localhost"`) — applying the full SSRF denylist (which also
   rejects loopback and private RFC1918 ranges) would break the tool's
   entire legitimate use case, since local/private-network port checks
   ARE the intended capability, not a bug. What has NO legitimate use
   case for this tool, ever, is probing the cloud metadata / link-local
   range (`169.254.0.0/16` IPv4, `fe80::/10` IPv6) — the specific
   range every cloud provider's instance-metadata service occupies
   (e.g. AWS/GCP/Azure's `169.254.169.254`), used in real-world SSRF
   attacks to steal instance credentials. Fixed by rejecting only
   link-local-resolving hosts (via Python's `ipaddress.ip_address(...).
   is_link_local`, the same primitive `_ssrf_denial_reason()` itself
   uses for this one specific check) — loopback and private addresses
   remain allowed, matching the tool's real, documented purpose.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#202/#203/#204/#206.**
   `wait_for_port` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` had NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: wait_for_port"`.

Fixed via a shared `wait_for_port_handler()`: `host` is resolved and
checked for a link-local address before the connect loop starts,
closing finding #1 without breaking the tool's real localhost/private-
network use case. A new `chat_agent.py` dispatch delegates to this
same shared handler, closing finding #2.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from typing import Any

WAIT_FOR_PORT_TOOL: dict[str, Any] = {
    "name": "wait_for_port",
    "description": "Wait until a TCP port is open (useful after starting a server). Returns when port accepts connections or times out.",
    "input_schema": {
        "type": "object",
        "properties": {
            "port": {"type": "integer", "description": "TCP port number"},
            "host": {"type": "string", "description": "Hostname (default: localhost)"},
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait (default: 30)",
            },
        },
        "required": ["port"],
    },
}


def _link_local_denial_reason(host: str) -> str | None:
    """Rejects only link-local-resolving hosts (169.254.0.0/16,
    fe80::/10 — the cloud instance-metadata range). Deliberately does
    NOT reject loopback/private addresses, unlike the full
    `_ssrf_denial_reason()` guard used by content-fetching tools — see
    this module's docstring for why (wait_for_port's entire purpose is
    checking local/private-network ports)."""
    try:
        addr_infos = socket.getaddrinfo(host, None)
    except Exception:
        return None  # let the real connect attempt below surface the real error
    for info in addr_infos:
        raw_addr = info[4][0]
        try:
            ip = ipaddress.ip_address(raw_addr)
        except ValueError:
            continue
        if ip.is_link_local:
            return (
                f"Host {host!r} resolves to {raw_addr!r}, a link-local address "
                "(includes the cloud instance-metadata range) — refusing to "
                "probe (SSRF protection)"
            )
    return None


def wait_for_port_handler(inp: dict[str, Any]) -> str:
    """Core wait_for_port logic — the one real implementation, reused
    unchanged in behavior except for the link-local guard now applied
    to `host` (see this module's docstring, finding #1)."""
    port = int(inp["port"])
    host = str(inp.get("host", "localhost"))
    timeout = int(inp.get("timeout", 30))

    denial = _link_local_denial_reason(host)
    if denial:
        return f"[POLICY DENIED] {denial}"

    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                elapsed = round(time.time() - start, 2)
                return f"Port {host}:{port} is open (waited {elapsed}s)"
        except (ConnectionRefusedError, OSError):
            time.sleep(0.5)
    return f"[TIMEOUT] Port {host}:{port} not open after {timeout}s"
