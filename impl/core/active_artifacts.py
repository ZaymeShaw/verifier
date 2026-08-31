from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .path_contract import LogicalPathRef, PathContractError, PathResolver, PathRoots, PathScope
from .portable_artifact import PortableArtifactWriter
from .project_config import resolve_project_config
from .schema import DraftLoopState, load_investigation_manifest, validate_investigation_manifest
from .schema.draft_state import DRAFT_RUN_REPORT_VERSION


_HISTORICAL_ITERATION = re.compile(
    r"^\d{3}-(?:run(?:[.-].+)?\.(?:json|md)|harness-review\.md|carrier-inbox\.md|review-input\.json)$"
)


@dataclass(frozen=True)
class ActiveArtifactFailure:
    code: str
    message: str
    path: Path
    family_id: str


@dataclass(frozen=True)
class ActiveArtifactContext:
    root: Path
    dotenv_path: Path
    environ: Mapping[str, str] | None
    writer: PortableArtifactWriter

    @property
    def projects_dir(self) -> Path:
        return self.root / "impl" / "projects"

    def project_spec(self, project_id: str):
        return resolve_project_config(
            project_id,
            projects_dir=self.projects_dir,
            dotenv_path=self.dotenv_path,
            environ=self.environ,
            require_values=False,
            verifier_root=self.root,
        )


@dataclass(frozen=True)
class _BlockedRoleLoopAudit:
    iteration: int
    report_path: Path
    review_path: Path
    review: Mapping[str, object]


ArtifactValidator = Callable[[ActiveArtifactContext, Path], None]
ArtifactPayloadValidator = Callable[[ActiveArtifactContext, Path, Any], None]
ArtifactBaseResolver = Callable[[ActiveArtifactContext], Path]


@dataclass(frozen=True)
class ActiveArtifactFamily:
    family_id: str
    lifecycle: str
    pattern: str
    validator: ArtifactValidator
    writer_policy: str = "registered_family_writer"
    consumer_boundaries: tuple[str, ...] = ()
    base: str = "impl/projects"
    base_resolver: ArtifactBaseResolver | None = None
    payload_validator: ArtifactPayloadValidator | None = None
    writable: bool = True
    owned_directory_patterns: tuple[str, ...] = ()
    owned_file_glob: str = "*.json"

    def base_path(self, context: ActiveArtifactContext) -> Path:
        if self.base_resolver is not None:
            return self.base_resolver(context).resolve(strict=False)
        return (context.root / self.base).resolve(strict=False)

    def discover(self, context: ActiveArtifactContext) -> tuple[Path, ...]:
        base = self.base_path(context)
        return tuple(sorted(path for path in base.glob(self.pattern) if path.is_file()))

    def owns(self, context: ActiveArtifactContext, path: Path) -> bool:
        base = self.base_path(context)
        target = Path(path).resolve(strict=False)
        if not target.is_relative_to(base):
            return False
        return _glob_matches(target.relative_to(base).as_posix(), self.pattern)

    def owned_directories(self, context: ActiveArtifactContext) -> tuple[Path, ...]:
        base = self.base_path(context)
        directories: set[Path] = set()
        for pattern in self.owned_directory_patterns:
            if pattern == ".":
                candidates = (base,)
            else:
                candidates = base.glob(pattern)
            directories.update(path for path in candidates if path.is_dir())
        return tuple(sorted(directories))

    def owns_directory_path(self, context: ActiveArtifactContext, path: Path) -> bool:
        base = self.base_path(context)
        target = Path(path).resolve(strict=False)
        if not target.is_relative_to(base):
            return False
        current = target if target.is_dir() else target.parent
        while current.is_relative_to(base):
            relative = current.relative_to(base).as_posix() or "."
            if any(_glob_matches(relative, pattern) for pattern in self.owned_directory_patterns):
                return True
            if current == base:
                break
            current = current.parent
        return False


class ActiveArtifactRegistry:
    """Authoritative discovery and validation boundary for active path artifacts."""

    def __init__(self, families: tuple[ActiveArtifactFamily, ...]) -> None:
        ids = [family.family_id for family in families]
        if len(ids) != len(set(ids)):
            raise ValueError("active artifact family ids must be unique")
        self.families = families
        self._families_by_id = {family.family_id: family for family in families}

    def family(self, family_id: str) -> ActiveArtifactFamily:
        try:
            return self._families_by_id[family_id]
        except KeyError as exc:
            raise PathContractError(
                "PATH_ACTIVE_UNKNOWN",
                family_id,
                "active artifact family is not registered",
            ) from exc

    def write_json(
        self,
        family_id: str,
        path: Path,
        payload: Any,
        *,
        root: Path | None = None,
        context: ActiveArtifactContext | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> Path:
        if context is not None and root is not None:
            raise ValueError("active artifact write accepts context or root, not both")
        if context is None:
            if root is None:
                raise ValueError("active artifact write requires context or root")
            context = self.context(root, environ=environ)
        family = self.family(family_id)
        if not family.writable or family.lifecycle != "derived_active":
            raise PathContractError(
                "PATH_WRITER_BYPASS",
                str(path),
                f"artifact family {family_id!r} does not permit active writes",
            )
        if not family.owns(context, path):
            raise PathContractError(
                "PATH_ACTIVE_UNKNOWN",
                str(path),
                f"target does not belong to active artifact family {family_id!r}",
            )
        normalized = context.writer.validate(payload)
        if family.payload_validator is not None:
            family.payload_validator(context, Path(path), normalized)
        return context.writer.write_json(Path(path), normalized, lifecycle=family.lifecycle)

    def classify_path(self, root: Path, path: Path) -> str | None:
        context = self.context(root)
        target = Path(path).resolve(strict=False)
        if any(family.owns(context, target) for family in self.families):
            return "active"
        if any(family.owns_directory_path(context, target) for family in self.families):
            return "historical" if _recognized_historical_artifact(target) else "unknown_owned"
        return None

    @staticmethod
    def context(
        root: Path,
        *,
        environ: Mapping[str, str] | None = None,
        dotenv_path: Path | None = None,
    ) -> ActiveArtifactContext:
        resolved_root = Path(root).resolve()
        return ActiveArtifactContext(
            root=resolved_root,
            dotenv_path=Path(dotenv_path or resolved_root / ".env"),
            environ=environ,
            writer=PortableArtifactWriter(),
        )

    def validate(
        self,
        root: Path,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> list[ActiveArtifactFailure]:
        return self.validate_context(self.context(root, environ=environ))

    def validate_context(
        self,
        context: ActiveArtifactContext,
    ) -> list[ActiveArtifactFailure]:
        failures: list[ActiveArtifactFailure] = []
        for family in self.families:
            for path in family.discover(context):
                try:
                    family.validator(context, path)
                except Exception as exc:
                    failures.append(
                        ActiveArtifactFailure(
                            code=_failure_code(exc),
                            message=f"{family.family_id} validation failed: {exc}",
                            path=path,
                            family_id=family.family_id,
                        )
                    )
        failures.extend(_find_unclassified_active_artifacts(context, self.families))
        return failures


def _read_object(context: ActiveArtifactContext, path: Path) -> Mapping[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise TypeError("active artifact must be a JSON object")
    context.writer.validate(raw)
    return raw


def _read_payload(context: ActiveArtifactContext, path: Path) -> Any:
    raw = json.loads(path.read_text(encoding="utf-8"))
    context.writer.validate(raw)
    return raw


def _manifest_payload(
    _context: ActiveArtifactContext,
    _path: Path,
    payload: Any,
) -> None:
    if not isinstance(payload, Mapping):
        raise TypeError("investigation manifest must be an object")
    from .schema import InvestigationManifest

    manifest = InvestigationManifest.from_dict(payload)
    validate_investigation_manifest(manifest)
    if manifest.schema_version < 2:
        raise ValueError("active investigation manifest must use portable schema v2")


def _trace_graph_payload(
    _context: ActiveArtifactContext,
    _path: Path,
    payload: Any,
) -> None:
    if not isinstance(payload, Mapping):
        raise TypeError("investigation trace graph must be an object")
    from .schema.investigation_trace import TraceGraph

    TraceGraph.from_dict(payload)


def _receipt_payload(
    _context: ActiveArtifactContext,
    path: Path,
    payload: Any,
) -> None:
    if not isinstance(payload, Mapping):
        raise TypeError("investigation validation receipt must be an object")
    if int(payload.get("schema_version") or 0) < 2:
        raise ValueError("active investigation receipt must use portable schema v2")
    project_id = path.parents[3].name
    role = path.parent.name
    if payload.get("project_id") != project_id or payload.get("role") != role:
        raise ValueError(f"Investigation validation receipt identity mismatch: {path}")


def _solidify_payload(
    _context: ActiveArtifactContext,
    path: Path,
    payload: Any,
) -> None:
    if not isinstance(payload, Mapping):
        raise TypeError("Draft Solidify receipt must be an object")
    from .solidify import SOLIDIFY_RECEIPT_VERSION

    schema_version = payload.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != SOLIDIFY_RECEIPT_VERSION
    ):
        raise ValueError("active Draft Solidify receipt has unsupported schema_version")
    project_id = path.parents[3].name
    role = path.parent.name
    if payload.get("project_id") != project_id or payload.get("role") != role:
        raise ValueError(f"Draft Solidify receipt identity mismatch: {path}")


def _draft_role_review_payload(
    _context: ActiveArtifactContext,
    path: Path,
    payload: Any,
) -> None:
    if not isinstance(payload, Mapping):
        raise TypeError("Draft role review must be an object")
    from .draft_role_review import DRAFT_ROLE_REVIEW_VERSION

    schema_version = payload.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != DRAFT_ROLE_REVIEW_VERSION
    ):
        raise ValueError("active Draft role review has unsupported schema_version")
    project_id = path.parents[4].name
    role = path.parents[1].name
    match = re.fullmatch(r"(\d{3})-role-review\.json", path.name)
    if match is None:
        raise ValueError(f"invalid Draft role review filename: {path.name}")
    iteration = int(match.group(1))
    if (
        payload.get("project_id") != project_id
        or payload.get("role") != role
        or payload.get("iteration") != iteration
    ):
        raise ValueError(f"Draft role review identity mismatch: {path}")


def _endpoint_payload(
    _context: ActiveArtifactContext,
    path: Path,
    payload: Any,
) -> None:
    if not isinstance(payload, Mapping):
        raise TypeError("endpoint discovery manifest must be an object")
    if int(payload.get("schema_version") or 0) < 2:
        raise ValueError("active endpoint manifest must use portable schema v2")
    project_id = path.parents[2].name
    if payload.get("project_id") != project_id:
        raise ValueError(f"endpoint manifest project_id must be {project_id!r}")
    endpoints = payload.get("endpoints") or []
    if not isinstance(endpoints, list):
        raise TypeError("endpoint manifest endpoints must be a list")
    if int(payload.get("endpoint_count") or 0) != len(endpoints):
        raise ValueError("endpoint manifest endpoint_count does not match endpoints")


def _draft_loop_payload(
    _context: ActiveArtifactContext,
    path: Path,
    payload: Any,
) -> None:
    if not isinstance(payload, Mapping):
        raise TypeError("Draft loop state must be an object")
    state = DraftLoopState.from_mapping(payload)
    project_id = path.parents[3].name
    role = path.parent.name
    if state.project_id != project_id or state.role != role:
        raise ValueError(f"Draft loop identity mismatch: expected {project_id}/{role}")


def _draft_iteration_cases_payload(
    _context: ActiveArtifactContext,
    _path: Path,
    payload: Any,
) -> None:
    if not isinstance(payload, list) or not payload:
        raise TypeError("Draft iteration cases must be a non-empty list")


def _case_pool_payload(
    _context: ActiveArtifactContext,
    _path: Path,
    payload: Any,
) -> None:
    if not isinstance(payload, Mapping):
        raise TypeError("case pool store must be an object")
    for project_id, pools in payload.items():
        if not isinstance(project_id, str) or not isinstance(pools, list):
            raise TypeError("case pool store must map project ids to pool lists")
        for pool in pools:
            if not isinstance(pool, Mapping) or not isinstance(pool.get("cases") or [], list):
                raise TypeError(f"case pool for {project_id!r} has invalid shape")


def _material_manifest_payload(
    _context: ActiveArtifactContext,
    path: Path,
    payload: Any,
) -> None:
    from .materials_store import validate_manifest_payload

    validate_manifest_payload(Path(path), payload)


def _validate_material_manifest(context: ActiveArtifactContext, path: Path) -> None:
    payload = _read_payload(context, path)
    _material_manifest_payload(context, path, payload)
    from .materials_store import verify_content_seal

    verify_content_seal(Path(path), payload)


def _capability_map_payload(
    _context: ActiveArtifactContext,
    _path: Path,
    payload: Any,
) -> None:
    if not isinstance(payload, Mapping):
        raise TypeError("capability map store must be an object of name -> entry")
    from .capability_store import validate_entry

    for name, entry in payload.items():
        validate_entry(str(name), entry)


def _validate_capability_map(context: ActiveArtifactContext, path: Path) -> None:
    _capability_map_payload(context, path, _read_payload(context, path))


def _mock_cases_payload(
    _context: ActiveArtifactContext,
    path: Path,
    payload: Any,
) -> None:
    if not isinstance(payload, list):
        raise TypeError("frozen MockCase dataset must be a list")
    from .mock import parse_mock_case

    project_id = path.parent.name
    for index, case in enumerate(payload):
        try:
            parse_mock_case(case, project_id=project_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"mock_cases[{index}] is invalid: {exc}") from exc


def _judge_investigation_contract_payload(
    _context: ActiveArtifactContext,
    path: Path,
    payload: Any,
) -> None:
    from .schema.investigation_judge import (
        JudgeInvestigationContract,
        validate_judge_contract,
    )

    if path.name != "judge-investigation-contract.json" or path.parents[1].name != "judge":
        raise ValueError(f"Judge investigation contract path identity mismatch: {path}")
    if not isinstance(payload, Mapping):
        raise TypeError("Judge investigation contract must be an object")
    validate_judge_contract(JudgeInvestigationContract.from_dict(payload))


def _mock_investigation_contract_payload(
    _context: ActiveArtifactContext,
    path: Path,
    payload: Any,
) -> None:
    from .schema.investigation_mock import (
        MockInvestigationContract,
        validate_mock_contract,
    )

    if path.name != "mock-investigation-contract.json" or path.parents[1].name != "mock":
        raise ValueError(f"Mock investigation contract path identity mismatch: {path}")
    if not isinstance(payload, Mapping):
        raise TypeError("Mock investigation contract must be an object")
    validate_mock_contract(MockInvestigationContract.from_dict(payload))


def _draft_solidify_probe_payload(
    _context: ActiveArtifactContext,
    path: Path,
    payload: Any,
) -> None:
    if not isinstance(payload, Mapping):
        raise TypeError("Draft solidify probe must be an object")
    project_id = path.parents[2].name
    match = re.fullmatch(r"([a-z][a-z0-9_-]*)-solidify-smoke\.json", path.name)
    if match is None:
        raise ValueError(f"invalid Draft solidify probe filename: {path.name}")
    role = match.group(1)
    if payload.get("project_id") != project_id or payload.get("role") != role:
        raise ValueError(
            f"Draft solidify probe identity mismatch: expected {project_id}/{role}"
        )
    if payload.get("status") not in {"succeeded", "failed", "blocked"}:
        raise ValueError("Draft solidify probe status must be succeeded, failed, or blocked")
    if not isinstance(payload.get("observed_asset_ids"), list):
        raise TypeError("Draft solidify probe observed_asset_ids must be a list")
    if not isinstance(payload.get("checks"), Mapping):
        raise TypeError("Draft solidify probe checks must be an object")


def _validate_judge_investigation_contract(
    context: ActiveArtifactContext, path: Path
) -> None:
    _judge_investigation_contract_payload(context, path, _read_payload(context, path))


def _authority_investigation_report_payload(
    _context: ActiveArtifactContext,
    path: Path,
    payload: Any,
) -> None:
    from .schema.investigation_judge import AuthorityInvestigationReport

    if path.name != "authority-investigation-report.json" or path.parents[1].name != "judge":
        raise ValueError(f"Authority investigation report path identity mismatch: {path}")
    if not isinstance(payload, Mapping):
        raise TypeError("Authority investigation report must be an object")
    report = AuthorityInvestigationReport.from_dict(payload)
    if not report.materials or not report.coverage_gaps:
        raise ValueError(
            "Authority investigation report must contain materials and coverage_gaps"
        )


def _validate_authority_investigation_report(
    context: ActiveArtifactContext, path: Path
) -> None:
    _authority_investigation_report_payload(context, path, _read_payload(context, path))


def _authority_claim_index_payload(
    _context: ActiveArtifactContext,
    path: Path,
    payload: Any,
) -> None:
    if path.name != "authority-claims.json" or path.parents[1].name != "judge":
        raise ValueError(f"Authority claim index path identity mismatch: {path}")
    if not isinstance(payload, Mapping):
        raise TypeError("Authority claim index must be an object")
    if int(payload.get("schema_version") or 0) != 1:
        raise ValueError("Authority claim index schema_version must be 1")
    claims = payload.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValueError("Authority claim index claims must be a non-empty array")


def _validate_authority_claim_index(
    context: ActiveArtifactContext, path: Path
) -> None:
    _authority_claim_index_payload(context, path, _read_payload(context, path))


def _key_index_experiment_payload(
    _context: ActiveArtifactContext,
    path: Path,
    payload: Any,
) -> None:
    if path.parent.name != "experiments":
        raise ValueError(f"Key-index experiment path identity mismatch: {path}")
    if not isinstance(payload, Mapping):
        raise TypeError("key-index experiment must be an object")


def _validate_key_index_experiment(
    context: ActiveArtifactContext, path: Path
) -> None:
    _key_index_experiment_payload(context, path, _read_payload(context, path))


def _gate_feedback_payload(
    _context: ActiveArtifactContext,
    path: Path,
    payload: Any,
) -> None:
    if not path.name.endswith("-gate-feedback.json"):
        raise ValueError(f"Gate feedback path identity mismatch: {path}")
    if not isinstance(payload, Mapping):
        raise TypeError("gate feedback must be an object")


def _validate_gate_feedback(context: ActiveArtifactContext, path: Path) -> None:
    _gate_feedback_payload(context, path, _read_payload(context, path))


def _context_governance_review_payload(
    _context: ActiveArtifactContext,
    path: Path,
    payload: Any,
) -> None:
    if path.parent.name != "context-governance":
        raise ValueError(f"Context governance review path identity mismatch: {path}")
    if not isinstance(payload, Mapping):
        raise TypeError("context governance review must be an object")


def _validate_context_governance_review(
    context: ActiveArtifactContext, path: Path
) -> None:
    _context_governance_review_payload(
        context, path, _read_payload(context, path)
    )


def _validate_mock_investigation_contract(
    context: ActiveArtifactContext, path: Path
) -> None:
    _mock_investigation_contract_payload(context, path, _read_payload(context, path))


def _validate_draft_solidify_probe(
    context: ActiveArtifactContext, path: Path
) -> None:
    _draft_solidify_probe_payload(context, path, _read_payload(context, path))


def _context_record_payload(
    context: ActiveArtifactContext,
    path: Path,
    payload: Any,
) -> None:
    if not isinstance(payload, Mapping):
        raise TypeError("context record must be an object")
    required = ("record_id", "trace_id", "project_id", "caller", "messages", "created_at")
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"context record is missing fields: {', '.join(missing)}")
    if not isinstance(payload.get("messages"), list):
        raise TypeError("context record messages must be a list")
    base = _context_store_base(context)
    relative = path.resolve(strict=False).relative_to(Path(base).resolve(strict=False))
    if len(relative.parts) == 3:
        project_id, trace_id, _filename = relative.parts
    elif len(relative.parts) == 2:
        project_id = ""
        trace_id, _filename = relative.parts
    else:
        raise ValueError(f"context record path must be <project>/<trace>/<file> or <trace>/<file>: {path}")
    if payload.get("project_id") != project_id or payload.get("trace_id") != trace_id:
        raise ValueError(f"context record identity mismatch: {path}")


def _validate_investigation_manifest(context: ActiveArtifactContext, path: Path) -> None:
    from .investigation import validate_investigation_package
    from .project_loader import resolve_role_assets

    _read_object(context, path)
    manifest = load_investigation_manifest(path)
    validate_investigation_manifest(manifest)
    if manifest.schema_version < 2:
        raise ValueError("active investigation manifest must use portable schema v2")

    project_root = path.parents[3].resolve()
    project_id = project_root.name
    role = path.parent.name
    spec = context.project_spec(project_id)
    selected = resolve_role_assets(spec, role, use_candidate=True)
    tool_aliases = {
        str(item["mapping"].production_path): Path(item["path"])
        for item in selected
        if item["mapping"].kind == "tool" and item["available"]
    }
    validation = validate_investigation_package(
        path.parent,
        project_root=project_root,
        expected_project_id=project_id,
        expected_role=role,
        tool_module_overrides=tool_aliases,
        source_root=spec.source_root_path() if spec.has_business_source else None,
    )
    registered_json = {
        Path(item).resolve()
        for item in [
            str(path),
            *(validation.get("artifacts") or []),
            *(validation.get("evidence_files") or []),
        ]
        if str(item).endswith(".json")
    }
    for candidate in sorted(path.parent.rglob("*.json")):
        if candidate.resolve() not in registered_json:
            raise PathContractError(
                "PATH_SCHEMA_BYPASS",
                str(candidate),
                "unclassified JSON in active investigation package",
            )


def _validate_investigation_trace(context: ActiveArtifactContext, path: Path) -> None:
    _trace_graph_payload(context, path, _read_payload(context, path))


def _validate_investigation_receipt(context: ActiveArtifactContext, path: Path) -> None:
    from .investigation_validation import require_investigation_validation_receipt

    raw = _read_object(context, path)
    if int(raw.get("schema_version") or 0) < 2:
        raise ValueError("active investigation receipt must use portable schema v2")
    project_root = path.parents[3].resolve()
    project_id = project_root.name
    role = path.parent.name
    spec = context.project_spec(project_id)
    require_investigation_validation_receipt(spec, role)


def _validate_endpoint_manifest(context: ActiveArtifactContext, path: Path) -> None:
    raw = _read_object(context, path)
    if int(raw.get("schema_version") or 0) < 2:
        raise ValueError("active endpoint manifest must use portable schema v2")
    project_root = path.parents[2].resolve()
    project_id = project_root.name
    if raw.get("project_id") != project_id:
        raise ValueError(f"endpoint manifest project_id must be {project_id!r}")
    spec = context.project_spec(project_id)
    endpoints = raw.get("endpoints") or []
    if not isinstance(endpoints, list):
        raise TypeError("endpoint manifest endpoints must be a list")
    if int(raw.get("endpoint_count") or 0) != len(endpoints):
        raise ValueError("endpoint manifest endpoint_count does not match endpoints")
    for index, endpoint in enumerate(endpoints):
        if not isinstance(endpoint, Mapping):
            raise TypeError(f"endpoints[{index}] must be an object")
        source = endpoint.get("source")
        if source is None:
            continue
        if not isinstance(source, Mapping):
            raise TypeError(f"endpoints[{index}].source must be a LogicalPathRef")
        reference = LogicalPathRef.from_mapping(
            source, field_path=f"endpoints[{index}].source"
        )
        if reference.location_scope is not PathScope.BUSINESS_SOURCE:
            raise ValueError(f"endpoints[{index}].source must use business_source scope")
        resolved = reference.resolve(
            spec.path_resolver,
            field_path=f"endpoints[{index}].source",
            expected_type="file",
        ).physical
        if reference.sha256:
            actual = hashlib.sha256(resolved.read_bytes()).hexdigest()
            if actual != reference.sha256:
                raise ValueError(
                    f"endpoint source hash changed: expected={reference.sha256}, actual={actual}"
                )


def _validate_staleness_report(context: ActiveArtifactContext, path: Path) -> None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, (Mapping, list)):
        raise TypeError("staleness report must be a JSON object or array")
    context.writer.validate(raw)


def _staleness_report_payload(
    _context: ActiveArtifactContext,
    _path: Path,
    payload: Any,
) -> None:
    if not isinstance(payload, (Mapping, list)):
        raise TypeError("staleness report payload must be an object or array")


def _validate_mapping_artifact(context: ActiveArtifactContext, path: Path) -> None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise TypeError(f"{path.name} must be a JSON object")
    context.writer.validate(raw)


def _mapping_payload(
    _context: ActiveArtifactContext,
    _path: Path,
    payload: Any,
) -> None:
    if not isinstance(payload, Mapping):
        raise TypeError("artifact payload must be an object")


def _trusted_blocked_role_loop(
    context: ActiveArtifactContext,
    project_id: str,
    role: str,
) -> _BlockedRoleLoopAudit | None:
    """Return the latest blocked review only when its audit hash chain is intact.

    A blocked loop may retain the Solidify/review snapshot that actually observed
    the infrastructure failure even after a candidate is edited.  That snapshot is
    historical audit evidence, not a fresh execution or promotion receipt.
    """
    role_root = (
        context.projects_dir / project_id / "draft" / ".state" / role
    )
    loop_path = role_root / "loop.json"
    if not loop_path.is_file():
        return None
    try:
        state = DraftLoopState.from_mapping(_read_object(context, loop_path))
        if (
            state.project_id != project_id
            or state.role != role
            or state.status != "blocked"
            or not state.iterations
        ):
            return None
        latest = state.iterations[-1]
        if latest.decision != "blocked" or latest.route != "blocked":
            return None

        expected_report_location = (
            f"draft/.state/{role}/iterations/{latest.iteration:03d}-run.json"
        )
        if latest.run_report.location != expected_report_location:
            return None
        spec = context.project_spec(project_id)
        report_path = latest.run_report.resolve(
            spec.path_resolver,
            field_path="draft_loop.latest.run_report",
            expected_type="file",
        ).physical
        actual_report_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
        if actual_report_hash != latest.run_report.sha256:
            return None

        review_path = (
            role_root
            / "iterations"
            / f"{latest.iteration:03d}-role-review.json"
        )
        expected_review_location = review_path.relative_to(
            context.projects_dir / project_id
        ).as_posix()
        review_hash = hashlib.sha256(review_path.read_bytes()).hexdigest()
        review_evidence = [
            item.artifact
            for item in latest.evidence
            if item.artifact.location_scope is PathScope.PROJECT_PACKAGE
            and item.artifact.location == expected_review_location
        ]
        if len(review_evidence) != 1 or review_evidence[0].sha256 != review_hash:
            return None

        review = _read_object(context, review_path)
        _draft_role_review_payload(context, review_path, review)
        if (
            review.get("iteration") != latest.iteration
            or review.get("decision") != "blocked"
            or review.get("route") != "blocked"
        ):
            return None
        return _BlockedRoleLoopAudit(
            iteration=latest.iteration,
            report_path=report_path,
            review_path=review_path,
            review=review,
        )
    except (OSError, TypeError, ValueError):
        return None


def _validate_draft_solidify(context: ActiveArtifactContext, path: Path) -> None:
    payload = _read_object(context, path)
    _solidify_payload(context, path, payload)
    from .draft_role_review import require_draft_role_review
    from .solidify import require_solidify_receipt

    project_id = path.parents[3].name
    role = path.parent.name
    spec = context.project_spec(project_id)
    try:
        require_solidify_receipt(spec, role)
        return
    except ValueError as exc:
        if not str(exc).startswith("Draft Solidify receipt is stale:"):
            raise
        stale_error = exc

    blocked = _trusted_blocked_role_loop(context, project_id, role)
    if blocked is None:
        raise stale_error
    review = require_draft_role_review(
        spec,
        role,
        blocked.iteration,
        run_report=blocked.report_path,
        decision="blocked",
        route="blocked",
        check_current_solidify=False,
    )
    actual_receipt_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if (
        not isinstance(review, Mapping)
        or review.get("solidify_receipt_sha256") != actual_receipt_hash
    ):
        raise ValueError(
            "Draft Solidify receipt is stale and is not the receipt referenced "
            "by the trusted blocked role review"
        ) from stale_error


def _validate_draft_role_review(context: ActiveArtifactContext, path: Path) -> None:
    payload = _read_object(context, path)
    _draft_role_review_payload(context, path, payload)
    from .draft_role_review import require_draft_role_review

    project_id = path.parents[4].name
    role = path.parents[1].name
    iteration = int(payload["iteration"] or 0)
    spec = context.project_spec(project_id)
    review_dir = path.parent
    iterations = [
        int(match.group(1))
        for candidate in review_dir.glob("*-role-review.json")
        if (match := re.fullmatch(r"(\d{3})-role-review\.json", candidate.name))
    ]
    latest_iteration = max(iterations, default=iteration)
    blocked = _trusted_blocked_role_loop(context, project_id, role)
    latest_is_trusted_blocked = (
        blocked is not None and blocked.iteration == latest_iteration
    )
    raw_report = payload.get("run_report")
    if not isinstance(raw_report, Mapping):
        raise TypeError("Draft role review run_report must be a LogicalPathRef")
    run_report = LogicalPathRef.from_mapping(
        raw_report, field_path="draft_role_review.run_report"
    ).resolve(
        spec.path_resolver,
        field_path="draft_role_review.run_report",
        expected_type="file",
    ).physical
    require_draft_role_review(
        spec,
        role,
        iteration,
        run_report=run_report,
        decision=str(payload.get("decision") or ""),
        route=str(payload.get("route") or ""),
        check_current_solidify=(
            iteration == latest_iteration and not latest_is_trusted_blocked
        ),
    )


def _validate_draft_loop(context: ActiveArtifactContext, state_path: Path) -> None:
    raw = _read_object(context, state_path)
    state = DraftLoopState.from_mapping(raw)
    project_root = state_path.parents[3].resolve()
    expected_project_id = project_root.name
    expected_role = state_path.parent.name
    if state.project_id != expected_project_id or state.role != expected_role:
        raise ValueError(
            f"Draft loop identity mismatch: expected {expected_project_id}/{expected_role}"
        )
    configured_roots = None
    if (project_root / "project.yaml").is_file():
        configured_roots = context.project_spec(state.project_id).path_roots
    roots = PathRoots(
        verifier_repo=context.root,
        business_source=configured_roots.business_source if configured_roots else None,
        project_package=project_root,
        knowledge_route=configured_roots.knowledge_route if configured_roots else None,
        artifact_package=configured_roots.artifact_package if configured_roots else None,
    )
    resolver = PathResolver(roots)
    for index, iteration in enumerate(state.iterations):
        expected_location = (
            f"draft/.state/{state.role}/iterations/{iteration.iteration:03d}-run.json"
        )
        if iteration.run_report.location != expected_location:
            raise ValueError(
                f"iterations[{index}].run_report must identify {expected_location!r}"
            )
        report_path = iteration.run_report.resolve(
            resolver,
            field_path=f"iterations[{index}].run_report",
            expected_type="file",
        ).physical
        actual_report_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
        if actual_report_hash != iteration.run_report.sha256:
            raise ValueError(
                f"{report_path}: run report hash changed; "
                f"expected={iteration.run_report.sha256}, actual={actual_report_hash}"
            )
        report = _read_object(context, report_path)
        if int(report.get("schema_version") or 0) != DRAFT_RUN_REPORT_VERSION:
            raise ValueError(
                f"{report_path}: expected Draft run report schema v{DRAFT_RUN_REPORT_VERSION}"
            )
        for evidence_index, evidence in enumerate(iteration.evidence):
            if index != len(state.iterations) - 1:
                continue
            evidence_path = evidence.artifact.resolve(
                resolver,
                field_path=f"iterations[{index}].evidence[{evidence_index}].artifact",
                expected_type="file",
            ).physical
            if not evidence.artifact.sha256:
                raise ValueError(
                    f"iterations[{index}].evidence[{evidence_index}] requires sha256"
                )
            actual_evidence_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            if actual_evidence_hash != evidence.artifact.sha256:
                raise ValueError(
                    f"{evidence_path}: review evidence hash changed; "
                    f"expected={evidence.artifact.sha256}, actual={actual_evidence_hash}"
                )


def _validate_draft_iteration_cases(context: ActiveArtifactContext, path: Path) -> None:
    _draft_iteration_cases_payload(context, path, _read_payload(context, path))


def _validate_case_pool_store(context: ActiveArtifactContext, path: Path) -> None:
    _case_pool_payload(context, path, _read_payload(context, path))


def _validate_mock_cases(context: ActiveArtifactContext, path: Path) -> None:
    _mock_cases_payload(context, path, _read_payload(context, path))


def _validate_context_record(context: ActiveArtifactContext, path: Path) -> None:
    _context_record_payload(context, path, _read_payload(context, path))


def _context_store_base(context: ActiveArtifactContext) -> Path:
    config_path = context.root / "impl" / "config.yaml"
    if not config_path.is_file():
        # Partial registry fixtures have no public configuration and therefore
        # cannot claim a context-store location during discovery or validation.
        return context.root / ".unconfigured-active-artifacts" / "context_store"
    from .config import resolve_runtime_config

    runtime = resolve_runtime_config(
        config_path=config_path,
        dotenv_path=context.dotenv_path,
        environ=context.environ,
    )
    return Path(runtime.context.store_root)


def _find_unclassified_active_artifacts(
    context: ActiveArtifactContext,
    families: tuple[ActiveArtifactFamily, ...],
) -> list[ActiveArtifactFailure]:
    failures: list[ActiveArtifactFailure] = []
    inspected: set[Path] = set()
    for owner in families:
        for directory in owner.owned_directories(context):
            for path in sorted(directory.rglob(owner.owned_file_glob)):
                if not path.is_file() or path in inspected:
                    continue
                inspected.add(path)
                if any(family.owns(context, path) for family in families):
                    continue
                if _recognized_historical_artifact(path):
                    continue
                failures.append(_unknown(path, owner.family_id))
    return failures


def _recognized_historical_artifact(path: Path) -> bool:
    parts = path.parts
    for index in range(len(parts) - 3):
        if (
            parts[index] == ".state"
            and parts[index + 2] == "history"
            and index + 3 < len(parts)
        ):
            return True
    return path.parent.name == "iterations" and bool(
        _HISTORICAL_ITERATION.fullmatch(path.name)
    )


def _glob_matches(value: str, pattern: str) -> bool:
    """Match registry globs with segment-safe ``*`` and recursive ``**``."""
    expression = ""
    index = 0
    while index < len(pattern):
        if pattern[index : index + 3] == "**/":
            expression += r"(?:[^/]+/)*"
            index += 3
        elif pattern[index : index + 2] == "**":
            expression += r".*"
            index += 2
        elif pattern[index] == "*":
            expression += r"[^/]*"
            index += 1
        elif pattern[index] == "?":
            expression += r"[^/]"
            index += 1
        else:
            expression += re.escape(pattern[index])
            index += 1
    return re.fullmatch(expression, value) is not None


def _unknown(path: Path, family_id: str) -> ActiveArtifactFailure:
    return ActiveArtifactFailure(
        code="PATH_ACTIVE_UNKNOWN",
        message="unclassified structured file in a registered active artifact directory",
        path=path,
        family_id=family_id,
    )


def _failure_code(exc: Exception) -> str:
    explicit = getattr(exc, "code", "")
    if explicit:
        return str(explicit)
    message = str(exc).lower()
    for code in (
        "PATH_ROOT_UNBOUND",
        "PATH_NOT_FOUND",
        "PATH_TYPE_MISMATCH",
        "PATH_PREFIX_NOT_ALLOWED",
        "PATH_SYMLINK_ESCAPE",
        "PATH_SCHEMA_BYPASS",
        "PATH_ACTIVE_UNKNOWN",
    ):
        if code.lower() in message:
            return code
    integrity_markers = ("hash", "sha256", "stale", "revision", "symbol", "changed")
    if any(marker in message for marker in integrity_markers):
        return "PATH_INTEGRITY_STALE"
    return "PATH_SCAN_FAILED"


DEFAULT_ACTIVE_ARTIFACT_REGISTRY = ActiveArtifactRegistry(
    (
        ActiveArtifactFamily(
            "investigation_manifest",
            "derived_active",
            "*/draft/investigation/*/manifest.json",
            _validate_investigation_manifest,
            consumer_boundaries=("Investigation", "Draft role loading", "promotion"),
            payload_validator=_manifest_payload,
            owned_directory_patterns=("*/draft/investigation/*",),
        ),
        ActiveArtifactFamily(
            "investigation_trace_graph",
            "derived_active",
            "*/draft/investigation/*/**/*.trace.json",
            _validate_investigation_trace,
            consumer_boundaries=("Investigation trace loading", "promotion"),
            payload_validator=_trace_graph_payload,
        ),
        ActiveArtifactFamily(
            "judge_investigation_contract",
            "derived_active",
            "*/draft/investigation/judge/docs/judge-investigation-contract.json",
            _validate_judge_investigation_contract,
            consumer_boundaries=("Judge Investigation", "Judge Draft role loading", "promotion"),
            payload_validator=_judge_investigation_contract_payload,
        ),
        ActiveArtifactFamily(
            "authority_investigation_report",
            "derived_active",
            "*/draft/investigation/judge/docs/authority-investigation-report.json",
            _validate_authority_investigation_report,
            consumer_boundaries=("Judge Investigation", "Judge Draft role loading", "promotion"),
            payload_validator=_authority_investigation_report_payload,
        ),
        ActiveArtifactFamily(
            "authority_claim_index",
            "derived_active",
            "*/draft/investigation/judge/docs/authority-claims.json",
            _validate_authority_claim_index,
            consumer_boundaries=("Judge Investigation", "Judge Draft role loading", "promotion"),
            payload_validator=_authority_claim_index_payload,
        ),
        ActiveArtifactFamily(
            "key_index_experiment",
            "derived_active",
            "*/draft/investigation/*/experiments/*.json",
            _validate_key_index_experiment,
            consumer_boundaries=("key-index experiment replay", "judge runtime"),
            payload_validator=_key_index_experiment_payload,
        ),
        ActiveArtifactFamily(
            "gate_feedback",
            "derived_active",
            "*/draft/.state/*/*-gate-feedback.json",
            _validate_gate_feedback,
            consumer_boundaries=("Draft gate replay", "promotion"),
            payload_validator=_gate_feedback_payload,
        ),
        ActiveArtifactFamily(
            "context_governance_review",
            "derived_active",
            "*/draft/.state/*/context-governance/*.json",
            _validate_context_governance_review,
            consumer_boundaries=("context governance audit", "judge context engineering"),
            payload_validator=_context_governance_review_payload,
        ),
        ActiveArtifactFamily(
            "mock_investigation_contract",
            "derived_active",
            "*/draft/investigation/mock/docs/mock-investigation-contract.json",
            _validate_mock_investigation_contract,
            consumer_boundaries=("Mock Investigation", "Mock Draft role loading", "promotion"),
            payload_validator=_mock_investigation_contract_payload,
        ),
        ActiveArtifactFamily(
            "draft_solidify_probe",
            "derived_active",
            "*/draft/probes/*-solidify-smoke.json",
            _validate_draft_solidify_probe,
            consumer_boundaries=("Solidify", "Draft Loop", "promotion"),
            payload_validator=_draft_solidify_probe_payload,
        ),
        ActiveArtifactFamily(
            "investigation_validation_receipt",
            "derived_active",
            "*/draft/.state/*/investigation-validation.json",
            _validate_investigation_receipt,
            consumer_boundaries=("Draft role loading", "promotion"),
            payload_validator=_receipt_payload,
        ),
        ActiveArtifactFamily(
            "draft_solidify_receipt",
            "derived_active",
            "*/draft/.state/*/solidify.json",
            _validate_draft_solidify,
            consumer_boundaries=("Draft role loading", "Draft Loop", "promotion"),
            payload_validator=_solidify_payload,
        ),
        ActiveArtifactFamily(
            "draft_role_review",
            "derived_active",
            "*/draft/.state/*/iterations/*-role-review.json",
            _validate_draft_role_review,
            consumer_boundaries=("Draft Loop review", "promotion"),
            payload_validator=_draft_role_review_payload,
        ),
        ActiveArtifactFamily(
            "draft_iteration_score",
            "derived_active",
            "*/draft/.state/*/iterations/*-score.json",
            _validate_mapping_artifact,
            consumer_boundaries=("Draft Loop review",),
            payload_validator=_mapping_payload,
        ),
        ActiveArtifactFamily(
            "draft_pending",
            "derived_active",
            "*/draft/.state/*/pending.json",
            _validate_mapping_artifact,
            consumer_boundaries=("Draft Loop",),
            payload_validator=_mapping_payload,
        ),
        ActiveArtifactFamily(
            "endpoint_discovery_manifest",
            "derived_active",
            "*/tools/api_discover/_manifest.json",
            _validate_endpoint_manifest,
            consumer_boundaries=("endpoint tool loading",),
            payload_validator=_endpoint_payload,
            owned_directory_patterns=("*/tools/api_discover",),
        ),
        ActiveArtifactFamily(
            "draft_loop",
            "derived_active",
            "*/draft/.state/*/loop.json",
            _validate_draft_loop,
            consumer_boundaries=("Draft resume", "promotion"),
            payload_validator=_draft_loop_payload,
            owned_directory_patterns=("*/draft/.state/*",),
            owned_file_glob="*",
        ),
        ActiveArtifactFamily(
            "draft_iteration_cases",
            "derived_active",
            "*/draft/.state/*/iteration-cases.json",
            _validate_draft_iteration_cases,
            consumer_boundaries=("Draft frozen iteration input",),
            payload_validator=_draft_iteration_cases_payload,
        ),
        ActiveArtifactFamily(
            "staleness_report",
            "derived_active",
            "*/draft/.state/*/staleness/*.json",
            _validate_staleness_report,
            consumer_boundaries=("staleness audit", "drift routing"),
            payload_validator=_staleness_report_payload,
            owned_directory_patterns=("*/draft/.state/*/staleness",),
        ),
        ActiveArtifactFamily(
            "case_pool_store",
            "derived_active",
            "impl/data/case_pools.json",
            _validate_case_pool_store,
            consumer_boundaries=("case pool API", "evaluation input selection"),
            base=".",
            payload_validator=_case_pool_payload,
        ),
        ActiveArtifactFamily(
            "project_mock_cases",
            "derived_active",
            "impl/data/*/mock_cases.json",
            _validate_mock_cases,
            consumer_boundaries=("MockCase loading", "evaluation input selection"),
            base=".",
            payload_validator=_mock_cases_payload,
        ),
        ActiveArtifactFamily(
            "capability_map_store",
            "derived_active",
            "impl/data/*/capability_map.json",
            _validate_capability_map,
            consumer_boundaries=("capability preset resolution", "materials management API"),
            base=".",
            payload_validator=_capability_map_payload,
        ),
        ActiveArtifactFamily(
            "materials_store",
            "derived_active",
            "impl/data/*/materials/*/manifest.json",
            _validate_material_manifest,
            consumer_boundaries=(
                "materials slot binding", "materials management API", "material:// resolver",
            ),
            base=".",
            payload_validator=_material_manifest_payload,
            owned_directory_patterns=("impl/data/*/materials",),
        ),
        ActiveArtifactFamily(
            "context_record",
            "derived_active",
            "**/*.json",
            _validate_context_record,
            consumer_boundaries=("context replay", "context API"),
            base_resolver=_context_store_base,
            payload_validator=_context_record_payload,
            owned_directory_patterns=(".",),
        ),
    )
)
