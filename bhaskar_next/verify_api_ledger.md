# Task 1 — Live LLM API Spend Ledger

Rules: Groq first (`USE_GROQ=true`); Anthropic only when the claim needs Claude specifically — Haiku 4.5 only, small inputs, low max_tokens.
Stop at ~60% of the Anthropic balance. Ask before any single call/run estimated > ~$0.10.

| Date | Item # | Provider | Model | Tokens in/out | Est. cost | Why an LLM was needed |
|---|---|---|---|---|---|---|
| 2026-09-21 | #11 | Groq | llama-3.3-70b / gpt-oss-120b | n/a (free tier) | $0.00 | First live pipeline attempts: model_not_found (models decommissioned in .env), then 429 rate limits (free-tier TPM below the PM prompt size) |
| 2026-09-21 | #11 | Anthropic | claude-haiku-4-5 | ~0.6k / 0.1k | ~$0.001 | 3 tiny probe calls: does the API accept tool_use history without a tools param; does Haiku fence "JSON only" replies |
| 2026-09-21 | #11 | Anthropic | sonnet-5 (pm) + haiku (planner/reflection) | ~2k / 1.4k (+ side calls) | ~$0.03 | 1st live pipeline run: Architect died on `thinking.type.enabled` 400 (no charge for the rejected request) |
| 2026-09-21 | #11 | Anthropic | sonnet-5 (pm), opus-4-8 (architect, decomposer) + haiku side calls | 26.2k / 6.0k (agent_runs) + side calls | ~$0.26 | Successful live PM -> Architect -> Decomposer run (task 271) stopped at the approval pause. Agents are mapped to Opus/Sonnet-5 by agent_models.json regardless of env overrides, so this cost more than the ~$0.10-0.20 I estimated |

**Running Anthropic total: ~$0.30 of the ~$5 balance (~6%).** Cap for me: ~$3 (60%).
Lesson for later batches: any live agent run costs ~$0.25+ because of the Opus mapping; check cost_estimate in agent_runs before repeating, prefer offline/mocked-API checks that enforce the real API rules, and reserve live runs for items that cannot be falsified otherwise.
| 2026-09-21 | #489 | Anthropic | claude-haiku-4-5 | ~0.6k-3.5k in / 20 out x 6 | ~$0.02 | Role classification against the real capability roster (4 entries before the fix, 85 after) |
| 2026-09-21 | #357/#504 | Anthropic | claude-haiku-4-5 | ~5.3k in / 250 out x 3 | ~$0.02 | 3 no-tools probes of the chat system prompt for 'I don't know' behaviour (inconclusive) |

**Running Anthropic total: ~$0.34 of the ~$5 balance (~7%).**
| 2026-09-21 | B6 scaffold | Anthropic | sonnet-5 (coder) + haiku side calls | 29.1k / 3.4k (+ side calls) | ~$0.16 | One live run_coder on a trivial add() task through the full scaffold (planner, memory, critique, lesson, static checks): produced the right patch in 135s; critique never satisfied on a trivial task (see #109 note) |

**Running Anthropic total: ~$0.50 of the ~$5 balance (~10%).** NOTE: backend/.env has USE_GROQ=true with decommissioned Groq models — outside pytest (which forces USE_GROQ=false) every agent run 404s until that is changed.
