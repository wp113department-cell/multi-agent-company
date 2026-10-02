"""Evidence script (Audit 10): merge every audit's JSON sidecar.

- Counts findings per layer and severity, as each audit stated them.
- Resolves cross-references: a finding marked OPEN->AUDIT-NN or closed by a
  later audit is linked to the finding that closed it (CLOSED_BY below, each
  entry checked against that later audit's report).
- Applies owner decisions recorded on 2026-10-02 (OWNER_DECISIONS).
- Computes the weighted score with the audit-10 spec's weights, then the
  Critical cap rule.

Run from What_is/AUDIT_REPORT/: python3 evidence/consolidate.py
"""

from __future__ import annotations

import glob
import json
from collections import Counter
from pathlib import Path

LAYER = {
    "01": "Architecture", "02": "Agents", "03": "Memory", "04": "Orchestration",
    "05": "Security", "06": "Infrastructure", "07": "AI Evaluation",
    "08": "Production Readiness", "09": "Performance & Scalability",
    "11": "Zero Policy", "12": "End-to-End", "13": "Operations / DR",
    "14": "Reproducibility",
}
WEIGHTS = {  # audit-10 spec, unchanged (sums to 100)
    "Security": 18, "Orchestration": 16, "Zero Policy": 14, "Agents": 12,
    "Production Readiness": 12, "Infrastructure": 10, "Memory": 8,
    "AI Evaluation": 5, "Performance & Scalability": 5,
}
CLOSED_BY = {
    "ARCH-01-005": "ZP-11-004 (dead module removed)",
    "ORCH-04-009": "PERF-09-003 (dispatcher agent calls moved to asyncio.to_thread)",
    "PROD-08-007": "PERF-09-001 (fleet-wide pre-call daily spend cap)",
}
OWNER_DECISIONS = {
    "INFRA-06-001": "DEFERRED_BY_OWNER (Actions disabled until audits finish)",
    "INFRA-06-005": "NOT_APPLICABLE (no domain; local-only deployment)",
    "OPS-13-006": "FIXED_PENDING_OWNER_PATH (backup service built + verified; owner sets GRIDIRON_BACKUP_DIR)",
    "PERF-09-010": "OWNER_CONFIG (MAX_CONCURRENT_AGENT_RUNS)",
}
DONE = ("FIXED", "RESOLVED", "DOCUMENTED")

rows, all_findings = [], []
for f in sorted(glob.glob("json/AUDIT_*.json")):
    num = Path(f).name.split("_")[1]
    if num == "10":  # this audit's own output, not an input
        continue
    d = json.load(open(f))
    sev = Counter(x.get("severity", "?") for x in d.get("findings", []))
    for x in d.get("findings", []):
        st = str(x.get("status", ""))
        final = st
        if x["id"] in CLOSED_BY:
            final = "CLOSED_BY " + CLOSED_BY[x["id"]]
        elif x["id"] in OWNER_DECISIONS:
            final = OWNER_DECISIONS[x["id"]]
        all_findings.append({**x, "audit": num, "layer": LAYER[num], "final_status": final})
    rows.append({"audit": num, "layer": LAYER[num], "score": d.get("layer_score"),
                 "critical": sev["Critical"], "high": sev["High"], "medium": sev["Medium"],
                 "low": sev["Low"], "verdict": d.get("verdict")})

def is_open(x: dict) -> bool:
    s = x["final_status"].upper()
    return not (s.startswith(DONE) or s.startswith("CLOSED_BY") or s.startswith("ACCEPTED")
                or s.startswith("NOT_APPLICABLE") or s.startswith("KNOWN"))

score = {r["layer"]: r["score"] for r in rows}
weighted = sum(score[k] * w for k, w in WEIGHTS.items()) / 100
open_crit_capped = [x for x in all_findings if is_open(x) and x["severity"] == "Critical"
                    and x["layer"] in ("Security", "Orchestration", "Zero Policy")]
final_score = min(weighted, 60) if open_crit_capped else weighted

out = {
    "scorecard": rows,
    "weighted_arithmetic": {k: f"{score[k]} x {w}% = {score[k]*w/100:.2f}" for k, w in WEIGHTS.items()},
    "weighted_overall": round(weighted, 2),
    "cap_applied": bool(open_crit_capped),
    "final_score": round(final_score, 2),
    "totals": dict(Counter(x["severity"] for x in all_findings)),
    "open_by_severity": dict(Counter(x["severity"] for x in all_findings if is_open(x))),
    "open": [{k: x[k] for k in ("id", "severity", "layer", "final_status", "finding")}
             for x in all_findings if is_open(x)],
    "critical_all": [{k: x.get(k) for k in ("id", "layer", "file", "final_status", "finding")}
                     for x in all_findings if x["severity"] == "Critical"],
    "high_all": [{k: x.get(k) for k in ("id", "layer", "file", "final_status", "finding")}
                 for x in all_findings if x["severity"] == "High"],
}
Path("evidence/consolidate.out.json").write_text(json.dumps(out, indent=1))
print(f"findings: {len(all_findings)} {out['totals']}")
print(f"open after cross-refs/decisions: {out['open_by_severity']}")
print("weighted:", " + ".join(f"{score[k]}x{w}%" for k, w in WEIGHTS.items()), f"= {weighted:.2f}")
print("cap applied:", out["cap_applied"], "| final:", out["final_score"])
for x in out["open"]:
    print(f"  OPEN {x['id']:13} {x['severity']:8} {x['final_status'][:70]}")
