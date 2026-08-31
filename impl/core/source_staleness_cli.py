"""CLI for the business-source staleness public facility.

Subcommands (Core-owned; the .agents skill wrapper may delegate here):

- persist-slice-hashes : freeze-time backfill of per-slice content hashes
- report-drift         : read-only consumption-aware drift routing table
- refresh-absorbable   : atomic refresh of EvidenceRef hashes routed absorb

Usage:
  python -m impl.core.source_staleness_cli --project client_search --role judge <subcommand>
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from impl.core.project_loader import (
    load_project,
    resolve_project_source_root,
    resolve_role_assets,
)
from impl.core.portable_artifact import project_artifact_repository_root, write_active_artifact
from impl.core.schema.investigation import (
    dump_investigation_manifest,
    load_investigation_manifest,
)
from impl.core.source_staleness import (
    ROUTING_ABSORB,
    build_audit_record,
    compute_slice_hashes,
    compute_slice_hashes_from_text,
    audit_large_materials_without_retrieval_channel,
    detect_ref_drift,
    evidence_navigation_entry_keys,
    file_sha256,
    material_decision_keys,
)

_STALENESS_STATE_RELATIVE = "draft/.state"


def _manifest_and_paths(spec: Any, role: str):
    project_root = spec.project_package_path(
        ".",
        field_path="project.package",
        expected_type="directory",
    )
    # 经角色资产解析调查包：draft 期落 candidate_path，晋升后落 production_path。
    packages = [
        Path(item["path"])
        for item in resolve_role_assets(spec, role, use_candidate=True)
        if item["mapping"].kind == "investigation"
    ]
    if len(packages) != 1:
        raise ValueError(
            f"expected exactly one {role} investigation package, got {len(packages)}"
        )
    package = packages[0]
    if not package.is_dir():
        raise FileNotFoundError(f"{role} investigation package not found: {package}")
    source_root = resolve_project_source_root(spec) if spec.has_business_source else None
    manifest_path = package / "manifest.json"
    manifest = load_investigation_manifest(manifest_path)
    return project_root, package, source_root, manifest_path, manifest


def _resolve_ref_path(spec: Any, project_root: Path, package: Path, source_root: Path | None, ref: Any) -> Path | None:
    location_ref = ref.location_ref
    if location_ref is None:
        return None
    location = str(location_ref.location or "").strip()
    scope = getattr(location_ref.location_scope, "value", None) or ""
    if scope == "project_package":
        return project_root / location
    if scope == "artifact_package":
        return package / location
    if scope == "business_source" and source_root is not None:
        return source_root / location
    return None


def _embedding_entry_keys(package: Path) -> list[str]:
    for path in sorted((package / "experiments").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        vectors = data.get("entry_vectors")
        if isinstance(vectors, dict):
            return sorted(str(key) for key in vectors)
    return []


def _frozen_content(
    manifest: Any,
    source_root: Path | None,
    path: Path,
    declared_sha256: str,
) -> tuple[str | None, bool]:
    """Return the frozen slice source text when it can be recovered.

    The frozen baseline is the content whose file hash equals the declared
    EvidenceRef hash: the current file when clean, or the committed revision
    content for business-source refs when the declared hash matches a commit.
    Otherwise the baseline is unknowable and only file-level detection applies.
    """
    actual = file_sha256(path)
    if declared_sha256 and actual == declared_sha256:
        return path.read_text(encoding="utf-8"), True
    if source_root is not None and path.is_relative_to(source_root):
        relative = path.relative_to(source_root).as_posix()
        revisions = {str(manifest.source_revision or ""), "HEAD"}
        for revision in sorted(revisions):
            if not revision:
                continue
            try:
                result = subprocess.run(
                    ["git", "-C", str(source_root), "show", f"{revision}:{relative}"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except (OSError, subprocess.CalledProcessError):
                continue
            if hashlib.sha256(result.stdout.encode("utf-8")).hexdigest() == declared_sha256:
                return result.stdout, True
    return None, False

def _drift_report_for_ref(spec: Any, project_root: Path, package: Path, source_root: Path | None, manifest: Any, ref: Any):
    ref_id = str(ref.ref_id or "").strip()
    path = _resolve_ref_path(spec, project_root, package, source_root, ref)
    if path is None or not path.is_file():
        return None
    metadata = ref.metadata if isinstance(ref.metadata, dict) else {}
    slice_spec = metadata.get("slice") if isinstance(metadata.get("slice"), dict) else None
    return detect_ref_drift(
        ref_id=ref_id,
        path=path,
        declared_sha256=str(ref.location_ref.sha256 or "") if ref.location_ref else "",
        slice_spec=slice_spec,
        declared_slice_hashes=metadata.get("slice_hashes") or None,
        consumption=metadata.get("consumption") or (),
        decisions=material_decision_keys(manifest.as_dict(), ref_id),
        navigation_entry_keys=evidence_navigation_entry_keys(manifest.as_dict(), ref_id),
        embedding_entry_keys=_embedding_entry_keys(package),
    )


def _state_dir(project_root: Path, role: str) -> Path:
    state = project_root / _STALENESS_STATE_RELATIVE / role / "staleness"
    state.mkdir(parents=True, exist_ok=True)
    return state


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _cmd_persist_slice_hashes(spec: Any, role: str) -> int:
    project_root, package, source_root, manifest_path, manifest = _manifest_and_paths(spec, role)
    updated: list[str] = []
    skipped: list[str] = []
    for ref in manifest.evidence_refs:
        metadata = ref.metadata
        slice_spec = metadata.get("slice") if isinstance(metadata.get("slice"), dict) else None
        if slice_spec is None:
            continue
        path = _resolve_ref_path(spec, project_root, package, source_root, ref)
        if path is None or not path.is_file():
            print(f"skip {ref.ref_id}: source not found", file=sys.stderr)
            continue
        declared = str(ref.location_ref.sha256 or "") if ref.location_ref else ""
        frozen_text, known = _frozen_content(manifest, source_root, path, declared)
        if not known:
            metadata.pop("slice_hashes", None)
            metadata.pop("slice_hashes_source_sha256", None)
            skipped.append(str(ref.ref_id))
            continue
        hashes = (
            compute_slice_hashes(path, slice_spec)
            if frozen_text is None
            else compute_slice_hashes_from_text(frozen_text, slice_spec)
        )
        metadata["slice_hashes"] = hashes
        metadata["slice_hashes_source_sha256"] = declared or file_sha256(path)
        updated.append(str(ref.ref_id))
    if not updated:
        print("no sliced EvidenceRefs to persist")
        if skipped:
            print(f"frozen baseline unknown for: {', '.join(skipped)}")
        return 0
    dump_investigation_manifest(manifest, manifest_path)
    print(f"persisted slice hashes for: {', '.join(updated)}")
    if skipped:
        print(f"frozen baseline unknown (file-level only), re-freeze after review: {', '.join(skipped)}")
    print(f"manifest: {manifest_path}")
    return 0


def _cmd_report_drift(spec: Any, role: str) -> int:
    project_root, package, source_root, manifest_path, manifest = _manifest_and_paths(spec, role)
    rows: list[dict[str, Any]] = []
    for ref in manifest.evidence_refs:
        report = _drift_report_for_ref(spec, project_root, package, source_root, manifest, ref)
        if report is None:
            continue
        rows.append(report.as_dict())
        print(
            f"{report.ref_id:<38} {report.routing:<18} "
            f"changed={int(report.file_changed)} slices={len(report.slice_changes)} "
            f"decisions={len(report.affected_decisions)} reason={report.reason}"
        )
    state = _state_dir(project_root, role)
    out = state / f"drift-report-{_stamp()}.json"
    write_active_artifact(
        "staleness_report", out, rows, repository_root=project_artifact_repository_root(out)
    )
    print(f"report: {out}")
    return 0


def _cmd_report_large_materials(spec: Any, role: str, threshold: int) -> int:
    project_root, package, source_root, manifest_path, manifest = _manifest_and_paths(spec, role)
    if source_root is None:
        print("no business source root configured; skipping large-material audit", file=sys.stderr)
        return 0
    declared_sources: dict[str, Path] = {}
    raw_paths = (
        ((spec.project.get("resources") or {}).get("source") or {}).get("paths") or {}
    )
    for logical_name, logical in raw_paths.items():
        if isinstance(logical, str) and logical.startswith("business://"):
            path = source_root / logical.removeprefix("business://")
            if path.is_file():
                declared_sources[str(logical_name)] = path
    findings = audit_large_materials_without_retrieval_channel(
        manifest,
        source_root,
        threshold_chars=threshold,
        declared_sources=declared_sources,
    )
    state = _state_dir(project_root, role)
    out = state / f"large-materials-{_stamp()}.json"
    report = {
        "schema_version": 1,
        "report_type": "large-materials",
        "generated_at": _stamp(),
        "threshold_chars": threshold,
        "refs_evaluated": len(manifest.evidence_refs),
        "findings": findings,
        "summary": {
            "large_without_retrieval_channel": len(findings),
            "ok": len(findings) == 0,
        },
    }
    write_active_artifact(
        "staleness_report", out, report, repository_root=project_artifact_repository_root(out)
    )
    if not findings:
        print("no large business-source materials without a retrieval channel")
    else:
        for item in findings:
            size = item.get("size_chars")
            size_str = f"{size:,}" if size is not None else "?"
            ref = item.get("ref_id") or item.get("logical_name") or "?"
            print(
                f"{ref:<38} size={size_str:>10} chars  "
                f"channel=MISSING  {item['problem']}"
            )
    print(f"report: {out}")
    return 0 if not findings else 2


def _cmd_refresh_absorbable(spec: Any, role: str) -> int:
    project_root, package, source_root, manifest_path, manifest = _manifest_and_paths(spec, role)
    audit: list[dict[str, Any]] = []
    updated: list[str] = []
    for ref in manifest.evidence_refs:
        path = _resolve_ref_path(spec, project_root, package, source_root, ref)
        if path is None or not path.is_file():
            continue
        report = _drift_report_for_ref(spec, project_root, package, source_root, manifest, ref)
        if report is None or report.routing != ROUTING_ABSORB:
            continue
        metadata = ref.metadata
        if ref.location_ref is not None:
            ref.location_ref = dataclasses.replace(
                ref.location_ref, sha256=report.actual_sha256
            )
        metadata["sha256"] = report.actual_sha256
        slice_spec = metadata.get("slice") if isinstance(metadata.get("slice"), dict) else None
        if slice_spec is not None and report.actual_sha256:
            hashes = compute_slice_hashes(path, slice_spec)
            metadata["slice_hashes"] = hashes
            metadata["slice_hashes_source_sha256"] = report.actual_sha256
        audit.append(build_audit_record(
            ref_id=ref.ref_id,
            action="auto_absorb",
            report=report,
            outcome={"manifest_sha256_changed": True},
        ))
        updated.append(str(ref.ref_id))
    if not updated:
        print("no absorbable refs; nothing refreshed")
        return 0
    dump_investigation_manifest(manifest, manifest_path)
    state = _state_dir(project_root, role)
    ledger = state / f"audit-{_stamp()}.json"
    write_active_artifact(
        "staleness_report", ledger, audit, repository_root=project_artifact_repository_root(ledger)
    )
    print(f"refreshed: {', '.join(updated)}")
    print(f"audit ledger: {ledger}")
    print("validation receipt stays valid: absorb only re-pins hashes, manifest structure is unchanged")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Business-source staleness facility CLI")
    parser.add_argument("--project", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument(
        "--threshold",
        type=int,
        default=30000,
        help="large-material size threshold in characters (default: 30000)",
    )
    parser.add_argument(
        "command",
        choices=[
            "persist-slice-hashes",
            "report-drift",
            "report-large-materials",
            "refresh-absorbable",
        ],
    )
    args = parser.parse_args(argv)
    spec = load_project(args.project)
    if args.command == "persist-slice-hashes":
        return _cmd_persist_slice_hashes(spec, args.role)
    if args.command == "report-drift":
        return _cmd_report_drift(spec, args.role)
    if args.command == "report-large-materials":
        return _cmd_report_large_materials(spec, args.role, args.threshold)
    return _cmd_refresh_absorbable(spec, args.role)


if __name__ == "__main__":
    raise SystemExit(main())
