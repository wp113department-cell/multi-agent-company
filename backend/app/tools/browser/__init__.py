"""Browser-automation tools (browser_open/navigate/screenshot/read_dom/
click/type/close) — tool_enhance.md productionization pass, §7 (TOOL
MODULARIZATION). All 7 share one Playwright driver
(app.repo_tools.browser_driver) and one session-id convention, so they
live together in one module rather than 7 near-empty files — see
browser_tools.py's own docstring for the full rationale.
"""

from __future__ import annotations
