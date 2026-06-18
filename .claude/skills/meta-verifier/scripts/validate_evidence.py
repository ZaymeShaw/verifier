#!/usr/bin/env python3
"""Validate a finding's evidence references.

Usage:
  echo '{"finding": {...}, "evidence": [...]}' | python validate_evidence.py
  python validate_evidence.py finding.json evidence.json

Output: JSON with validation results.
{
  "valid": true/false,
  "issues": [{"severity": "high", "category": "missing_evidence", "message": "..."}]
}
"""

import json
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))


def validate(finding: dict, evidence_list: list) -> dict:
    from meta_verifier import MetaVerifierFindingValidator, MetaVerifierFinding, MetaVerifierEvidence

    evidence = [MetaVerifierEvidence.from_dict(e) for e in evidence_list]
    finding_obj = MetaVerifierFinding.from_dict(finding)
    checklist = []  # standalone mode: no checklist context

    validator = MetaVerifierFindingValidator()
    audit_results = validator.validate_confirmed_findings([finding_obj], evidence, checklist)

    issues = [
        {"severity": r.severity, "category": r.category, "message": r.message}
        for r in audit_results
    ]

    evidence_ids = {e.get("evidence_id", "") for e in evidence_list}
    refs = set(finding.get("evidence_refs", []))
    missing = refs - evidence_ids
    for m in missing:
        issues.append({"severity": "high", "category": "unresolved_ref", "message": f"evidence_ref '{m}' not found in evidence list"})

    return {"valid": len(issues) == 0, "finding_id": finding.get("finding_id", ""), "issues": issues}


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        with open(sys.argv[1]) as f:
            finding = json.load(f)
        with open(sys.argv[2]) as f:
            evidence_list = json.load(f)
    elif len(sys.argv) == 2:
        with open(sys.argv[1]) as f:
            data = json.load(f)
        finding = data.get("finding", {})
        evidence_list = data.get("evidence", [])
    else:
        data = json.load(sys.stdin)
        finding = data.get("finding", {})
        evidence_list = data.get("evidence", [])

    result = validate(finding, evidence_list)
    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
