from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


VALIDATION_RECEIPT_VERSION = 1


@dataclass(frozen=True)
class InvestigationValidationReceipt:
    schema_version: int
    project_id: str
    role: str
    manifest_sha256: str
    source_revision: str
    source_root: str
    tool_inputs_sha256: str
    tools: tuple[Mapping[str, Any], ...]


def validation_receipt_path(spec: Any, role: str) -> Path:
    return Path(spec.root) / "draft" / ".state" / str(role) / "investigation-validation.json"


def write_investigation_validation_receipt(
    spec: Any,
    role: str,
    validation_result: Mapping[str, Any],
    tool_inputs: Mapping[str, Any],
) -> Path:
    if validation_result.get("ok") is not True or validation_result.get("tool_execution_requested") is not True:
        raise ValueError("Investigation validation receipt requires a successful --execute-tools result")
    tools = tuple(dict(item) for item in validation_result.get("tools") or [])
    if any(item.get("execution") != "succeeded" or int(item.get("execution_count") or 0) < 1 for item in tools):
        raise ValueError("Investigation validation receipt requires every implemented Tool to execute")
    source_revision = str(validation_result.get("source_revision") or "")
    receipt = InvestigationValidationReceipt(
        schema_version=VALIDATION_RECEIPT_VERSION,
        project_id=str(spec.project_id),
        role=str(role),
        manifest_sha256=str(validation_result.get("manifest_sha256") or ""),
        source_revision=source_revision,
        source_root=str(validation_result.get("source_root") or ""),
        tool_inputs_sha256=_stable_hash(tool_inputs),
        tools=tools,
    )
    if not receipt.manifest_sha256 or not receipt.tool_inputs_sha256:
        raise ValueError("Investigation validation receipt is missing immutable validation hashes")
    path = validation_receipt_path(spec, role)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(receipt), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def require_investigation_validation_receipt(spec: Any, role: str) -> Mapping[str, Any]:
    """Fail closed unless the candidate investigation package and Tool bytes were executed."""
    from .investigation import validate_investigation_package
    from .project_loader import resolve_role_assets

    path = validation_receipt_path(spec, role)
    if not path.is_file():
        raise FileNotFoundError(
            f"Draft investigation has no successful Tool validation receipt: {path}; "
            "run validate_investigation.py --execute-tools"
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise TypeError(f"Investigation validation receipt must be an object: {path}")
    if int(raw.get("schema_version") or 0) != VALIDATION_RECEIPT_VERSION:
        raise ValueError(f"unsupported Investigation validation receipt version: {path}")
    if raw.get("project_id") != spec.project_id or raw.get("role") != role:
        raise ValueError(f"Investigation validation receipt identity mismatch: {path}")

    selected = resolve_role_assets(spec, role, use_candidate=True)
    packages = [Path(item["path"]) for item in selected if item["mapping"].kind == "investigation"]
    if len(packages) != 1:
        raise ValueError(
            f"Draft role={role} requires exactly one enabled investigation package; found={len(packages)}"
        )
    tool_aliases = {
        str(item["mapping"].production_path): Path(item["path"])
        for item in selected
        if item["mapping"].kind == "tool" and item["available"]
    }
    current = validate_investigation_package(
        packages[0],
        project_root=Path(spec.root),
        expected_project_id=spec.project_id,
        expected_role=role,
        tool_module_overrides=tool_aliases,
        source_root=Path(spec.source_project) if getattr(spec, "source_project", "") else None,
    )
    if raw.get("manifest_sha256") != current.get("manifest_sha256"):
        raise ValueError("Investigation validation receipt is stale: manifest changed")
    if raw.get("source_revision") != current.get("source_revision"):
        raise ValueError("Investigation validation receipt is stale: business source revision changed")
    if str(raw.get("source_root") or "") != str(current.get("source_root") or ""):
        raise ValueError("Investigation validation receipt is stale: business source repository changed")

    recorded_tools = {
        str(item.get("tool_id")): item
        for item in raw.get("tools") or []
        if isinstance(item, Mapping)
    }
    current_tools = {str(item.get("tool_id")): item for item in current.get("tools") or []}
    if set(recorded_tools) != set(current_tools):
        raise ValueError("Investigation validation receipt is stale: implemented Tool set changed")
    for tool_id, item in current_tools.items():
        recorded = recorded_tools[tool_id]
        if recorded.get("module_sha256") != item.get("module_sha256"):
            raise ValueError(f"Investigation validation receipt is stale: Tool changed: {tool_id}")
        if recorded.get("execution") != "succeeded" or int(recorded.get("execution_count") or 0) < 1:
            raise ValueError(f"Investigation validation receipt did not execute Tool: {tool_id}")
    return raw


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
