"""Fleet-wide daily LLM spend cap — a hard stop, checked BEFORE every call.

Production audit 09 (2026-10-02). Before this, COST_BUDGET_DAILY_USD was only
checked after an agent run had finished (base_graph post-run block) and only
per agent, so it never stopped spend: each of the ~85 agents could spend the
whole "daily" budget, and a run over budget had already been paid for.

How it works:
- ``install()`` wraps the Anthropic SDK's ``Messages.create`` / ``.stream``
  (sync and async) at class level, so every client anywhere in the process —
  base_graph, chat, memory consolidation, role detection, the router, git
  push summaries, any future call site — goes through one gate. Test mocks
  replace the client object, never this class, so they are unaffected.
- Before each call: ``check()`` raises ``DailyBudgetExceeded`` once today's
  recorded spend has reached the cap. Nothing is sent, nothing is billed.
- After each call: the response's real ``usage`` (input, output, cache write
  1.25x, cache read 0.1x) is priced by model tier and added to the ledger.
- Ledger: Redis ``INCRBYFLOAT gridiron:spend:<UTC day>`` (atomic, shared by
  every worker process, survives an app restart) when Redis is reachable;
  an in-process counter otherwise (per-process only — documented limit).
- ``spent_today_with_db_floor()`` (async, for the API pre-dispatch refusal)
  also takes today's ``agent_runs.cost_estimate`` sum as a floor, so a lost
  Redis key cannot reset the day to zero.

``COST_BUDGET_DAILY_USD <= 0`` disables the cap.
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_KEY_PREFIX = "gridiron:spend:"
_REDIS_RETRY_SECONDS = 30.0

_lock = threading.Lock()
_local: dict[str, float] = {}
_redis_client: Any = None
_redis_down_until = 0.0
_installed = False


class DailyBudgetExceeded(RuntimeError):
    def __init__(self, limit: float, spent: float) -> None:
        self.limit = limit
        self.spent = spent
        super().__init__(
            f"Daily LLM budget reached: ${spent:.4f} spent today, "
            f"limit ${limit:.2f} (COST_BUDGET_DAILY_USD). No further LLM calls "
            "until tomorrow (UTC) or until the limit is raised."
        )


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _redis() -> Any:
    global _redis_client, _redis_down_until
    if not get_settings().spend_guard_redis:
        return None
    if _redis_client is not None:
        return _redis_client
    if time.monotonic() < _redis_down_until:
        return None
    try:
        import redis

        client = redis.Redis.from_url(
            get_settings().redis_url, socket_timeout=0.5, socket_connect_timeout=0.5
        )
        client.ping()
        _redis_client = client
        return client
    except Exception as exc:
        _redis_down_until = time.monotonic() + _REDIS_RETRY_SECONDS
        logger.warning(
            "Spend guard: Redis unavailable, using in-process ledger: %s", exc
        )
        return None


def _redis_failed(exc: Exception) -> None:
    global _redis_client, _redis_down_until
    _redis_client = None
    _redis_down_until = time.monotonic() + _REDIS_RETRY_SECONDS
    logger.warning("Spend guard: Redis error, using in-process ledger: %s", exc)


def spent_today() -> float:
    day = _today()
    with _lock:
        local = _local.get(day, 0.0)
    client = _redis()
    if client is not None:
        try:
            raw = client.get(_KEY_PREFIX + day)
            shared = float(raw) if raw is not None else 0.0
            # The local counter can only be ahead if Redis lost writes.
            return max(shared, local)
        except Exception as exc:
            _redis_failed(exc)
    return local


def record(usd: float) -> None:
    if usd <= 0:
        return
    day = _today()
    with _lock:
        _local[day] = _local.get(day, 0.0) + usd
    client = _redis()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.incrbyfloat(_KEY_PREFIX + day, usd)
            pipe.expire(_KEY_PREFIX + day, 3 * 86400)
            pipe.execute()
        except Exception as exc:
            _redis_failed(exc)


def check() -> None:
    """Raise DailyBudgetExceeded when today's spend has reached the cap."""
    limit = get_settings().cost_budget_daily_usd
    if limit <= 0:
        return
    spent = spent_today()
    if spent >= limit:
        raise DailyBudgetExceeded(limit, spent)


async def spent_today_with_db_floor() -> float:
    """Ledger spend, floored by today's durable agent_runs cost sum."""
    import asyncio

    from sqlalchemy import func, select

    from app.db.models import AgentRun
    from app.db.session import get_session_factory

    ledger = await asyncio.to_thread(spent_today)
    try:
        start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        async with get_session_factory()() as db:
            row = await db.execute(
                select(func.coalesce(func.sum(AgentRun.cost_estimate), 0)).where(
                    AgentRun.started_at >= start
                )
            )
            db_sum = float(row.scalar_one() or 0)
    except Exception as exc:
        logger.warning("Spend guard: agent_runs floor query failed: %s", exc)
        db_sum = 0.0
    return max(ledger, db_sum)


async def check_before_dispatch() -> None:
    """Async gate for API endpoints that start LLM work."""
    limit = get_settings().cost_budget_daily_usd
    if limit <= 0:
        return
    spent = await spent_today_with_db_floor()
    if spent >= limit:
        raise DailyBudgetExceeded(limit, spent)


def cost_of(model: str, usage: Any) -> float:
    """Price one response's usage at its model's tier."""
    from app.pipeline.cost_controller import cost_rates_for_tier

    name = (model or "").lower()
    tier = "haiku" if "haiku" in name else "opus" if "opus" in name else "sonnet"
    rate_in, rate_out = cost_rates_for_tier(tier, get_settings())

    def _n(attr: str) -> int:
        val = getattr(usage, attr, 0)
        return val if isinstance(val, int) else 0

    return (
        _n("input_tokens") * rate_in
        + _n("cache_creation_input_tokens") * rate_in * 1.25
        + _n("cache_read_input_tokens") * rate_in * 0.1
        + _n("output_tokens") * rate_out
    )


def _record_response(response: Any, model: str) -> None:
    try:
        usage = getattr(response, "usage", None)
        if usage is not None:
            record(cost_of(getattr(response, "model", None) or model, usage))
    except Exception as exc:
        logger.warning("Spend guard: could not record usage: %s", exc)


class _SyncStreamGuard:
    def __init__(self, inner: Any, model: str) -> None:
        self._inner = inner
        self._model = model
        self._stream: Any = None

    def __enter__(self) -> Any:
        self._stream = self._inner.__enter__()
        return self._stream

    def __exit__(self, *exc: Any) -> Any:
        try:
            return self._inner.__exit__(*exc)
        finally:
            _record_response(
                getattr(self._stream, "current_message_snapshot", None), self._model
            )


class _AsyncStreamGuard:
    def __init__(self, inner: Any, model: str) -> None:
        self._inner = inner
        self._model = model
        self._stream: Any = None

    async def __aenter__(self) -> Any:
        self._stream = await self._inner.__aenter__()
        return self._stream

    async def __aexit__(self, *exc: Any) -> Any:
        try:
            return await self._inner.__aexit__(*exc)
        finally:
            _record_response(
                getattr(self._stream, "current_message_snapshot", None), self._model
            )


def install() -> None:
    """Wrap the Anthropic SDK message methods once per process."""
    global _installed
    if _installed:
        return
    try:
        from anthropic.resources.messages import AsyncMessages, Messages
    except Exception as exc:  # SDK layout changed — fail loudly in logs
        logger.error("Spend guard NOT installed (anthropic SDK layout): %s", exc)
        return

    orig_create = Messages.create
    orig_stream = Messages.stream
    orig_acreate = AsyncMessages.create
    orig_astream = AsyncMessages.stream

    @functools.wraps(orig_create)
    def create(self: Any, *args: Any, **kwargs: Any) -> Any:
        check()
        response = orig_create(self, *args, **kwargs)
        if not kwargs.get("stream"):
            _record_response(response, str(kwargs.get("model", "")))
        return response

    @functools.wraps(orig_stream)
    def stream(self: Any, *args: Any, **kwargs: Any) -> Any:
        check()
        return _SyncStreamGuard(
            orig_stream(self, *args, **kwargs), str(kwargs.get("model", ""))
        )

    @functools.wraps(orig_acreate)
    async def acreate(self: Any, *args: Any, **kwargs: Any) -> Any:
        import asyncio

        await asyncio.to_thread(check)
        response = await orig_acreate(self, *args, **kwargs)
        if not kwargs.get("stream"):
            await asyncio.to_thread(
                _record_response, response, str(kwargs.get("model", ""))
            )
        return response

    @functools.wraps(orig_astream)
    def astream(self: Any, *args: Any, **kwargs: Any) -> Any:
        check()
        return _AsyncStreamGuard(
            orig_astream(self, *args, **kwargs), str(kwargs.get("model", ""))
        )

    Messages.create = create  # type: ignore[method-assign]
    Messages.stream = stream  # type: ignore[method-assign]
    AsyncMessages.create = acreate  # type: ignore[method-assign]
    AsyncMessages.stream = astream  # type: ignore[method-assign]
    _installed = True
    logger.info("Spend guard installed on the Anthropic SDK")


def reset_local_for_tests() -> None:
    with _lock:
        _local.clear()
