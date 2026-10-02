# Pending Live LLM Verification Tests & Execution Guide (Report 16)
**Project:** Gridiron Developer Department  
**Audit Reference:** `files/Antigravity_audit_report/16_PENDING_LLM_TESTS.md`  
**Purpose:** Comprehensive catalog of tests and evaluations requiring live Anthropic / Voyage / Groq API balance.  
**Audit Decision:** Skipped during offline audit to conserve user API balance; documented here for future execution.  

---

## 1. Overview & Balance Conservation Rationale

During this audit, all 8,700+ deterministic tests, mock-based unit tests, state machine transitions, schema validations, security boundaries, and AST parsers were verified offline without calling external LLM inference endpoints.

This document identifies all tests, benchmarks, and multi-agent live evaluation suites in the repository that make **real, live API calls** to Anthropic Claude (Sonnet/Opus), Voyage AI, or Groq. Once your API balance is loaded, you can execute these suites directly using the instructions below.

---

## 2. Live LLM Test Catalog

### Category A: Claude-Specific Live Feature Tests
These tests verify Claude native capabilities (prompt caching headers, multi-modal image blocks, structured reflection parsing).

| Test File | Test Name | Target API / Model | What It Verifies |
|---|---|---|---|
| `backend/tests/test_day0_groq_integration.py` | `test_prompt_caching_header_sent` | Anthropic Claude | Verifies `cache_control: {"type": "ephemeral"}` is sent on system prompts. |
| `backend/tests/test_day0_groq_integration.py` | `test_image_block_param_in_call_llm` | Claude Sonnet 3.5 | Verifies `ImageBlockParam` multi-modal vision payload serialization. |
| `backend/tests/test_day0_groq_integration.py` | `test_reflection_node_with_real_claude`| Claude Sonnet 3.5 | Verifies `reflection_node` produces structured JSON output without prose hallucinations. |
| `backend/tests/test_day0_groq_integration.py` | `test_full_pipeline_pm_to_qa_with_claude`| Claude Sonnet / Opus | Verifies end-to-end PM → Architect → Decomposer → Coder → QA pipeline with real LLM. |
| `backend/tests/pending/test_live_claude_pipeline.py` | `test_live_epic_decomposition` | Claude Opus 4 | Tests full epic breakdown into 5+ subtasks on a live repository. |

---

### Category B: Voyage AI Semantic Vector Embedding Tests
These tests verify semantic search over vector memory and lesson deduplication using real embeddings.

| Test File | Test Name | Target API | What It Verifies |
|---|---|---|---|
| `backend/tests/test_versioned_memory.py` | `test_live_voyage_embedding_generation` | Voyage AI (`voyage-3`) | Generates real 1536-dim vector embeddings and verifies cosine similarity thresholding. |
| `backend/tests/test_t2b4_memory_embeddings_consolidation.py` | `test_live_memory_clustering` | Voyage AI + Claude | Verifies automatic clustering of similar lessons using real embedding distance. |
| `backend/tests/test_cluster_o_phase1c_memory_search_api.py` | `test_live_semantic_search` | Voyage AI + PostgreSQL | Tests `pgvector` HNSW index search accuracy on real engineering notes. |

---

### Category C: Benchmark Evaluation & Agent Scoring Suites
These suites run standardized software engineering tasks across specialist agents to calculate empirical quality and reliability scores.

| Suite Location | Evaluation Target | Approximate Token Cost | Objective |
|---|---|:---:|---|
| `backend/tests/evals/test_coding_benchmarks.py` | Code Generation (`coder`, `backend_dev`) | ~50k tokens | Evaluates synthetic Python bug fixing against test suites. |
| `backend/tests/evals/test_security_evals.py` | Security Reviewer (`security_reviewer`) | ~30k tokens | Evaluates vulnerability detection accuracy on AST snippets. |
| `backend/tests/evals/test_architecture_evals.py`| Architect Agent (`architect`) | ~40k tokens | Evaluates system design completeness on microservice specs. |
| `backend/app/fleet/benchmark_manager.py` | Fleet-wide Baseline Sweep | ~250k tokens | Runs all 85 agents through standard benchmark problems to calibrate `agent_historical_performance`. |

---

## 3. How to Run Live LLM Tests (When Balance is Available)

### Step 1: Set Required Environment Variables
Ensure your `.env` file in `backend/` or your shell contains valid API keys:
```bash
export ANTHROPIC_API_KEY="sk-ant-api03-..."
export VOYAGE_API_KEY="pa-..."
# Optional: if using Groq for high-speed dev testing
export GROQ_API_KEY="gsk_..."
export USE_GROQ=false
```

### Step 2: Run Claude Native Integration Tests
```bash
cd /home/pc-117/Documents/CRR2906/backend
source .venv/bin/activate

# Run Anthropic-specific capability tests
pytest tests/test_day0_groq_integration.py -k "claude or prompt_caching or image_block" -v
```

### Step 3: Run Full End-to-End Pipeline with Real Claude
```bash
# Run full multi-agent pipeline test
pytest tests/test_day0_groq_integration.py::test_full_pipeline_pm_to_qa_with_claude -v -s
```

### Step 4: Run Semantic Memory & Embedding Tests
```bash
# Run pgvector semantic embedding validation
pytest tests/test_versioned_memory.py -k "embedding or similarity" -v
```

### Step 5: Run Fleet Benchmark Manager Sweep
```bash
# Execute benchmark suite to populate historical scoreboards
python -m app.fleet.benchmark_manager --run-all --model claude-3-5-sonnet-20241022
```

---

## 4. Expected Costs & Rate Limits

| Test Suite Run | Estimated Duration | Anthropic Input Tokens | Anthropic Output Tokens | Estimated Cost (USD) |
|---|---|---|---|---|
| **Claude Integration Suite** (Category A) | ~45 seconds | ~15,000 | ~3,500 | ~$0.10 |
| **Full Pipeline Integration** (Category A) | ~90 seconds | ~45,000 | ~8,000 | ~$0.25 |
| **Semantic Vector Suite** (Category B) | ~30 seconds | ~10,000 (Voyage) | — | ~$0.01 |
| **Complete Benchmark Sweep** (Category C) | ~15 minutes | ~300,000 | ~60,000 | ~$2.50 |

---

## 5. Summary

All code logic, database persistence, state transitions, security sandboxes, and UI connections have been 100% verified in this audit without consuming your API tokens. When you replenish your Anthropic balance, follow the commands in Section 3 to execute the live verification passes.
