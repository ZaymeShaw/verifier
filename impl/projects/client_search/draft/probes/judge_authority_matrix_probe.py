from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from impl.core.authority_gate import apply_authority_gate
from impl.core.draft_gate_feedback import analyze_judge_gate_obligations
from impl.core.judge import finalize_judge_result
from impl.core.schema import AuthorityResolution, normalize_judge_result, to_dict


PROBES = Path(__file__).resolve().parent
CONFIG_PATH = PROBES / "judge-authority-quadrants.json"
REPORT_PATH = PROBES / "judge-authority-expanded-matrix.json"
TABLE_PATH = PROBES / "judge-authority-expanded-matrix.md"

SHORT_STATUS = {
    "fulfilled": "F",
    "not_fulfilled": "NF",
    "not_evaluable": "NE",
}
SEED_STATUSES = tuple(SHORT_STATUS)
RESOLUTION_STATUSES = (
    "supported",
    "contradicted",
    "unresolved",
    "ungoverned",
    "gap_only",
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _blocking_ids(result: dict[str, Any]) -> list[str]:
    return [
        str(item.get("expectation_id") or "")
        for item in result.get("business_expectations") or []
        if item.get("blocking") and item.get("expectation_id")
    ]


def _seed_blocking_status(result: dict[str, Any], status: str) -> None:
    blocking_ids = set(_blocking_ids(result))
    for assessment in result.get("fulfillment_assessments") or []:
        if str(assessment.get("expectation_id") or "") in blocking_ids:
            assessment["status"] = status
            assessment["authority_tool_call_ids"] = []


def _attach_call(result: dict[str, Any], call_id: str) -> None:
    blocking_ids = set(_blocking_ids(result))
    for assessment in result.get("fulfillment_assessments") or []:
        if str(assessment.get("expectation_id") or "") in blocking_ids:
            assessment["authority_tool_call_ids"] = [call_id]


def _finalize(result: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_judge_result(result)
    if normalized is None:
        raise ValueError("invalid frozen Judge result")
    return to_dict(finalize_judge_result(normalized))


def _apply_resolution(
    result: dict[str, Any],
    *,
    call_id: str,
    resolution_status: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolution = AuthorityResolution(
        status=resolution_status,
        statement="mocked deterministic authority conclusion",
        reason="full Cartesian authority protocol probe",
        basis_evidence_ref_ids=("probe-evidence",),
        required_evidence=("missing-governing-material",)
        if resolution_status in {"unresolved", "ungoverned", "gap_only"}
        else (),
    )
    runtime_audit = {
        call_id: {
            "resolution": resolution,
            "environment_snapshot_sha256": "probe-snapshot",
        }
    }
    gate_audit = {
        call_id: {
            "resolution": to_dict(resolution),
            "environment_snapshot_sha256": "probe-snapshot",
        }
    }
    normalized = normalize_judge_result(result)
    if normalized is None:
        raise ValueError("invalid Judge result before authority gate")
    gated = apply_authority_gate(normalized, runtime_audit)
    return to_dict(finalize_judge_result(gated)), gate_audit


def _gate(
    result: dict[str, Any],
    *,
    authority_enabled: bool,
    authority_required: bool,
    availability: str,
    compact_material_backed: bool,
    call_ids: list[str],
    audit: dict[str, Any],
) -> dict[str, Any]:
    if not authority_enabled or not authority_required:
        return {"status": "not_applicable", "finding_counts": {}, "findings": []}
    return analyze_judge_gate_obligations(
        result=result,
        runtime={
            "authority_tool_call_ids": call_ids,
            "authority_audit": audit,
        },
        obligations=[{
            "subject": "client_search:case-specific-normative-claim",
            "trigger": "normative_rule",
            "authority_required": True,
            "authority_availability": availability,
            "compact_material_backed": compact_material_backed,
            "blocking_expectation_ids": _blocking_ids(result),
        }],
    )


def _expected_observable(
    *,
    seed_status: str,
    authority_enabled: bool,
    authority_required: bool,
    availability: str,
    compact_material_backed: bool | None,
    resolution_status: str | None,
) -> dict[str, Any]:
    final_status = seed_status
    gate_status = "not_applicable"
    findings: list[str] = []
    effectiveness = "PASS"
    if authority_enabled and authority_required:
        gate_status = "passed"
        if availability == "available":
            if resolution_status in {"unresolved", "ungoverned", "gap_only"}:
                final_status = "not_evaluable"
            elif resolution_status == "contradicted" and seed_status == "fulfilled":
                final_status = "not_evaluable"
        elif compact_material_backed is False:
            gate_status = "failed"
            findings = ["availability_miss"]
            if seed_status != "not_evaluable":
                effectiveness = "DETECTED_INVALID"
    return {
        "final_status": final_status,
        "gate_status": gate_status,
        "gate_findings": findings,
        "effectiveness": effectiveness,
    }


def _row(
    *,
    frozen_case: dict[str, Any],
    baseline_result: dict[str, Any],
    scenario: str,
    authority_enabled: bool,
    authority_required: bool,
    availability: str,
    compact_material_backed: bool | None,
    seed_status: str,
    resolution_status: str | None,
    expected_effect: str,
) -> dict[str, Any]:
    result = copy.deepcopy(baseline_result)
    baseline_status = str((result.get("overall_fulfillment") or {}).get("status") or "")
    _seed_blocking_status(result, seed_status)
    result = _finalize(result)
    initial_status = str((result.get("overall_fulfillment") or {}).get("status") or "")

    call_ids: list[str] = []
    gate_audit: dict[str, Any] = {}
    if authority_enabled and authority_required and resolution_status:
        call_id = f"authority.probe.{frozen_case['id']}.{scenario}.{seed_status}"
        call_ids = [call_id]
        _attach_call(result, call_id)
        result, gate_audit = _apply_resolution(
            result,
            call_id=call_id,
            resolution_status=resolution_status,
        )

    gate = _gate(
        result,
        authority_enabled=authority_enabled,
        authority_required=authority_required,
        availability=availability,
        compact_material_backed=bool(compact_material_backed),
        call_ids=call_ids,
        audit=gate_audit,
    )
    final_status = str((result.get("overall_fulfillment") or {}).get("status") or "")
    finding_codes = [str(item.get("code") or "") for item in gate.get("findings") or []]
    expected = _expected_observable(
        seed_status=seed_status,
        authority_enabled=authority_enabled,
        authority_required=authority_required,
        availability=availability,
        compact_material_backed=compact_material_backed,
        resolution_status=resolution_status,
    )
    actual = {
        "final_status": final_status,
        "gate_status": gate.get("status"),
        "gate_findings": finding_codes,
    }
    effectiveness = expected["effectiveness"] if actual == {
        key: expected[key] for key in actual
    } else "FAIL"
    trace = frozen_case.get("trace") or {}
    return {
        "case_id": frozen_case["id"],
        "query_input": frozen_case.get("user_intent") or "",
        "live_output": trace.get("extracted_output") or {},
        "expected_business_outcome_note": frozen_case.get("expected_business_outcome") or "",
        "scenario": scenario,
        "config": {
            "authority_enabled": authority_enabled,
            "authority_required": authority_required,
            "authority_availability": availability,
            "compact_material_backed": compact_material_backed,
            "mock_resolution_status": resolution_status,
            "judge_seed_status": seed_status,
        },
        "baseline_draft_status": SHORT_STATUS.get(baseline_status, baseline_status),
        "initial_status": SHORT_STATUS[initial_status],
        "authority_call_count": len(call_ids),
        "authority_resolution": resolution_status,
        "final_status": SHORT_STATUS[final_status],
        "gate_status": gate.get("status"),
        "gate_findings": finding_codes,
        "expected_effect": expected_effect,
        "effectiveness": effectiveness,
        "baseline_reason": baseline_result.get("reasoning_summary") or baseline_result.get("summary") or {},
    }


def _case_rows(
    frozen_case: dict[str, Any], baseline_result: dict[str, Any]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for authority_required in (False, True):
        for seed_status in SEED_STATUSES:
            rows.append(_row(
                frozen_case=frozen_case,
                baseline_result=baseline_result,
                scenario=(
                    "disabled_would_require_authority"
                    if authority_required else "disabled_not_required"
                ),
                authority_enabled=False,
                authority_required=authority_required,
                availability="disabled",
                compact_material_backed=None,
                seed_status=seed_status,
                resolution_status=None,
                expected_effect="Authority 关闭；零调用并保留 Judge 三态",
            ))
    for seed_status in SEED_STATUSES:
        rows.append(_row(
            frozen_case=frozen_case,
            baseline_result=baseline_result,
            scenario="enabled_not_required",
            authority_enabled=True,
            authority_required=False,
            availability="available",
            compact_material_backed=None,
            seed_status=seed_status,
            resolution_status=None,
            expected_effect="Authority 开启但无需裁决；零调用且结果不变",
        ))
    for seed_status in SEED_STATUSES:
        for resolution_status in RESOLUTION_STATUSES:
            rows.append(_row(
                frozen_case=frozen_case,
                baseline_result=baseline_result,
                scenario=f"available_{resolution_status}",
                authority_enabled=True,
                authority_required=True,
                availability="available",
                compact_material_backed=False,
                seed_status=seed_status,
                resolution_status=resolution_status,
                expected_effect="Authority 可用；按五值 resolution 消费依赖 assessment",
            ))
    for seed_status in SEED_STATUSES:
        rows.append(_row(
            frozen_case=frozen_case,
            baseline_result=baseline_result,
            scenario="unavailable_material_sufficient",
            authority_enabled=True,
            authority_required=True,
            availability="unavailable",
            compact_material_backed=True,
            seed_status=seed_status,
            resolution_status=None,
            expected_effect="Authority 不可用但固定材料充分；零调用并保留 Judge 结果",
        ))
        rows.append(_row(
            frozen_case=frozen_case,
            baseline_result=baseline_result,
            scenario="unavailable_gap",
            authority_enabled=True,
            authority_required=True,
            availability="unavailable",
            compact_material_backed=False,
            seed_status=seed_status,
            resolution_status=None,
            expected_effect="材料存在缺口；NE 合法，F/NF 必须被 availability_miss 检出",
        ))
    return rows


def _combination_key(row: dict[str, Any]) -> str:
    config = row["config"]
    return "|".join([
        str(config["authority_enabled"]).lower(),
        str(config["authority_required"]).lower(),
        str(config["authority_availability"]),
        str(config["compact_material_backed"]),
        str(config["mock_resolution_status"]),
        str(config["judge_seed_status"]),
    ])


def build_report() -> dict[str, Any]:
    config = _load_json(CONFIG_PATH)
    frozen_cases = _load_json(PROBES / config["frozen_source"])
    frozen_run = _load_json((PROBES / config["frozen_run"]).resolve())
    cases_by_id = {str(item["id"]): item for item in frozen_cases}
    rows_by_id = {str(item["case_key"]): item for item in frozen_run["rows"]}
    case_ids = list(dict.fromkeys(
        config["normal_case_ids"] + config["authority_case_ids"]
    ))
    rows = [
        row
        for case_id in case_ids
        for row in _case_rows(cases_by_id[case_id], rows_by_id[case_id]["draft"])
    ]
    counts: dict[str, Any] = {
        "rows": len(rows),
        "rows_per_case": {},
        "distinct_cases": len(case_ids),
        "distinct_combinations": len({_combination_key(row) for row in rows}),
        "final_status": {},
        "authority_enabled": {},
        "authority_required": {},
        "scenario": {},
        "effectiveness": {},
    }
    for row in rows:
        case_id = row["case_id"]
        counts["rows_per_case"][case_id] = counts["rows_per_case"].get(case_id, 0) + 1
        for key in ("final_status", "effectiveness", "scenario"):
            value = str(row[key])
            counts[key][value] = counts[key].get(value, 0) + 1
        for key in ("authority_enabled", "authority_required"):
            value = str(row["config"][key]).lower()
            counts[key][value] = counts[key].get(value, 0) + 1
    return {
        "schema_version": 2,
        "suite_id": config["suite_id"],
        "source": {
            "frozen_cases": config["frozen_source"],
            "frozen_run": config["frozen_run"],
            "frozen_run_status": frozen_run.get("run_status"),
            "frozen_run_case_count": frozen_run.get("case_count"),
            "frozen_run_authority_enabled": False,
        },
        "dimensions": {
            "case_ids": case_ids,
            "judge_seed_statuses": list(SEED_STATUSES),
            "resolution_statuses": list(RESOLUTION_STATUSES),
            "valid_combinations_per_case": 30,
        },
        "counts": counts,
        "rows": rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Client Search Judge Authority 全交叉验证矩阵",
        "",
        "说明：每个冻结业务 Case 都运行同一组 30 个合法配置组合；使用公共 `apply_authority_gate`、`analyze_judge_gate_obligations` 与 `finalize_judge_result`。",
        "",
        "| Case | Query 输入 | Live 输出 | 配置 | 是否应裁决 | Authority | 初始 | 最终 | Gate | 效果 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in report["rows"]:
        config = row["config"]
        live = json.dumps(row["live_output"], ensure_ascii=False, separators=(",", ":"))
        config_text = (
            f"enabled={str(config['authority_enabled']).lower()}, "
            f"available={config['authority_availability']}, "
            f"material={config['compact_material_backed']}"
        )
        authority = (
            f"calls={row['authority_call_count']}, "
            f"resolution={row['authority_resolution'] or '-'}"
        )
        gate = f"{row['gate_status']}:{','.join(row['gate_findings']) or '-'}"
        lines.append(
            "| " + " | ".join([
                f"{row['case_id']} / {row['scenario']}",
                str(row["query_input"]).replace("|", "\\|"),
                f"`{live}`".replace("|", "\\|"),
                config_text,
                "是" if config["authority_required"] else "否",
                authority,
                row["initial_status"],
                row["final_status"],
                gate,
                f"{row['effectiveness']}：{row['expected_effect']}",
            ]) + " |"
        )
    lines.extend([
        "",
        "## 汇总",
        "",
        "```json",
        json.dumps(report["counts"], ensure_ascii=False, indent=2),
        "```",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    report = build_report()
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    TABLE_PATH.write_text(render_markdown(report))
    print(json.dumps(report["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
