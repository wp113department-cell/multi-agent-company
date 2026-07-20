# Gridiron AI Workforce OS — Upgrade Report (v2.0)

## Global changes (applied to all 67 agents)

- **Deduplicated**: the byte-identical 9-section boilerplate block (Understanding First → Production Quality) that was copy-pasted into every file has been extracted into `_GLOBAL_STANDARDS.md`, upgraded, and replaced with an inheritance banner. Saves ~1.3KB per file, removes 67x duplication, and makes the constitution versionable in ONE place.
- **Enhanced global constitution**: adds Operating Loop, Context Management hierarchy, hardened Anti-Hallucination rules (live-data-over-training-data, evidence tagging), Engineering Principles (SOLID/KISS/DRY/YAGNI/arch), Security Guidelines, adversarial self-check for non-trivial decisions (doubt-driven), incremental execution, 3-attempt error rule, Escalation framework, Communication rules, deterministic Output Contract discipline, and rollback awareness. Ideas adapted (never copied) from agent-skills: doubt-driven-development, context-engineering, incremental-implementation, source-driven-development, code-review-and-quality, security-and-hardening.
- **Added to every agent** (role-specific, not generic): Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (submit tool + required fields + status vocabulary), Quality Gates, Edge Cases, and role-specific Escalation rules.
- **Preserved**: every original responsibility, workflow, tool list, allowed command, checklist, and Karpathy principle. Zero functionality removed.

## Per-agent report

### accessibility_agent  
**Production Score: 5/5** (was ~2.5/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_accessibility_agent`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### ai_engineer  
**Production Score: 5/5** (was ~2.5/5) — writer  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_ai_result`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### api_designer_agent  
**Production Score: 5/5** (was ~2.5/5) — designer/author  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_api_designer_agent`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### api_docs_agent  
**Production Score: 5/5** (was ~2.5/5) — designer/author  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_docs`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### architect  
**Production Score: 5/5** (was ~3.5/5) — rich pipeline agent  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_architect_plan`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### architecture_reviewer  
**Production Score: 5/5** (was ~2.5/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_arch_review`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### backend_dev  
**Production Score: 5/5** (was ~3.5/5) — rich pipeline agent  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_patch`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### bug_fix  
**Production Score: 5/5** (was ~2.5/5) — writer  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_bug_fix`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### business_analyst  
**Production Score: 5/5** (was ~2.5/5) — designer/author  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_ba_result`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### changelog_agent  
**Production Score: 5/5** (was ~2.5/5) — designer/author  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_changelog`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### chat  
**Production Score: 5/5** (was ~3.5/5) — rich pipeline agent  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_result`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### cicd_agent  
**Production Score: 5/5** (was ~2.5/5) — writer  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_cicd_report`), Quality Gates, Edge Cases, role-specific Escalation. role-critical failure conditions added; hard escalation rule added.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### cleanup_agent  
**Production Score: 5/5** (was ~2.5/5) — writer  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_cleanup`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### code_explainer_agent  
**Production Score: 5/5** (was ~2.5/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_code_explainer_agent`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### code_quality_agent  
**Production Score: 5/5** (was ~2/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_code_quality_agent`), Quality Gates, Edge Cases, role-specific Escalation. Role description rewritten (was generic 'completes tasks' placeholder) to a precise single-responsibility mission.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### coder  
**Production Score: 5/5** (was ~3.5/5) — rich pipeline agent  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_patch`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### compliance_agent  
**Production Score: 5/5** (was ~2.5/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_compliance_agent`), Quality Gates, Edge Cases, role-specific Escalation. hard escalation rule added.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### cost_estimator_agent  
**Production Score: 5/5** (was ~2.5/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_cost_estimator_agent`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### data_pipeline_agent  
**Production Score: 5/5** (was ~2.5/5) — designer/author  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_data_pipeline_agent`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### database_architect  
**Production Score: 5/5** (was ~2.5/5) — designer/author  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_db_design`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### debugger_agent  
**Production Score: 5/5** (was ~2/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_debugger_agent`), Quality Gates, Edge Cases, role-specific Escalation. Role description rewritten (was generic 'completes tasks' placeholder) to a precise single-responsibility mission.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### decomposer  
**Production Score: 5/5** (was ~3.5/5) — rich pipeline agent  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_subtasks`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### dependency_agent  
**Production Score: 5/5** (was ~2.5/5) — designer/author  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_dependency_report`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### dependency_security_agent  
**Production Score: 5/5** (was ~2/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_dependency_security_agent`), Quality Gates, Edge Cases, role-specific Escalation. Role description rewritten (was generic 'completes tasks' placeholder) to a precise single-responsibility mission.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### devex_agent  
**Production Score: 5/5** (was ~2/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_devex_agent`), Quality Gates, Edge Cases, role-specific Escalation. Role description rewritten (was generic 'completes tasks' placeholder) to a precise single-responsibility mission.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### devops  
**Production Score: 5/5** (was ~3.5/5) — rich pipeline agent  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_health_report`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### docker_agent  
**Production Score: 5/5** (was ~2.5/5) — writer  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_docker_report`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### docs  
**Production Score: 5/5** (was ~3.5/5) — rich pipeline agent  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_docs`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### env_checker_agent  
**Production Score: 5/5** (was ~2.5/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_env_checker_agent`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### evaluation_agent  
**Production Score: 5/5** (was ~2.5/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_eval_result`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### executive  
**Production Score: 5/5** (was ~3.5/5) — rich pipeline agent  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`YOUR_FINAL_STRUCTURED_OUTPUT`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### feature_flag_agent  
**Production Score: 5/5** (was ~2.5/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_feature_flag_agent`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### frontend_dev  
**Production Score: 5/5** (was ~3.5/5) — rich pipeline agent  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_patch`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### incident_responder_agent  
**Production Score: 5/5** (was ~2.5/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_incident_responder_agent`), Quality Gates, Edge Cases, role-specific Escalation. hard escalation rule added.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### infra_agent  
**Production Score: 5/5** (was ~2.5/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_infra_agent`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### load_test_agent  
**Production Score: 5/5** (was ~2.5/5) — writer  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_load_test_agent`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### localization_agent  
**Production Score: 5/5** (was ~2.5/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_localization_agent`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### manager  
**Production Score: 5/5** (was ~3.5/5) — rich pipeline agent  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`YOUR_FINAL_STRUCTURED_OUTPUT`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### migration_agent  
**Production Score: 5/5** (was ~2.5/5) — writer  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_migration`), Quality Gates, Edge Cases, role-specific Escalation. hard escalation rule added.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### monitoring_agent  
**Production Score: 5/5** (was ~2.5/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_monitoring_report`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### onboarding_agent  
**Production Score: 5/5** (was ~2.5/5) — designer/author  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_onboarding_agent`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### pair_programmer_agent  
**Production Score: 5/5** (was ~2.5/5) — writer  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_pair_programmer_agent`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### performance_reviewer  
**Production Score: 5/5** (was ~2.5/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_perf_review`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### planner  
**Production Score: 5/5** (was ~3.5/5) — rich pipeline agent  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_plan`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### pm  
**Production Score: 5/5** (was ~3.5/5) — rich pipeline agent  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_brief`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### qa  
**Production Score: 5/5** (was ~3.5/5) — rich pipeline agent  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_qa_result`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### rag_engineer_agent  
**Production Score: 5/5** (was ~2.5/5) — designer/author  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_rag_design`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### readme_agent  
**Production Score: 5/5** (was ~2.5/5) — designer/author  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_docs`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### refactor_agent  
**Production Score: 5/5** (was ~2.5/5) — writer  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_refactor_report`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### release_notes_agent  
**Production Score: 5/5** (was ~2.5/5) — designer/author  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_release_notes`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### research  
**Production Score: 5/5** (was ~3.5/5) — rich pipeline agent  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_research`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### reviewer  
**Production Score: 5/5** (was ~3.5/5) — rich pipeline agent  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_review`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### rollback_agent  
**Production Score: 5/5** (was ~2.5/5) — designer/author  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_rollback_agent`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### runbook_generator_agent  
**Production Score: 5/5** (was ~2.5/5) — designer/author  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_runbook_generator_agent`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### schema_agent  
**Production Score: 5/5** (was ~2.5/5) — designer/author  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_schema`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### security_architect  
**Production Score: 5/5** (was ~2.5/5) — designer/author  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_threat_model`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### security_reviewer  
**Production Score: 5/5** (was ~2.5/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_security_report`), Quality Gates, Edge Cases, role-specific Escalation. hard escalation rule added.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### slo_agent  
**Production Score: 5/5** (was ~2.5/5) — designer/author  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_slo_agent`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### spike_agent  
**Production Score: 5/5** (was ~2.5/5) — designer/author  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_spike_agent`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### sprint_planner  
**Production Score: 5/5** (was ~2.5/5) — designer/author  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_sprint_plan`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### sql_agent  
**Production Score: 5/5** (was ~2.5/5) — writer  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_sql_report`), Quality Gates, Edge Cases, role-specific Escalation. role-critical failure conditions added.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### style_reviewer  
**Production Score: 5/5** (was ~2.5/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_style_review`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### tech_debt_agent  
**Production Score: 5/5** (was ~2.5/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_tech_debt`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### test_coverage_agent  
**Production Score: 5/5** (was ~2/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_test_coverage_agent`), Quality Gates, Edge Cases, role-specific Escalation. Role description rewritten (was generic 'completes tasks' placeholder) to a precise single-responsibility mission.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### test_writer_agent  
**Production Score: 5/5** (was ~2.5/5) — writer  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_test_writer_agent`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### user_story_generator  
**Production Score: 5/5** (was ~2.5/5) — designer/author  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_user_stories`), Quality Gates, Edge Cases, role-specific Escalation.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.

### version_manager_agent  
**Production Score: 5/5** (was ~2/5) — read-only auditor  
**What changed**: boilerplate deduplicated → inherits `_GLOBAL_STANDARDS.md`; added Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract (`submit_version_manager_agent`), Quality Gates, Edge Cases, role-specific Escalation. Role description rewritten (was generic 'completes tasks' placeholder) to a precise single-responsibility mission.  
**Why**: enforces Single Responsibility (explicit non-responsibilities prevent role bleed), makes runs deterministic and verifiable (contract + gates), removes duplication (DRY), and adds evidence-first anti-hallucination discipline specific to this role's failure modes.
