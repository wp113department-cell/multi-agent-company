"""Architecture Mapper — LLM-prompt-driven summary of a repo's major
components and how they relate.

Gap-closure (files/GAPS_ALL_FILES_REPORT.md, 2026-07-23): REPO-FIRST research
(done before this was built) found NO static-analysis precedent for this in
any of the 10 reference repos — open-hands's agenthub/ (where the plan
expected to find one) no longer exists in the clone; continue's repo-map
(generateRepoMap.ts) is a flat file+signature list with no graph; continue's
only "architecture" handling is an LLM prompt asking the model to freehand a
prose summary from folder READMEs (onboard.ts). This module intentionally
matches that precedent — a real, novel static-analysis architecture-detection
algorithm has no prior art to build from and would be high-risk/high-effort
for uncertain payoff; a single, JSON-schema-validated LLM call over real
structural signals is the honest, minimal way to close this gap.

Inputs: folder structure (same ignore-list as scanner.py), README*.md
content, and the top-ranked files from cross_file_graph.py's real,
function-level PageRank (files a real call graph considers most central) —
a genuinely informative slice of the repo, not "dump everything at the
model."

Not a LangGraph task agent (no retries/self-correction/tool loop needed for
a one-shot summarization) — a direct Anthropic call, matching the simplest
existing precedent for that in this codebase (agents/base.py's
_make_client() + client.messages.create()), with JSON-parse-and-validate
retry on invalid output.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from app.repo_tools.cross_file_graph import build_cross_file_graph
from app.repo_tools.scanner import RepoIndex, _IGNORE_DIRS

logger = logging.getLogger(__name__)

_MAX_README_CHARS = 4000
_MAX_TOP_FILES = 20
_MAX_STRUCTURE_LINES = 200
_MAX_FOLDER_DEPTH = 3
_MAX_RETRIES = 2


class ArchitectureComponent(BaseModel):
    name: str
    description: str
    files: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class ArchitectureMap(BaseModel):
    summary: str
    components: list[ArchitectureComponent] = Field(default_factory=list)


def _gather_folder_structure(
    repo_path: str, max_depth: int = _MAX_FOLDER_DEPTH
) -> list[str]:
    """Directory tree, ignoring the same dirs scanner.py's index_repository()
    does, capped at max_depth to keep the prompt bounded."""
    base = Path(repo_path)
    entries: list[str] = []
    for root, dirs, _files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS]
        rel = Path(root).relative_to(base)
        depth = len(rel.parts)
        if depth > max_depth:
            dirs[:] = []
            continue
        if str(rel) != ".":
            entries.append(f"{'  ' * depth}{rel}/")
    return sorted(entries)


def _gather_readmes(repo_path: str) -> dict[str, str]:
    base = Path(repo_path)
    readmes: dict[str, str] = {}
    for p in base.rglob("README*.md"):
        if any(part in _IGNORE_DIRS for part in p.parts):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(p.relative_to(base))
        readmes[rel] = text[:_MAX_README_CHARS]
    return readmes


def _build_prompt(repo_path: str, index: RepoIndex) -> str:
    structure = _gather_folder_structure(repo_path)
    readmes = _gather_readmes(repo_path)
    graph_result = build_cross_file_graph(index)
    top_files = sorted(graph_result.file_rank.items(), key=lambda kv: -kv[1])[
        :_MAX_TOP_FILES
    ]

    parts = [
        "Analyze this repository's architecture from the structural signals "
        "below (folder layout, README content, and the most structurally "
        "central files per a real cross-file call graph). Identify the "
        "major components (e.g. API layer, agent orchestration, data layer, "
        "frontend) and how they relate.",
        "\n## Folder structure\n" + "\n".join(structure[:_MAX_STRUCTURE_LINES]),
    ]
    for path, text in readmes.items():
        parts.append(f"\n## README: {path}\n{text}")
    if top_files:
        parts.append(
            "\n## Most structurally central files (by real cross-file call graph)\n"
            + "\n".join(f"- {p} (rank={r:.4f})" for p, r in top_files)
        )
    return "\n".join(parts)


_SYSTEM_PROMPT = (
    "You analyze software repository architecture. Respond with ONLY a JSON "
    "object matching this exact shape, no prose before or after:\n"
    '{"summary": "<2-4 sentence overview>", "components": [{"name": "<component name>", '
    '"description": "<what it does>", "files": ["<representative file paths>"], '
    '"depends_on": ["<names of other components this one depends on>"]}]}'
)


def build_architecture_map(repo_path: str, index: RepoIndex) -> ArchitectureMap:
    """One direct Anthropic call + JSON-parse-and-validate, retried on
    invalid output. Returns a summary-only ArchitectureMap (empty
    components) if every attempt fails — callers should treat that as a
    soft failure, not raise, matching this codebase's convention for
    best-effort repo-intelligence features (e.g. embeddings.py's zero-
    vector fallback)."""
    from app.agents.base import _make_client
    from app.config import get_settings

    settings = get_settings()
    prompt = _build_prompt(repo_path, index)
    client = _make_client()

    last_error: Exception | str = "no attempts made"
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=settings.model_planner,
                max_tokens=2048,
                system=[{"type": "text", "text": _SYSTEM_PROMPT}],
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            data = json.loads(text)
            return ArchitectureMap.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            logger.warning(
                "Architecture map attempt %d/%d produced invalid JSON: %s",
                attempt + 1,
                _MAX_RETRIES + 1,
                exc,
            )
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Architecture map attempt %d/%d failed: %s",
                attempt + 1,
                _MAX_RETRIES + 1,
                exc,
            )

    logger.error(
        "Architecture map failed after %d attempts: %s", _MAX_RETRIES + 1, last_error
    )
    return ArchitectureMap(
        summary=f"Failed to generate architecture map: {last_error}", components=[]
    )
