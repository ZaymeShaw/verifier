#!/usr/bin/env python3
"""Render findings and evidence into a markdown verification report.

Usage:
  echo '{"user_goal": "...", "findings": [...], "evidence": [...], "coverage": {...}}' | python render_report.py
  python render_report.py report_input.json

Output: markdown report to stdout.
"""

import json
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

SEVERITY_ICON = {"high": "!!", "medium": "!", "low": "-"}
CATEGORY_LABEL = {
    "functional_defect": "功能缺陷",
    "algorithm_capability_problem": "算法能力问题",
    "design_architecture_defect": "设计/架构缺陷",
    "unmet_user_need": "用户目标缺口",
    "reproduction_record": "问题复现记录",
}


def render(data: dict) -> str:
    lines = []

    lines.append(f"# Meta-Verifier Report")
    lines.append("")
    lines.append(f"**User Goal**: {data.get('user_goal', 'N/A')}")
    lines.append("")

    coverage = data.get("coverage", {})
    if coverage:
        lines.append("## Visibility Scope")
        lines.append(f"- Visible: {', '.join(coverage.get('visible_layers', []))}")
        invisible = coverage.get("invisible_layers", [])
        if invisible:
            lines.append(f"- Invisible: {', '.join(invisible)}")
            for impact in coverage.get("confidence_impact", []):
                lines.append(f"  - {impact}")
        lines.append("")

    findings = data.get("findings", [])
    confirmed = [f for f in findings if f.get("evidence_status") == "confirmed"]
    unverified = [f for f in findings if f.get("evidence_status") != "confirmed"]

    lines.append(f"## Findings ({len(findings)} total, {len(confirmed)} confirmed)")

    if not findings:
        lines.append("")
        lines.append("No findings reported.")
        probes = data.get("higher_level_probes", [])
        if probes:
            lines.append("")
            lines.append("### Higher-level probes executed")
            for p in probes:
                lines.append(f"- {p}")
        lines.append("")
        lines.append("> Note: No confirmed issues does not mean the system passed.")
        lines.append("> Consider investigating invisible surfaces and edge cases.")

    for f in confirmed:
        lines.append("")
        lines.append(f"### {SEVERITY_ICON.get(f.get('severity', ''), '')} {f.get('user_impact', 'No description')[:80]}")
        lines.append(f"- **Category**: {CATEGORY_LABEL.get(f.get('category', ''), f.get('category', 'unknown'))}")
        lines.append(f"- **Severity**: {f.get('severity', 'N/A')}")
        lines.append(f"- **Evidence**: {', '.join(f.get('evidence_refs', []))}")
        if f.get("reproduction_steps"):
            lines.append(f"- **Reproduction**: {'; '.join(f.get('reproduction_steps', []))}")
        if f.get("suspected_areas"):
            lines.append(f"- **Suspected**: {', '.join(f.get('suspected_areas', []))}")
        if f.get("recommendation"):
            lines.append(f"- **Recommendation**: {f.get('recommendation', '')}")

    if unverified:
        lines.append("")
        lines.append("## Unverified Critiques / Hypotheses")
        for f in unverified:
            lines.append(f"- [{f.get('evidence_status', 'hypothesis')}] {f.get('user_impact', '')[:100]}")

    audit = data.get("audit_summary", [])
    if audit:
        lines.append("")
        lines.append("## Audit Summary")
        for a in audit:
            lines.append(f"- [{a.get('severity', '')}] {a.get('category', '')}: {a.get('message', '')}")

    risks = data.get("biggest_risks", [])
    if risks:
        lines.append("")
        lines.append("## Biggest Risks")
        for r in risks:
            lines.append(f"- {r}")

    investigations = data.get("next_investigations", [])
    if investigations:
        lines.append("")
        lines.append("## Next Investigations")
        for inv in investigations:
            lines.append(f"- {inv}")

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) == 2:
        with open(sys.argv[1]) as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    print(render(data))
