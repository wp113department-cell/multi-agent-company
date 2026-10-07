"""Plain-language catalog of the built-in agents, for the Agents page.

Categories follow the project's own fleet directory (PROJECT_MASTER_GUIDE §5).
An agent missing from the map is shown under "Specialized engineering", so a
newly added agent always appears, never silently disappears.
"""

from __future__ import annotations

from typing import Any

CATEGORIES: list[tuple[str, str, list[str]]] = [
    (
        "Leadership & planning",
        "Turn a goal into a plan and coordinate the work.",
        [
            "pm",
            "architect",
            "decomposer",
            "planner",
            "executive",
            "manager",
            "research",
            "sprint_planner",
            "cost_estimator_agent",
            "spike_agent",
            "roadmap_agent",
            "business_analyst",
            "user_story_generator",
        ],
    ),
    (
        "Developers",
        "Write and change the code.",
        [
            "coder",
            "backend_dev",
            "frontend_dev",
            "mobile_dev",
            "ai_engineer",
            "bug_fix",
            "refactor_agent",
            "cleanup_agent",
            "pair_programmer_agent",
            "chat_agent",
        ],
    ),
    (
        "Code quality & review",
        "Review the work and keep the code healthy.",
        [
            "reviewer",
            "code_quality_agent",
            "style_reviewer",
            "architecture_reviewer",
            "performance_reviewer",
            "tech_debt_agent",
            "debugger_agent",
            "code_explainer_agent",
        ],
    ),
    (
        "Testing",
        "Prove the code works.",
        [
            "qa",
            "test_writer_agent",
            "test_coverage_agent",
            "evaluation_agent",
            "load_test_agent",
        ],
    ),
    (
        "Security & compliance",
        "Find risks before they ship.",
        [
            "security_reviewer",
            "security_architect",
            "compliance_agent",
            "dependency_security_agent",
            "env_checker_agent",
        ],
    ),
    (
        "DevOps & reliability",
        "Build, deploy and keep things running.",
        [
            "devops",
            "docker_agent",
            "cicd_agent",
            "infra_agent",
            "monitoring_agent",
            "incident_responder_agent",
            "rollback_agent",
            "runbook_generator_agent",
            "slo_agent",
        ],
    ),
    (
        "Data & databases",
        "Design and change data storage.",
        [
            "database_architect",
            "schema_agent",
            "sql_agent",
            "migration_agent",
            "data_pipeline_agent",
            "rag_engineer_agent",
        ],
    ),
    (
        "Documentation",
        "Explain the project to people.",
        [
            "docs",
            "readme_agent",
            "api_docs_agent",
            "changelog_agent",
            "release_notes_agent",
            "onboarding_agent",
            "agent_roster_doc_agent",
            "architecture_doc_agent",
            "tool_catalog_doc_agent",
            "deployment_guide_doc_agent",
            "migration_guide_doc_agent",
        ],
    ),
    (
        "Self-improvement",
        "Watch the team and suggest improvements.",
        [
            "agent_advisor",
            "agent_debugger",
            "agent_performance_reviewer",
            "quality_auditor",
            "knowledge_curator",
            "barot_agent",
        ],
    ),
    (
        "Specialized engineering",
        "Experts for specific topics.",
        [
            "devex_agent",
            "accessibility_agent",
            "localization_agent",
            "feature_flag_agent",
            "api_designer_agent",
            "version_manager_agent",
            "dependency_agent",
            "ux_design_agent",
            "tech_advisor_agent",
            "prompt_engineer_agent",
            "agentic_ai_architect",
            "mcp_developer_agent",
        ],
    ),
]

_CATEGORY_OF = {name: cat for cat, _, names in CATEGORIES for name in names}
_DEFAULT_CATEGORY = "Specialized engineering"


def display_name(name: str) -> str:
    """'backend_dev' -> 'Backend Dev', 'qa' -> 'QA', 'pm' -> 'PM'."""
    special = {
        "qa": "QA",
        "pm": "PM",
        "ai": "AI",
        "api": "API",
        "sql": "SQL",
        "slo": "SLO",
        "cicd": "CI/CD",
        "ux": "UX",
        "rag": "RAG",
        "mcp": "MCP",
        "devops": "DevOps",
        "devex": "DevEx",
    }
    words = [w for w in name.split("_") if w != "agent"] or [name]
    return " ".join(special.get(w, w.capitalize()) for w in words)


def build_catalog() -> dict[str, Any]:
    """Every registered built-in agent, grouped by category."""
    from app.fleet.agent_registry import get_agent_registry
    from app.fleet.capability_registry import (
        ensure_all_agents_registered,
        get_capability_registry,
    )

    ensure_all_agents_registered()
    registry = get_agent_registry()
    agents: dict[str, list[dict[str, Any]]] = {}
    for cap in sorted(get_capability_registry().all(), key=lambda c: c.name):
        instance = registry.get(cap.name)
        category = _CATEGORY_OF.get(cap.name, _DEFAULT_CATEGORY)
        agents.setdefault(category, []).append(
            {
                "name": cap.name,
                "displayName": display_name(cap.name),
                "purpose": cap.description,
                "tools": list(cap.tools),
                "capabilities": list(cap.capabilities),
                "available": bool(instance.is_available) if instance else True,
                "state": instance.state.value if instance else "available",
                "risk": cap.risk_level,
            }
        )
    order = [c for c, _, _ in CATEGORIES]
    return {
        "total": sum(len(v) for v in agents.values()),
        "categories": [
            {
                "name": cat,
                "description": next((d for c, d, _ in CATEGORIES if c == cat), ""),
                "count": len(agents[cat]),
                "agents": agents[cat],
            }
            for cat in order
            if cat in agents
        ],
    }
