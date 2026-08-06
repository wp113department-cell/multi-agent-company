# Batch 9 — Large Project Handling, File Understanding, Modern Tech Coverage, Tech Adaptation, Documentation-Driven Development

Covers §15, §16, §79 (partial), §80, §81. Evidence-only, file:line cited.

---

## §15 Large Project Handling

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Understand 9,000+ line files | **YES — genuinely well-engineered** | `read_file` checks against `file_fold_line_threshold` (default 1000). If exceeded and the file type is tree-sitter-parseable, `fold_file_content()` replaces the body with a real structural view (function/class signatures + line ranges) rather than truncating — an explicit `[NOTE] ... showing structure only` marker, never silent. Non-code files fall back to bounded truncation with an explicit `[TRUNCATED]` marker. Tested against a real 9000+ line file (`test_gap60_61_scan_and_large_file_performance.py`). |
| Edit very large files safely | **PARTIAL** | `edit_file`'s exact-substring match preserves correctness regardless of file size, but there's no streaming — full file is loaded into memory on every read/write, and no special-casing for huge files beyond that. Works, but not optimized. |
| **Gap found: `read_files` (plural/batch) has no folding protection** | **NO** | Only `read_file` (singular) gets the folding/truncation treatment. `read_files` does a plain `read_text()` per path with no size guard at all beyond the 20-file count cap — a batch call including one 9,000-line file would return its full content unfolded, inconsistent with the single-file path. |
| Scan 1,000+ files | **YES** | No file-count cap; real incremental caching via SHA-256 content hashing (`known_hashes`), skipping unchanged files, genuinely wired into real callers (`api/repo.py`, `base_graph.py`, `mcp/server.py`) — not dead code. |
| Modify 100+ files | **PARTIAL** | Confirmed, consistent with Batch 1: only `rename_symbol` does unbounded multi-file writes in one call; no dedicated batch-edit tool exists. |
| Build complete projects (scaffold) | **YES** | Real mechanism: `pipeline/bootstrap.py` detects a blank repo, runs `git_init`, has the architect agent produce a scaffold plan (`submit_scaffold_plan`), then the coder agent writes files and commits. Wired into real launch paths, tested across 5+ test files. |
| Repository-wide refactoring | **PARTIAL** | Same `rename_symbol` finding from Batch 1 — real but regex-based, not true AST-aware. |

**§15 overall: YES with one clear, fixable inconsistency** (`read_files` batch calls bypass the large-file protection that `read_file` singular gets).

---

## §16 File Understanding

| File type | Verdict | Evidence |
|---|---|---|
| Python | **YES** | Real tree-sitter AST parsing (`tspython`), symbol/import extraction with line ranges. |
| TypeScript/JavaScript | **YES** | Real tree-sitter parsing (`tsjs`), covers `.js/.ts/.tsx/.jsx`. |
| HTML/CSS | **NO** | No dedicated parser found — generic text only. |
| PHP | **NO** | Zero references anywhere. |
| Markdown | **PARTIAL — broken as shipped** | Real code exists (`import markdown` → HTML render), but **the `markdown` pip package is not installed and not in `requirements.txt`** — the handler currently always falls through to its `<pre>{text}</pre>` fallback. Functioning code, non-functioning dependency. |
| JSON | **PARTIAL** | Real syntax validation only (`json.loads()`), despite the tool being *described* as schema validation — it isn't; no JSON Schema check happens. |
| YAML | **YES** | Real `yaml.safe_load()` syntax validation. Note: PyYAML is installed but not pinned in `requirements.txt` (a CLAUDE.md pinning-rule violation, minor). |
| Docker/Docker Compose | **PARTIAL** | Real agent and CLI-based interaction exist, but no structural Dockerfile/compose parser — generic text + CLI only. |
| Jupyter Notebook | **NO** | Zero references (`nbformat`/`ipynb`) anywhere. |
| PDF | **YES** | Real, `pdfplumber` correctly pinned and installed, page-capped extraction, registered tool. |
| Images | **PARTIAL** | Real Pillow-based handling (format/size/base64 thumbnail) — but **Pillow is not pinned in `requirements.txt`** despite being installed and used, same pinning gap as YAML. |
| Audio/Video | **NO** | Zero references anywhere. |
| XML | **NO** | Zero references anywhere. |
| CSV | **YES** | Real, stdlib `csv` module, working preview tool. |
| Excel | **NO** | Zero references (`openpyxl`/`xlsx`) anywhere. |
| Word/PowerPoint | **NO** | Zero references (`docx`/`pptx`) anywhere. |

**§16 overall: PARTIAL.** Genuine, working support for the file types that matter most for a coding assistant (Python, TS/JS, PDF, images, CSV, YAML) — this isn't a token gesture. But roughly half the explicitly-asked-about types (HTML/CSS structural parsing, PHP, Jupyter, XML, Excel, Word/PowerPoint, audio/video) have zero support, and two of the "working" ones (Markdown, and the unpinned YAML/Pillow deps) have real correctness/reproducibility gaps that a dependency audit alone wouldn't catch without actually trying to import the packages, as this audit did.

**Production Enhancement Plan:** Add `markdown`, `PyYAML`, and `Pillow` to `requirements.txt` with exact pins (they're already used in production code paths — this is a one-line-per-package fix that closes a real "works on my machine" gap). Fix or relabel the `json_validate` tool description to match its actual behavior (syntax-only, not schema validation) — as described it will mislead an agent into trusting a schema check that never happens.

---

## §79 (partial) / §80 Technology Adaptation / §81 Documentation-Driven Development

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Open URLs | **YES** | Real, multiple implementations (`fetch_url` via curl, `ae_fetch_url` via urllib, plus real `web_search` via DuckDuckGo) — genuine HTTP requests, not stubs. |
| SSRF protection on URL fetch | **YES — Production Ready** | `_ssrf_denial_reason()` resolves the hostname and checks every resolved IP (not just the string) against private/loopback/link-local/multicast/reserved/unspecified ranges, explicitly covering the 169.254.169.254 cloud-metadata endpoint and IPv6 equivalents. This is genuinely correct SSRF defense (resolves-then-checks, defeating DNS rebinding), applied consistently to both fetch implementations. |
| Summarize fetched web content | **NO** | Both fetch tools return raw, character-truncated content — no LLM summarization step inside the tool itself. |
| Detect "I don't know this technology, let me look it up" | **NO — not found** | No explicit gap-detection mechanism exists. What exists is prompt-level instruction (e.g. `spike_agent.py` telling itself to cite tool output "never from training data alone") — a hallucination-avoidance instruction, not a technology-gap detector. Notably, `spike_agent.py` (the agent closest to a "research a new technology" role) doesn't even have `web_search`/`fetch_url` in its allowed tools — it's repo-local-only, unable to reach external docs even if it wanted to. |
| Inspect external GitHub repositories | **NO** | The 4 `github_*` tools all operate on the local cloned repo's own remote via `gh` CLI — none can inspect an arbitrary external repo. |
| Inspect APIs (OpenAPI/Swagger) | **NO** | Zero references anywhere. |
| Feed external docs into coding-task context | **NO — not integrated** | `fetch_url` is available as an opt-in, per-call tool an agent *could* invoke mid-task, but there's no pipeline that pre-fetches or pins external documentation into context automatically. |

**§79/80/81 overall: PARTIAL, with one standout strength and one clear structural gap.** The SSRF-hardened URL fetching is genuinely production-grade security work — better than what many production systems ship. But the actual "technology adaptation" capability the questions are really asking about (recognize an unfamiliar technology → decide to look it up → fetch → validate compatibility → propose a plan) doesn't exist as a coherent flow; the individual primitive (fetch) exists but isn't wired into any decision-making process, and the one agent most likely to need it (`spike_agent`) can't reach it.

**Production Enhancement Plan:** Give `spike_agent` (and any other research/planning agent) access to `web_search`/`fetch_url` — this is a one-line allowlist change given the tools already exist and are hardened. If genuine "detect unfamiliar tech → look it up" behavior is wanted, it likely belongs as a planner-node prompt instruction (checked against the real tool list, since the mechanism itself — planning + tool access — already exists per Batch 4) rather than new infrastructure.

---

## Summary — Batch 9

- **YES:** 8
- **PARTIAL:** 11
- **NO:** 10

**Findings worth flagging:**
1. Large-file handling for single-file reads is genuinely well-built (structural folding, not truncation) — but the plural `read_files` path silently skips this protection, a real, fixable inconsistency between two tools that should behave the same way.
2. Three real, working file-handling code paths (Markdown, YAML, image) depend on pip packages that are used but not pinned in `requirements.txt` — one of them (`markdown`) isn't even installed, so the code silently falls back to a degraded path every time.
3. SSRF protection on the URL-fetch tool is a genuine, above-average piece of security engineering, worth crediting explicitly rather than folding into a generic "partial" score.
