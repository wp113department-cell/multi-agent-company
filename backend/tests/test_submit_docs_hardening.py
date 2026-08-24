"""submit_docs tool #85 — tool_enhance.md productionization pass
(2026-08-24).

No security vulnerability and no functional bug found. This is a pure
in-memory result sink shared identically by four real implementations
(`make_doc_generator_handlers`, `make_docs_handlers`,
`make_readme_agent_handlers`, `make_api_docs_agent_handlers`) plus
`app/agents/architecture_doc_agent.py`'s reuse of `make_docs_handlers`'
own entry. Unified into one shared `make_submit_docs_handler()` factory
in `app.tools.agents.submit_docs` purely for maintainability — the
four bodies were already functionally identical, differing only in
cosmetic return-message text that no existing test asserts on.

Not in `CHAT_TOOLS` — confirmed this is intentional (a batch-agent
final-answer tool, never exposed to the interactive chat session).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.architecture_doc_agent import make_architecture_doc_handlers
from app.agents.tools import (
    CHAT_TOOLS,
    make_api_docs_agent_handlers,
    make_doc_generator_handlers,
    make_docs_handlers,
    make_readme_agent_handlers,
)
from app.tools.agents.submit_docs import SUBMIT_DOCS_TOOL, make_submit_docs_handler


def test_submit_docs_tool_schema_requires_files_written_and_summary() -> None:
    assert SUBMIT_DOCS_TOOL["name"] == "submit_docs"
    assert SUBMIT_DOCS_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "files_written",
        "summary",
    ]


def test_submit_docs_is_not_in_chat_tools() -> None:
    """Intentional — a batch-agent final-answer tool, not for interactive chat."""
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_docs" not in names


def test_make_submit_docs_handler_stores_into_the_given_dict() -> None:
    docs_result: dict = {}
    handler = make_submit_docs_handler(docs_result)
    result = handler({"files_written": ["docs/a.md"], "summary": "wrote a.md"})
    assert result == "Docs submitted"
    assert docs_result == {"files_written": ["docs/a.md"], "summary": "wrote a.md"}


def test_make_submit_docs_handler_uses_the_dict_it_was_given_not_a_copy() -> None:
    """Real callers pass their own per-instance dict and read it back via
    handlers["_docs_result"] after the run — the handler must mutate
    that exact object, not an internal copy."""
    docs_result: dict = {}
    handler = make_submit_docs_handler(docs_result)
    handler({"files_written": [], "summary": "x"})
    assert docs_result["summary"] == "x"


@pytest.mark.parametrize(
    "factory_name,factory,args_builder",
    [
        ("doc_generator", make_doc_generator_handlers, lambda repo: (repo,)),
        ("docs_agent", make_docs_handlers, lambda repo: (repo, repo)),
        ("readme_agent", make_readme_agent_handlers, lambda repo: (repo,)),
        ("api_docs_agent", make_api_docs_agent_handlers, lambda repo: (repo,)),
    ],
)
def test_all_four_factories_store_real_submission(
    tmp_path: Path, factory_name: str, factory, args_builder
) -> None:
    handlers = factory(*args_builder(str(tmp_path)))
    result = handlers["submit_docs"](
        {"files_written": ["docs/real.md"], "summary": "a real summary"}
    )
    assert result == "Docs submitted", f"{factory_name}: unexpected return message"
    assert handlers["_docs_result"] == {
        "files_written": ["docs/real.md"],
        "summary": "a real summary",
    }


def test_architecture_doc_agent_reuses_docs_handlers_submit_docs(
    tmp_path: Path,
) -> None:
    """architecture_doc_agent.py reuses make_docs_handlers()'s own
    submit_docs entry directly — not a fifth separate implementation."""
    handlers = make_architecture_doc_handlers(str(tmp_path))
    result = handlers["submit_docs"](
        {"files_written": ["ARCHITECTURE.md"], "summary": "wrote architecture doc"}
    )
    assert result == "Docs submitted"
    assert handlers["_docs_result"]["summary"] == "wrote architecture doc"


def test_docs_results_are_isolated_per_factory_call(tmp_path: Path) -> None:
    """Two separate real agent instances must never share state."""
    h1 = make_doc_generator_handlers(str(tmp_path))
    h2 = make_doc_generator_handlers(str(tmp_path))
    h1["submit_docs"]({"files_written": ["a.md"], "summary": "first"})
    assert h2["_docs_result"] == {}
    h2["submit_docs"]({"files_written": ["b.md"], "summary": "second"})
    assert h1["_docs_result"]["summary"] == "first"
    assert h2["_docs_result"]["summary"] == "second"
