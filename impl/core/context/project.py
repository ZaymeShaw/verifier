from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from ..project_loader import (
    resolve_project_package_root,
    resolve_project_source_root,
    resolve_role_assets,
)
from .adapters import initialize_context_adapters, load_configured_context_adapter, load_project_context_adapter
from .bootstrap import build_context_runtime
from .embedding import DeterministicHashEmbeddingProvider
from .models import ContextUnitRecord
from .resolvers import CompositeContentResolver, FileContentResolver
from ..config import get_runtime_config


_MANDATORY_ROLES = {"judge", "mock"}


def role_asset_context_records(
    spec: Any,
    *,
    role: str,
    use_candidate: bool,
    require_available: bool = False,
) -> list[ContextUnitRecord]:
    """Resolve one Role's declared Context/investigation assets as ContextUnit records.

    This is the shared bridge used by mandatory Judge/Mock injection and Attribute's
    searchable Context runtime.  A candidate asset is fail-closed when selected by
    ``resolve_role_assets``; an absent production counterpart may be skipped so a
    candidate-only investigation package does not leak into Current.
    """
    selected_assets = [
        item
        for item in resolve_role_assets(spec, role, use_candidate=use_candidate)
        if item["mapping"].kind in {"context", "context_builder", "investigation"}
    ]
    return _context_records(
        spec,
        role=role,
        use_candidate=use_candidate,
        selected_assets=selected_assets,
        require_available=require_available,
    )


def load_role_mandatory_context(
    spec: Any,
    *,
    role: str,
    operation: str,
    trace_id: str = "",
    run_id: str = "",
    case_id: str = "",
    embedding_provider: Any = None,
) -> Optional[Dict[str, Any]]:
    """Register configured Context assets and deterministically load one Role's mandatory units.

    None means the project has not migrated this Role to ContextUnit yet. Once a Role has
    any enabled context/investigation asset, missing or unauthorized material is an error;
    callers must not fall back to direct document reads.
    """
    normalized_role = str(role or "").strip()
    if normalized_role not in _MANDATORY_ROLES:
        raise ValueError(f"mandatory ContextUnit injection is not defined for role={normalized_role!r}")
    draft_enabled = spec.role_draft(normalized_role).get("enabled") is True
    selected_assets = [
        item
        for item in resolve_role_assets(spec, normalized_role, use_candidate=draft_enabled)
        if item["mapping"].kind in {"context", "context_builder", "investigation"}
    ]
    configured_adapter = load_configured_context_adapter(spec)
    project_adapter = load_project_context_adapter(spec)
    if (
        not draft_enabled
        and selected_assets
        and not any(item["available"] for item in selected_assets)
        and all(item["candidate_path"] is not None for item in selected_assets)
    ):
        # A newly solidified Role may declare only candidate implementations.
        # Current records those production selections as unavailable and keeps
        # its existing empty Context baseline until promotion.
        selected_assets = []
    if not selected_assets and configured_adapter is None and project_adapter is None:
        return None

    roots = _content_roots(spec)
    resolver = CompositeContentResolver([FileContentResolver(roots)] if roots else [])
    records = _context_records(
        spec,
        role=normalized_role,
        use_candidate=draft_enabled,
        selected_assets=selected_assets,
        require_available=True,
    )
    mandatory_ids = [record.id for record in records if normalized_role in record.roles]
    if not mandatory_ids and configured_adapter is None and project_adapter is None:
        raise ValueError(f"role={normalized_role} has Context assets but no loadable mandatory ContextUnit")

    context_config = dict(spec.verifier_extra_value("context", {}) or {})
    project_policy = context_config.get("policy") if isinstance(context_config.get("policy"), Mapping) else None
    configured_context = get_runtime_config().context
    public_policy = {
        "default": {
            "enabled": True,
            "allowed_roles": [normalized_role],
            "allowed_statuses": ["active"],
            "candidate_limit": configured_context.candidate_limit,
            "load_limit": max(configured_context.load_limit, len(mandatory_ids) or 1),
            "content_char_budget": configured_context.content_char_budget,
            "query_limit": configured_context.query_limit,
            "top_k_per_query": configured_context.top_k_per_query,
        },
        "roles": {
            normalized_role: {
                "operations": {operation: {"mandatory_ids": mandatory_ids}}
            }
        },
    }
    runtime = build_context_runtime(
        project_id=spec.project_id,
        project_root=resolve_project_package_root(spec, must_exist=False),
        # Judge/Mock mandatory loading is ID-based and never performs semantic
        # Search. Use a stable local registration vector by default so this path
        # does not acquire Attribute's external embedding dependency.
        embedding_provider=embedding_provider
        or DeterministicHashEmbeddingProvider(model_id="mandatory-context-v1"),
        content_resolver=resolver,
        public_policy=public_policy,
        project_policy=project_policy,
    )
    registration = runtime.register_context_units(records) if records else {"items": []}
    adapters = [item for item in (configured_adapter, project_adapter) if item is not None]
    adapter_initialization = None
    if adapters:
        adapter_initialization = initialize_context_adapters(
            runtime,
            project_spec=spec,
            project_adapters=adapters,
        )
    run = runtime.start_run(
        role=normalized_role,
        operation=operation,
        trace_id=trace_id,
        run_id=run_id,
        case_id=case_id,
    )
    expected_ids = list(run.debug_snapshot()["context_debug"]["mandatory_ids"])
    units = run.load_mandatory_context_units()
    if not expected_ids:
        raise ValueError(f"role={normalized_role} Context migration declares no mandatory ContextUnit IDs")
    if len(units) != len(expected_ids):
        raise RuntimeError(
            f"mandatory ContextUnit load mismatch for role={normalized_role}: "
            f"expected={expected_ids}, loaded={[unit.id for unit in units]}"
        )
    content = "\n\n".join(
        f"## ContextUnit: {unit.name} ({unit.id})\n{unit.content}" for unit in units
    )
    return {
        "content": content,
        "unit_ids": [unit.id for unit in units],
        "registration": registration,
        "adapter_initialization": adapter_initialization,
        "debug": run.debug_snapshot(),
    }


def _asset_records(
    spec: Any,
    selected_assets: Iterable[Mapping[str, Any]],
    *,
    require_available: bool,
) -> Iterable[ContextUnitRecord]:
    project_root = resolve_project_package_root(spec, must_exist=False)
    for selected in selected_assets:
        mapping = selected["mapping"]
        path = Path(selected["path"])
        if not selected["available"]:
            if require_available:
                raise FileNotFoundError(f"enabled Context role asset not found: {path}")
            continue
        files = [path] if path.is_file() else sorted(
            item
            for item in path.rglob("*")
            if item.is_file()
            and item.suffix.lower() in {".md", ".mmd", ".json", ".txt"}
            and not (mapping.kind == "investigation" and item.name == "manifest.json")
        )
        if not files:
            raise ValueError(f"Context role asset contains no supported files: {path}")
        for index, file_path in enumerate(files):
            suffix = "" if len(files) == 1 else f".{index}"
            unit_id = f"project.{spec.project_id}.asset.{mapping.asset_id}{suffix}"
            yield ContextUnitRecord(
                id=unit_id,
                name=f"{mapping.asset_id}: {file_path.name}",
                description=(
                    f"Project {mapping.kind} asset {mapping.asset_id} for roles "
                    f"{', '.join(mapping.roles)}; "
                    f"source={file_path.resolve().relative_to(project_root)}"
                ),
                content=None,
                content_ref=file_path.resolve().as_uri(),
                project_id=spec.project_id,
                scope="project_static",
                roles=tuple(mapping.roles),
                unit_type="investigation" if mapping.kind == "investigation" else "project_document",
                source_type="role_asset",
                tags={"asset_id": mapping.asset_id, "source": selected["source"]},
            )


def _context_records(
    spec: Any,
    *,
    role: str,
    use_candidate: bool,
    selected_assets: list[Mapping[str, Any]],
    require_available: bool,
) -> list[ContextUnitRecord]:
    builders = [item for item in selected_assets if item["mapping"].kind == "context_builder"]
    direct_assets = [item for item in selected_assets if item["mapping"].kind == "context"]
    if not builders:
        direct_assets.extend(
            item for item in selected_assets if item["mapping"].kind == "investigation"
        )
    records = list(_asset_records(spec, direct_assets, require_available=require_available))
    for builder in builders:
        if not builder["available"]:
            if require_available:
                raise FileNotFoundError(f"enabled Context builder role asset not found: {builder['path']}")
            continue
        records.extend(
            _load_context_builder_records(
                spec,
                role=role,
                use_candidate=use_candidate,
                builder=builder,
                selected_assets=selected_assets,
            )
        )
    seen: set[str] = set()
    for record in records:
        if record.id in seen:
            raise ValueError(f"duplicate project ContextUnit ID: {record.id}")
        seen.add(record.id)
    return records


def _load_context_builder_records(
    spec: Any,
    *,
    role: str,
    use_candidate: bool,
    builder: Mapping[str, Any],
    selected_assets: list[Mapping[str, Any]],
) -> list[ContextUnitRecord]:
    module_path = Path(builder["path"])
    digest = hashlib.sha256(str(module_path).encode("utf-8")).hexdigest()[:12]
    module_spec = importlib.util.spec_from_file_location(
        f"project_context_builder_{digest}", module_path
    )
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"cannot import Context builder: {module_path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    factory = getattr(module, "build_context_unit_records", None)
    if not callable(factory):
        raise TypeError(
            f"Context builder must define build_context_unit_records(): {module_path}"
        )
    built = list(factory(spec, role, use_candidate, selected_assets) or [])
    mapping = builder["mapping"]
    for record in built:
        if not isinstance(record, ContextUnitRecord):
            raise TypeError(f"Context builder must return ContextUnitRecord: {module_path}")
        if record.project_id != spec.project_id:
            raise ValueError(f"Context builder returned cross-project record: {record.id}")
        if role not in record.roles or not set(record.roles).issubset(set(mapping.roles)):
            raise ValueError(
                f"Context builder record roles exceed RoleAssetMapping permissions: {record.id}"
            )
    return built


def _content_roots(spec: Any) -> list[Path]:
    roots = []
    project_root = resolve_project_package_root(spec, must_exist=False)
    if project_root.exists():
        roots.append(project_root)
    if spec.has_business_source:
        source_root = resolve_project_source_root(spec)
        if source_root not in roots:
            roots.append(source_root)
    return roots
