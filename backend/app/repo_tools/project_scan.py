"""Free project overview (W1, 2026-10-09).

When a project is opened, the team should first understand it. This is the
no-AI part: it only reads files (never runs anything from the project) and
works out the languages, frameworks, how to run and test it, the top-level
structure and a few plain warnings. It is cheap and cached, and its short
text form is added to every agent's repo context (base_graph), so the
planner knows the stack and the test command from the start. A deeper AI
summary is optional and only made when the user asks (api/projects.py).
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", ".next",
    "dist", "build", ".mypy_cache", ".pytest_cache", ".ruff_cache", "target",
    ".gradle", ".idea", ".vscode", "coverage", ".tox", ".gridiron-sandbox-py",
}  # fmt: skip
_LANGS = {
    ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript",
    ".jsx": "JavaScript", ".mjs": "JavaScript", ".go": "Go", ".rs": "Rust",
    ".java": "Java", ".kt": "Kotlin", ".rb": "Ruby", ".php": "PHP", ".cs": "C#",
    ".cpp": "C++", ".cc": "C++", ".c": "C", ".h": "C", ".swift": "Swift",
    ".dart": "Dart", ".scala": "Scala", ".sql": "SQL", ".html": "HTML",
    ".css": "CSS", ".scss": "CSS", ".vue": "Vue", ".svelte": "Svelte",
    ".sh": "Shell", ".ps1": "PowerShell",
}  # fmt: skip
_JS_FRAMEWORKS = {
    "next": "Next.js", "react": "React", "vue": "Vue", "svelte": "Svelte",
    "@angular/core": "Angular", "express": "Express", "fastify": "Fastify",
    "@nestjs/core": "NestJS", "vite": "Vite", "jest": "Jest", "vitest": "Vitest",
    "@playwright/test": "Playwright", "tailwindcss": "Tailwind CSS",
    "prisma": "Prisma", "electron": "Electron", "react-native": "React Native",
}  # fmt: skip
_PY_FRAMEWORKS = {
    "django": "Django", "fastapi": "FastAPI", "flask": "Flask", "pytest": "pytest",
    "sqlalchemy": "SQLAlchemy", "pandas": "pandas", "numpy": "NumPy",
    "streamlit": "Streamlit", "celery": "Celery", "pydantic": "Pydantic",
}  # fmt: skip
_MAX_FILES = 20000
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_TTL = 300.0


def _read(path: Path, limit: int = 200_000) -> str:
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def _walk(root: Path) -> tuple[Counter[str], int, int, bool]:
    langs: Counter[str] = Counter()
    files = size = 0
    has_tests = False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        rel = os.path.relpath(dirpath, root)
        if re.search(r"(^|/)(tests?|__tests__|spec)(/|$)", rel):
            has_tests = True
        for name in filenames:
            files += 1
            if files > _MAX_FILES:
                return langs, files, size, has_tests
            if re.match(
                r"^(test_.*\.py|.*_test\.(py|go)|.*\.(test|spec)\.[jt]sx?)$", name
            ):
                has_tests = True
            lang = _LANGS.get(Path(name).suffix.lower())
            if lang:
                langs[lang] += 1
            try:
                size += (Path(dirpath) / name).stat().st_size
            except OSError:
                pass
    return langs, files, size, has_tests


def _node(root: Path, frameworks: list[str], run: list[str], test: list[str]) -> None:
    pkg = root / "package.json"
    if not pkg.is_file():
        return
    try:
        data = json.loads(_read(pkg))
    except ValueError:
        return
    deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    frameworks += [label for dep, label in _JS_FRAMEWORKS.items() if dep in deps]
    scripts = data.get("scripts") or {}
    manager = (
        "pnpm"
        if (root / "pnpm-lock.yaml").exists()
        else "yarn" if (root / "yarn.lock").exists() else "npm"
    )
    for name in ("dev", "start", "serve"):
        if name in scripts:
            run.append(f"{manager} run {name}")
            break
    if "test" in scripts:
        test.append(f"{manager} test")


def _python(root: Path, frameworks: list[str], run: list[str], test: list[str]) -> None:
    text = " ".join(
        _read(root / name).lower()
        for name in ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile")
    )
    if not text.strip() and not (root / "manage.py").exists():
        return
    frameworks += [
        label for dep, label in _PY_FRAMEWORKS.items() if re.search(rf"\b{dep}\b", text)
    ]
    if (root / "manage.py").exists():
        run.append("python manage.py runserver")
    elif "fastapi" in text:
        run.append("uvicorn <module>:app --reload")
    if "pytest" in text or (root / "pytest.ini").exists():
        test.append("pytest")


def _other(root: Path, frameworks: list[str], run: list[str], test: list[str]) -> None:
    if (root / "go.mod").exists():
        frameworks.append("Go modules")
        run.append("go run .")
        test.append("go test ./...")
    if (root / "Cargo.toml").exists():
        frameworks.append("Cargo")
        run.append("cargo run")
        test.append("cargo test")
    if (root / "pom.xml").exists():
        frameworks.append("Maven")
        test.append("mvn test")
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        frameworks.append("Gradle")
        test.append("./gradlew test")
    makefile = _read(root / "Makefile")
    if makefile:
        targets = set(re.findall(r"^([A-Za-z][\w-]*):", makefile, re.M))
        if "test" in targets:
            test.append("make test")
        if "run" in targets or "dev" in targets:
            run.append("make run" if "run" in targets else "make dev")
    if (root / "docker-compose.yml").exists() or (root / "compose.yaml").exists():
        frameworks.append("Docker Compose")
        run.append("docker compose up")
    elif (root / "Dockerfile").exists():
        frameworks.append("Docker")


def scan_project(folder: str) -> dict[str, Any]:
    """The free overview of the project in `folder` (cached for 5 minutes)."""
    now = time.monotonic()
    hit = _CACHE.get(folder)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    root = Path(folder)
    if not root.is_dir():
        return {"ok": False, "error": "The project folder was not found."}
    langs, files, size, has_tests = _walk(root)
    frameworks: list[str] = []
    run: list[str] = []
    test: list[str] = []
    _node(root, frameworks, run, test)
    _python(root, frameworks, run, test)
    _other(root, frameworks, run, test)
    try:
        top = sorted(
            (p.name + ("/" if p.is_dir() else ""))
            for p in root.iterdir()
            if p.name not in _SKIP_DIRS and not p.name.startswith(".")
        )
    except OSError:
        top = []
    readme = next(
        (p for p in root.iterdir() if p.name.lower().startswith("readme")), None
    )
    title = ""
    if readme is not None and readme.is_file():
        for line in _read(readme, 4000).splitlines():
            if line.strip().strip("#").strip():
                title = line.strip().strip("#").strip()[:120]
                break
    warnings: list[str] = []
    if files == 0:
        warnings.append("The folder is empty: this is a new project.")
    else:
        if readme is None:
            warnings.append("No README: there is no description of the project.")
        if not has_tests and not test:
            warnings.append("No tests found.")
        if (root / ".env").exists() and not (root / ".env.example").exists():
            warnings.append("A .env file exists but no .env.example documents it.")
    if files > _MAX_FILES:
        warnings.append(
            f"Large project: only the first {_MAX_FILES} files were scanned."
        )
    overview = {
        "ok": True,
        "title": title,
        "languages": [name for name, _ in langs.most_common(6)],
        "frameworks": list(dict.fromkeys(frameworks)),
        "runCommands": list(dict.fromkeys(run)),
        "testCommands": list(dict.fromkeys(test)),
        "topLevel": top[:25],
        "fileCount": min(files, _MAX_FILES),
        "sizeBytes": size,
        "hasTests": has_tests or bool(test),
        "warnings": warnings,
    }
    _CACHE[folder] = (now, overview)
    return overview


def overview_text(folder: str) -> str:
    """A few lines for an agent's context; "" when nothing useful."""
    o = scan_project(folder)
    if not o.get("ok") or not o.get("fileCount"):
        return ""
    lines = ["## Project overview (free scan)"]
    if o["languages"]:
        lines.append("Languages: " + ", ".join(o["languages"]))
    if o["frameworks"]:
        lines.append("Frameworks/tools: " + ", ".join(o["frameworks"]))
    if o["runCommands"]:
        lines.append("Run: " + "; ".join(o["runCommands"]))
    if o["testCommands"]:
        lines.append("Test: " + "; ".join(o["testCommands"]))
    if o["topLevel"]:
        lines.append("Top level: " + ", ".join(o["topLevel"][:15]))
    if o["warnings"]:
        lines.append("Notes: " + " ".join(o["warnings"]))
    return "\n".join(lines)[:1500]


def reset_cache() -> None:
    """Test-only."""
    _CACHE.clear()
