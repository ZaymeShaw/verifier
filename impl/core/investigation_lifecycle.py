"""调查增量门禁（spec/alg/investigate.md §1.8「增量门禁」）。

Gate 1 baseline（production → draft）：范围型逐字节复制 + 基线回执。
Gate 2 increment（draft → draft）：机器算漂移范围 → 人确认 → 机器重钉
确认范围内的哈希/切片并闭合校验。

路径全部由 项目+角色 按约定推导，不接受手工路径：
- production 包：``investigation/<role>/``
- draft 包：``draft/investigation/<role>/``
- 回执：``draft/.state/<role>/staleness/investigation-{baseline,drift-*,increment-*}.json``
"""
from __future__ import annotations

import dataclasses
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .investigation import detect_source_revision
from .path_contract import PathScope
from .portable_artifact import project_artifact_repository_root, write_active_artifact
from .project_loader import resolve_project_source_root
from .schema.investigation import dump_investigation_manifest, load_investigation_manifest
from .source_staleness import (
    compute_slice_hashes,
    detect_ref_drift,
    evidence_navigation_entry_keys,
    file_sha256,
    material_decision_keys,
)


class InvestigationLifecycleError(ValueError):
    """门禁拒绝：前置缺失、范围非法或闭合校验失败。"""


BASELINE_RECEIPT_NAME = "investigation-baseline.json"
_EXCLUDE_DIR_NAMES = {"__pycache__"}
_EXCLUDE_SUFFIXES = (".pyc",)
_EXCLUDE_NAME_MARKERS = (".bak",)


def production_package_path(spec: Any, role: str) -> Path:
    return spec.project_package_path(
        f"investigation/{role}",
        field_path=f"investigation.production_package.{role}",
        must_exist=False,
    )


def draft_package_path(spec: Any, role: str) -> Path:
    return spec.project_package_path(
        f"draft/investigation/{role}",
        field_path=f"investigation.draft_package.{role}",
        must_exist=False,
    )


def _state_staleness_dir(spec: Any, role: str) -> Path:
    project_root = spec.project_package_path(
        ".", field_path="project.package", expected_type="directory"
    )
    state = project_root / "draft" / ".state" / role / "staleness"
    state.mkdir(parents=True, exist_ok=True)
    return state


def _baseline_receipt_path(spec: Any, role: str) -> Path:
    return _state_staleness_dir(spec, role) / BASELINE_RECEIPT_NAME


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _write_receipt(path: Path, payload: Mapping[str, Any]) -> Path:
    return write_active_artifact(
        "staleness_report",
        path,
        dict(payload),
        repository_root=project_artifact_repository_root(path),
    )


def _is_excluded(relative: Path) -> bool:
    if any(part in _EXCLUDE_DIR_NAMES for part in relative.parts):
        return True
    name = relative.name
    return name.endswith(_EXCLUDE_SUFFIXES) or ".bak" in name


def _iter_package_files(package: Path) -> List[Path]:
    return sorted(
        relative
        for relative in (
            path.relative_to(package) for path in package.rglob("*") if path.is_file()
        )
        if not _is_excluded(relative)
    )


def _package_hashes(package: Path) -> Dict[str, str]:
    return {
        str(relative): file_sha256(package / relative)
        for relative in _iter_package_files(package)
    }


def _require_baseline_receipt(spec: Any, role: str) -> Mapping[str, Any]:
    import json

    path = _baseline_receipt_path(spec, role)
    if not path.is_file():
        raise InvestigationLifecycleError(
            f"Gate 1 未完成：缺少基线回执 {path}。先运行 "
            "investigation-lifecycle baseline。"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _business_evidence(manifest: Any) -> List[Any]:
    refs = []
    for evidence in manifest.evidence_refs:
        location_ref = evidence.location_ref
        if location_ref is None:
            continue
        scope = getattr(location_ref.location_scope, "value", "")
        if scope == "business_source":
            refs.append(evidence)
    return refs


def _logic_evidence(manifest: Any) -> List[Any]:
    """逻辑型证据：锚在项目包/包内的资产（project.yaml、judge.md、边界文档等）。

    其内容变化=行为变化，increment 只报告不重钉，由人复核。
    """
    refs = []
    for evidence in manifest.evidence_refs:
        location_ref = evidence.location_ref
        if location_ref is None:
            continue
        scope = getattr(location_ref.location_scope, "value", "")
        if scope in ("project_package", "artifact_package"):
            refs.append(evidence)
    return refs


def _drift_report_for(
    manifest: Any, source_root: Path, package: Path, ref: Any
) -> Dict[str, Any]:
    metadata = ref.metadata if isinstance(ref.metadata, dict) else {}
    slice_spec = metadata.get("slice") if isinstance(metadata.get("slice"), dict) else None
    report = detect_ref_drift(
        ref_id=str(ref.ref_id),
        path=source_root / str(ref.location_ref.location),
        declared_sha256=str(ref.location_ref.sha256 or ""),
        slice_spec=slice_spec,
        declared_slice_hashes=metadata.get("slice_hashes") or None,
        consumption=metadata.get("consumption") or (),
        decisions=material_decision_keys(manifest.as_dict(), str(ref.ref_id)),
        navigation_entry_keys=evidence_navigation_entry_keys(manifest.as_dict(), str(ref.ref_id)),
    )
    return report.as_dict()


# ---------------------------------------------------------------------------
# Gate 1: baseline
# ---------------------------------------------------------------------------

def _ensure_draft_role_copy(spec: Any, role: str, project_root: Path) -> str:
    """draft/<role>.py 缺失时把 production 实现逐字节复制过去，让 draft 开关可用。

    已有真实 draft 实现时不动；production 角色实现缺失时跳过。
    复制（而非生成薄 wrapper）：行为等价由逐字节相同保证；调查层想优化时
    直接改 draft 副本；晋升走标准流程把 draft 副本搬回 production。
    """
    draft_role = project_root / "draft" / f"{role}.py"
    if draft_role.is_file():
        return "existing"
    production_role = project_root / f"{role}.py"
    if not production_role.is_file():
        return "skipped-no-production-role"
    draft_role.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(production_role, draft_role)
    return "copied"


def _candidate_asset_gaps(spec: Any, role: str) -> List[str]:
    """该 role 声明了 candidate_path 但文件缺失的资产清单（fail-closed 用）。"""
    gaps: List[str] = []
    for mapping in spec.asset_mappings():
        if not mapping.enabled or role not in mapping.roles or not mapping.logical_candidate_path:
            continue
        candidate = spec.resolve_path(
            mapping.logical_candidate_path,
            field_path=f"verifier.assets.{mapping.asset_id}.candidate_path",
            allowed_scopes={PathScope.PROJECT_PACKAGE},
            must_exist=False,
        )
        if not candidate.exists():
            gaps.append(f"{mapping.asset_id}: {mapping.logical_candidate_path}")
    return gaps


def create_baseline(spec: Any, role: str, *, overwrite: bool = False) -> Dict[str, Any]:
    production = production_package_path(spec, role)
    draft = draft_package_path(spec, role)
    if not production.is_dir():
        raise InvestigationLifecycleError(f"production 调查包不存在: {production}")
    if draft.exists() and not overwrite:
        raise InvestigationLifecycleError(
            f"draft 调查包已存在: {draft}。确认废弃后先删除，或用 --force 覆盖。"
        )

    copied: List[str] = []
    excluded: List[str] = []
    for source_path in sorted(production.rglob("*")):
        relative = source_path.relative_to(production)
        if source_path.is_dir():
            continue
        if _is_excluded(relative):
            excluded.append(str(relative))
            continue
        target = draft / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        copied.append(str(relative))

    manifest_path = draft / "manifest.json"
    if not manifest_path.is_file():
        raise InvestigationLifecycleError(
            f"基线复制完成但目标缺少 manifest.json: {manifest_path}"
        )
    manifest = load_investigation_manifest(manifest_path)

    production_hashes = _package_hashes(production)
    draft_hashes = _package_hashes(draft)
    if production_hashes != draft_hashes:
        raise InvestigationLifecycleError(
            "基线校验失败：draft 包与 production 包逐文件哈希不一致"
        )

    source_root = (
        resolve_project_source_root(spec) if spec.has_business_source else None
    )
    current_revision = ""
    if source_root is not None:
        try:
            current_revision = detect_source_revision(source_root)
        except (OSError, RuntimeError, ValueError):
            current_revision = ""

    project_root = spec.project_package_path(
        ".", field_path="project.package", expected_type="directory"
    )

    # draft 模式可用性：角色实现复制 + 全部 candidate 资产完整性。
    role_impl_status = _ensure_draft_role_copy(spec, role, project_root)
    asset_gaps = _candidate_asset_gaps(spec, role)
    if asset_gaps:
        raise InvestigationLifecycleError(
            "基线校验失败：以下 candidate 资产缺失，draft 模式无法启用：\n  "
            + "\n  ".join(asset_gaps)
        )

    receipt = {
        "schema_version": 1,
        "gate": "baseline",
        "project_id": spec.project_id,
        "role": role,
        "generated_at": _stamp(),
        "source_package": production.relative_to(project_root).as_posix(),
        "target_package": draft.relative_to(project_root).as_posix(),
        "source_revision": manifest.source_revision,
        "current_source_revision": current_revision,
        "file_count": len(copied),
        "files": {name: digest for name, digest in sorted(draft_hashes.items())},
        "excluded": sorted(excluded),
        "draft_role_impl": role_impl_status,
        "candidate_asset_gaps": [],
    }
    _write_receipt(_baseline_receipt_path(spec, role), receipt)
    return receipt


# ---------------------------------------------------------------------------
# Gate 2: drift（机器算范围）
# ---------------------------------------------------------------------------


def drift_report(spec: Any, role: str) -> Dict[str, Any]:
    _require_baseline_receipt(spec, role)
    draft = draft_package_path(spec, role)
    manifest = load_investigation_manifest(draft / "manifest.json")
    source_root = (
        resolve_project_source_root(spec) if spec.has_business_source else None
    )
    if source_root is None or not Path(source_root).is_dir():
        raise InvestigationLifecycleError(
            "业务源码根不可达，无法计算漂移范围。请在有业务代码的机器上运行。"
        )

    drifted: List[Dict[str, Any]] = []
    clean: List[str] = []
    missing: List[str] = []
    for ref in _business_evidence(manifest):
        path = source_root / str(ref.location_ref.location)
        if not path.is_file():
            missing.append(str(ref.ref_id))
            continue
        report = _drift_report_for(manifest, source_root, draft, ref)
        if report["file_changed"] or report["slice_changes"]:
            drifted.append(report)
        else:
            clean.append(str(ref.ref_id))

    # 逻辑型资产漂移：只报告不重钉（内容变化=行为变化，必须人复核）。
    project_root = spec.project_package_path(
        ".", field_path="project.package", expected_type="directory"
    )
    logic_drift: List[Dict[str, str]] = []
    for ref in _logic_evidence(manifest):
        scope = getattr(ref.location_ref.location_scope, "value", "")
        base = project_root if scope == "project_package" else draft
        path = base / str(ref.location_ref.location)
        declared = str(
            ref.location_ref.sha256 or (ref.metadata or {}).get("sha256") or ""
        )
        if not path.is_file():
            logic_drift.append({
                "ref_id": str(ref.ref_id),
                "asset_ref": str(ref.location_ref.location),
                "reason": "file missing",
            })
            continue
        actual = file_sha256(path)
        if declared and actual != declared:
            logic_drift.append({
                "ref_id": str(ref.ref_id),
                "asset_ref": str(ref.location_ref.location),
                "declared_sha256": declared,
                "actual_sha256": actual,
                "reason": "content changed; human review required",
            })

    payload = {
        "schema_version": 1,
        "gate": "increment-scope",
        "project_id": spec.project_id,
        "role": role,
        "generated_at": _stamp(),
        "manifest_source_revision": manifest.source_revision,
        "drifted": drifted,
        "logic_drift": logic_drift,
        "clean": sorted(clean),
        "missing": sorted(missing),
        "needs_confirmation": [str(item["ref_id"]) for item in drifted],
    }
    out = _state_staleness_dir(spec, role) / f"investigation-drift-{_stamp()}.json"
    _write_receipt(out, payload)

    print(f"=== Gate 2 增量范围（{spec.project_id}/{role}） ===")
    print(f"manifest source_revision: {manifest.source_revision}")
    if not drifted and not missing:
        print("无业务源漂移：所有 business_source 证据哈希与磁盘一致。")
    for item in drifted:
        print(f"\n[漂移] {item['ref_id']}  routing={item['routing']}")
        print(f"  declared={item['declared_sha256'][:12]}  actual={item['actual_sha256'][:12]}")
        slices = [change["slice_key"] for change in item.get("slice_changes") or []]
        if slices:
            print(f"  变化切片({len(slices)}): {', '.join(slices)}")
        if item.get("affected_decisions"):
            print(f"  牵连 decision（待人复核）: {', '.join(item['affected_decisions'])}")
    if logic_drift:
        print("\n[逻辑型漂移] 以下资产内容已变化，可能影响判定逻辑，需人复核（不自动重钉）:")
        for item in logic_drift:
            print(f"  {item['ref_id']}: {item['asset_ref']}（{item['reason']}）")
    if missing:
        print(f"\n[缺失] 业务文件不存在: {', '.join(missing)}")
    if clean:
        print(f"\n[一致] {len(clean)} 份: {', '.join(clean)}")
    print(f"\n待确认增量范围: {', '.join(payload['needs_confirmation']) or '（无）'}")
    print(f"范围报告: {out}")
    return payload


# ---------------------------------------------------------------------------
# Gate 2: increment（机器执行确认范围 + 闭合校验）
# ---------------------------------------------------------------------------


def apply_increment(
    spec: Any,
    role: str,
    confirmed_refs: Sequence[str],
    *,
    source_revision: str = "",
) -> Dict[str, Any]:
    _require_baseline_receipt(spec, role)
    refs = [str(item).strip() for item in confirmed_refs if str(item).strip()]
    if not refs:
        raise InvestigationLifecycleError(
            "increment 需要确认范围：--refs 至少给一个 EvidenceRef id"
            "（先运行 drift 查看待确认清单）。"
        )

    draft = draft_package_path(spec, role)
    manifest_path = draft / "manifest.json"
    manifest = load_investigation_manifest(manifest_path)
    source_root = (
        resolve_project_source_root(spec) if spec.has_business_source else None
    )
    if source_root is None or not Path(source_root).is_dir():
        raise InvestigationLifecycleError(
            "业务源码根不可达，无法执行增量。请在有业务代码的机器上运行。"
        )

    business = {str(ref.ref_id): ref for ref in _business_evidence(manifest)}
    unknown = [ref_id for ref_id in refs if ref_id not in business]
    if unknown:
        raise InvestigationLifecycleError(
            f"确认范围包含未知/非 business_source 的 EvidenceRef: {', '.join(unknown)}"
        )

    target_revision = str(source_revision or "").strip()
    if not target_revision:
        target_revision = detect_source_revision(source_root)
    if not target_revision:
        raise InvestigationLifecycleError(
            "无法确定目标 source_revision：业务仓库不是 git checkout，"
            "请显式传 --source-revision。"
        )

    updated: List[Dict[str, Any]] = []
    for ref_id in refs:
        ref = business[ref_id]
        path = source_root / str(ref.location_ref.location)
        if not path.is_file():
            raise InvestigationLifecycleError(f"源文件不存在，无法重钉: {path}")
        actual = file_sha256(path)
        metadata = ref.metadata if isinstance(ref.metadata, dict) else {}
        slice_spec = metadata.get("slice") if isinstance(metadata.get("slice"), dict) else None
        before = str(ref.location_ref.sha256 or "")
        ref.location_ref = dataclasses.replace(ref.location_ref, sha256=actual)
        metadata["sha256"] = actual
        if slice_spec is not None:
            metadata["slice_hashes"] = compute_slice_hashes(path, slice_spec)
            metadata["slice_hashes_source_sha256"] = actual
        metadata["source_revision"] = target_revision
        updated.append(
            {
                "ref_id": ref_id,
                "before_sha256": before,
                "after_sha256": actual,
                "changed": before != actual,
            }
        )

    # revision pin 是包级声明：钉到目标版本后，所有 business_source 证据的
    # source_revision 元数据必须同步（结构校验要求二者一致）。这是 pin 同步，
    # 不是内容修改，全部记录在回执里。
    synced: List[str] = []
    for ref_id, ref in business.items():
        if ref_id in refs:
            continue
        metadata = ref.metadata if isinstance(ref.metadata, dict) else {}
        if str(metadata.get("source_revision") or "") != target_revision:
            metadata["source_revision"] = target_revision
            synced.append(ref_id)
    manifest.source_revision = target_revision

    # 闭合校验先于写盘：manifest 写入会触发全包校验（含哈希严格校验），
    # 带遗留漂移的 manifest 不允许落盘。
    violations = _closure_violations(manifest, source_root)
    deferred = [
        str(item["ref_id"])
        for item in violations
        if item["reason"] == "file hash drift remains"
    ]
    receipt = {
        "schema_version": 1,
        "gate": "increment",
        "project_id": spec.project_id,
        "role": role,
        "generated_at": _stamp(),
        "source_revision": target_revision,
        "confirmed_refs": refs,
        "updated": updated,
        "revision_pin_synced": synced,
        "closure": {"passed": not violations, "violations": violations},
        "deferred_drift": deferred,
    }
    out = _state_staleness_dir(spec, role) / f"investigation-increment-{_stamp()}.json"
    _write_receipt(out, receipt)

    if violations:
        details = "; ".join(
            f"{item['ref_id']}: {item['reason']}" for item in violations
        )
        raise InvestigationLifecycleError(
            f"确认范围不完整，manifest 未写入（回执 {out}）：{details}。"
            "请补齐确认范围后重跑 increment（可一次给全：--refs "
            + ",".join(refs + [ref_id for ref_id in deferred if ref_id not in refs])
            + "）。"
        )
    dump_investigation_manifest(manifest, manifest_path)
    receipt["receipt"] = str(out)
    return receipt


def require_increment_closed(spec: Any, role: str) -> None:
    """物化候选包前的门禁（investigate.md 增量门禁出口条件）。

    要求：基线回执存在，且最新增量回执的闭合校验通过。未闭合即拒绝，
    避免把带漂移登记哈希的候选内容导出为资料。
    """
    import json as _json

    state = _state_staleness_dir(spec, role)
    _require_baseline_receipt(spec, role)
    increments = sorted(state.glob("investigation-increment-*.json"))
    if not increments:
        raise InvestigationLifecycleError(
            f"Gate 2 未完成：{state} 下没有增量回执。先运行 "
            "investigation-lifecycle --gate drift 查看范围，确认后用 "
            "--gate increment --refs <清单> 执行。"
        )
    latest = _json.loads(increments[-1].read_text(encoding="utf-8"))
    closure = latest.get("closure") or {}
    if closure.get("passed") is not True:
        raise InvestigationLifecycleError(
            f"最新增量回执未闭合（{increments[-1].name}）："
            + "; ".join(
                f"{item.get('ref_id')}: {item.get('reason')}"
                for item in closure.get("violations") or []
            )
        )


def _closure_violations(manifest: Any, source_root: Path) -> List[Dict[str, str]]:
    violations: List[Dict[str, str]] = []
    for ref in _business_evidence(manifest):
        ref_id = str(ref.ref_id)
        path = source_root / str(ref.location_ref.location)
        if not path.is_file():
            violations.append({"ref_id": ref_id, "reason": "source file missing"})
            continue
        declared = str(ref.location_ref.sha256 or "")
        actual = file_sha256(path)
        if declared != actual:
            violations.append({"ref_id": ref_id, "reason": "file hash drift remains"})
            continue
        metadata = ref.metadata if isinstance(ref.metadata, dict) else {}
        slice_spec = metadata.get("slice") if isinstance(metadata.get("slice"), dict) else None
        if slice_spec is None:
            continue
        declared_slices = metadata.get("slice_hashes") or {}
        actual_slices = compute_slice_hashes(path, slice_spec)
        if dict(declared_slices) != actual_slices:
            violations.append({"ref_id": ref_id, "reason": "slice hashes drift remains"})
    return violations
