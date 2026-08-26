"""Tool Governance Manifest — §8 of Master Prompt v4.

Every tool bound to any agent must have an entry here.
Rules:
- High-risk tools require the calling agent's contract to explicitly list them
  under allowed_tools.
- An agent cannot use a tool merely because it is importable.
- No orphaned or undocumented tools allowed.

Risk levels:
  low    — read-only, no side effects outside the process
  medium — writes files in the worktree, runs tests, queries DB read-only
  high   — executes arbitrary commands, pushes to remote, modifies DB schema,
            deletes data, writes outside worktree

Retry policy:
  none       — no retry (idempotent reads, or retrying would make things worse)
  once       — retry once on transient failure
  backoff    — exponential backoff (network calls)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolManifestEntry:
    purpose: str
    permissions: list[str]
    timeout_s: int
    retry_policy: str  # "none" | "once" | "backoff"
    verification_required: bool
    risk_level: str  # "low" | "medium" | "high"
    notes: str = ""


TOOL_MANIFEST: dict[str, ToolManifestEntry] = {
    # ----------------------------------------------------------------
    # READ-ONLY TOOLS (low risk)
    # ----------------------------------------------------------------
    "read_file": ToolManifestEntry(
        purpose="Read the contents of a file in the repository",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "read_files": ToolManifestEntry(
        purpose="Read multiple files at once",
        permissions=["read_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "list_files": ToolManifestEntry(
        purpose="List files in a directory",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "search_code": ToolManifestEntry(
        purpose="Search for a text pattern across the repository",
        permissions=["read_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "search_symbols": ToolManifestEntry(
        purpose="Search for function/class definitions by name",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "search_imports": ToolManifestEntry(
        purpose="Search for import statements across the repo",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "get_file_tree": ToolManifestEntry(
        purpose="Return the directory tree structure",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "file_exists": ToolManifestEntry(
        purpose="Check whether a file exists",
        permissions=["read_repo"],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "file_info": ToolManifestEntry(
        purpose="Return metadata about a file (size, mtime, etc.)",
        permissions=["read_repo"],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "find_references": ToolManifestEntry(
        purpose="Find all usages of a symbol in the codebase",
        permissions=["read_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "find_todos": ToolManifestEntry(
        purpose="Find TODO/FIXME comments in the codebase",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "find_file": ToolManifestEntry(
        purpose="Find a file by name pattern",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "find_function_body": ToolManifestEntry(
        purpose="Extract the body of a named function",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "find_api": ToolManifestEntry(
        purpose="Find API route definitions",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "find_config": ToolManifestEntry(
        purpose="Find configuration files",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "find_route": ToolManifestEntry(
        purpose="Find web framework route definitions",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "find_sql": ToolManifestEntry(
        purpose="Find SQL queries in the codebase",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "find_test": ToolManifestEntry(
        purpose="Find test files and test functions",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "find_queue": ToolManifestEntry(
        purpose="Find task queue or job queue definitions",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "find_worker": ToolManifestEntry(
        purpose="Find background worker definitions",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "find_unused_imports": ToolManifestEntry(
        purpose="Find unused import statements",
        permissions=["read_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "analyze_file": ToolManifestEntry(
        purpose="Structural analysis of a source file (classes, functions, imports)",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "analyze_error": ToolManifestEntry(
        purpose="Parse and analyze an error message or stack trace",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "summarize_folder": ToolManifestEntry(
        purpose="Summarize the contents and purpose of a folder",
        permissions=["read_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "summarize_repo": ToolManifestEntry(
        purpose="High-level summary of the repository",
        permissions=["read_repo"],
        timeout_s=15,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "list_functions": ToolManifestEntry(
        purpose="List all function definitions in a file",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "list_classes": ToolManifestEntry(
        purpose="List all class definitions in a file",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "list_env_vars": ToolManifestEntry(
        purpose="List environment variable references in the codebase",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "count_lines": ToolManifestEntry(
        purpose="Count lines of code in a file or directory",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "loc_stats": ToolManifestEntry(
        purpose="Lines-of-code statistics across the repository",
        permissions=["read_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "estimate_complexity": ToolManifestEntry(
        purpose="Estimate cyclomatic complexity of a function or file",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "parse_ast": ToolManifestEntry(
        purpose="Parse a file into its AST representation",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "call_graph": ToolManifestEntry(
        purpose="Build a call graph from a file or module",
        permissions=["read_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "import_graph": ToolManifestEntry(
        purpose="Build a module import dependency graph",
        permissions=["read_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "compare_files": ToolManifestEntry(
        purpose="Compare two files and show differences",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "sync_files": ToolManifestEntry(
        purpose="Copy a source file's content to one or more target paths "
        "where they differ (AUDIT_Q_BATCH01 §18 'Synchronize files')",
        permissions=["write_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "hash_file": ToolManifestEntry(
        purpose="Compute the hash of a file for integrity checks",
        permissions=["read_repo"],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "csv_preview": ToolManifestEntry(
        purpose="Preview the first rows of a CSV file",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "read_image": ToolManifestEntry(
        purpose="Read and describe an image file",
        permissions=["read_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "read_pdf": ToolManifestEntry(
        purpose="Extract text from a PDF file",
        permissions=["read_repo"],
        timeout_s=15,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "read_env_var": ToolManifestEntry(
        purpose="Read a non-secret environment variable value",
        permissions=["read_env"],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "env_diff": ToolManifestEntry(
        purpose="Compare current environment variables to .env.example",
        permissions=["read_env", "read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "json_query": ToolManifestEntry(
        purpose="Query a JSON document with a jq-like expression",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "json_validate": ToolManifestEntry(
        purpose="Validate JSON syntax, optionally against a JSON Schema (schema_path)",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "yaml_validate": ToolManifestEntry(
        purpose="Validate YAML syntax, optionally against a JSON Schema (schema_path)",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    # AUDIT_Q_BATCH09 §16/§79/§80 gap-closure — file type + inspection tools
    "xml_validate": ToolManifestEntry(
        purpose="Validate an XML file for well-formedness",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "read_notebook": ToolManifestEntry(
        purpose="Read a Jupyter notebook's cells and outputs",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "parse_dockerfile": ToolManifestEntry(
        purpose="Parse a Dockerfile into its structural instructions",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "parse_docker_compose": ToolManifestEntry(
        purpose="Parse a docker-compose file into a per-service structural summary",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "github_inspect_repo": ToolManifestEntry(
        purpose="Inspect an external public GitHub repository's metadata and file listing",
        permissions=["network"],
        timeout_s=20,
        retry_policy="backoff",
        verification_required=False,
        risk_level="low",
    ),
    "openapi_inspect": ToolManifestEntry(
        purpose="Summarize a local OpenAPI/Swagger spec's API surface",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "base64_encode": ToolManifestEntry(
        purpose="Encode a string to base64",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "generate_diagram": ToolManifestEntry(
        purpose="Generate a Mermaid diagram from code or description",
        permissions=["read_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "mermaid_from_schema": ToolManifestEntry(
        purpose="Generate a Mermaid ER diagram from a DB schema",
        permissions=["read_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "export_markdown": ToolManifestEntry(
        purpose="Export content as a Markdown document",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "template_render": ToolManifestEntry(
        purpose="Render a Jinja2 template with provided variables",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "known_issues_read": ToolManifestEntry(
        purpose="Read the known issues log for the project",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "task_history_query": ToolManifestEntry(
        purpose="Query the task history database for past runs",
        permissions=["read_db"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "capability_gap_scan": ToolManifestEntry(
        purpose=(
            "AUDIT_Q_BATCH15 §76 gap-closure — deterministically cluster real "
            "AgentRun history by agent to surface repeated-failure capability gaps"
        ),
        permissions=["read_db"],
        timeout_s=15,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    # ----------------------------------------------------------------
    # GIT READ (low risk)
    # ----------------------------------------------------------------
    "git_log": ToolManifestEntry(
        purpose="Read the git commit log",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "git_log_file": ToolManifestEntry(
        purpose="Read the git log for a specific file",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "git_status": ToolManifestEntry(
        purpose="Show the working tree status",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "git_diff": ToolManifestEntry(
        purpose="Show git diff of working tree or between commits",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "git_show": ToolManifestEntry(
        purpose="Show a specific commit or object",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "git_blame": ToolManifestEntry(
        purpose="Show who last modified each line of a file",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "git_branch": ToolManifestEntry(
        purpose="List or query git branches",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "git_stash_list": ToolManifestEntry(
        purpose="List git stash entries",
        permissions=["read_repo"],
        timeout_s=3,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    # ----------------------------------------------------------------
    # GIT WRITE (medium risk)
    # ----------------------------------------------------------------
    "git_commit": ToolManifestEntry(
        purpose="Create a git commit in the worktree",
        permissions=["write_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "git_checkout": ToolManifestEntry(
        purpose="Switch branches or restore files",
        permissions=["write_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "create_branch": ToolManifestEntry(
        purpose="Create a new git branch",
        permissions=["write_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="medium",
    ),
    "git_stash": ToolManifestEntry(
        purpose="Stash working tree changes",
        permissions=["write_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="medium",
    ),
    "git_restore": ToolManifestEntry(
        purpose="Restore a file to its committed state (discards changes)",
        permissions=["write_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "git_merge": ToolManifestEntry(
        purpose="Merge a branch into the current branch",
        permissions=["write_repo"],
        timeout_s=15,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "git_rebase": ToolManifestEntry(
        purpose="Rebase the current branch",
        permissions=["write_repo"],
        timeout_s=15,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "git_cherry_pick": ToolManifestEntry(
        purpose="Apply a commit from another branch",
        permissions=["write_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "git_tag": ToolManifestEntry(
        purpose="Create or list git tags",
        permissions=["write_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="medium",
    ),
    "git_pull": ToolManifestEntry(
        purpose="Fetch and merge from remote",
        permissions=["write_repo", "network"],
        timeout_s=30,
        retry_policy="once",
        verification_required=True,
        risk_level="medium",
    ),
    "git_fetch": ToolManifestEntry(
        purpose="Fetch from remote without merging",
        permissions=["network"],
        timeout_s=20,
        retry_policy="once",
        verification_required=False,
        risk_level="low",
    ),
    "git_worktree": ToolManifestEntry(
        purpose="Manage git worktrees",
        permissions=["write_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "git_reset": ToolManifestEntry(
        purpose="Reset HEAD to a prior commit (destructive if --hard)",
        permissions=["write_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=True,
        risk_level="high",
        notes="--hard flag discards all uncommitted work. Requires human approval.",
    ),
    # ----------------------------------------------------------------
    # GIT PUSH / REMOTE (high risk)
    # ----------------------------------------------------------------
    "git_push": ToolManifestEntry(
        purpose="Push commits to a remote repository",
        permissions=["write_remote"],
        timeout_s=30,
        retry_policy="none",
        verification_required=True,
        risk_level="high",
        notes="Requires user confirmation. Never auto-pushed.",
    ),
    # ----------------------------------------------------------------
    # FILE WRITE (medium risk)
    # ----------------------------------------------------------------
    "edit_file": ToolManifestEntry(
        purpose="Surgical text replacement in a repo file",
        permissions=["write_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "write_file": ToolManifestEntry(
        purpose="Write or overwrite a file in the repo",
        permissions=["write_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "append_file": ToolManifestEntry(
        purpose="Append content to an existing file",
        permissions=["write_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="medium",
    ),
    "insert_at_line": ToolManifestEntry(
        purpose="Insert text at a specific line number",
        permissions=["write_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "insert_before": ToolManifestEntry(
        purpose="Insert text before a marker string",
        permissions=["write_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "insert_after": ToolManifestEntry(
        purpose="Insert text after a marker string",
        permissions=["write_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "delete_lines": ToolManifestEntry(
        purpose="Delete specific line numbers from a file",
        permissions=["write_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "delete_block": ToolManifestEntry(
        purpose="Delete a block of code by marker",
        permissions=["write_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "replace_function": ToolManifestEntry(
        purpose="Replace an entire function definition in a file",
        permissions=["write_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "replace_class": ToolManifestEntry(
        purpose="Replace an entire class definition in a file",
        permissions=["write_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "rename_symbol": ToolManifestEntry(
        purpose="Rename a symbol across the codebase",
        permissions=["write_repo"],
        timeout_s=15,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "organize_imports": ToolManifestEntry(
        purpose="Sort and organize import statements in a file",
        permissions=["write_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "format_file": ToolManifestEntry(
        purpose="Format a file with the configured code formatter",
        permissions=["write_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "generate_patch": ToolManifestEntry(
        purpose="Generate a unified diff patch from two content strings",
        permissions=[],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "apply_patch": ToolManifestEntry(
        purpose="Apply a unified diff patch to the repository",
        permissions=["write_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    # ----------------------------------------------------------------
    # FILE MANAGEMENT (medium risk)
    # ----------------------------------------------------------------
    "create_directory": ToolManifestEntry(
        purpose="Create a directory in the repository",
        permissions=["write_repo"],
        timeout_s=3,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "rename_file": ToolManifestEntry(
        purpose="Rename a file",
        permissions=["write_repo"],
        timeout_s=3,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "copy_file": ToolManifestEntry(
        purpose="Copy a file to a new location",
        permissions=["write_repo"],
        timeout_s=3,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "move_file": ToolManifestEntry(
        purpose="Move a file to a new location",
        permissions=["write_repo"],
        timeout_s=3,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "delete_file": ToolManifestEntry(
        purpose="Delete a file from the repository",
        permissions=["write_repo"],
        timeout_s=3,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "zip_files": ToolManifestEntry(
        purpose="Compress files into a zip archive",
        permissions=["write_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "unzip_files": ToolManifestEntry(
        purpose="Extract a zip archive",
        permissions=["write_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "undo_changes": ToolManifestEntry(
        purpose="Restore a file to its last committed state (discards uncommitted changes)",
        permissions=["write_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=True,
        risk_level="high",
        notes="Destructive — requires user confirmation dialog.",
    ),
    # ----------------------------------------------------------------
    # BASH / EXECUTION (medium–high risk)
    # ----------------------------------------------------------------
    "bash": ToolManifestEntry(
        purpose="Execute a shell command in the repository or worktree",
        permissions=["execute"],
        timeout_s=120,
        retry_policy="none",
        verification_required=True,
        risk_level="high",
        notes="All bash handlers are gated by allowlist or check_allowlisted_command.",
    ),
    "run_tests": ToolManifestEntry(
        purpose="Run the project test suite",
        permissions=["execute"],
        timeout_s=120,
        retry_policy="once",
        verification_required=True,
        risk_level="medium",
    ),
    "run_linter": ToolManifestEntry(
        purpose="Run the configured linter (ruff, eslint, etc.)",
        permissions=["execute"],
        timeout_s=30,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "run_single_test": ToolManifestEntry(
        purpose="Run a single test function",
        permissions=["execute"],
        timeout_s=60,
        retry_policy="once",
        verification_required=True,
        risk_level="medium",
    ),
    "type_check": ToolManifestEntry(
        purpose="Run the type checker (mypy, pyright, tsc)",
        permissions=["execute"],
        timeout_s=60,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "coverage_report": ToolManifestEntry(
        purpose="Generate a test coverage report",
        permissions=["execute"],
        timeout_s=120,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "run_make": ToolManifestEntry(
        purpose="Run a make target",
        permissions=["execute"],
        timeout_s=120,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "run_script": ToolManifestEntry(
        purpose="Run a named script from the project",
        permissions=["execute"],
        timeout_s=120,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "run_python_snippet": ToolManifestEntry(
        purpose="Execute a small Python snippet",
        permissions=["execute"],
        timeout_s=30,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "run_node": ToolManifestEntry(
        purpose="Execute a Node.js script",
        permissions=["execute"],
        timeout_s=30,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "run_background": ToolManifestEntry(
        purpose="Start a command in the background and return a process handle",
        permissions=["execute"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="medium",
        notes="Background processes are tracked per session. Optional "
        "wait_for_pids expresses a dependency on other background jobs.",
    ),
    "list_background_processes": ToolManifestEntry(
        purpose="List this session's own tracked background processes with "
        "age and possibly-hung status",
        permissions=["execute"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "run_parallel_commands": ToolManifestEntry(
        purpose="Run several independent shell commands concurrently (fan-out)",
        permissions=["execute"],
        timeout_s=60,
        retry_policy="none",
        verification_required=True,
        risk_level="high",
        notes="Each sub-command is policy-checked individually inside the "
        "handler (the tool_input field is 'commands', a list, not the "
        "generic single 'command' field _policy_check scans). Any "
        "sub-command flagged dangerous is refused entirely — no "
        "multi-command confirmation flow exists, so use bash individually "
        "for those.",
    ),
    "kill_process": ToolManifestEntry(
        purpose="Kill a background process by handle",
        permissions=["execute"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="medium",
    ),
    "read_output": ToolManifestEntry(
        purpose="Read buffered output from a background process",
        permissions=["execute"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "wait_for_port": ToolManifestEntry(
        purpose="Wait until a TCP port is open (used for server startup)",
        permissions=["network"],
        timeout_s=60,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    # ----------------------------------------------------------------
    # PACKAGE MANAGEMENT (medium risk)
    # ----------------------------------------------------------------
    "pip_install": ToolManifestEntry(
        purpose="Install Python packages via pip",
        permissions=["execute", "network"],
        timeout_s=120,
        retry_policy="once",
        verification_required=True,
        risk_level="medium",
        notes="AUDIT_Q_BATCH07 §39 gap-closure (2026-08-11): requires user "
        "confirmation via session.request_confirmation() when run from an "
        "interactive session; blocked outright otherwise.",
    ),
    "pip_list": ToolManifestEntry(
        purpose="List installed Python packages",
        permissions=["execute"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "deps_outdated": ToolManifestEntry(
        purpose="List outdated dependencies",
        permissions=["execute", "network"],
        timeout_s=30,
        retry_policy="once",
        verification_required=False,
        risk_level="low",
    ),
    "check_license_compliance": ToolManifestEntry(
        purpose="Classify every installed package's license against SPDX identifiers "
        "(AUDIT_Q_BATCH11 §85 'Licensing policy enforcement')",
        permissions=["read_env"],
        timeout_s=15,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "npm_install": ToolManifestEntry(
        purpose="Run npm install",
        permissions=["execute", "network"],
        timeout_s=120,
        retry_policy="once",
        verification_required=True,
        risk_level="medium",
        notes="AUDIT_Q_BATCH07 §39 gap-closure (2026-08-11): requires user "
        "confirmation via session.request_confirmation() when run from an "
        "interactive session; blocked outright otherwise.",
    ),
    "npm_run": ToolManifestEntry(
        purpose="Run an npm script",
        permissions=["execute"],
        timeout_s=120,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "semver_bump": ToolManifestEntry(
        purpose="Bump the semantic version in package.json or pyproject.toml",
        permissions=["write_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    # ----------------------------------------------------------------
    # DATABASE (medium–high risk)
    # ----------------------------------------------------------------
    "explain_query": ToolManifestEntry(
        purpose="Run EXPLAIN ANALYZE on a SQL query (read-only)",
        permissions=["read_db"],
        timeout_s=30,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "inspect_schema": ToolManifestEntry(
        purpose="Inspect the database schema",
        permissions=["read_db"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "run_sql": ToolManifestEntry(
        purpose="Execute a read-only SQL query",
        permissions=["read_db"],
        timeout_s=30,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "run_migration": ToolManifestEntry(
        purpose="Run Alembic database migrations",
        permissions=["write_db"],
        timeout_s=120,
        retry_policy="none",
        verification_required=True,
        risk_level="high",
        notes="Modifies DB schema. Requires user confirmation. Blocked in production env.",
    ),
    "seed_database": ToolManifestEntry(
        purpose="Run a database seed script to populate initial data",
        permissions=["write_db"],
        timeout_s=120,
        retry_policy="none",
        verification_required=True,
        risk_level="high",
        notes="Modifies DB data. Requires user confirmation. Blocked in production env.",
    ),
    # ----------------------------------------------------------------
    # DOCKER (medium risk)
    # ----------------------------------------------------------------
    "docker_build": ToolManifestEntry(
        purpose="Build a Docker image",
        permissions=["execute", "docker"],
        timeout_s=300,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "docker_compose": ToolManifestEntry(
        purpose="Run docker-compose commands",
        permissions=["execute", "docker"],
        timeout_s=120,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "diagnose_deployment_failure": ToolManifestEntry(
        purpose="Gather real docker ps/logs/inspect state and generate an LLM root-cause diagnosis",
        permissions=["read_repo", "docker"],
        timeout_s=45,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "docker_exec": ToolManifestEntry(
        purpose="Execute a command inside a running container",
        permissions=["execute", "docker"],
        timeout_s=60,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    "docker_logs": ToolManifestEntry(
        purpose="Read logs from a Docker container",
        permissions=["docker"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "docker_ps": ToolManifestEntry(
        purpose="List running Docker containers",
        permissions=["docker"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "docker_restart": ToolManifestEntry(
        purpose="Restart a Docker container",
        permissions=["execute", "docker"],
        timeout_s=30,
        retry_policy="none",
        verification_required=True,
        risk_level="medium",
    ),
    # ----------------------------------------------------------------
    # NETWORK / HTTP (low–medium risk)
    # ----------------------------------------------------------------
    "http_request": ToolManifestEntry(
        purpose="Make an HTTP request to an external URL",
        permissions=["network"],
        timeout_s=30,
        retry_policy="backoff",
        verification_required=False,
        risk_level="low",
    ),
    "fetch_url": ToolManifestEntry(
        purpose="Fetch the content of a URL, optionally with an LLM-generated summary",
        permissions=["network"],
        timeout_s=30,
        retry_policy="backoff",
        verification_required=False,
        risk_level="low",
    ),
    "inspect_github_repo": ToolManifestEntry(
        purpose="Read-only inspection of an arbitrary external GitHub repo via the GitHub REST API",
        permissions=["network"],
        timeout_s=25,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "inspect_openapi_spec": ToolManifestEntry(
        purpose="Parse and summarize a real OpenAPI/Swagger spec's endpoints and schemas",
        permissions=["network"],
        timeout_s=25,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "web_search": ToolManifestEntry(
        purpose="Search the web for information",
        permissions=["network"],
        timeout_s=15,
        retry_policy="backoff",
        verification_required=False,
        risk_level="low",
    ),
    "check_url_status": ToolManifestEntry(
        purpose="Check the HTTP status of a URL",
        permissions=["network"],
        timeout_s=10,
        retry_policy="once",
        verification_required=False,
        risk_level="low",
    ),
    "health_check": ToolManifestEntry(
        purpose="Check the health of a service endpoint",
        permissions=["network"],
        timeout_s=10,
        retry_policy="once",
        verification_required=False,
        risk_level="low",
    ),
    "list_open_ports": ToolManifestEntry(
        purpose="List open TCP ports on localhost",
        permissions=["network"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    # ----------------------------------------------------------------
    # BROWSER (medium risk)
    # ----------------------------------------------------------------
    "browser_open": ToolManifestEntry(
        purpose="Open a URL in a Playwright browser session",
        permissions=["network", "browser"],
        timeout_s=30,
        retry_policy="none",
        verification_required=False,
        risk_level="medium",
        notes="SSRF guard active. Private/loopback URLs blocked unless ALLOW_INTERNAL_BROWSER_URLS=1.",
    ),
    "browser_navigate": ToolManifestEntry(
        purpose="Navigate to a URL in the current browser session",
        permissions=["network", "browser"],
        timeout_s=30,
        retry_policy="none",
        verification_required=False,
        risk_level="medium",
    ),
    "browser_screenshot": ToolManifestEntry(
        purpose="Take a screenshot of the current browser page",
        permissions=["browser"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "browser_read_dom": ToolManifestEntry(
        purpose="Read the DOM text content of the current browser page",
        permissions=["browser"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "browser_click": ToolManifestEntry(
        purpose="Click an element in the browser by CSS selector",
        permissions=["browser"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="medium",
    ),
    "browser_type": ToolManifestEntry(
        purpose="Type text into an element in the browser",
        permissions=["browser"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="medium",
    ),
    "browser_close": ToolManifestEntry(
        purpose="Close the current browser session",
        permissions=["browser"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    # ----------------------------------------------------------------
    # SECURITY (low risk — read-only analysis)
    # ----------------------------------------------------------------
    "secrets_scan": ToolManifestEntry(
        purpose="Scan the repository for accidentally committed secrets",
        permissions=["read_repo"],
        timeout_s=30,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "dead_code_detect": ToolManifestEntry(
        purpose="Detect dead/unused code in the repository",
        permissions=["read_repo"],
        timeout_s=30,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "circular_dep_detect": ToolManifestEntry(
        purpose="Detect circular import dependencies",
        permissions=["read_repo"],
        timeout_s=15,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "cpu_profile": ToolManifestEntry(
        purpose="Profile CPU usage of a function or script",
        permissions=["execute"],
        timeout_s=60,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "cpu_usage": ToolManifestEntry(
        purpose="Report current CPU usage",
        permissions=["execute"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "memory_usage": ToolManifestEntry(
        purpose="Report current memory usage",
        permissions=["execute"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "disk_usage": ToolManifestEntry(
        purpose="Report disk usage",
        permissions=["execute"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "list_processes": ToolManifestEntry(
        purpose="List running processes",
        permissions=["execute"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    # ----------------------------------------------------------------
    # MEMORY (medium risk)
    # ----------------------------------------------------------------
    "memory_read": ToolManifestEntry(
        purpose="Read entries from the engineering memory store",
        permissions=["read_memory"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "memory_write": ToolManifestEntry(
        purpose="Write a lesson or fact to the engineering memory store",
        permissions=["write_memory"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="medium",
    ),
    "delegate_to_agent": ToolManifestEntry(
        purpose=(
            "plan14 Day 4 (#1 Agent-to-Agent Delegation) — delegate a "
            "specific, well-scoped sub-task to another agent by capability, "
            "resolved via FleetManager.select(). Real invocation, gated by "
            "app.agents.delegation's depth limit, cycle detection, "
            "config-driven allowed-capability policy, shared budget, and a "
            "wall-clock timeout."
        ),
        permissions=["execute"],
        timeout_s=300,
        retry_policy="none",
        verification_required=False,
        risk_level="high",
        notes=(
            "high risk deliberately: can trigger real, costly agent work. "
            "Marking it high-risk here reinforces plan14 Day 1's dynamic-"
            "tool-selection contract-drift check — any agent whose runtime "
            "tool list includes this tool but whose own AgentCapability."
            "tools doesn't declare it gets it filtered out automatically."
        ),
    ),
    "bhaskar_tool": ToolManifestEntry(
        purpose=(
            "Universal 'no existing tool fits' fallback (app/tools/agents/"
            "bhaskar_tool.py). Runs a small internal LangGraph sub-agent "
            "(app/agents/bhaskar_agent.py) that researches, writes, and "
            "tests a one-off Python script for a task no other tool "
            "covers, inside a hardened sandbox (app/agents/"
            "bhaskar_sandbox.py: isolated tempdir, scrubbed environment, "
            "kernel resource limits, per-connection SSRF-guarded network "
            "access). Bounded by settings.bhaskar_tool_timeout_seconds, "
            "settings.bhaskar_tool_max_retries, and settings."
            "bhaskar_tool_max_turns — never an unbounded loop. Successful "
            "generations are cached (settings.bhaskar_tool_cache_"
            "max_entries entries, settings.bhaskar_tool_cache_ttl_seconds "
            "TTL) via app.fleet.scratchpad's concurrency-safe "
            "write_entry_with_eviction."
        ),
        permissions=["execute", "network"],
        timeout_s=210,  # bhaskar_tool_timeout_seconds default (180s) + slack
        retry_policy="none",  # bhaskar_tool_handler owns its own bounded retry
        verification_required=True,
        risk_level="high",
        notes=(
            "high risk deliberately: LLM-driven code generation AND "
            "execution, even though execution is sandboxed. Marking it "
            "high-risk here reinforces plan14 Day 1's dynamic-tool-"
            "selection contract-drift check — any agent whose runtime "
            "tool list includes this tool but whose own AgentCapability."
            "tools doesn't declare it gets it filtered out automatically, "
            "same reinforcement pattern as delegate_to_agent above. The "
            "sandbox (app/agents/bhaskar_sandbox.py) is defense-in-depth, "
            "not a hard multi-tenant boundary — see that module's own "
            "docstring for exactly what it does and does not guarantee."
        ),
    ),
    "propose_subtask": ToolManifestEntry(
        purpose=(
            "plan14 follow-on #2 (Dynamic Subtask Creation) — proposes a "
            "new subtask to be validated and, if accepted, dispatched after "
            "the proposing subtask completes. Does not run anything itself "
            "— app.pipeline.dynamic_subtasks.integrate_proposals() applies "
            "the real allow-matrix/duplicate/depth/count/file-lock checks "
            "at the next wave boundary."
        ),
        permissions=["write_pipeline_state"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="high",
        notes=(
            "high risk deliberately: can grow the epic's own subtask set "
            "and, if accepted, trigger real, costly follow-up agent work. "
            "Same dynamic-tool-selection contract-drift reinforcement as "
            "delegate_to_agent above — see that entry's own notes."
        ),
    ),
    "record_learning": ToolManifestEntry(
        purpose=(
            "Record a non-obvious finding for future agents working on similar "
            "tasks (MASTER_AGENT_v2.md Phase 1.4) — writes to memory_embeddings' "
            "learning category via embed_learning_signal_sync."
        ),
        permissions=["write_memory"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
        notes="Never raises — a broken memory backend returns an [ERROR] string, not an exception.",
    ),
    "record_preference": ToolManifestEntry(
        purpose=(
            "Record a stated human preference (style, naming, testing, tooling, "
            "workflow) for future work in this project — AUDIT_Q_BATCH15 §74/§113 "
            "gap-closure. Writes to memory_embeddings' preference category via "
            "embed_preference_sync."
        ),
        permissions=["write_memory"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
        notes="Never raises — a broken memory backend returns an [ERROR] string, not an exception.",
    ),
    "request_clarification": ToolManifestEntry(
        purpose=(
            "Flag a genuinely underspecified task for human/upstream-agent review "
            "(MASTER_AGENT_v2.md Phase 5.3) — records a real pending_approvals row "
            "via app/fleet/approval_gate.py and ends the run with "
            "status='needs_clarification'."
        ),
        permissions=["write_memory"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
        notes="Never raises — a failed write returns an [ERROR] string, not an exception.",
    ),
    "decision_log_append": ToolManifestEntry(
        purpose="Append a decision record to the project decision log",
        permissions=["write_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "known_issues_write": ToolManifestEntry(
        purpose="Record a known issue in the project issue log",
        permissions=["write_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "task_progress": ToolManifestEntry(
        purpose="Report progress on the current task",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "read_logs": ToolManifestEntry(
        purpose="Read application or system logs",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    # ----------------------------------------------------------------
    # GITHUB / INTEGRATIONS (high risk)
    # ----------------------------------------------------------------
    "create_pr": ToolManifestEntry(
        purpose="Create a GitHub pull request; auto-generates title/body via LLM from the real diff when omitted",
        permissions=["write_remote"],
        timeout_s=45,
        retry_policy="once",
        verification_required=True,
        risk_level="high",
    ),
    "github_create_pr": ToolManifestEntry(
        # tool_enhance.md productionization pass, tool #6 (2026-08-16) —
        # real doc/code mismatch found: this said "via API" but the real
        # implementation (app/tools/git/pull_request.py's shared
        # create_pr_handler, delegated to by this tool) shells out to the
        # `gh` CLI, same mechanism as create_pr — not a direct REST call.
        purpose="Create a GitHub pull request using the gh CLI (title/body required explicitly, no auto-generation — see create_pr for that)",
        permissions=["write_remote"],
        timeout_s=30,
        retry_policy="once",
        verification_required=True,
        risk_level="high",
    ),
    "github_comment": ToolManifestEntry(
        purpose="Add a comment to a GitHub issue or PR",
        permissions=["write_remote"],
        timeout_s=10,
        retry_policy="once",
        verification_required=False,
        risk_level="medium",
    ),
    "github_create_issue": ToolManifestEntry(
        purpose="Create a GitHub issue",
        permissions=["write_remote"],
        timeout_s=10,
        retry_policy="once",
        verification_required=False,
        risk_level="medium",
    ),
    "github_list_prs": ToolManifestEntry(
        purpose="List open pull requests on a GitHub repository",
        permissions=["network"],
        timeout_s=10,
        retry_policy="once",
        verification_required=False,
        risk_level="low",
    ),
    "linear_create_issue": ToolManifestEntry(
        purpose="Create a Linear issue",
        permissions=["write_remote"],
        timeout_s=10,
        retry_policy="once",
        verification_required=False,
        risk_level="medium",
    ),
    "slack_send_message": ToolManifestEntry(
        purpose="Send a message to a Slack channel",
        permissions=["write_remote"],
        timeout_s=10,
        retry_policy="once",
        verification_required=False,
        risk_level="medium",
    ),
    # ----------------------------------------------------------------
    # SUBMIT TOOLS (low risk — just structured output)
    # ----------------------------------------------------------------
    "submit_patch": ToolManifestEntry(
        purpose="Submit a completed patch for review",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_qa_result": ToolManifestEntry(
        purpose="Submit QA results (tests, typecheck, lint)",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_review": ToolManifestEntry(
        purpose="Submit a code review verdict",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_health_report": ToolManifestEntry(
        purpose="Submit a DevOps health report",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_research": ToolManifestEntry(
        purpose="Submit research findings",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_docs": ToolManifestEntry(
        purpose="Submit generated documentation",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_result": ToolManifestEntry(
        purpose="Submit a generic agent result",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_bug_fix": ToolManifestEntry(
        purpose="Submit a completed bug fix",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_arch_review": ToolManifestEntry(
        purpose="Submit an architecture review",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_security_report": ToolManifestEntry(
        purpose="Submit a security audit report",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_perf_review": ToolManifestEntry(
        purpose="Submit a performance review report",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_migration": ToolManifestEntry(
        purpose="Submit a completed database migration",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_docker_report": ToolManifestEntry(
        purpose="Submit a Docker health/config report",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_cicd_report": ToolManifestEntry(
        purpose="Submit a CI/CD pipeline report",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_refactor_report": ToolManifestEntry(
        purpose="Submit a refactor completion report",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_cleanup": ToolManifestEntry(
        purpose="Submit a cleanup completion report",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_dependency_report": ToolManifestEntry(
        purpose="Submit a dependency audit report",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_monitoring_report": ToolManifestEntry(
        purpose="Submit a monitoring configuration report",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_sql_report": ToolManifestEntry(
        purpose="Submit a SQL analysis report",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_style_review": ToolManifestEntry(
        purpose="Submit a style/formatting review",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_tech_debt": ToolManifestEntry(
        purpose="Submit a technical debt analysis report",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_sprint_plan": ToolManifestEntry(
        purpose="Submit a sprint plan",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_ba_result": ToolManifestEntry(
        purpose="Submit a business analysis result",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_ai_result": ToolManifestEntry(
        purpose="Submit an AI engineering result",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "submit_schema": ToolManifestEntry(
        purpose="Submit a database schema result",
        permissions=[],
        timeout_s=2,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "generate_api_docs_text": ToolManifestEntry(
        purpose="Generate API documentation text",
        permissions=["read_repo"],
        timeout_s=10,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "generate_changelog": ToolManifestEntry(
        purpose="Generate a CHANGELOG from git history",
        permissions=["read_repo"],
        timeout_s=15,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "generate_commit_msg": ToolManifestEntry(
        purpose="Generate a conventional commit message for staged changes via LLM, grounded in the real staged diff",
        permissions=["read_repo"],
        timeout_s=30,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "review_diff": ToolManifestEntry(
        purpose="LLM-generated structured review (summary/risk/omissions) of a real git diff",
        permissions=["read_repo"],
        timeout_s=30,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "explain_merge_conflict": ToolManifestEntry(
        purpose="LLM-generated plain-English explanation of real parsed merge-conflict hunks",
        permissions=["read_repo"],
        timeout_s=30,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "generate_release_notes": ToolManifestEntry(
        purpose="Generate release notes from git history and issues",
        permissions=["read_repo"],
        timeout_s=15,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
    "type": ToolManifestEntry(
        purpose="Return the inferred type of a variable or expression",
        permissions=["read_repo"],
        timeout_s=5,
        retry_policy="none",
        verification_required=False,
        risk_level="low",
    ),
}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def get_manifest(tool_name: str) -> ToolManifestEntry | None:
    return TOOL_MANIFEST.get(tool_name)


def is_high_risk(tool_name: str) -> bool:
    entry = TOOL_MANIFEST.get(tool_name)
    return entry is not None and entry.risk_level == "high"


def get_high_risk_tools() -> list[str]:
    return [name for name, entry in TOOL_MANIFEST.items() if entry.risk_level == "high"]


def verify_agent_contract(
    agent_name: str, tool_list: list[str], contract_allowed_tools: list[str]
) -> list[str]:
    """Return list of violations: high-risk tools used but not declared in contract."""
    violations = []
    for tool in tool_list:
        if is_high_risk(tool) and tool not in contract_allowed_tools:
            violations.append(
                f"Agent {agent_name!r} uses high-risk tool {tool!r} "
                f"but it is not in AGENT_CONTRACT.allowed_tools"
            )
    return violations
