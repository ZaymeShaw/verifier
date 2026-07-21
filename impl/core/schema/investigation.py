from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .base import to_dict
from .evidence import EvidenceRef


INVESTIGATION_SCHEMA_VERSION = 1
MAX_INLINE_EVIDENCE_PAYLOAD_BYTES = 16_384


@dataclass(frozen=True)
class ToolImplementationRef:
    tool_id: str
    module_path: str
    factory: str


@dataclass
class ToolRequirement:
    tool_id: str
    description: str
    applicable_scenario: str
    parameters: Dict[str, Any]
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    implementation: Optional[ToolImplementationRef] = None
    implementation_gap: str = ""


@dataclass
class InvestigationManifest:
    schema_version: int
    project_id: str
    role: str
    source_revision: str
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    tool_requirements: list[ToolRequirement] = field(default_factory=list)
    artifacts: Dict[str, str] = field(default_factory=dict)
    unresolved_reason: str = ""

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InvestigationManifest":
        evidence_refs = [_evidence_ref(item) for item in value.get("evidence_refs") or []]
        requirements = [_tool_requirement(item) for item in value.get("tool_requirements") or []]
        return cls(
            schema_version=int(value.get("schema_version") or 0),
            project_id=str(value.get("project_id") or ""),
            role=str(value.get("role") or ""),
            source_revision=str(value.get("source_revision") or ""),
            evidence_refs=evidence_refs,
            tool_requirements=requirements,
            artifacts={str(key): str(item) for key, item in dict(value.get("artifacts") or {}).items()},
            unresolved_reason=str(value.get("unresolved_reason") or ""),
        )

    def as_dict(self) -> Dict[str, Any]:
        return to_dict(self)


def load_investigation_manifest(path: Path) -> InvestigationManifest:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise TypeError("investigation manifest must be a JSON object")
    return InvestigationManifest.from_dict(raw)


def dump_investigation_manifest(manifest: InvestigationManifest, path: Path) -> None:
    Path(path).write_text(
        json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def validate_investigation_manifest(manifest: InvestigationManifest) -> None:
    if manifest.schema_version != INVESTIGATION_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported investigation schema_version={manifest.schema_version}; "
            f"expected {INVESTIGATION_SCHEMA_VERSION}"
        )
    for field_name in ("project_id", "role", "source_revision"):
        if not str(getattr(manifest, field_name) or "").strip():
            raise ValueError(f"InvestigationManifest.{field_name} is required")

    evidence_ids: set[str] = set()
    for evidence in manifest.evidence_refs:
        _validate_evidence_ref(evidence)
        if evidence.ref_id in evidence_ids:
            raise ValueError(f"duplicate EvidenceRef.ref_id: {evidence.ref_id}")
        evidence_ids.add(evidence.ref_id)

    tool_ids: set[str] = set()
    for requirement in manifest.tool_requirements:
        _validate_tool_requirement(requirement)
        if requirement.tool_id in tool_ids:
            raise ValueError(f"duplicate ToolRequirement.tool_id: {requirement.tool_id}")
        tool_ids.add(requirement.tool_id)
        for evidence in requirement.evidence_refs:
            if evidence.ref_id in evidence_ids:
                raise ValueError(f"duplicate EvidenceRef.ref_id: {evidence.ref_id}")
            evidence_ids.add(evidence.ref_id)

    for artifact_path, purpose in manifest.artifacts.items():
        if not artifact_path.strip() or not purpose.strip():
            raise ValueError("InvestigationManifest.artifacts requires non-empty path and purpose")


def _evidence_ref(value: Any) -> EvidenceRef:
    if isinstance(value, EvidenceRef):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("evidence_refs items must be objects")
    return EvidenceRef(
        ref_id=str(value.get("ref_id") or ""),
        source=str(value.get("source") or ""),
        kind=str(value.get("kind") or ""),
        stage=str(value.get("stage") or ""),
        summary=str(value.get("summary") or ""),
        location=str(value.get("location") or ""),
        payload=value.get("payload"),
        metadata=dict(value.get("metadata") or {}),
    )


def _tool_requirement(value: Any) -> ToolRequirement:
    if isinstance(value, ToolRequirement):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("tool_requirements items must be objects")
    implementation = value.get("implementation")
    implementation_ref = None
    if implementation is not None:
        if not isinstance(implementation, Mapping):
            raise TypeError("ToolRequirement.implementation must be an object or null")
        implementation_ref = ToolImplementationRef(
            tool_id=str(implementation.get("tool_id") or ""),
            module_path=str(implementation.get("module_path") or ""),
            factory=str(implementation.get("factory") or ""),
        )
    return ToolRequirement(
        tool_id=str(value.get("tool_id") or ""),
        description=str(value.get("description") or ""),
        applicable_scenario=str(value.get("applicable_scenario") or ""),
        parameters=dict(value.get("parameters") or {}),
        evidence_refs=[_evidence_ref(item) for item in value.get("evidence_refs") or []],
        implementation=implementation_ref,
        implementation_gap=str(value.get("implementation_gap") or ""),
    )


def _validate_evidence_ref(evidence: EvidenceRef) -> None:
    if not evidence.ref_id.strip():
        raise ValueError("EvidenceRef.ref_id is required")
    if not evidence.kind.strip():
        raise ValueError(f"EvidenceRef.kind is required: {evidence.ref_id}")
    if not evidence.location.strip() and evidence.payload in (None, "", [], {}):
        raise ValueError(f"EvidenceRef requires location or payload: {evidence.ref_id}")
    if evidence.payload is not None:
        try:
            encoded = json.dumps(evidence.payload, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"EvidenceRef.payload must be JSON serializable: {evidence.ref_id}") from exc
        if len(encoded) > MAX_INLINE_EVIDENCE_PAYLOAD_BYTES:
            raise ValueError(
                f"EvidenceRef.payload exceeds {MAX_INLINE_EVIDENCE_PAYLOAD_BYTES} bytes: {evidence.ref_id}"
            )


def _validate_tool_requirement(requirement: ToolRequirement) -> None:
    for field_name in ("tool_id", "description", "applicable_scenario"):
        if not str(getattr(requirement, field_name) or "").strip():
            raise ValueError(f"ToolRequirement.{field_name} is required")
    if requirement.parameters.get("type") != "object":
        raise ValueError(f"ToolRequirement.parameters.type must be object: {requirement.tool_id}")
    for evidence in requirement.evidence_refs:
        _validate_evidence_ref(evidence)
    if requirement.implementation is None:
        if not requirement.implementation_gap.strip():
            raise ValueError(
                f"ToolRequirement without implementation requires implementation_gap: {requirement.tool_id}"
            )
        return
    implementation = requirement.implementation
    if implementation.tool_id != requirement.tool_id:
        raise ValueError(f"ToolImplementationRef.tool_id mismatch: {requirement.tool_id}")
    if not implementation.module_path.strip() or not implementation.factory.strip():
        raise ValueError(f"ToolImplementationRef module_path/factory are required: {requirement.tool_id}")
    if requirement.implementation_gap.strip():
        raise ValueError(
            f"implemented ToolRequirement cannot also declare implementation_gap: {requirement.tool_id}"
        )
