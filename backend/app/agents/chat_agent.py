"""Interactive streaming chat agent — the core of the conversational interface."""
from __future__ import annotations

import asyncio
import logging
import subprocess
import uuid
from pathlib import Path
from typing import Any, cast

import anthropic
from anthropic.types import (
    MessageParam,
    RawContentBlockDeltaEvent,
    TextDelta,
    ToolParam,
)

from app.agents.base import get_effective_api_key
from app.agents.base_graph import VerificationConfig
from app.agents.tools import CHAT_TOOLS, _is_dangerous_command, _is_protected_path
from app.config import get_settings
from app.models.chat import ChatSession
from app.repo_tools import ast_engine as _ast_engine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fleet OS capability declaration.
#
# ChatAgent is an interactive, open-ended, multi-turn session (not a single-shot
# run_agent_graph task) — dangerous tool calls already gate on
# session.request_confirmation() instead of a post-hoc VerificationConfig state
# machine. AGENT_CONTRACT/_register() exist so the fleet capability_registry can
# discover it like every other agent; VerificationConfig documents the same
# read/write verification semantics the other 67 agents declare, for parity.
# ---------------------------------------------------------------------------

AGENT_CONTRACT: dict[str, Any] = {
    "name": "chat_agent",
    "description": "Interactive streaming chat agent — full agentic loop over the repo (read/search/edit/git/test/db/docker) with human confirmation gating dangerous actions.",
    "allowed_tools": [t["name"] for t in CHAT_TOOLS],
    "input_types": ["chat_session", "user_message"],
    "output_types": ["streamed_events", "AgentResult"],
    "side_effects": ["reads/writes repo files", "runs bash", "runs git (incl. push, with confirmation)"],
    "permissions": ["read_repo", "write_repo", "execute_bash", "git_write"],
    "risk_level": "high",
    "expected_verification": {"read": "read_file or search_code must run before write/bash tools"},
    "dependencies": [],
}

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "run_tests": "tests_passed", "run_linter": "lint_ran",
        "git_diff": "diff_checked", "read_file": "read", "search_code": "read",
    },
    reset_by=("write_file", "edit_file", "apply_patch"),
    reset_keys=("tests_passed",),
    enforce_in_result={"read": "read"},
    initial={"read": False, "tests_passed": False, "lint_ran": False, "diff_checked": False},
)


def _register() -> None:
    try:
        from app.fleet.capability_registry import AgentCapability, register
        from app.fleet.agent_registry import get_agent_registry
        register(AgentCapability(
            name=AGENT_CONTRACT["name"],
            description=AGENT_CONTRACT["description"],
            tools=AGENT_CONTRACT["allowed_tools"],
            input_types=AGENT_CONTRACT["input_types"],
            output_types=AGENT_CONTRACT["output_types"],
            capabilities=["interactive_chat_session"],
            risk_level=AGENT_CONTRACT["risk_level"],
            dependencies=AGENT_CONTRACT["dependencies"],
        ))
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()


def _load_role(name: str) -> str:
    roles_dir = Path(__file__).parent.parent.parent / "roles"
    p = roles_dir / f"{name}.md"
    return p.read_text(encoding="utf-8") if p.exists() else f"You are the {name} agent."


def _run_subprocess(command: str, cwd: str, timeout: int = 120) -> str:
    """Run a shell command synchronously (safe to call from a thread pool)."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = result.stdout
        if result.stderr:
            out += "\n[stderr]\n" + result.stderr
        if result.returncode != 0:
            out += f"\n[exit {result.returncode}]"
        return out.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"[ERROR] Command timed out after {timeout}s"
    except Exception as e:
        return f"[ERROR] {e}"


def _git(args: list[str], cwd: str, timeout: int = 30) -> str:
    """Run a git command and return combined output."""
    try:
        r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "[ERROR] git timed out"
    except Exception as e:
        return f"[ERROR] {e}"


class ChatAgent:
    """
    Async streaming chat agent that runs a full agentic loop:
    LLM call → tool execution → LLM call → … until stop_reason == end_turn.

    Dangerous operations pause and request user confirmation via
    session.request_confirmation() before executing.
    """

    MAX_ITERATIONS = 30

    def __init__(self, session: ChatSession) -> None:
        self.session = session
        self.root = Path(session.repo_path)
        self._system = _load_role("chat")
        # Per-session background process table (one ChatAgent per ChatSession) —
        # mirrors make_chat_handlers()'s per-session isolation in tools.py so one
        # session cannot kill or read another session's background process.
        self._background_processes: dict[int, subprocess.Popen[str]] = {}

    def _client(self) -> anthropic.AsyncAnthropic:
        return anthropic.AsyncAnthropic(api_key=get_effective_api_key())

    # ------------------------------------------------------------------
    # Tool execution — dispatches all 36 CHAT_TOOLS
    # ------------------------------------------------------------------

    async def _execute_tool(self, tool_name: str, inp: dict[str, Any]) -> str:  # noqa: C901
        root = self.root
        repo = str(root)

        # ========== FILE SYSTEM — READ ==========

        if tool_name == "read_file":
            p = root / str(inp["path"])
            if not p.exists():
                return f"[ERROR] File not found: {inp['path']}"
            try:
                return p.read_text(encoding="utf-8")
            except Exception as e:
                return f"[ERROR] {e}"

        if tool_name == "read_files":
            file_parts: list[str] = []
            for rel in (inp.get("paths") or [])[:20]:
                fp = root / str(rel)
                try:
                    file_parts.append(f"=== {rel} ===\n{fp.read_text(encoding='utf-8')}" if fp.exists() else f"=== {rel} ===\n[NOT FOUND]")
                except Exception as e:
                    file_parts.append(f"=== {rel} ===\n[ERROR] {e}")
            return "\n\n".join(file_parts) or "[ERROR] No paths given"

        if tool_name == "file_exists":
            p = root / str(inp["path"])
            return "file" if p.is_file() else "directory" if p.is_dir() else "not_found"

        if tool_name == "file_info":
            import datetime
            p = root / str(inp["path"])
            if not p.exists():
                return f"[ERROR] Not found: {inp['path']}"
            stat = p.stat()
            line_count = ""
            if p.is_file():
                try:
                    line_count = f"\nlines: {len(p.read_text(encoding='utf-8', errors='replace').splitlines())}"
                except Exception:
                    pass
            return (
                f"path: {inp['path']}\ntype: {'file' if p.is_file() else 'dir'}\n"
                f"size: {stat.st_size} bytes{line_count}\n"
                f"modified: {datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds')}"
            )

        if tool_name == "list_files":
            directory = str(inp.get("directory", ""))
            pattern = str(inp.get("pattern", "**/*"))
            search_root = root / directory if directory else root
            if not search_root.exists():
                return f"[ERROR] Directory not found: {directory}"
            paths = sorted(
                str(fp.relative_to(root)) for fp in search_root.glob(pattern) if fp.is_file()
            )
            return "\n".join(paths[:300])

        if tool_name == "get_file_tree":
            directory = str(inp.get("directory", ""))
            max_depth = min(int(inp.get("max_depth", 3)), 4)
            start = root / directory if directory else root
            if not start.exists():
                return f"[ERROR] Not found: {directory}"
            _SKIP = {"__pycache__", "node_modules", ".next", ".venv", "venv", ".git", "dist", "build", ".mypy_cache"}
            tree_lines: list[str] = [directory or "."]

            def _tree(path: Path, depth: int, prefix: str) -> None:
                if depth > max_depth:
                    return
                try:
                    items = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name))
                except PermissionError:
                    return
                items = [i for i in items if i.name not in _SKIP and not i.name.startswith(".")]
                for idx, item in enumerate(items):
                    conn = "└── " if idx == len(items) - 1 else "├── "
                    tree_lines.append(f"{prefix}{conn}{item.name}")
                    if item.is_dir() and depth < max_depth:
                        ext = "    " if idx == len(items) - 1 else "│   "
                        _tree(item, depth + 1, prefix + ext)

            _tree(start, 1, "")
            return "\n".join(tree_lines[:300])

        # ========== SEARCH ==========

        if tool_name == "search_code":
            pattern = str(inp["pattern"])
            fp = inp.get("file_pattern", "")
            cmd_args = ["grep", "-rn", "--include", str(fp) if fp else "*", pattern, repo]
            try:
                r = subprocess.run(cmd_args, capture_output=True, text=True, timeout=15)
                return r.stdout[:8000] or "(no matches)"
            except subprocess.TimeoutExpired:
                return "[ERROR] Search timed out"

        if tool_name == "search_symbols":
            sym_name = str(inp["name"])
            kind = str(inp.get("kind", "all"))
            patterns: list[str] = []
            if kind in ("function", "all"):
                patterns += [f"def {sym_name}", f"async def {sym_name}", f"function {sym_name}", f"const {sym_name} ="]
            if kind in ("class", "all"):
                patterns += [f"class {sym_name}", f"interface {sym_name}", f"type {sym_name} ="]
            sym_results: list[str] = []
            for pat in patterns:
                try:
                    r = subprocess.run(
                        ["grep", "-rn", "--include=*.py", "--include=*.ts", "--include=*.tsx", pat, repo],
                        capture_output=True, text=True, timeout=10,
                    )
                    if r.stdout:
                        sym_results.append(r.stdout[:2000])
                except subprocess.TimeoutExpired:
                    pass
            combined = "\n".join(sym_results)[:6000]
            return combined or f"(no symbol '{sym_name}' found)"

        if tool_name == "find_references":
            sym = str(inp["symbol"])
            fp = inp.get("file_pattern", "")
            ref_cmd = ["grep", "-rn"]
            if fp:
                ref_cmd += ["--include", str(fp)]
            ref_cmd += [r"\b" + sym + r"\b", repo]
            try:
                r = subprocess.run(ref_cmd, capture_output=True, text=True, timeout=15)
                return r.stdout[:6000] or f"(no references to '{sym}')"
            except subprocess.TimeoutExpired:
                return "[ERROR] Search timed out"

        if tool_name == "find_todos":
            directory = str(inp.get("directory", ""))
            kind = str(inp.get("kind", "all"))
            search_root = root / directory if directory else root
            markers = ["TODO", "FIXME", "HACK", "XXX"] if kind == "all" else [kind]
            try:
                r = subprocess.run(
                    ["grep", "-rn", "-E", f"({'|'.join(markers)}):", str(search_root),
                     "--include=*.py", "--include=*.ts", "--include=*.tsx", "--include=*.md"],
                    capture_output=True, text=True, timeout=15,
                )
                return r.stdout[:5000] or "(no TODOs found)"
            except subprocess.TimeoutExpired:
                return "[ERROR] Search timed out"

        if tool_name == "search_imports":
            module = str(inp["module"])
            fp = inp.get("file_pattern", "")
            imp_patterns = [f"import {module}", f"from {module}", f'require("{module}")', f"require('{module}')"]
            import_results: list[str] = []
            for pat in imp_patterns:
                imp_cmd = ["grep", "-rn"]
                if fp:
                    imp_cmd += ["--include", str(fp)]
                imp_cmd += [pat, repo]
                try:
                    r = subprocess.run(imp_cmd, capture_output=True, text=True, timeout=10)
                    if r.stdout.strip():
                        import_results.append(r.stdout[:2000])
                except subprocess.TimeoutExpired:
                    pass
            return "\n".join(import_results)[:6000] or f"(no imports of '{module}')"

        if tool_name == "analyze_file":
            rel = str(inp["path"])
            fp = root / rel
            if not fp.exists():
                return f"[ERROR] Not found: {rel}"
            content = fp.read_text(encoding="utf-8", errors="replace")
            af_lines = content.splitlines()
            af_imports: list[str] = []
            af_defs: list[str] = []
            for i, line in enumerate(af_lines, 1):
                s = line.strip()
                if s.startswith(("import ", "from ")):
                    af_imports.append(f"  L{i}: {s}")
                elif s.startswith(("def ", "async def ", "class ", "export function ",
                                   "export async function ", "export class ", "export const ",
                                   "export interface ", "export type ", "export default function ")):
                    af_defs.append(f"  L{i}: {s[:120]}")
            af_result = [f"File: {rel}  ({len(af_lines)} lines)"]
            if af_imports:
                af_result += [f"\nImports ({len(af_imports)}):"] + af_imports[:30]
            if af_defs:
                af_result += [f"\nDefinitions ({len(af_defs)}):"] + af_defs[:50]
            return "\n".join(af_result)

        # ========== GIT — READ ==========

        if tool_name == "git_log":
            count = min(int(inp.get("count", 10)), 30)
            file_filter = str(inp.get("file", ""))
            log_args = ["log", "--oneline", f"-{count}", "--no-merges"]
            if file_filter:
                log_args += ["--", file_filter]
            return _git(log_args, repo)

        if tool_name == "git_status":
            return _git(["status", "--short", "--branch"], repo) or "(clean)"

        if tool_name == "git_show":
            ref = str(inp.get("ref", "HEAD"))
            out = _git(["show", "--stat", "--no-color", ref], repo)
            return out[:5000]

        if tool_name == "git_blame":
            rel = str(inp["path"])
            blame_start = inp.get("start_line")
            blame_end = inp.get("end_line")
            blame_args = ["blame", "--date=short", "-w"]
            if blame_start and blame_end:
                blame_args.append(f"-L{blame_start},{blame_end}")
            blame_args.append(rel)
            return _git(blame_args, repo)[:5000]

        if tool_name == "git_diff":
            file_ = str(inp.get("file", ""))
            staged = _git(["diff", "--cached", "--no-color"], repo)
            unstaged_args = ["diff", "--no-color"] + ([file_] if file_ else [])
            unstaged = _git(unstaged_args, repo)
            out = ""
            if staged.strip():
                out += "=== STAGED ===\n" + staged
            if unstaged.strip():
                out += "=== UNSTAGED ===\n" + unstaged
            return out or "No changes."

        # ========== FILE SYSTEM — WRITE ==========

        if tool_name == "write_file":
            rel = str(inp["path"])
            if _is_protected_path(rel):
                return f"[POLICY DENIED] Cannot write to protected path: {rel}"
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(inp["content"]), encoding="utf-8")
            return f"Written {rel} ({len(str(inp['content']))} bytes)"

        if tool_name == "edit_file":
            rel = str(inp["path"])
            old_s = str(inp["old_string"])
            new_s = str(inp["new_string"])
            target = root / rel
            if not target.exists():
                return f"[ERROR] File not found: {rel}"
            text = target.read_text(encoding="utf-8")
            count = text.count(old_s)
            if count == 0:
                return f"[ERROR] old_string not found in {rel}. Check whitespace/newlines."
            if count > 1:
                return f"[ERROR] old_string appears {count} times — must be unique. Add more context."
            target.write_text(text.replace(old_s, new_s, 1), encoding="utf-8")
            return f"Edited {rel}"

        if tool_name == "append_file":
            rel = str(inp["path"])
            if _is_protected_path(rel):
                return f"[POLICY DENIED] Cannot write to protected path: {rel}"
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            content = str(inp["content"])
            with open(target, "a", encoding="utf-8") as f:
                f.write(content)
            return f"Appended {len(content)} bytes to {rel}"

        if tool_name == "rename_file":
            from_rel = str(inp["from_path"])
            to_rel = str(inp["to_path"])
            if _is_protected_path(from_rel) or _is_protected_path(to_rel):
                return "[POLICY DENIED] Protected path involved"
            src = root / from_rel
            dst = root / to_rel
            if not src.exists():
                return f"[ERROR] Source not found: {from_rel}"
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            return f"Moved {from_rel} → {to_rel}"

        if tool_name == "copy_file":
            import shutil as _shutil
            from_rel = str(inp["from_path"])
            to_rel = str(inp["to_path"])
            if _is_protected_path(to_rel):
                return f"[POLICY DENIED] Protected destination: {to_rel}"
            src = root / from_rel
            dst = root / to_rel
            if not src.exists():
                return f"[ERROR] Source not found: {from_rel}"
            dst.parent.mkdir(parents=True, exist_ok=True)
            _shutil.copy2(str(src), str(dst))
            return f"Copied {from_rel} → {to_rel}"

        if tool_name == "delete_file":
            rel = str(inp["path"])
            if _is_protected_path(rel):
                return f"[POLICY DENIED] Cannot delete protected path: {rel}"
            target = root / rel
            if not target.exists():
                return f"[ERROR] File not found: {rel}"
            if not target.is_file():
                return f"[ERROR] {rel} is a directory — use bash 'rm -rf' for directories"
            target.unlink()
            return f"Deleted {rel}"

        # ========== GIT — WRITE ==========

        if tool_name == "git_commit":
            message = str(inp["message"])
            raw_files = inp.get("files", [])
            files: list[str] = list(raw_files) if isinstance(raw_files, list) else ["--all"]
            try:
                if files == ["--all"] or files == ["-a"]:
                    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
                else:
                    for gf in files:
                        subprocess.run(["git", "add", str(gf)], cwd=repo, check=True, capture_output=True)
                r = subprocess.run(["git", "commit", "-m", message], cwd=repo, capture_output=True, text=True)
                return (r.stdout + r.stderr).strip()
            except subprocess.CalledProcessError as e:
                return f"[ERROR] git add failed: {e}"
            except Exception as e:
                return f"[ERROR] {e}"

        if tool_name == "git_branch":
            action = str(inp.get("action", "list"))
            bname = str(inp.get("name", ""))
            if action == "list":
                return _git(["branch", "-a"], repo)
            if action == "create":
                return "[ERROR] name required" if not bname else _git(["branch", bname], repo) or f"Branch '{bname}' created"
            if action == "delete":
                return "[ERROR] name required" if not bname else _git(["branch", "-d", bname], repo)
            return f"[ERROR] Unknown action: {action}"

        if tool_name == "create_branch":
            bname = str(inp["name"])
            do_checkout = bool(inp.get("checkout", True))
            from_b = str(inp.get("from_branch", ""))
            create_args = ["branch", bname] + ([from_b] if from_b else [])
            out = _git(create_args, repo)
            if "[ERROR]" in out:
                return out
            if do_checkout:
                return _git(["checkout", bname], repo) or f"Created and switched to branch: {bname}"
            return f"Created branch: {bname}"

        if tool_name == "git_checkout":
            ck_target = str(inp["target"])
            file_arg = str(inp.get("file", ""))
            if file_arg:
                return _git(["checkout", ck_target, "--", file_arg], repo)
            return _git(["checkout", ck_target], repo)

        if tool_name == "git_stash":
            action = str(inp.get("action", "push"))
            msg = str(inp.get("message", ""))
            if action == "push" and msg:
                return _git(["stash", "push", "-m", msg], repo)
            return _git(["stash", action], repo)

        if tool_name == "git_pull":
            remote = str(inp.get("remote", "origin"))
            branch = str(inp.get("branch", ""))
            rebase = bool(inp.get("rebase", False))
            pull_args = ["pull"] + (["--rebase"] if rebase else []) + [remote] + ([branch] if branch else [])
            return await asyncio.to_thread(_git, pull_args, repo, 60)

        if tool_name == "git_fetch":
            remote = str(inp.get("remote", "origin"))
            prune = bool(inp.get("prune", False))
            return await asyncio.to_thread(_git, ["fetch", remote] + (["--prune"] if prune else []), repo, 60)

        if tool_name == "git_restore":
            rel = str(inp["path"])
            restore_staged = bool(inp.get("staged", False))
            restore_args = ["restore"] + (["--staged"] if restore_staged else []) + [rel]
            return _git(restore_args, repo)

        if tool_name == "git_push":
            branch = str(inp.get("branch", ""))
            remote = str(inp.get("remote", "origin"))
            force = bool(inp.get("force", False))
            cmd_preview = f"git push {remote} {branch}{'  --force' if force else ''}".strip()
            approved = await self.session.request_confirmation(
                action_id=str(uuid.uuid4()),
                description="Push commits to remote repository",
                details=cmd_preview,
            )
            if not approved:
                return "[DENIED] User declined git push."
            push_args = ["push", remote] + ([branch] if branch else []) + (["--force"] if force else [])
            return await asyncio.to_thread(_git, push_args, repo, 60)

        # ========== TERMINAL ==========

        if tool_name == "bash":
            command = str(inp["command"])
            cwd = str(inp.get("cwd") or repo)
            if _is_dangerous_command(command):
                approved = await self.session.request_confirmation(
                    action_id=str(uuid.uuid4()),
                    description="Run potentially destructive command",
                    details=command,
                )
                if not approved:
                    return f"[DENIED] User declined: {command!r}"
            return await asyncio.to_thread(_run_subprocess, command, cwd, 120)

        # ========== TESTING / LINTING ==========

        if tool_name == "run_tests":
            runner = str(inp.get("runner", "pytest"))
            test_path = str(inp.get("path", ""))
            flags = str(inp.get("flags", ""))
            if runner == "pytest":
                cmd_str = f"cd {repo} && source .venv/bin/activate 2>/dev/null; python -m pytest {test_path} {flags} --tb=short -q 2>&1 | head -150"
            elif runner == "npm_test":
                web = str(root.parent / "apps" / "web")
                cmd_str = f"cd {web} && npm test {flags} 2>&1 | head -100"
            elif runner == "tsc":
                web = str(root.parent / "apps" / "web")
                cmd_str = f"cd {web} && npx tsc --noEmit {flags} 2>&1 | head -100"
            else:
                return f"[ERROR] Unknown runner: {runner}"
            return await asyncio.to_thread(_run_subprocess, cmd_str, repo, 180)

        if tool_name == "run_linter":
            lint_tool = str(inp.get("tool", "all"))
            lint_path = str(inp.get("path", ""))
            fix = bool(inp.get("fix", False))
            lint_parts: list[str] = []

            async def _lint(cmd_str: str, label: str) -> None:
                out = await asyncio.to_thread(_run_subprocess, cmd_str, repo, 90)
                lint_parts.append(f"=== {label} ===\n{out or 'clean'}")

            if lint_tool in ("ruff", "all"):
                t = lint_path or repo
                await _lint(f"cd {repo} && source .venv/bin/activate 2>/dev/null; python -m ruff check {t} {'--fix' if fix else ''} 2>&1 | head -50", "ruff")
            if lint_tool in ("mypy", "all"):
                t = lint_path or repo
                await _lint(f"cd {repo} && source .venv/bin/activate 2>/dev/null; python -m mypy {t} --ignore-missing-imports 2>&1 | head -50", "mypy")
            if lint_tool in ("tsc", "all"):
                web = str(root.parent / "apps" / "web")
                await _lint(f"cd {web} && npx tsc --noEmit 2>&1 | head -50", "tsc")
            if lint_tool == "black":
                t = lint_path or repo
                await _lint(f"cd {repo} && source .venv/bin/activate 2>/dev/null; python -m black {'--check' if not fix else ''} {t} 2>&1 | head -50", "black")

            return "\n\n".join(lint_parts) or f"[ERROR] Unknown linter: {lint_tool}"

        if tool_name == "submit_result":
            return f"Task complete: {inp.get('status', 'done')}\n{inp.get('summary', '')}"

        # ========== BATCH 1 — File / Editing extras ==========

        if tool_name == "find_file":
            name = str(inp["name"])
            ff_dir = str(inp.get("directory", ""))
            ff_root = root / ff_dir if ff_dir else root
            try:
                r = await asyncio.to_thread(
                    subprocess.run,
                    ["find", str(ff_root), "-name", name,
                     "-not", "-path", "*/node_modules/*",
                     "-not", "-path", "*/__pycache__/*",
                     "-not", "-path", "*/.git/*",
                     "-not", "-path", "*/.venv/*"],
                    capture_output=True, text=True, timeout=15,
                )
                found = [l for l in r.stdout.splitlines() if l.strip()]
                if not found:
                    return f"(no files matching '{name}')"
                ff_rel_paths: list[str] = []
                for ff_path in found[:100]:
                    try:
                        ff_rel_paths.append(str(Path(ff_path).relative_to(root)))
                    except ValueError:
                        ff_rel_paths.append(ff_path)
                return "\n".join(ff_rel_paths)
            except Exception as e:
                return f"[ERROR] {e}"

        if tool_name == "format_file":
            rel = str(inp["path"])
            formatter = str(inp.get("formatter", "auto"))
            fmt_target = root / rel
            if not fmt_target.exists():
                return f"[ERROR] File not found: {rel}"
            if formatter == "auto":
                formatter = "ruff" if fmt_target.suffix == ".py" else "prettier"
            activate = f"source {repo}/.venv/bin/activate 2>/dev/null || true"
            if formatter in ("ruff", "black"):
                cmd_s = f"{activate} && python -m {formatter} format {str(fmt_target)} 2>&1"
            else:
                cmd_s = f"cd {repo} && npx prettier --write {str(fmt_target)} 2>&1"
            return await asyncio.to_thread(_run_subprocess, cmd_s, repo, 30)

        if tool_name == "organize_imports":
            rel = str(inp["path"])
            oi_target = root / rel
            if not oi_target.exists():
                return f"[ERROR] File not found: {rel}"
            activate = f"source {repo}/.venv/bin/activate 2>/dev/null || true"
            cmd_s = f"{activate} && python -m ruff check --select I --fix {str(oi_target)} 2>&1"
            return await asyncio.to_thread(_run_subprocess, cmd_s, repo, 30)

        if tool_name == "insert_at_line":
            rel = str(inp["path"])
            line_num = int(inp["line"])
            content = str(inp["content"])
            if _is_protected_path(rel):
                return f"[POLICY DENIED] Cannot write to protected path: {rel}"
            ial_target = root / rel
            if not ial_target.exists():
                return f"[ERROR] File not found: {rel}"
            try:
                file_lines = ial_target.read_text(encoding="utf-8").splitlines(keepends=True)
                insert_at = max(0, line_num - 1) if line_num > 0 else len(file_lines)
                insert_at = min(insert_at, len(file_lines))
                ins_content = content if content.endswith("\n") else content + "\n"
                file_lines.insert(insert_at, ins_content)
                ial_target.write_text("".join(file_lines), encoding="utf-8")
                return f"Inserted at line {line_num} in {rel}"
            except Exception as e:
                return f"[ERROR] {e}"

        if tool_name == "replace_function":
            rel = str(inp["path"])
            rf_name = str(inp["function_name"])
            new_code = str(inp["new_code"])
            if _is_protected_path(rel):
                return f"[POLICY DENIED] Cannot write to protected path: {rel}"
            rf_target = root / rel
            if not rf_target.exists():
                return f"[ERROR] File not found: {rel}"
            try:
                rf_lines = rf_target.read_text(encoding="utf-8").splitlines(keepends=True)
                rf_start: int | None = None
                rf_indent = 0
                for rf_i, rf_line in enumerate(rf_lines):
                    s = rf_line.strip()
                    if s.startswith(f"def {rf_name}(") or s.startswith(f"async def {rf_name}("):
                        rf_start = rf_i
                        rf_indent = len(rf_line) - len(rf_line.lstrip())
                        break
                if rf_start is None:
                    return f"[ERROR] Function '{rf_name}' not found in {rel}"
                rf_end = len(rf_lines)
                for rf_j in range(rf_start + 1, len(rf_lines)):
                    rf_jl = rf_lines[rf_j]
                    if rf_jl.strip() == "":
                        continue
                    rf_jind = len(rf_jl) - len(rf_jl.lstrip())
                    if rf_jind <= rf_indent and rf_jl.strip() and not rf_jl.strip().startswith(("#", "@")):
                        rf_end = rf_j
                        break
                rf_new = new_code if new_code.endswith("\n") else new_code + "\n"
                rf_target.write_text("".join(rf_lines[:rf_start] + [rf_new] + rf_lines[rf_end:]), encoding="utf-8")
                return f"Replaced '{rf_name}' in {rel} (lines {rf_start + 1}-{rf_end})"
            except Exception as e:
                return f"[ERROR] {e}"

        if tool_name == "delete_lines":
            rel = str(inp["path"])
            dl_start = int(inp["start_line"])
            dl_end = int(inp["end_line"])
            if _is_protected_path(rel):
                return f"[POLICY DENIED] Cannot write to protected path: {rel}"
            dl_target = root / rel
            if not dl_target.exists():
                return f"[ERROR] File not found: {rel}"
            if dl_start < 1 or dl_end < dl_start:
                return f"[ERROR] Invalid range: {dl_start}-{dl_end}"
            try:
                dl_lines = dl_target.read_text(encoding="utf-8").splitlines(keepends=True)
                total = len(dl_lines)
                if dl_start > total:
                    return f"[ERROR] File only has {total} lines"
                dl_s = dl_start - 1
                dl_e = min(dl_end, total)
                deleted = dl_e - dl_s
                dl_target.write_text("".join(dl_lines[:dl_s] + dl_lines[dl_e:]), encoding="utf-8")
                return f"Deleted {deleted} lines ({dl_start}-{dl_end}) from {rel}"
            except Exception as e:
                return f"[ERROR] {e}"

        if tool_name == "apply_patch":
            import os as _os
            import tempfile as _tempfile
            patch_content = str(inp["patch"])
            strip = int(inp.get("strip", 1))
            try:
                with _tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as pf:
                    pf.write(patch_content)
                    pf_name = pf.name
            except Exception as e:
                return f"[ERROR] Cannot write patch file: {e}"
            try:
                r = await asyncio.to_thread(
                    subprocess.run,
                    ["patch", f"-p{strip}", "--input", pf_name],
                    cwd=repo, capture_output=True, text=True, timeout=30,
                )
                return (r.stdout + r.stderr).strip() or "Patch applied"
            except FileNotFoundError:
                return "[ERROR] 'patch' command not found"
            except Exception as e:
                return f"[ERROR] {e}"
            finally:
                try:
                    _os.unlink(pf_name)
                except Exception:
                    pass

        if tool_name == "compare_files":
            rel_a = str(inp["path_a"])
            rel_b = str(inp["path_b"])
            context = int(inp.get("context", 3))
            cf_a = root / rel_a
            cf_b = root / rel_b
            if not cf_a.exists():
                return f"[ERROR] File not found: {rel_a}"
            if not cf_b.exists():
                return f"[ERROR] File not found: {rel_b}"
            r = subprocess.run(["diff", f"-U{context}", str(cf_a), str(cf_b)], capture_output=True, text=True)
            return r.stdout[:8000] or "Files are identical"

        # ========== BATCH 2 — Terminal extras ==========

        if tool_name == "run_background":
            rb_command = str(inp["command"])
            rb_cwd = str(inp.get("cwd") or repo)
            try:
                proc = subprocess.Popen(
                    rb_command, shell=True, cwd=rb_cwd,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                self._background_processes[proc.pid] = proc
                return f"Started background process PID {proc.pid}: {rb_command[:80]}"
            except Exception as e:
                return f"[ERROR] {e}"

        if tool_name == "kill_process":
            import os as _os
            import signal as _signal
            kp_pid = int(inp["pid"])
            kp_sig_name = str(inp.get("signal", "TERM"))
            sig_map = {"TERM": _signal.SIGTERM, "KILL": _signal.SIGKILL, "INT": _signal.SIGINT}
            kp_sig = sig_map.get(kp_sig_name, _signal.SIGTERM)
            try:
                _os.kill(kp_pid, kp_sig)
                return f"Sent {kp_sig_name} to PID {kp_pid}"
            except ProcessLookupError:
                return f"[ERROR] No process with PID {kp_pid}"
            except Exception as e:
                return f"[ERROR] {e}"

        if tool_name == "run_python_snippet":
            import shlex as _shlex
            code = str(inp["code"])
            ps_timeout = int(inp.get("timeout", 30))
            activate = f"source {repo}/.venv/bin/activate 2>/dev/null || true"
            cmd_s = f"{activate} && python3 -c {_shlex.quote(code)} 2>&1"
            return await asyncio.to_thread(_run_subprocess, cmd_s, repo, ps_timeout)

        if tool_name == "run_make":
            make_target = str(inp.get("target", ""))
            make_dir_rel = str(inp.get("directory", ""))
            make_dir = (root / make_dir_rel) if make_dir_rel else root
            if not (make_dir / "Makefile").exists() and not (make_dir / "makefile").exists():
                return f"[ERROR] No Makefile found in {make_dir}"
            if not make_target:
                r = subprocess.run(["make", "-pRrq"], cwd=str(make_dir), capture_output=True, text=True, timeout=10)
                tgts: list[str] = []
                for mk_line in r.stdout.splitlines():
                    if mk_line and not mk_line.startswith(("\t", "#", " ")) and ":" in mk_line:
                        tgt = mk_line.split(":")[0].strip()
                        if tgt and not tgt.startswith(".") and " " not in tgt:
                            tgts.append(tgt)
                return "Targets:\n" + "\n".join(sorted(set(tgts[:30]))) if tgts else "Makefile found but targets not parseable"
            cmd_s = f"make {make_target}"
            return await asyncio.to_thread(_run_subprocess, cmd_s, str(make_dir), 120)

        if tool_name == "fetch_url":
            fu_url = str(inp["url"])
            fu_timeout = int(inp.get("timeout", 15))
            cmd_s = f"curl -s -L --max-time {fu_timeout} --user-agent 'Gridiron-Agent/1.0' {fu_url} 2>&1"
            return await asyncio.to_thread(_run_subprocess, cmd_s, repo, fu_timeout + 5)

        # ========== BATCH 3 — Git extras ==========

        if tool_name == "git_merge":
            gm_branch = str(inp["branch"])
            gm_no_ff = bool(inp.get("no_ff", False))
            gm_squash = bool(inp.get("squash", False))
            gm_msg = str(inp.get("message", ""))
            gm_args = ["merge"] + (["--no-ff"] if gm_no_ff else []) + (["--squash"] if gm_squash else [])
            if gm_msg:
                gm_args += ["-m", gm_msg]
            gm_args.append(gm_branch)
            return _git(gm_args, repo)

        if tool_name == "git_reset":
            gr_ref = str(inp.get("ref", "HEAD"))
            gr_mode = str(inp.get("mode", "mixed"))
            if gr_mode == "hard":
                approved = await self.session.request_confirmation(
                    action_id=str(uuid.uuid4()),
                    description="git reset --hard — discards ALL uncommitted changes",
                    details=f"git reset --hard {gr_ref}",
                )
                if not approved:
                    return "[DENIED] User declined git reset --hard."
            return _git(["reset", f"--{gr_mode}", gr_ref], repo)

        if tool_name == "git_worktree":
            gw_action = str(inp.get("action", "list"))
            gw_wt_path = str(inp.get("path", ""))
            gw_branch = str(inp.get("branch", ""))
            if gw_action == "list":
                return _git(["worktree", "list"], repo)
            elif gw_action == "add":
                if not gw_wt_path or not gw_branch:
                    return "[ERROR] path and branch required for add"
                return await asyncio.to_thread(_git, ["worktree", "add", gw_wt_path, gw_branch], repo, 30)
            elif gw_action == "remove":
                if not gw_wt_path:
                    return "[ERROR] path required for remove"
                return _git(["worktree", "remove", gw_wt_path], repo)
            return f"[ERROR] Unknown action: {gw_action}"

        if tool_name == "create_pr":
            pr_title = str(inp["title"])
            pr_body = str(inp.get("body", ""))
            pr_base = str(inp.get("base", "main"))
            pr_draft = bool(inp.get("draft", False))
            pr_cmd_parts = ["gh", "pr", "create", "--title", pr_title, "--base", pr_base]
            if pr_body:
                pr_cmd_parts += ["--body", pr_body]
            if pr_draft:
                pr_cmd_parts.append("--draft")
            cmd_s = " ".join(__import__("shlex").quote(c) for c in pr_cmd_parts)
            return await asyncio.to_thread(_run_subprocess, cmd_s, repo, 30)

        if tool_name == "generate_commit_msg":
            gcm_staged = bool(inp.get("staged_only", True))
            gcm_diff_args = ["diff", "--cached"] if gcm_staged else ["diff"]
            gcm_stat = _git(gcm_diff_args + ["--stat"], repo)
            gcm_diff = _git(gcm_diff_args, repo)[:3000]
            if not gcm_stat.strip():
                return "[ERROR] No staged changes. Stage files first."
            return (
                f"=== Changed files ===\n{gcm_stat}\n\n"
                f"=== Diff (truncated) ===\n{gcm_diff}\n\n"
                "Write a conventional commit message:\n"
                "Format: <type>(<scope>): <description>\n"
                "Types: feat, fix, docs, refactor, test, chore, style, perf"
            )

        # ========== BATCH 4 — Testing extras ==========

        if tool_name == "run_single_test":
            rst_kw = str(inp["keyword"])
            rst_file = str(inp.get("file", ""))
            rst_verbose = bool(inp.get("verbose", True))
            rst_vflag = "-v" if rst_verbose else "-q"
            activate = f"source {repo}/.venv/bin/activate 2>/dev/null || true"
            rst_path = rst_file if rst_file else "backend/tests/"
            cmd_s = f"{activate} && python -m pytest {rst_path} -k '{rst_kw}' {rst_vflag} --tb=short 2>&1 | head -100"
            return await asyncio.to_thread(_run_subprocess, cmd_s, repo, 120)

        if tool_name == "coverage_report":
            cov_path = str(inp.get("path", "backend/tests/"))
            cov_source = str(inp.get("source", "backend/app/"))
            cov_min = inp.get("min_coverage")
            activate = f"source {repo}/.venv/bin/activate 2>/dev/null || true"
            cov_min_flag = f"--cov-fail-under={cov_min}" if cov_min else ""
            cmd_s = (
                f"{activate} && python -m pytest {cov_path} "
                f"--cov={cov_source} --cov-report=term-missing {cov_min_flag} "
                f"--tb=no -q 2>&1 | tail -50"
            )
            return await asyncio.to_thread(_run_subprocess, cmd_s, repo, 180)

        if tool_name == "type_check":
            tc_path = str(inp.get("path", ""))
            tc_strict = bool(inp.get("strict", False))
            tc_lang = str(inp.get("language", "both"))
            activate = f"source {repo}/.venv/bin/activate 2>/dev/null || true"
            tc_results: list[str] = []
            if tc_lang in ("python", "both"):
                py_path = tc_path or "backend/"
                sf = "--strict" if tc_strict else "--ignore-missing-imports"
                tc_results.append(await asyncio.to_thread(
                    _run_subprocess,
                    f"{activate} && python -m mypy {py_path} {sf} 2>&1 | head -60",
                    repo, 90,
                ))
            if tc_lang in ("typescript", "both"):
                web = str(root.parent / "apps" / "web")
                tc_results.append(await asyncio.to_thread(
                    _run_subprocess,
                    f"cd {web} && npx tsc --noEmit 2>&1 | head -60",
                    repo, 90,
                ))
            return "\n\n".join(tc_results) or "[ERROR] No language selected"

        # ========== BATCH 5 — Code Intelligence ==========

        if tool_name == "list_functions":
            rel = str(inp["path"])
            lf_fp = root / rel
            if not lf_fp.exists():
                return f"[ERROR] File not found: {rel}"
            lf_lines = lf_fp.read_text(encoding="utf-8", errors="replace").splitlines()
            lf_results: list[str] = []
            for lf_i, lf_line in enumerate(lf_lines, 1):
                s = lf_line.strip()
                if s.startswith(("def ", "async def ")):
                    lf_results.append(f"  L{lf_i}: {s.split(':')[0] if ':' in s else s}")
                elif s.startswith(("export function ", "export async function ", "function ")) and "(" in s:
                    lf_results.append(f"  L{lf_i}: {s[:120]}")
                elif s.startswith(("export const ", "const ")) and ("=>" in s or "= (" in s or "= async" in s):
                    lf_results.append(f"  L{lf_i}: {s[:120]}")
            return f"Functions in {rel} ({len(lf_results)}):\n" + "\n".join(lf_results) if lf_results else f"(no functions in {rel})"

        if tool_name == "list_classes":
            rel = str(inp["path"])
            lc_fp = root / rel
            if not lc_fp.exists():
                return f"[ERROR] File not found: {rel}"
            lc_lines = lc_fp.read_text(encoding="utf-8", errors="replace").splitlines()
            lc_results: list[str] = []
            lc_current: str | None = None
            lc_base_indent = 0
            for lc_i, lc_line in enumerate(lc_lines, 1):
                s = lc_line.strip()
                curr_indent = len(lc_line) - len(lc_line.lstrip())
                if s.startswith(("class ", "export class ", "export default class ")):
                    lc_current = s.split("(")[0].split("{")[0].rstrip()
                    lc_base_indent = curr_indent
                    lc_results.append(f"\nL{lc_i}: {lc_current}")
                elif lc_current and curr_indent > lc_base_indent:
                    if s.startswith(("def ", "async def ")):
                        lc_results.append(f"    L{lc_i}: {s.split(':')[0]}")
                    elif s.startswith(("public ", "private ", "protected ", "async ", "static ")) and "(" in s:
                        lc_results.append(f"    L{lc_i}: {s[:120]}")
                elif lc_current and lc_line.strip() and curr_indent <= lc_base_indent and not s.startswith(("@", "#", "/")):
                    lc_current = None
            return f"Classes in {rel}:\n" + "\n".join(lc_results) if lc_results else f"(no classes in {rel})"

        if tool_name == "find_function_body":
            rel = str(inp["path"])
            ffb_name = str(inp["function_name"])
            ffb_fp = root / rel
            if not ffb_fp.exists():
                return f"[ERROR] File not found: {rel}"
            ffb_lines = ffb_fp.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            ffb_start: int | None = None
            ffb_base = 0
            for ffb_i, ffb_line in enumerate(ffb_lines):
                s = ffb_line.strip()
                if s.startswith(f"def {ffb_name}(") or s.startswith(f"async def {ffb_name}("):
                    ffb_start = ffb_i
                    ffb_base = len(ffb_line) - len(ffb_line.lstrip())
                    break
            if ffb_start is None:
                return f"[ERROR] Function '{ffb_name}' not found in {rel}"
            ffb_end = len(ffb_lines)
            for ffb_j in range(ffb_start + 1, len(ffb_lines)):
                ffb_jl = ffb_lines[ffb_j]
                if ffb_jl.strip() == "":
                    continue
                ffb_jind = len(ffb_jl) - len(ffb_jl.lstrip())
                if ffb_jind <= ffb_base and ffb_jl.strip() and not ffb_jl.strip().startswith(("@", "#")):
                    ffb_end = ffb_j
                    break
            body = "".join(ffb_lines[ffb_start:ffb_end])
            return f"=== {ffb_name} (lines {ffb_start + 1}-{ffb_end}) ===\n{body}"

        # ========== BATCH 6 — Debug tools ==========

        if tool_name == "read_logs":
            rl_path = str(inp.get("path", ""))
            rl_lines = int(inp.get("lines", 50))
            rl_level = str(inp.get("level", "all"))
            out = ""
            if rl_path and ("/" in rl_path or rl_path.endswith(".log")):
                log_file = root / rl_path if not Path(rl_path).is_absolute() else Path(rl_path)
                if log_file.exists():
                    r = subprocess.run(["tail", f"-{rl_lines}", str(log_file)], capture_output=True, text=True)
                    out = r.stdout
                else:
                    return f"[ERROR] Log file not found: {rl_path}"
            elif rl_path:
                r = subprocess.run(["journalctl", "-u", rl_path, f"-n{rl_lines}", "--no-pager"],
                                    capture_output=True, text=True, timeout=10)
                out = r.stdout or r.stderr
            else:
                log_dirs = [root / "logs", root / "backend" / "logs", Path("/tmp")]
                found_logs: list[Path] = []
                for ld in log_dirs:
                    if ld.exists():
                        found_logs.extend(ld.glob("*.log"))
                if not found_logs:
                    return "(no log files found — specify path or service name)"
                newest = max(found_logs, key=lambda p: p.stat().st_mtime)
                r = subprocess.run(["tail", f"-{rl_lines}", str(newest)], capture_output=True, text=True)
                out = f"From {newest}:\n" + r.stdout
            if rl_level != "all":
                out = "\n".join(line for line in out.splitlines() if rl_level.upper() in line.upper())
            return out[:5000] or "(no log entries)"

        if tool_name == "analyze_error":
            ae_error = str(inp["error"])
            ae_lines = ae_error.strip().splitlines()
            exception_line = ""
            for ae_line in reversed(ae_lines):
                if any(x in ae_line for x in ("Error:", "Exception:", "Warning:", "Traceback")):
                    exception_line = ae_line
                    break
            ae_frames: list[str] = []
            ae_i = 0
            while ae_i < len(ae_lines):
                ae_line = ae_lines[ae_i]
                if ae_line.strip().startswith("File ") and "line " in ae_line:
                    if not any(x in ae_line for x in ("site-packages", ".venv", "lib/python")):
                        code_line = ae_lines[ae_i + 1].strip() if ae_i + 1 < len(ae_lines) else ""
                        ae_frames.append(f"  {ae_line.strip()}\n    → {code_line}")
                    ae_i += 2
                else:
                    ae_i += 1
            ae_result = ["=== Error Analysis ==="]
            if exception_line:
                ae_result.append(f"Exception: {exception_line.strip()}")
            if ae_frames:
                ae_result.append(f"\nRelevant frames ({len(ae_frames)}):")
                ae_result.extend(ae_frames[-5:])
            ae_low = ae_error.lower()
            suggestions: list[str] = []
            if "modulenotfounderror" in ae_low or "importerror" in ae_low:
                suggestions.append("→ Missing dependency — run: pip install -r requirements.txt")
            elif "attributeerror" in ae_low:
                suggestions.append("→ Object doesn't have this attribute — check spelling and type")
            elif "typeerror" in ae_low:
                suggestions.append("→ Wrong argument type/count — check function signature")
            elif "keyerror" in ae_low:
                suggestions.append("→ Key not found — use .get() or check key exists")
            elif "filenotfounderror" in ae_low:
                suggestions.append("→ Path doesn't exist — verify path and working directory")
            elif "connectionrefusederror" in ae_low or "connection refused" in ae_low:
                suggestions.append("→ Service not running — check if DB/Redis/backend is started")
            elif "syntaxerror" in ae_low:
                suggestions.append("→ Python syntax error — check brackets, colons, indentation")
            if suggestions:
                ae_result.append("\nSuggestions:")
                ae_result.extend(suggestions)
            return "\n".join(ae_result)

        # ========== BATCH 7 — Database tools ==========

        if tool_name == "run_sql":
            from app.config import get_settings as _get_settings
            rs_query = str(inp["query"])
            rs_params: list[str] = list(inp.get("params") or [])
            for rs_i, rs_p in enumerate(rs_params, 1):
                rs_query = rs_query.replace(f"${rs_i}", f"'{rs_p}'")
            rs_db_url = str(getattr(_get_settings(), "database_url", ""))
            if not rs_db_url:
                return "[ERROR] DATABASE_URL not configured"
            return await asyncio.to_thread(
                _run_subprocess,
                f"psql '{rs_db_url}' -c {__import__('shlex').quote(rs_query)} --no-password 2>&1",
                repo, 30,
            )

        if tool_name == "inspect_schema":
            from app.config import get_settings as _get_settings
            is_table = str(inp.get("table", ""))
            is_db_url = str(getattr(_get_settings(), "database_url", ""))
            if not is_db_url:
                return "[ERROR] DATABASE_URL not configured"
            if is_table:
                is_q = (
                    "SELECT column_name, data_type, is_nullable, column_default "
                    "FROM information_schema.columns "
                    f"WHERE table_name = '{is_table}' ORDER BY ordinal_position"
                )
            else:
                is_q = (
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' ORDER BY table_name"
                )
            return await asyncio.to_thread(
                _run_subprocess,
                f"psql '{is_db_url}' -c {__import__('shlex').quote(is_q)} --no-password 2>&1",
                repo, 10,
            )

        # ========== BATCH 8 — Docker tools ==========

        if tool_name == "docker_ps":
            show_all = bool(inp.get("all", False))
            cmd_s = "docker ps --format 'table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.Names}}'" + (" -a" if show_all else "")
            return await asyncio.to_thread(_run_subprocess, cmd_s, repo, 10)

        if tool_name == "docker_logs":
            dl_container = str(inp["container"])
            dock_lines = int(inp.get("lines", 50))
            return await asyncio.to_thread(
                _run_subprocess, f"docker logs --tail {dock_lines} {dl_container} 2>&1", repo, 15
            )

        if tool_name == "docker_exec":
            import shlex as _shlex
            de_container = str(inp["container"])
            de_command = str(inp["command"])
            return await asyncio.to_thread(
                _run_subprocess,
                f"docker exec {de_container} sh -c {_shlex.quote(de_command)} 2>&1",
                repo, 30,
            )

        if tool_name == "docker_compose":
            dc_action = str(inp["action"])
            dc_services = " ".join(str(s) for s in (inp.get("services") or []))
            dc_detach = bool(inp.get("detach", True))
            if dc_action == "up":
                dc_cmd = f"docker compose up {'-d' if dc_detach else ''} {dc_services}"
            elif dc_action in ("down", "restart", "build", "ps", "pull"):
                dc_cmd = f"docker compose {dc_action} {dc_services}"
            elif dc_action == "logs":
                dc_cmd = f"docker compose logs --tail=50 {dc_services}"
            else:
                return f"[ERROR] Unknown action: {dc_action}"
            return await asyncio.to_thread(_run_subprocess, dc_cmd.strip(), repo, 120)

        # ========== BATCH 9 — Security ==========

        if tool_name == "secrets_scan":
            ss_dir = str(inp.get("directory", ""))
            ss_root = str(root / ss_dir) if ss_dir else repo
            ss_patterns = [
                r"(?i)(password|passwd|pwd)\s*[=:]\s*['\"][^'\"]{4,}['\"]",
                r"(?i)(api[_-]?key|apikey)\s*[=:]\s*['\"][^'\"]{8,}['\"]",
                r"(?i)(secret[_-]?key|secretkey)\s*[=:]\s*['\"][^'\"]{8,}['\"]",
                r"(sk-[a-zA-Z0-9]{20,})",
                r"(AKIA[0-9A-Z]{16})",
                r"(ghp_[a-zA-Z0-9]{36})",
            ]
            ss_exclude = ["--exclude-dir=node_modules", "--exclude-dir=.git", "--exclude-dir=.venv",
                          "--exclude-dir=__pycache__", "--exclude=*.env", "--exclude=.env*", "--exclude=*.example"]
            ss_findings: list[str] = []
            for ss_pat in ss_patterns:
                cmd_s = f"grep -rn -E {__import__('shlex').quote(ss_pat)} {ss_root} {' '.join(ss_exclude)} 2>/dev/null || true"
                result = await asyncio.to_thread(_run_subprocess, cmd_s, repo, 15)
                if result and result != "(no output)":
                    ss_findings.append(result)
            return "⚠️  Potential secrets found:\n\n" + "\n\n".join(ss_findings)[:5000] if ss_findings else "✅ No hardcoded secrets detected."

        # ========== BATCH 10 — AST Engine ==========

        if tool_name == "parse_ast":
            pa_rel = str(inp["path"])
            pa_fp = root / pa_rel
            if not pa_fp.exists():
                return f"[ERROR] File not found: {pa_rel}"
            return await asyncio.to_thread(_ast_engine.parse_file_ast, str(pa_fp))

        if tool_name == "import_graph":
            ig_rel = str(inp["path"])
            ig_fp = root / ig_rel
            if not ig_fp.exists():
                return f"[ERROR] File not found: {ig_rel}"
            return await asyncio.to_thread(_ast_engine.build_import_graph, str(ig_fp))

        if tool_name == "call_graph":
            cg_rel = str(inp["path"])
            cg_fn = str(inp.get("function_name", ""))
            cg_fp = root / cg_rel
            if not cg_fp.exists():
                return f"[ERROR] File not found: {cg_rel}"
            return await asyncio.to_thread(_ast_engine.build_call_graph, str(cg_fp), cg_fn)

        if tool_name == "dead_code_detect":
            dcd_d = str(inp.get("directory", ""))
            dcd_target = str(root / dcd_d) if dcd_d else repo
            return await asyncio.to_thread(_ast_engine.detect_dead_code, dcd_target)

        if tool_name == "circular_dep_detect":
            cdd_d = str(inp.get("directory", ""))
            cdd_target = str(root / cdd_d) if cdd_d else repo
            return await asyncio.to_thread(_ast_engine.detect_circular_imports, cdd_target)

        if tool_name == "rename_symbol":
            rsym_old = str(inp["old_name"])
            rsym_new = str(inp["new_name"])
            rsym_d = str(inp.get("directory", ""))
            rsym_pat = str(inp.get("file_pattern", "*.py"))
            rsym_target = str(root / rsym_d) if rsym_d else repo
            if rsym_old == rsym_new:
                return "[ERROR] old_name and new_name are the same"
            return await asyncio.to_thread(_ast_engine.rename_symbol, rsym_old, rsym_new, rsym_target, rsym_pat)

        # ========== BATCH 11 — Git extras ==========

        if tool_name == "git_rebase":
            grb_onto = str(inp["onto"])
            if bool(inp.get("interactive", False)):
                return "[BLOCKED] Interactive rebase requires a TTY. Run 'git rebase -i' manually in a terminal."
            return await asyncio.to_thread(
                _git, ["rebase", grb_onto], repo, 60
            )

        if tool_name == "git_cherry_pick":
            gcp_hash = str(inp["commit_hash"])
            gcp_args = ["cherry-pick"]
            if bool(inp.get("no_commit", False)):
                gcp_args.append("--no-commit")
            gcp_args.append(gcp_hash)
            return await asyncio.to_thread(_git, gcp_args, repo, 30)

        # ========== BATCH 12 — Terminal extras ==========

        if tool_name == "read_output":
            import fcntl as _fcntl2
            import os as _os2
            ro_pid = int(inp["pid"])
            ro_max_lines = int(inp.get("lines", 50))
            ro_proc = self._background_processes.get(ro_pid)
            if ro_proc is None:
                return f"[ERROR] No tracked background process with PID {ro_pid}"
            if ro_proc.poll() is not None:
                return f"Process {ro_pid} has exited (code {ro_proc.returncode})"
            ro_lines: list[str] = []
            for ro_stream in [ro_proc.stdout, ro_proc.stderr]:
                if ro_stream is None:
                    continue
                ro_fd = ro_stream.fileno()
                ro_fl = _fcntl2.fcntl(ro_fd, _fcntl2.F_GETFL)
                _fcntl2.fcntl(ro_fd, _fcntl2.F_SETFL, ro_fl | _os2.O_NONBLOCK)
                try:
                    ro_chunk = ro_stream.read(8192)
                    if ro_chunk:
                        ro_lines.extend(ro_chunk.splitlines())
                except (IOError, BlockingIOError, TypeError):
                    pass
            return "\n".join(ro_lines[-ro_max_lines:]) if ro_lines else f"(no output yet from PID {ro_pid})"

        if tool_name == "run_node":
            import shlex as _shlex2
            rnd_code = str(inp["code"])
            rnd_timeout = int(inp.get("timeout", 30))
            rnd_node_chk = await asyncio.to_thread(
                lambda: subprocess.run(["which", "node"], capture_output=True, text=True, timeout=5)
            )
            if rnd_node_chk.returncode != 0:
                rnd_node_chk2 = await asyncio.to_thread(
                    lambda: subprocess.run(["which", "nodejs"], capture_output=True, text=True, timeout=5)
                )
                if rnd_node_chk2.returncode != 0:
                    return "[ERROR] Node.js not found. Install via nvm or your package manager."
            rnd_cmd = f"node -e {_shlex2.quote(rnd_code)} 2>&1"
            return await asyncio.to_thread(_run_subprocess, rnd_cmd, repo, rnd_timeout)

        if tool_name == "run_script":
            rscr_rel = str(inp["path"])
            rscr_fp = root / rscr_rel
            if not rscr_fp.exists():
                return f"[ERROR] Script not found: {rscr_rel}"
            rscr_interp = str(inp.get("interpreter", "auto"))
            if rscr_interp == "auto":
                rscr_interp = (
                    "python3" if rscr_fp.suffix == ".py"
                    else "node" if rscr_fp.suffix in (".js", ".mjs", ".cjs")
                    else "bash"
                )
            rscr_cmd = f"{rscr_interp} {str(rscr_fp)} 2>&1"
            return await asyncio.to_thread(_run_subprocess, rscr_cmd, repo, 120)

        if tool_name == "docker_build":
            dbld_tag = str(inp["tag"])
            dbld_context = str(inp.get("context", "."))
            dbld_df = inp.get("dockerfile")
            dbld_ctx_path = str(root / dbld_context) if dbld_context != "." else repo
            dbld_cmd_parts = ["docker", "build", "-t", dbld_tag]
            if dbld_df:
                dbld_cmd_parts += ["-f", str(root / str(dbld_df))]
            dbld_cmd_parts.append(dbld_ctx_path)
            import shlex as _shlex3
            dbld_cmd_str = " ".join(_shlex3.quote(c) for c in dbld_cmd_parts) + " 2>&1"
            return await asyncio.to_thread(_run_subprocess, dbld_cmd_str, repo, 600)

        if tool_name == "docker_restart":
            drst_name = str(inp["container"])
            drst_cmd = f"docker restart {drst_name} 2>&1"
            return await asyncio.to_thread(_run_subprocess, drst_cmd, repo, 60)

        # ========== BATCH 13 — Smart search ==========

        if tool_name == "find_route":
            frt_method = str(inp.get("method", "")).upper()
            frt_path_pat = str(inp.get("path_pattern", ""))
            frt_pat = (
                rf"@(router|app)\.{frt_method.lower()}\(" if frt_method
                else r"@(router|app)\.(get|post|put|delete|patch|head|options)\("
            )
            frt_cmd = (
                f"grep -rn -E {__import__('shlex').quote(frt_pat)} {repo} "
                "--include=*.py --include=*.ts "
                "--exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=__pycache__ 2>/dev/null || true"
            )
            frt_result = await asyncio.to_thread(_run_subprocess, frt_cmd, repo, 15)
            if frt_path_pat:
                frt_result = "\n".join(ln for ln in frt_result.splitlines() if frt_path_pat in ln)
            return frt_result[:5000] if frt_result.strip() else (
                "No routes found" + (f" for {frt_method}" if frt_method else "")
            )

        if tool_name == "find_api":
            fapi_name = str(inp.get("name", ""))
            fapi_pat = (
                fapi_name if fapi_name
                else r"@(router|app)\.(get|post|put|delete|patch)\("
            )
            fapi_cmd = (
                f"grep -rn -E {__import__('shlex').quote(fapi_pat)} {repo} "
                "--include=*.py --include=*.ts "
                "--exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=__pycache__ 2>/dev/null || true"
            )
            fapi_result = await asyncio.to_thread(_run_subprocess, fapi_cmd, repo, 15)
            return fapi_result[:5000] if fapi_result.strip() else (
                "No API definitions found" + (f" matching '{fapi_name}'" if fapi_name else "")
            )

        if tool_name == "find_sql":
            import shlex as _shlex4
            fsql_kw = str(inp.get("keyword", "")).upper()
            if fsql_kw:
                # -i case-insensitive, -w whole-word; avoid (?i) inline flag
                fsql_cmd = (
                    f"grep -rn -i -w {_shlex4.quote(fsql_kw)} {repo} "
                    "--include=*.py --include=*.sql --include=*.ts "
                    "--exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=__pycache__ 2>/dev/null || true"
                )
            else:
                fsql_cmd = (
                    f"grep -rn -i -E 'SELECT|INSERT|UPDATE|DELETE|CREATE TABLE|ALTER TABLE' {repo} "
                    "--include=*.py --include=*.sql --include=*.ts "
                    "--exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=__pycache__ 2>/dev/null || true"
                )
            fsql_result = await asyncio.to_thread(_run_subprocess, fsql_cmd, repo, 15)
            return fsql_result[:5000] if fsql_result.strip() else "No SQL statements found"

        if tool_name == "find_test":
            ftest_fn = str(inp["function_name"])
            ftest_pat = rf"def test_{ftest_fn}|def test.*{ftest_fn}"
            ftest_cmd = (
                f"grep -rn -E {__import__('shlex').quote(ftest_pat)} {repo} "
                "--include=*.py --include=*.test.ts --include=*.spec.ts "
                "--exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=__pycache__ 2>/dev/null || true"
            )
            ftest_result = await asyncio.to_thread(_run_subprocess, ftest_cmd, repo, 15)
            return ftest_result[:5000] if ftest_result.strip() else f"No tests found for '{ftest_fn}'"

        if tool_name == "find_config":
            fcfg_key = str(inp["key"])
            fcfg_pat = fcfg_key.upper()
            fcfg_cmd = (
                f"grep -rn {__import__('shlex').quote(fcfg_pat)} {repo} "
                "--include=*.env* --include=.env* --include=*.yaml --include=*.yml "
                "--include=*.toml --include=config.py --include=settings.py "
                "--exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=__pycache__ 2>/dev/null || true"
            )
            fcfg_result = await asyncio.to_thread(_run_subprocess, fcfg_cmd, repo, 15)
            if not fcfg_result.strip():
                # Try lowercase too
                fcfg_cmd2 = (
                    f"grep -rn {__import__('shlex').quote(fcfg_key.lower())} {repo} "
                    "--include=*.yaml --include=*.yml --include=*.toml "
                    "--exclude-dir=node_modules --exclude-dir=.venv 2>/dev/null || true"
                )
                fcfg_result = await asyncio.to_thread(_run_subprocess, fcfg_cmd2, repo, 15)
            return fcfg_result[:5000] if fcfg_result.strip() else f"'{fcfg_key}' not found in config files"

        # ========== BATCH 14 — Monitoring ==========

        if tool_name == "cpu_usage":
            cpu_cmd = "cat /proc/stat 2>/dev/null | head -1 || top -bn1 2>/dev/null | grep -i cpu | head -3"
            cpu_raw = await asyncio.to_thread(_run_subprocess, cpu_cmd, repo, 5)
            # Parse /proc/stat if available
            if cpu_raw.startswith("cpu "):
                cpu_fields = cpu_raw.split()
                if len(cpu_fields) >= 5:
                    cpu_total = sum(int(f) for f in cpu_fields[1:] if f.isdigit())
                    cpu_idle = int(cpu_fields[4])
                    cpu_pct = round((cpu_total - cpu_idle) / cpu_total * 100, 1) if cpu_total else 0
                    return f"CPU: {cpu_pct}% used"
            return f"CPU: {cpu_raw[:300]}"

        if tool_name == "memory_usage":
            memus_cmd = "cat /proc/meminfo 2>/dev/null | head -8 || free -h 2>/dev/null"
            return await asyncio.to_thread(_run_subprocess, memus_cmd, repo, 5)

        if tool_name == "disk_usage":
            import shutil as _shu2
            disk_path = str(inp.get("path", "")) or repo
            try:
                dsk_u = _shu2.disk_usage(disk_path)
                dsk_gb = 1024 ** 3
                dsk_pct = round(dsk_u.used / dsk_u.total * 100, 1) if dsk_u.total else 0
                return (
                    f"Disk usage for {disk_path}:\n"
                    f"  Total: {dsk_u.total / dsk_gb:.1f} GB\n"
                    f"  Used:  {dsk_u.used / dsk_gb:.1f} GB  ({dsk_pct}%)\n"
                    f"  Free:  {dsk_u.free / dsk_gb:.1f} GB"
                )
            except Exception as dsk_e:
                return f"[ERROR] {dsk_e}"

        if tool_name == "health_check":
            from app.config import get_settings as _gs2
            hc_svc = str(inp.get("service", "all"))
            hc_settings = _gs2()
            hc_port = getattr(hc_settings, "port", 8000)
            hc_res: list[str] = []
            if hc_svc in ("all", "backend"):
                hc_curl = f"curl -s -o /dev/null -w '%{{http_code}}' http://localhost:{hc_port}/health 2>/dev/null || echo 000"
                hc_code = (await asyncio.to_thread(_run_subprocess, hc_curl, repo, 5)).strip()
                hc_res.append(f"Backend (:{hc_port}/health): {'✅ UP' if hc_code == '200' else f'⚠️ HTTP {hc_code}'}")
            if hc_svc in ("all", "db"):
                hc_db_url = getattr(hc_settings, "database_url", "")
                if hc_db_url:
                    hc_pg = await asyncio.to_thread(_run_subprocess, f"pg_isready -d '{hc_db_url}' 2>&1", repo, 5)
                    hc_res.append(f"Database: {'✅ UP' if 'accepting' in hc_pg else f'❌ {hc_pg[:80]}'}")
                else:
                    hc_res.append("Database: (DATABASE_URL not configured)")
            return "\n".join(hc_res) if hc_res else "No services checked"

        if tool_name == "task_progress":
            from app.config import get_settings as _gs3
            tprog_tid = inp.get("task_id")
            tprog_lim = int(inp.get("limit", 10))
            tp_db_url = getattr(_gs3(), "database_url", "")
            if not tp_db_url:
                return "[ERROR] DATABASE_URL not set"
            if tprog_tid is not None:
                tprog_sql = f"SELECT id, status, created_at, updated_at FROM dev_tasks WHERE id = {int(tprog_tid)} LIMIT 1;"
            else:
                tprog_sql = f"SELECT id, status, created_at, updated_at FROM dev_tasks ORDER BY created_at DESC LIMIT {tprog_lim};"
            tprog_cmd = f"psql '{tp_db_url}' -c {__import__('shlex').quote(tprog_sql)} --no-psqlrc 2>&1"
            return await asyncio.to_thread(_run_subprocess, tprog_cmd, repo, 10)

        # ========== BATCH 15 — Editing extras ==========

        if tool_name == "replace_class":
            rcl_rel = str(inp["path"])
            rcl_name = str(inp["class_name"])
            rcl_new = str(inp["new_code"])
            if _is_protected_path(rcl_rel):
                return f"[POLICY DENIED] Protected path: {rcl_rel}"
            rcl_fp = root / rcl_rel
            if not rcl_fp.exists():
                return f"[ERROR] File not found: {rcl_rel}"
            rcl_lines = rcl_fp.read_text(encoding="utf-8").splitlines(keepends=True)
            rcl_start: int | None = None
            rcl_base_i = 0
            for rcl_idx, rcl_ln in enumerate(rcl_lines):
                rcl_s = rcl_ln.strip()
                if (rcl_s.startswith(f"class {rcl_name}(")
                        or rcl_s.startswith(f"class {rcl_name}:")
                        or rcl_s == f"class {rcl_name}"):
                    rcl_start = rcl_idx
                    rcl_base_i = len(rcl_ln) - len(rcl_ln.lstrip())
                    break
            if rcl_start is None:
                return f"[ERROR] Class '{rcl_name}' not found in {rcl_rel}"
            rcl_end_i = len(rcl_lines)
            for rcl_j2 in range(rcl_start + 1, len(rcl_lines)):
                rcl_jl2 = rcl_lines[rcl_j2]
                if rcl_jl2.strip() == "":
                    continue
                rcl_ji2 = len(rcl_jl2) - len(rcl_jl2.lstrip())
                if rcl_ji2 <= rcl_base_i and rcl_jl2.strip() and not rcl_jl2.strip().startswith(("@", "#")):
                    rcl_end_i = rcl_j2
                    break
            rcl_before = "".join(rcl_lines[:rcl_start])
            rcl_after = "".join(rcl_lines[rcl_end_i:])
            rcl_new_final = rcl_new if rcl_new.endswith("\n") else rcl_new + "\n"
            rcl_fp.write_text(rcl_before + rcl_new_final + rcl_after, encoding="utf-8")
            return f"Replaced class '{rcl_name}' in {rcl_rel} (was lines {rcl_start + 1}–{rcl_end_i})"

        if tool_name == "undo_changes":
            undo_rel = str(inp["path"])
            if _is_protected_path(undo_rel):
                return f"[POLICY DENIED] Protected path: {undo_rel}"
            undo_fp = root / undo_rel
            if not undo_fp.exists():
                return f"[ERROR] File not found: {undo_rel}"
            confirmed_undo = await self.session.request_confirmation(
                action_id=str(uuid.uuid4()),
                description=f"git checkout -- {undo_rel}",
                details="DISCARDS all uncommitted changes to this file — irreversible",
            )
            if not confirmed_undo:
                return f"[CANCELLED] undo_changes for {undo_rel} cancelled by user"
            return await asyncio.to_thread(_git, ["checkout", "--", undo_rel], repo, 15)

        if tool_name == "generate_patch":
            import difflib as _dl
            gpatch_a = str(inp.get("content_a", ""))
            gpatch_b = str(inp.get("content_b", ""))
            gpatch_fn = str(inp.get("filename", "file"))
            gpatch_diff = list(_dl.unified_diff(
                gpatch_a.splitlines(keepends=True),
                gpatch_b.splitlines(keepends=True),
                fromfile=f"a/{gpatch_fn}",
                tofile=f"b/{gpatch_fn}",
            ))
            return "".join(gpatch_diff) if gpatch_diff else "(no differences)"

        # ========== BATCH 16 — DB extras ==========

        if tool_name == "explain_query":
            expq_sql = str(inp["query"]).strip().rstrip(";")
            from app.config import get_settings as _gs4
            expq_db = getattr(_gs4(), "database_url", "")
            if not expq_db:
                return "[ERROR] DATABASE_URL not set"
            expq_full = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {expq_sql};"
            expq_cmd = f"psql '{expq_db}' -c {__import__('shlex').quote(expq_full)} --no-psqlrc 2>&1"
            return await asyncio.to_thread(_run_subprocess, expq_cmd, repo, 30)

        if tool_name == "run_migration":
            rmig_dir = str(inp.get("direction", "upgrade"))
            rmig_rev = str(inp.get("revision", "head" if rmig_dir == "upgrade" else "-1"))
            rmig_confirmed = await self.session.request_confirmation(
                action_id=str(uuid.uuid4()),
                description=f"alembic {rmig_dir} {rmig_rev}",
                details="Modifies the database schema — review migration file before confirming",
            )
            if not rmig_confirmed:
                return "[CANCELLED] run_migration cancelled by user"
            rmig_backend = str(root / "backend") if (root / "backend").exists() else repo
            activate = f"source {rmig_backend}/.venv/bin/activate 2>/dev/null || true"
            rmig_cmd = f"{activate} && cd {rmig_backend} && alembic {rmig_dir} {rmig_rev} 2>&1"
            return await asyncio.to_thread(_run_subprocess, rmig_cmd, rmig_backend, 120)

        if tool_name == "seed_database":
            seeddb_script = str(inp.get("script", ""))
            if not seeddb_script:
                seeddb_script = "backend/scripts/seed.py"
            seeddb_fp = root / seeddb_script
            if not seeddb_fp.exists():
                return f"[ERROR] Seed script not found: {seeddb_script}"
            seeddb_confirmed = await self.session.request_confirmation(
                action_id=str(uuid.uuid4()),
                description=f"Run seed script: {seeddb_script}",
                details="Modifies database data — will insert/update rows",
            )
            if not seeddb_confirmed:
                return "[CANCELLED] seed_database cancelled by user"
            activate = f"source {repo}/.venv/bin/activate 2>/dev/null || true"
            seeddb_cmd = f"{activate} && python3 {str(seeddb_fp)} 2>&1"
            return await asyncio.to_thread(_run_subprocess, seeddb_cmd, repo, 120)

        return f"[ERROR] Unknown tool: {tool_name}"

    # ------------------------------------------------------------------
    # Main agentic loop
    # ------------------------------------------------------------------

    async def run(self, user_message: str) -> None:
        """
        Process user_message through the full agentic loop.
        Events are pushed to session.push() for SSE delivery.
        """
        self.session.history.append({"role": "user", "content": user_message})
        client = self._client()
        settings = get_settings()

        for iteration in range(self.MAX_ITERATIONS):
            await self.session.push({"type": "thinking", "iteration": iteration})

            full_text = ""
            tool_uses: list[dict[str, Any]] = []
            stop_reason = "end_turn"

            # Cast our dict-based messages/tools to what the SDK expects
            sdk_messages = cast(list[MessageParam], self.session.history)
            sdk_tools = cast(list[ToolParam], CHAT_TOOLS)

            try:
                async with client.messages.stream(
                    model=settings.model_coder,
                    max_tokens=8192,
                    system=self._system,
                    messages=sdk_messages,
                    tools=sdk_tools,
                ) as stream:
                    async for event in stream:
                        if isinstance(event, RawContentBlockDeltaEvent):
                            delta = event.delta
                            if isinstance(delta, TextDelta):
                                full_text += delta.text
                                await self.session.push({"type": "text_delta", "text": delta.text})

                    final = await stream.get_final_message()
                    stop_reason = final.stop_reason or "end_turn"
                    for block in final.content:
                        if block.type == "tool_use":
                            tool_uses.append({
                                "id": block.id,
                                "name": block.name,
                                "input": block.input,
                            })

            except anthropic.APIStatusError as e:
                await self.session.push({"type": "error", "message": f"API error: {e.message}"})
                break
            except Exception as e:
                await self.session.push({"type": "error", "message": str(e)})
                logger.exception("Chat agent error on iteration %d", iteration)
                break

            # Append assistant turn to history
            turn_content: list[dict[str, Any]] = []
            if full_text:
                turn_content.append({"type": "text", "text": full_text})
            for tu in tool_uses:
                turn_content.append({"type": "tool_use", "id": tu["id"], "name": tu["name"], "input": tu["input"]})
            if turn_content:
                self.session.history.append({"role": "assistant", "content": turn_content})

            if stop_reason != "tool_use" or not tool_uses:
                break

            # Execute tools and collect results
            tool_results: list[dict[str, Any]] = []
            for tu in tool_uses:
                await self.session.push({
                    "type": "tool_call",
                    "tool_name": tu["name"],
                    "tool_input": tu["input"],
                    "tool_use_id": tu["id"],
                })
                try:
                    result = await self._execute_tool(tu["name"], tu["input"])
                except Exception as e:
                    result = f"[ERROR] Tool {tu['name']} failed: {e}"
                    logger.exception("Tool %s failed", tu["name"])

                await self.session.push({
                    "type": "tool_result",
                    "tool_name": tu["name"],
                    "tool_use_id": tu["id"],
                    "output": result[:3000],
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": result,
                })

            self.session.history.append({"role": "user", "content": tool_results})

        await self.session.push({"type": "done"})
