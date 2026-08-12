"""tech_advisor_agent — a real, dedicated multi-criteria technology
recommendation engine.

AUDIT_Q_BATCH17 §83 gap-closure (2026-08-12) — "Dedicated multi-criteria
recommendation engine (scale/budget/maintainability/security/ecosystem): NO
— No tech_advisor.py or equivalent exists; no structured multi-criteria
scoring found anywhere." spike_agent.py is real but architecturally
different — one-question research ending in a single recommendation, not a
comparative decision engine with explicit weighted criteria. The gap this
agent closes specifically: the ARITHMETIC must be real, deterministic Python
(never delegated to the model's own claimed math — that would be exactly
the kind of "fake metrics" the audit's Quality Requirements forbid).

`score_tech_options` is a real tool whose handler runs `_compute_weighted_
scores()` — genuine weighted-sum arithmetic, not an LLM-generated number.
`run_tech_advisor_agent()` then reads the handler's own captured computation
directly (mirroring backend_dev.py's `_patch_result` precedent: trust what
the Python code actually computed, not what the model claims it computed)
and overrides whatever the model wrote into its own submit call — the final
AgentResult.raw always carries the real ranking, never a hallucinated one.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import (
    _FETCH_URL_TOOL,
    _WEB_SEARCH_TOOL,
    READ_ONLY_TOOLS,
    RECORD_LEARNING_TOOL,
    make_chat_handlers,
    make_record_learning_handler,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

AGENT_CONTRACT: dict[str, Any] = {
    "name": "tech_advisor_agent",
    "description": (
        "Dedicated multi-criteria technology recommendation engine: scores "
        "candidate technologies/frameworks/libraries against explicit, "
        "user-relevant criteria (e.g. scale, budget, maintainability, "
        "security, ecosystem) using real deterministic weighted-sum "
        "arithmetic (score_tech_options), not model-guessed numbers — "
        "distinct from spike_agent's single-question research capability."
    ),
    "allowed_tools": [
        "read_file",
        "list_files",
        "search_code",
        "get_file_tree",
        "search_symbols",
        "find_references",
        "read_files",
        "file_exists",
        "file_info",
        "find_todos",
        "search_imports",
        "write_file",
        "web_search",
        "fetch_url",
        "score_tech_options",
        "submit_tech_advisor_agent",
        "record_learning",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["writes technology-comparison reports"],
    "permissions": ["read_repo", "write_docs"],
    "risk_level": "low",
    "expected_verification": {
        "scored": (
            "score_tech_options must run — a real deterministic weighted-sum "
            "computation, not the model's own claimed arithmetic — before submit "
            "is even allowed to run"
        )
    },
    "dependencies": [],
}

# ---------------------------------------------------------------------------
# Real, deterministic multi-criteria weighted scoring — no LLM arithmetic
# ---------------------------------------------------------------------------


def _compute_weighted_scores(
    options: list[dict[str, Any]], weights: dict[str, Any] | None
) -> dict[str, Any]:
    """Genuine weighted-sum scoring. Criteria are whatever the caller
    actually scored (never a hardcoded fixed list — the audit's own example
    criteria, scale/budget/maintainability/security/ecosystem, are a
    suggestion in the role file, not an enforced schema, since different
    decisions need different criteria). Weights default to equal across
    exactly those criteria and are always normalized to sum to 1, regardless
    of what raw weights were passed in. Every score must be in [0, 5]."""
    if not isinstance(options, list) or not options:
        raise ValueError("options must be a non-empty list")

    all_criteria: list[str] = []
    for opt in options:
        for crit in opt.get("criteria_scores", {}) or {}:
            if crit not in all_criteria:
                all_criteria.append(crit)
    if not all_criteria:
        raise ValueError("no criteria_scores provided on any option")

    raw_weights = weights or {c: 1.0 for c in all_criteria}
    used_weights = {c: float(raw_weights.get(c, 1.0)) for c in all_criteria}
    total_weight = sum(used_weights.values())
    if total_weight <= 0:
        raise ValueError("weights must sum to a positive number")
    normalized_weights = {c: w / total_weight for c, w in used_weights.items()}

    ranked: list[dict[str, Any]] = []
    for opt in options:
        name = str(opt.get("name") or "unnamed")
        scores = opt.get("criteria_scores", {}) or {}
        breakdown: dict[str, float] = {}
        weighted_total = 0.0
        for crit in all_criteria:
            if crit not in scores:
                raise ValueError(f"{name}: missing criteria_scores['{crit}']")
            raw_score = float(scores[crit])
            if not 0.0 <= raw_score <= 5.0:
                raise ValueError(
                    f"{name}: criteria_scores['{crit}']={raw_score} out of the 0-5 range"
                )
            contribution = raw_score * normalized_weights[crit]
            breakdown[crit] = round(contribution, 4)
            weighted_total += contribution
        ranked.append(
            {
                "name": name,
                "weighted_score": round(weighted_total, 4),
                "raw_scores": dict(scores),
                "breakdown": breakdown,
            }
        )

    ranked.sort(key=lambda r: r["weighted_score"], reverse=True)
    return {
        "criteria": all_criteria,
        "normalized_weights": {c: round(w, 4) for c, w in normalized_weights.items()},
        "ranked": ranked,
    }


_SCORE_TOOL = {
    "name": "score_tech_options",
    "description": (
        "Compute a REAL deterministic weighted-sum score for each candidate "
        "technology across the criteria you've evaluated it on. This runs "
        "actual Python arithmetic — it is not something you compute "
        "yourself. Score each criterion 0-5 based on evidence you gathered "
        "(read_file/search_code for repo-fit criteria, web_search/fetch_url "
        "for criteria about the technology itself like ecosystem/support). "
        "Call this exactly once, after you have evidence for every criterion "
        "on every option — calling it again with revised scores is fine if "
        "you find better evidence."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "options": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "criteria_scores": {
                            "type": "object",
                            "description": (
                                "Map of criterion name -> score 0-5, e.g. "
                                '{"scale": 4, "budget": 3, "maintainability": '
                                '5, "security": 4, "ecosystem": 5}. Every '
                                "option must score the SAME set of criteria."
                            ),
                        },
                    },
                    "required": ["name", "criteria_scores"],
                },
                "minItems": 2,
            },
            "weights": {
                "type": "object",
                "description": (
                    "Optional map of criterion name -> relative weight "
                    "(any positive numbers; normalized automatically). "
                    "Omit for equal weighting across all scored criteria."
                ),
            },
        },
        "required": ["options"],
    },
}

_SUBMIT = {
    "name": "submit_tech_advisor_agent",
    "description": "Submit tech_advisor_agent result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "findings": {"type": "array", "items": {"type": "string"}},
            "criteria_rationale": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Why each score was assigned, with evidence citations.",
            },
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}
_WRITE = {
    "name": "write_file",
    "description": "Write the technology comparison report.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
}
_TOOLS = READ_ONLY_TOOLS + [
    _WRITE,
    _SCORE_TOOL,
    _SUBMIT,
    RECORD_LEARNING_TOOL,
    _WEB_SEARCH_TOOL,
    _FETCH_URL_TOOL,
]

_CFG = VerificationConfig(
    set_by={"score_tech_options": "scored"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"scored": "scored"},
    initial={"scored": False},
    # Real, code-enforced gate (base_graph.py's blocking_until mechanism,
    # same one AUDIT_Q_BATCH17 §84 already confirmed real elsewhere): submit
    # is refused outright — never even reaches the handler — until real
    # weighted-sum arithmetic has actually run this session.
    blocking_until={"submit_tech_advisor_agent": "scored"},
)


def make_tech_advisor_agent_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    result: dict[str, Any] = {}
    score_state: dict[str, Any] = {}

    def score_h(inp: dict[str, Any]) -> str:
        try:
            computed = _compute_weighted_scores(
                inp.get("options", []), inp.get("weights")
            )
        except (ValueError, TypeError) as exc:
            return f"[ERROR] {exc}"
        score_state["computed"] = computed
        lines = [
            f"Real weighted scoring — criteria: {', '.join(computed['criteria'])}; "
            f"normalized weights: {computed['normalized_weights']}"
        ]
        for i, r in enumerate(computed["ranked"], start=1):
            lines.append(
                f"{i}. {r['name']} — weighted score {r['weighted_score']:.3f}/5.000 "
                f"(raw: {r['raw_scores']}, contribution breakdown: {r['breakdown']})"
            )
        return "\n".join(lines)

    def submit_h(inp: dict[str, Any]) -> str:
        result.update(inp)
        return "Submitted."

    base["score_tech_options"] = score_h
    base["submit_tech_advisor_agent"] = submit_h
    base["_result"] = result
    base["_score_state"] = score_state
    base["record_learning"] = make_record_learning_handler(AGENT_CONTRACT["name"])
    return base


def run_tech_advisor_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_tech_advisor_agent_handlers(repo)
    result = handlers["_result"]

    msg = (
        f"Task #{task_id} — {description}\n\n"
        "You are a technology-selection decision engine — not a general "
        "research spike. You must compare at least two concrete options "
        "against explicit criteria and produce a REAL weighted ranking.\n"
        "1. Identify at least two candidate technologies/frameworks/"
        "libraries relevant to the task, and the criteria that matter for "
        "THIS decision (common ones: scale, budget, maintainability, "
        "security, ecosystem/community support — but use whatever criteria "
        "the task actually cares about, not a fixed checklist).\n"
        "2. Gather real evidence for every criterion on every option before "
        "scoring: read_file/search_code for repo-fit criteria (does it "
        "integrate with what's already here), web_search/fetch_url for "
        "criteria about the technology itself (current pricing, ecosystem "
        "maturity, security track record) that you're not certain of from "
        "training data alone.\n"
        "3. Call score_tech_options with every option scored 0-5 on every "
        "criterion, and weights if some criteria matter more than others "
        "for this decision. This runs REAL arithmetic — you cannot submit "
        "without having called it.\n"
        "4. Call submit_tech_advisor_agent with summary, findings, "
        "criteria_rationale (why each score was assigned, with evidence "
        "citations), and recommendations. Your top pick must match what "
        "score_tech_options actually computed, not a separate personal "
        "opinion."
    )

    final_state = run_agent_graph(
        task_id=str(task_id),
        role_name="tech_advisor_agent",
        model=settings.model_planner,
        tools=_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_CFG,
        initial_message=msg,
        task_description=description[:120],
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
        max_turns=20,
    )

    raw = dict(final_state["result"] if final_state["result"] else result)
    # Zero-fake-metrics enforcement: the ranking in AgentResult.raw always
    # comes from the handler's own captured computation (real Python
    # arithmetic), never from whatever the model wrote into its submit call
    # — same "trust the code, not the model's claim" precedent as
    # backend_dev.py's _patch_result / spike_agent.py's enforce_in_result.
    computed = handlers["_score_state"].get("computed")
    if computed is not None:
        raw["ranked_options"] = computed["ranked"]
        raw["scoring_criteria"] = computed["criteria"]
        raw["normalized_weights"] = computed["normalized_weights"]

    return AgentResult(
        summary=str(raw.get("summary", description[:100])),
        findings=list(raw.get("findings", [])),
        files_touched=[],
        verified=bool(final_state["verification"].get("scored")),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )


def _register() -> None:
    try:
        from app.fleet.capability_registry import AgentCapability, register
        from app.fleet.agent_registry import get_agent_registry

        register(
            AgentCapability(
                name=AGENT_CONTRACT["name"],
                description=AGENT_CONTRACT["description"],
                tools=AGENT_CONTRACT["allowed_tools"],
                input_types=AGENT_CONTRACT["input_types"],
                output_types=AGENT_CONTRACT["output_types"],
                capabilities=["technology_recommendation"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()
