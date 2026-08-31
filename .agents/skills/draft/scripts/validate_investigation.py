#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from impl.core.draft_gate_feedback import build_authority_gate_feedback, write_gate_feedback
from impl.core.investigation import validate_investigation_package
from impl.core.investigation_validation import write_investigation_validation_receipt
from impl.core.project_loader import load_project, resolve_role_assets


def _load_tool_inputs(value: str) -> dict:
    raw = value.strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        loaded = json.loads(raw)
    else:
        loaded = json.loads(Path(raw).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise TypeError("--tool-inputs must be a JSON object keyed by tool_id")
    return loaded


def _require_key_index_selection_receipts(
    package: Path, project_root: Path, project_id: str, role: str
) -> None:
    """A Manifest-registered Key-Index is a formal asset; it must be backed by
    a passing selection-phase receipt from validate_key_index_experiment.py
    whose report is still byte-identical."""
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    registered = {
        str(item.get("index_key") or "").strip()
        for item in manifest.get("key_indexes") or []
        if str(item.get("index_key") or "").strip()
        and str(item.get("target_kind") or "").strip()
        not in {"material_decision", "evidence_locator"}
    }
    if not registered:
        return
    gates_dir = project_root / "draft" / ".state" / role / "key-index-gates"
    covered: set[str] = set()
    for receipt_path in sorted(gates_dir.glob("*-selection.json")) if gates_dir.is_dir() else []:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("project_id") != project_id or receipt.get("role") != role:
            continue
        if receipt.get("phase") != "selection" or receipt.get("decision_status") != "selected":
            continue
        report_path = project_root / str(receipt.get("report_location") or "")
        if not report_path.is_file():
            continue
        if hashlib.sha256(report_path.read_bytes()).hexdigest() != receipt.get("report_sha256"):
            continue
        covered.update(str(key) for key in receipt.get("index_keys") or [])
    missing = sorted(registered - covered)
    if missing:
        raise ValueError(
            "Manifest key_indexes registered without a passing Key-Index selection "
            "receipt (run validate_key_index_experiment.py --phase selection on the "
            "frozen experiment report first): " + ", ".join(missing)
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate one Draft investigation package.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--execute-tools", action="store_true")
    parser.add_argument(
        "--tool-inputs",
        default="",
        help="Inline JSON or JSON file: tool_id -> list of kwargs objects.",
    )
    args = parser.parse_args()
    if args.tool_inputs and not args.execute_tools:
        parser.error("--tool-inputs requires --execute-tools")

    spec = load_project(args.project)
    project_root = spec.project_package_path(
        ".",
        field_path="project.package",
        expected_type="directory",
    )
    package = spec.project_package_path(
        f"draft/investigation/{args.role}",
        field_path=f"verifier.assets.investigation.{args.role}",
        expected_type="directory",
    )
    role_root = Path(__file__).resolve().parents[1]
    tool_module_overrides = {
        item["mapping"].production_path: Path(item["path"])
        for item in resolve_role_assets(spec, args.role, use_candidate=True)
        if item["mapping"].kind == "tool" and item["available"]
    }
    tool_inputs = _load_tool_inputs(args.tool_inputs) if args.tool_inputs else None
    feedback_path = project_root / "draft" / ".state" / args.role / "investigation-gate-feedback.json"
    try:
        result = validate_investigation_package(
            package,
            project_root=project_root,
            expected_project_id=args.project,
            expected_role=args.role,
            role_contract_root=role_root,
            execute_tools=args.execute_tools,
            tool_module_overrides=tool_module_overrides,
            tool_test_inputs=tool_inputs,
            source_root=spec.source_root_path() if spec.has_business_source else None,
            # 调查校验关心结构与工具执行；业务源漂移记入警告，闭合归 Solidify。
            business_source_staleness_policy="warn",
        )
        _require_key_index_selection_receipts(
            package, project_root, args.project, args.role
        )
    except Exception as exc:  # noqa: BLE001 - CLI must preserve gate diagnosis
        feedback = build_authority_gate_feedback(
            project_id=args.project, role=args.role, owner_stage="investigate", error=exc
        )
        write_gate_feedback(feedback_path, feedback)
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        print(feedback["diagnosis"], file=sys.stderr)
        print(f"Harness feedback: {feedback_path}", file=sys.stderr)
        return 1
    # The gate passed: stale feedback must not keep blocking the Draft Loop.
    feedback_path.unlink(missing_ok=True)
    if args.execute_tools:
        receipt = write_investigation_validation_receipt(
            spec,
            args.role,
            result,
            tool_inputs or {},
        )
        result["validation_receipt"] = str(receipt)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
