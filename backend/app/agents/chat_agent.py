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
from app.agents.tools import CHAT_TOOLS, _is_dangerous_command, _is_protected_path
from app.config import get_settings
from app.models.chat import ChatSession

logger = logging.getLogger(__name__)


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
