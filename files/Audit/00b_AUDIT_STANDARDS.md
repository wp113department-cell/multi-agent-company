# AUDIT STANDARDS — Evidence Schema & Machine-Readable Output
# Referenced by every audit prompt in this suite (01-11). Paste this in
# alongside whichever numbered audit you're running, or tell Claude Code
# "also follow 00b_AUDIT_STANDARDS.md's evidence and output format."

## Evidence Schema (required for every finding, in every audit)

Every single finding, in every audit in this suite, must be reported using
this exact structure — no exceptions, no "see above":

```
- id: <AUD-##-NNN>                 (e.g. SEC-05-014, AGENT-02-031)
  severity: Critical | High | Medium | Low
  file: <exact path from repo root>
  location: <function/class name>
  line: <exact line number or range>
  finding: <one paragraph, factual, no hedging>
  evidence: <the actual code snippet or exact quote proving it — not a
             paraphrase; if you can't quote it, you don't have evidence>
  production_impact: <what breaks, for whom, under what condition>
  confidence: High | Medium | Low   (Low = "plausible but I could not
              fully trace this — recommend manual verification")
  recommendation: <a specific, scoped fix — not "improve X">
  effort: Small (single file) | Medium (few files) | Large (cross-cutting)
```

If you cannot produce `file`, `location`, and `line` for a claim, it is not
a finding — write `NOT FOUND` or `UNVERIFIED (state why)` instead of
asserting it as fact. This applies to positive claims too: "this system has
no prompt injection risk" needs the same evidentiary bar as a Critical
finding.

## Severity Definitions (use consistently across all 11 audits)

- **Critical**: causes data loss, unsafe/unauthorized execution, a security
  breach, or a hard crash reachable from normal production usage.
- **High**: causes incorrect behavior, a silently-swallowed failure, or a
  significant production-impacting bug, but not immediately catastrophic.
- **Medium**: a real defect with limited blast radius (edge case, rare
  condition, degraded-but-functional behavior).
- **Low**: code quality, maintainability, or a theoretical/unlikely issue.

Do not inflate Medium findings to High to seem thorough, and do not
downgrade real Criticals to look better — both distort the final
consolidation audit's release decision.

## Required Machine-Readable Output

In addition to the human-readable Markdown report, every audit (01-11) must
ALSO emit a JSON sidecar with this shape, saved alongside the Markdown
report (e.g. `AUDIT_02_AGENT.json` next to `AUDIT_02_AGENT.md`):

```json
{
  "audit_id": "02",
  "audit_name": "Master Agent Audit",
  "run_date": "<ISO 8601>",
  "layer_score": 0,
  "findings": [
    {
      "id": "AGENT-02-001",
      "severity": "High",
      "file": "backend/app/agents/example.py",
      "location": "run_example",
      "line": "42-48",
      "finding": "...",
      "evidence": "...",
      "production_impact": "...",
      "confidence": "High",
      "recommendation": "...",
      "effort": "Small"
    }
  ],
  "counts": {"critical": 0, "high": 0, "medium": 0, "low": 0},
  "not_found": ["list of things checked for but not present in the repo"],
  "verdict": "READY | NOT READY | N/A"
}
```

This lets the final consolidation audit (10) programmatically merge and
dedupe findings across all prior audits instead of re-reading prose, and
lets you hand the JSON to any LLM/tool later without re-parsing Markdown.

## Rule: No Padding

Do not manufacture findings to look thorough. A layer with 3 real Critical
issues and a clean bill of health everywhere else should report exactly
that — 3 findings, not 30 diluted ones. Depth means "verify claims with
evidence," not "produce more paragraphs." If a checklist item genuinely has
nothing wrong, report it as `VERIFIED CLEAN` with the evidence that proves
it, and move on.
