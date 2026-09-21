"""Real, bounded professional-role detection for chat's adaptive expertise.

AUDIT_Q_BATCH17 §73 gap-closure (2026-08-12) — "Adaptive Expertise: NO —
no intent/role classification exists anywhere in the system (chat_agent.py's
routing distinguishes only 'tool call vs. stop,' nothing about the user's
professional role) ... nothing detects which one a conversational user
implicitly needs, or adapts tone/terminology to a detected role."

Mirrors two established precedents in this codebase rather than inventing a
new mechanism:
  - `app.pipeline.bootstrap.detect_project_type` — one cheap Haiku call,
    deterministic fallback, never raises.
  - `app.agents.user_sentiment.detect_user_frustration` — a real, bounded
    signal folded into THIS turn's system prompt as an additive directive
    string, not a new LangGraph routing edge (chat_agent.py's `_route_
    after_llm`/`_route_after_tool` — the actual tool_use/stop decision —
    are untouched; this only enriches what the model is told before it
    decides).

Domain-agnostic by construction: the candidate role list comes from the
fleet's own live `capability_registry` (whatever agents are actually
registered), never a hardcoded list of roles that would drift out of sync
with the real agent roster.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Conservative cap on how much of the live capability catalog gets sent to
# the classifier prompt — keeps the call cheap even as the roster grows.
_MAX_CATALOG_ENTRIES = 150


@dataclass
class RoleSignal:
    """role=None means no confident match — the caller should apply no
    directive, deliberately conservative so a generic/ambiguous message
    never gets an invented persona forced onto it."""

    role: str | None
    directive: str = ""


_agents_imported = False


def _ensure_agents_registered() -> None:
    """Agents register themselves in capability_registry when their module is imported, and
    most are imported lazily on first use — a freshly started server had 4 registered agents
    (pm, bug_fix, qa, executive), so every message was classified against a 4-entry roster
    (a React question came back as "bug_fix") until enough other agents had happened to run.
    Import them all once so the roster the classifier sees is the real one."""
    global _agents_imported
    if _agents_imported:
        return
    _agents_imported = True
    import importlib
    import pkgutil

    import app.agents as agents_pkg

    for module in pkgutil.iter_modules(agents_pkg.__path__):
        try:
            importlib.import_module(f"app.agents.{module.name}")
        except Exception:
            logger.debug(
                "role detection: could not import %s", module.name, exc_info=True
            )


def _load_catalog() -> list[tuple[str, str]]:
    """Real, live (name, description) pairs from capability_registry — never
    a hardcoded role list, so this tracks whatever domains are actually
    registered without needing a matching edit here."""
    _ensure_agents_registered()
    try:
        from app.fleet.capability_registry import get_capability_registry

        entries = get_capability_registry().all()
    except Exception:
        return []
    return [(e.name, e.description) for e in entries[:_MAX_CATALOG_ENTRIES]]


def detect_professional_role(user_message: str, model: str) -> RoleSignal:
    """One cheap classification call matching `user_message` against the
    fleet's own live agent roster. Returns a no-op signal (role=None) on any
    failure, empty roster, or when the model itself reports no clear match —
    never raises, mirrors `bootstrap.py::detect_project_type`'s fallback
    contract exactly.
    """
    catalog = _load_catalog()
    if not catalog:
        return RoleSignal(role=None)

    import anthropic

    from app.agents.base import get_effective_api_key
    from app.config import get_settings

    listing = "\n".join(f"- {name}: {desc}" for name, desc in catalog)
    prompt = (
        "A user sent this message to a multi-domain software engineering "
        "assistant. Which ONE of the following specialist domains, if any, "
        "does the message most clearly call for? Respond with ONLY the "
        "exact name from the list below, or the single word 'none' if no "
        "domain clearly applies (small talk, an ambiguous question, or a "
        "message that spans many domains equally).\n\n"
        f"{listing}\n\n"
        f"Message: {user_message[:500]}"
    )
    try:
        client = anthropic.Anthropic(
            api_key=get_effective_api_key(),
            max_retries=get_settings().llm_call_max_retries,
        )
        response = client.messages.create(
            model=model,
            max_tokens=20,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
    except Exception:
        logger.debug("role detection call failed (non-fatal)", exc_info=True)
        return RoleSignal(role=None)

    matched = next((name for name, _ in catalog if name == text), None)
    if matched is None:
        return RoleSignal(role=None)

    description = next(desc for name, desc in catalog if name == matched)
    directive = (
        f"\n\n[The user's message aligns with the '{matched}' domain "
        f"({description}). If it fits naturally, adapt your terminology and "
        "depth to that domain's audience — don't force it, and don't "
        "announce that you've detected this.]"
    )
    return RoleSignal(role=matched, directive=directive)
