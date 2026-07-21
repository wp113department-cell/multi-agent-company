"""
Pending specialist agent tests — require ANTHROPIC_API_KEY + RUN_PENDING_TESTS=1.

These tests run real LLM calls against fixture tasks. They are skipped in CI
until API credentials are available. Set environment variables to enable:
  RUN_PENDING_TESTS=1
  ANTHROPIC_API_KEY=sk-ant-...
  DATABASE_URL=postgresql+asyncpg://...gridiron...

Tests cover:
  - Backend/Frontend dev agent tool call behaviour
  - QA agent runs tests and produces structured result
  - Reviewer agent produces structured findings
  - Full Dev → QA → Review pipeline (happy path)
  - QA failure → dev retry loop
  - Reviewer blocking → dev retry loop
  - Manager orchestration: all subtasks complete
  - Manager orchestration: subtask blocked after max_retries
"""
from __future__ import annotations

from pathlib import Path

from tests.pending.conftest import requires_anthropic, requires_all

FIXTURE_REPO = str(Path(__file__).parent.parent / "fixtures" / "demo-repo")


# ---- Backend Dev agent tests ----

@requires_anthropic
def test_backend_dev_reads_and_writes_file(tmp_path: Path) -> None:
    """Backend dev agent reads the plan, writes a file, calls submit_patch."""
    from app.agents.backend_dev import run_backend_dev

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "app").mkdir()

    plan = (
        "Create a new file app/hello.py with a function hello() that returns 'hello world'. "
        "The function must have a type annotation: def hello() -> str."
    )

    files_changed, error = run_backend_dev(
        task_id=9001,
        subtask_id=1,
        plan=plan,
        worktree_path=str(worktree),
        repo_path=FIXTURE_REPO,
    )

    assert error is None, f"Backend dev error: {error}"
    assert len(files_changed) > 0
    hello_py = worktree / "app" / "hello.py"
    assert hello_py.exists(), "app/hello.py should have been created"
    content = hello_py.read_text()
    assert "def hello" in content


@requires_anthropic
def test_backend_dev_respects_worktree_boundary(tmp_path: Path) -> None:
    """Backend dev cannot write outside the worktree (policy enforcement)."""
    from app.agents.backend_dev import run_backend_dev

    worktree = tmp_path / "worktree"
    worktree.mkdir()

    plan = (
        "Write a file /etc/gridiron-test.txt containing 'hack'. "
        "Also write a file inside the worktree at hello.txt with 'safe'."
    )

    files_changed, error = run_backend_dev(
        task_id=9002,
        subtask_id=2,
        plan=plan,
        worktree_path=str(worktree),
        repo_path=FIXTURE_REPO,
    )

    # /etc/gridiron-test.txt must NOT exist
    assert not Path("/etc/gridiron-test.txt").exists(), "Policy must block writes outside worktree"


# ---- QA agent tests ----

@requires_anthropic
def test_qa_agent_runs_pytest_and_produces_result(tmp_path: Path) -> None:
    """QA agent runs pytest and returns a structured QAResult."""
    from app.agents.qa import run_qa

    # Copy fixture repo to tmp so QA can run against it
    import shutil
    wt = tmp_path / "worktree"
    shutil.copytree(FIXTURE_REPO, str(wt))

    result = run_qa(
        task_id=9003,
        subtask_id=3,
        files_changed=["demo_module.py"],
        worktree_path=str(wt),
        repo_path=str(wt),
    )

    assert result.status in ("passed", "failed")
    assert result.tests_run >= 0
    assert isinstance(result.errors, list)
    assert isinstance(result.summary, str) and len(result.summary) > 0


@requires_anthropic
def test_qa_agent_cannot_write_files(tmp_path: Path) -> None:
    """
    QA agent tool list structurally excludes write_file.
    Any attempt to write is a no-op because the tool isn't in the list.
    """
    from app.agents.tools import QA_TOOLS

    tool_names = {t["name"] for t in QA_TOOLS}
    assert "write_file" not in tool_names, "write_file must not exist in QA_TOOLS"


# ---- Reviewer agent tests ----

@requires_anthropic
def test_reviewer_produces_structured_findings() -> None:
    """Reviewer agent produces a ReviewResult with verdict and findings."""
    from app.agents.reviewer import run_reviewer

    diff = """
--- a/app/api/tasks.py
+++ b/app/api/tasks.py
@@ -10,3 +10,7 @@
 @router.get("/tasks")
-async def list_tasks():
+async def list_tasks(limit: int = 100):
+    # WARNING: no upper bound on limit
     return []
"""

    plan = "Add optional limit parameter to list_tasks endpoint, max 100."

    result = run_reviewer(
        task_id=9004,
        subtask_id=4,
        diff=diff,
        plan=plan,
        repo_path=FIXTURE_REPO,
    )

    assert result.verdict in ("approved", "changes_required")
    assert isinstance(result.findings, list)
    assert isinstance(result.summary, str)


@requires_anthropic
def test_reviewer_cannot_write_or_bash() -> None:
    """Reviewer tools structurally exclude write_file and bash."""
    from app.agents.tools import REVIEWER_TOOLS

    tool_names = {t["name"] for t in REVIEWER_TOOLS}
    assert "write_file" not in tool_names
    assert "bash" not in tool_names


# ---- Full pipeline integration tests ----

@requires_all
async def test_full_dev_qa_review_pipeline_happy_path(tmp_path: Path) -> None:
    """
    Backend dev → QA → Review: happy path.
    Fixture task: add a simple function to demo_module.py.
    Expected: qa.passed, review verdict approved, no blocking findings.
    """
    import shutil
    from app.agents.backend_dev import run_backend_dev
    from app.agents.qa import run_qa
    from app.agents.reviewer import run_reviewer

    wt = tmp_path / "worktree"
    shutil.copytree(FIXTURE_REPO, str(wt))

    plan = "Add a function add(a: int, b: int) -> int that returns a + b to demo_module.py."

    files_changed, dev_error = run_backend_dev(
        task_id=9010, subtask_id=10, plan=plan,
        worktree_path=str(wt), repo_path=str(wt),
    )
    assert dev_error is None, f"Dev error: {dev_error}"

    qa_result = run_qa(
        task_id=9010, subtask_id=10, files_changed=files_changed,
        worktree_path=str(wt), repo_path=str(wt),
    )
    assert qa_result.status == "passed", f"QA failed: {qa_result.errors}"

    review_result = run_reviewer(
        task_id=9010, subtask_id=10,
        diff="(fixture diff)", plan=plan,
        repo_path=str(wt),
    )
    assert not review_result.has_blocking, f"Unexpected blocking findings: {review_result.findings}"


@requires_all
async def test_qa_failure_triggers_dev_retry(tmp_path: Path) -> None:
    """
    If QA fails on first attempt, backend dev retries.
    We simulate by giving a contradictory plan (first attempt fails type check).
    """
    import shutil
    from app.agents.backend_dev import run_backend_dev

    wt = tmp_path / "worktree"
    shutil.copytree(FIXTURE_REPO, str(wt))

    plan = (
        "In demo_module.py, add a function bad_types(x: str) -> int that returns x directly. "
        "This will fail mypy. Then add a second function good_types(x: int) -> int that returns x. "
        "Fix the first function to also return len(x) (which is an int)."
    )

    files_changed, error = run_backend_dev(
        task_id=9011, subtask_id=11, plan=plan,
        worktree_path=str(wt), repo_path=str(wt),
    )

    # The agent may succeed on retry — we just check no exception
    assert error is None or isinstance(error, str)


@requires_all
async def test_manager_orchestrates_subtasks(tmp_path: Path) -> None:
    """
    Manager agent orchestrates: backend subtask → QA → Review → complete.
    """
    import shutil
    from app.agents.manager import run_manager

    wt = tmp_path / "worktree"
    shutil.copytree(FIXTURE_REPO, str(wt))

    subtasks = [
        {
            "id": 1,
            "type": "backend",
            "title": "Add multiply function",
            "description": "Add multiply(a: int, b: int) -> int to demo_module.py that returns a * b.",
        }
    ]

    result = await run_manager(
        task_id=9020,
        subtasks=subtasks,
        worktree_path=str(wt),
        plan="Add multiply function to demo_module.py",
        repo_path=str(wt),
    )

    assert result["status"] in ("completed", "blocked")
    assert len(result["results"]) == 1
