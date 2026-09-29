"""Smart task router — pick the fewest agents that can do the job (2026-09-29).

Before: every task went through one fixed pipeline. In "full" mode that was PM
+ Opus architect + Opus decomposer, then dev + QA + reviewer + 3 LLM quality
gates per subtask (~21 agent runs for a 3-subtask task). Most real tasks are
one-area changes ("make the login button blue", "add a /health field") that a
single capable specialist does end to end with its own tools.

Tiers:
  small   one area (UI, or backend/API/DB)  → ONE specialist
  medium  touches UI and backend           → backend_dev, then frontend_dev,
                                             in the same worktree
  large   a new project / whole app / big  → the existing full pipeline
          multi-area build                   (PM → Architect → Decomposer)

Classification is free keyword/size rules first. Only when the rules can't
tell does it make ONE small Haiku call (max_tokens=80, ~$0.001). Decisions
are cached by the normalized task text — in Redis when it is reachable (shared
by every backend process), else in-process — so a re-run never pays twice.

Whatever the tier, nothing skips the human gates: the routed plan is approved
before any code is written, and git push still needs approval.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

EXECUTORS = ("frontend_dev", "backend_dev", "coder")
ROUTE_SEPARATOR = "+"

_LARGE = re.compile(
    r"\b(from scratch|new (project|app|application|service|repo(sitory)?)|"
    r"entire (app|application|project|system|site|website|platform)|"
    r"whole (app|application|project|system|site|website|platform)|"
    r"full[- ]stack (app|application)|build (a|an|the) (complete|full|new)|"
    r"scaffold|bootstrap (a|the) project|microservices?|re-?architect|"
    r"multi-?tenant|end[- ]to[- ]end (app|application|system))\b"
)
_FRONTEND = re.compile(
    r"\b(ui|ux|css|scss|tailwind|styl(e|es|ing)|button|page|screen|component|"
    r"layout|frontend|front-end|react|next\.?js|tsx|jsx|colou?r|font|"
    r"responsive|modal|dialog|navbar|nav bar|sidebar|header|footer|form|"
    r"dark mode|light mode|theme|icon|animation|dashboard ui|design)\b"
)
_BACKEND = re.compile(
    r"\b(api|endpoint|route|router|database|db|sql|postgres|migration|model|"
    r"schema|backend|back-end|fastapi|server|auth|jwt|login api|query|"
    r"orm|sqlalchemy|redis|queue|worker|celery|webhook|cron|python)\b"
)
# above this many characters a task is treated as large regardless of words
_LARGE_TEXT_CHARS = 1500

_CLASSIFY_PROMPT = (
    "Classify this software task. Reply with ONLY compact JSON like "
    '{{"tier":"small|medium|large","areas":["frontend"|"backend"]}}.\n'
    "small = one area, a focused change. medium = touches frontend and backend. "
    "large = a new project, a whole application, or a big multi-part build.\n\n"
    "Task: {task}"
)


@dataclass(frozen=True)
class RouteDecision:
    tier: str  # small | medium | large
    agents: tuple[str, ...]  # executors in order; empty for large (full pipeline)
    reason: str
    source: str  # rules | llm | cache | fallback

    @property
    def assigned_agent(self) -> str:
        """Durable encoding stored in DevTask.assigned_agent (read back at
        plan approval by agents_from_assigned())."""
        return ROUTE_SEPARATOR.join(self.agents) if self.agents else "manager"


def agents_from_assigned(assigned: str | None) -> list[str] | None:
    """Inverse of RouteDecision.assigned_agent: the executor list a routed task
    was assigned, or None for any older/non-routed value (planner, coder, …)."""
    if not assigned:
        return None
    parts = [p for p in assigned.split(ROUTE_SEPARATOR) if p]
    if parts and all(p in EXECUTORS for p in parts) and parts != ["coder"]:
        return parts
    return None


def _decision_for(
    tier: str, areas: set[str], reason: str, source: str
) -> RouteDecision:
    if tier == "large":
        return RouteDecision("large", (), reason, source)
    if "frontend" in areas and "backend" in areas:
        return RouteDecision("medium", ("backend_dev", "frontend_dev"), reason, source)
    if "frontend" in areas:
        return RouteDecision("small", ("frontend_dev",), reason, source)
    if "backend" in areas:
        return RouteDecision("small", ("backend_dev",), reason, source)
    return RouteDecision("small", ("coder",), reason, source)


def classify_by_rules(text: str) -> RouteDecision | None:
    """Free, deterministic classification. None = not confident → ask Haiku."""
    t = text.lower()
    if len(t) > _LARGE_TEXT_CHARS:
        return _decision_for("large", set(), "long, multi-part description", "rules")
    if _LARGE.search(t):
        return _decision_for(
            "large", set(), f"project-scale wording ({_LARGE.search(t).group(0)!r})", "rules"  # type: ignore[union-attr]
        )
    fe = sorted({m.group(0) for m in _FRONTEND.finditer(t)})
    be = sorted({m.group(0) for m in _BACKEND.finditer(t)})
    areas = ({"frontend"} if fe else set()) | ({"backend"} if be else set())
    if not areas:
        return None
    tier = "medium" if len(areas) == 2 else "small"
    why = ", ".join(
        part
        for part in (
            f"UI words: {', '.join(fe[:4])}" if fe else "",
            f"backend words: {', '.join(be[:4])}" if be else "",
        )
        if part
    )
    return _decision_for(tier, areas, why, "rules")


def classify_by_llm(text: str) -> RouteDecision | None:
    """One small Haiku call. Never raises — None on any failure."""
    try:
        from app.agents.base_graph import _call_anthropic, _make_client, _parse_llm_json

        r = _call_anthropic(
            _make_client(),
            model=get_settings().model_router,
            max_tokens=80,
            messages=[
                {"role": "user", "content": _CLASSIFY_PROMPT.format(task=text[:1200])}
            ],
        )
        raw = "".join(getattr(b, "text", "") for b in r.content)
        data = _parse_llm_json(raw)
        tier = str(data.get("tier", "")).lower()
        areas = {str(a).lower() for a in data.get("areas", []) if a}
        if tier not in ("small", "medium", "large"):
            return None
        return _decision_for(tier, areas, f"classifier: {tier}, {sorted(areas)}", "llm")
    except Exception:
        logger.debug("task_router: LLM classification failed", exc_info=True)
        return None


# --- cache ------------------------------------------------------------------

_LOCAL: dict[str, tuple[float, str]] = {}
_LOCAL_LOCK = threading.Lock()
_TTL_SECONDS = 7 * 24 * 3600


def _cache_key(text: str) -> str:
    norm = " ".join(text.lower().split())
    return "gridiron:route:" + hashlib.sha256(norm.encode()).hexdigest()[:32]


def _redis() -> Any:
    try:
        import redis

        client = redis.Redis.from_url(
            get_settings().redis_url, socket_timeout=0.3, socket_connect_timeout=0.3
        )
        client.ping()
        return client
    except Exception:
        return None


def _cache_get(key: str) -> RouteDecision | None:
    raw: str | None = None
    client = _redis()
    if client is not None:
        try:
            val = client.get(key)
            raw = val.decode() if isinstance(val, bytes) else val
        except Exception:
            raw = None
    if raw is None:
        with _LOCAL_LOCK:
            hit = _LOCAL.get(key)
            if hit and time.monotonic() - hit[0] < _TTL_SECONDS:
                raw = hit[1]
    if raw is None:
        return None
    try:
        d = json.loads(raw)
        return RouteDecision(d["tier"], tuple(d["agents"]), d["reason"], "cache")
    except Exception:
        return None


def _cache_put(key: str, decision: RouteDecision) -> None:
    raw = json.dumps(asdict(decision))
    with _LOCAL_LOCK:
        _LOCAL[key] = (time.monotonic(), raw)
    client = _redis()
    if client is not None:
        try:
            client.set(key, raw, ex=_TTL_SECONDS)
        except Exception:
            pass


def route_task(title: str, description: str) -> RouteDecision:
    """Decide the smallest set of agents for a task. Never raises."""
    text = f"{title}\n{description}".strip()
    key = _cache_key(text)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    decision = classify_by_rules(text) or classify_by_llm(text)
    if decision is None:
        decision = RouteDecision(
            "small", ("coder",), "no clear area — general developer", "fallback"
        )
    _cache_put(key, decision)
    return decision
