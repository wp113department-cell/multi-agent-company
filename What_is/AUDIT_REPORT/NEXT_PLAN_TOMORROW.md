# Plan for 2026-10-06

State on 2026-10-05 (end of day):
- All 14 audits are GREEN.
- The Antigravity and Qoder cross-checks are done.
- Every pending live-AI test has run except the one below.
- All work is pushed, and GitHub CI is green.
- Anthropic spend: $3.94 of $4. Full ledger: `PENDING_TESTS_API_KEYS.md` §N.

**Start of day:**
1. `systemctl --user start docker-desktop`
2. `docker compose up -d db redis`
3. Run a health check.

## Open items (none of these affect a GREEN flag)

| # | Item | Needs | Est. cost |
|---|---|---|---|
| 1 | **Quality-mode live run**: one agent run with Sonnet plus reflection, critique and planning turned on. It proves the big-token features end to end. | Owner tops up the Anthropic balance (≥ $0.50) | $0.20–0.40 |
| 2 | **Rotate the Groq API key** in the Groq console, then update `backend/.env`. It appeared in a tool output on 2026-10-05. | Owner | $0 |
| 3 | **L1 decision: strict output-format checks.** 1 schema miss in ~25 live runs (security_architect's `submit_threat_model` left out `overall_risk`). Recommendation: strict for submit tools whose output feeds code (patches, plans); soft for reports. | Owner decides → implement with tests | $0 (verifying live: ~$0.05) |
| 4 | **Improve the two weakest agents.** The sprint planner (0.55) and bug_fix (0.40) spend their turns exploring and hand in thin answers. Tighten their role prompts and exploration limits, then re-run evals 001 and 006 only. | Code work + one re-check | ~$0.15–0.30 |

## Rules (unchanged)
- Run every CI job locally and get it green before any push.
- Run no paid LLM call without the owner's go.
- Rehearse every paid test with a fake key first, and never re-run a test that already passed.
- Never give an agent `/tmp` as a repo; it indexes it and exhausts the RAM.

## Done 2026-10-06
1. ✅ Quality-mode live run: 3/3 pass (Sonnet + all aux features), $0.52.
2. ⚠️ Groq key: the owner rotated it in the console, but `backend/.env` still holds the old key and Groq still accepts it. Paste the new key into `.env` and revoke the old one. This is an owner action outside the code.
3. ✅ L1: strict submit schema for code/plan tools (`STRICT_SUBMIT_TOOLS`), tests added.
4. ✅ Weak agents: turn budget in their role prompts. sprint_planner 0.55 → 0.91, bug_fix 0.40 → 0.60.
