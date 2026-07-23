from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional

from .adapter_v2 import ProjectAdapter
from .project_config import PROJECTS_DIR, resolve_project_config
from .path_contract import PathRoots, PathScope, logical_ref_for_path
from .schema import ProjectSpec, RoleAssetMapping

def list_projects() -> List[str]:
    if not PROJECTS_DIR.exists():
        return []
    return sorted(path.name for path in PROJECTS_DIR.iterdir() if (path / "project.yaml").exists())


def load_project(project_id: str) -> ProjectSpec:
    return resolve_project_config(project_id)


def resolve_project_source_root(spec: ProjectSpec) -> Path:
    """Canonical business-root accessor."""
    accessor = getattr(spec, "source_root_path", None)
    if not callable(accessor):
        raise RuntimeError(f"project {spec.project_id} has no source_root_path accessor")
    return accessor()


def resolve_project_package_root(
    spec: ProjectSpec, *, must_exist: bool = True
) -> Path:
    """Canonical project-package accessor."""
    accessor = getattr(spec, "project_package_path", None)
    if not callable(accessor):
        raise RuntimeError(f"project {spec.project_id} has no project_package_path accessor")
    return accessor(must_exist=must_exist)


def resolve_role_assets(spec: ProjectSpec, role: str, use_candidate: bool) -> List[Dict[str, Any]]:
    """Resolve one authoritative asset list for production, draft checks and promotion."""
    normalized_role = str(role or "").strip()
    if not normalized_role:
        raise ValueError("role is required")
    root = resolve_project_package_root(spec, must_exist=False)
    seen_ids: set[str] = set()
    production_targets: Dict[Path, str] = {}
    resolved: List[Dict[str, Any]] = []
    for mapping in spec.asset_mappings():
        _validate_role_asset_mapping(mapping)
        if mapping.asset_id in seen_ids:
            raise ValueError(f"duplicate role asset_id: {mapping.asset_id}")
        seen_ids.add(mapping.asset_id)
        if not mapping.logical_production_path:
            raise ValueError(
                f"RoleAssetMapping requires logical_production_path: {mapping.asset_id}"
            )
        production_path = spec.resolve_path(
            mapping.logical_production_path,
            field_path=f"verifier.assets.{mapping.asset_id}.production_path",
            allowed_scopes={PathScope.PROJECT_PACKAGE},
            must_exist=False,
        )
        draft_root = (root / "draft").resolve()
        if production_path.is_relative_to(draft_root):
            raise ValueError(
                f"RoleAssetMapping.production_path must stay outside draft/: {mapping.asset_id}"
            )
        prior = production_targets.get(production_path)
        if prior is not None:
            raise ValueError(
                f"role assets {prior!r} and {mapping.asset_id!r} share production_path {mapping.production_path!r}"
            )
        production_targets[production_path] = mapping.asset_id
        if not mapping.enabled or normalized_role not in mapping.roles:
            continue
        candidate_path = None
        if mapping.candidate_path:
            if not mapping.logical_candidate_path:
                raise ValueError(
                    f"RoleAssetMapping requires logical_candidate_path: {mapping.asset_id}"
                )
            candidate_path = spec.resolve_path(
                mapping.logical_candidate_path,
                field_path=f"verifier.assets.{mapping.asset_id}.candidate_path",
                allowed_scopes={PathScope.PROJECT_PACKAGE},
                must_exist=False,
            )
            if not candidate_path.is_relative_to(draft_root):
                raise ValueError(
                    f"RoleAssetMapping.candidate_path must resolve under draft/: {mapping.asset_id}"
                )
        selected = candidate_path if use_candidate and candidate_path is not None else production_path
        if use_candidate and candidate_path is not None and not candidate_path.exists():
            raise FileNotFoundError(f"enabled candidate role asset not found: {candidate_path}")
        resolved.append(
            {
                "mapping": mapping,
                "path": selected,
                "location_ref": logical_ref_for_path(
                    selected,
                    scope=PathScope.PROJECT_PACKAGE,
                    roots=spec.path_roots or PathRoots(project_package=root),
                    field_path=f"verifier.assets.{mapping.asset_id}.selected_path",
                ),
                "production_path": production_path,
                "candidate_path": candidate_path,
                "available": selected.exists(),
                "source": "candidate" if use_candidate and candidate_path is not None else "production",
            }
        )
    return resolved


def _validate_role_asset_mapping(mapping: RoleAssetMapping) -> None:
    if not mapping.asset_id.strip():
        raise ValueError("RoleAssetMapping.asset_id is required")
    if mapping.kind not in {"tool", "context", "context_builder", "investigation", "other"}:
        raise ValueError(f"unsupported RoleAssetMapping.kind: {mapping.kind!r}")
    if not mapping.roles or any(not role.strip() for role in mapping.roles):
        raise ValueError(f"RoleAssetMapping.roles is required: {mapping.asset_id}")
    if len(set(mapping.roles)) != len(mapping.roles):
        raise ValueError(f"RoleAssetMapping.roles contains duplicates: {mapping.asset_id}")
    if not mapping.production_path.strip():
        raise ValueError(f"RoleAssetMapping.production_path is required: {mapping.asset_id}")

def _load_project_module(spec: ProjectSpec, filename: str, role: str) -> Optional[ModuleType]:
    """Load optional project-layer protocol module.

    spec/info-volume.md: core only defines the protocol and dispatch seam.  Project
    judge/attribute strategies live in impl/projects/<project>/{role}.py when a
    project opts in. A draft role is loaded only when project.yaml explicitly
    enables <role>_draft for manual validation; default production never auto-loads draft.
    """
    module_path = Path(filename)
    if not module_path.is_absolute():
        module_path = spec.project_package_path(
            filename,
            field_path=f"verifier.roles.{role}.module",
            must_exist=False,
        )
    if not module_path.exists():
        return None
    module_name = f"impl_project_{spec.project_id}_{role}"
    module_spec = importlib.util.spec_from_file_location(module_name, module_path)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"cannot load project {role} module: {module_path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def _safe_draft_role_filename(spec: ProjectSpec, role: str) -> Optional[str]:
    draft_cfg = spec.role_draft(role)
    if not isinstance(draft_cfg, dict) or draft_cfg.get("enabled") is not True:
        return None
    resolved = spec.role_draft_path(role, must_exist=False)
    if resolved is not None:
        if not resolved.is_file():
            raise FileNotFoundError(f"enabled {role} draft module not found: {resolved}")
        return str(resolved)
    module = str(draft_cfg.get("module") or f"draft/{role}.py")
    module_path = Path(module)
    if module_path.is_absolute() or ".." in module_path.parts or module_path.parts[:1] != ("draft",):
        raise ValueError(f"{role}_draft.module must be a relative path under draft/")
    draft_root = spec.project_package_path(
        "draft", field_path=f"verifier.roles.{role}.draft_root", must_exist=False
    )
    try:
        resolved_module = spec.project_package_path(
            module,
            field_path=f"verifier.roles.{role}.draft.module",
            must_exist=False,
        )
    except ValueError as exc:
        raise ValueError(
            f"{role}_draft.module must resolve under the project draft/ directory"
        ) from exc
    if not resolved_module.is_relative_to(draft_root):
        raise ValueError(f"{role}_draft.module must resolve under the project draft/ directory")
    if not resolved_module.is_file():
        raise FileNotFoundError(f"enabled {role} draft module not found: {resolved_module}")
    return module


def load_project_judge(spec: ProjectSpec) -> Optional[ModuleType]:
    draft_filename = _safe_draft_role_filename(spec, "judge")
    if draft_filename:
        return _load_project_module(spec, draft_filename, "judge_draft")
    return _load_project_module(spec, "judge.py", "judge")


def load_project_mock(spec: ProjectSpec) -> Optional[ModuleType]:
    draft_filename = _safe_draft_role_filename(spec, "mock")
    if draft_filename:
        return _load_project_module(spec, draft_filename, "mock_draft")
    return _load_project_module(spec, "mock.py", "mock")


def load_project_attribute(spec: ProjectSpec) -> Optional[ModuleType]:
    draft_filename = _safe_draft_role_filename(spec, "attribute")
    if draft_filename:
        return _load_project_module(spec, draft_filename, "attribute_draft")
    return _load_project_module(spec, "attribute.py", "attribute")


def load_project_tools(spec: ProjectSpec) -> Any:
    module_path = spec.project_package_path(
        "tools.py", field_path="verifier.tools.module", must_exist=False
    )
    if module_path.is_file():
        module = _load_project_module(spec, "tools.py", "tools")
    else:
        module = _load_project_module(spec, "tools/project_tools.py", "tools")
    if module is None:
        from .tools_protocol import ProjectTools

        return ProjectTools(spec)

    from .tools_protocol import ProjectTools

    candidates = [
        value
        for value in vars(module).values()
        if inspect.isclass(value)
        and value.__module__ == module.__name__
        and issubclass(value, ProjectTools)
        and value is not ProjectTools
    ]
    if len(candidates) != 1:
        source = getattr(module, "__file__", module.__name__)
        raise TypeError(f"{source} must define exactly one ProjectTools subclass")
    return candidates[0](spec)


def load_project_role_tools(spec: ProjectSpec, role: str) -> List[Any]:
    """Load one Role's Tool set, preferring a validated investigation package.

    Projects without an available investigation package retain the existing
    ProjectTools baseline.  Once a package is available for the selected
    Production/Draft mode, every implemented Tool must be enabled through the same
    RoleAssetMapping used by Draft check and Promote; no legacy fallback is mixed in.
    """
    normalized_role = str(role or "").strip()
    use_candidate = spec.role_draft(normalized_role).get("enabled") is True
    selected = resolve_role_assets(spec, normalized_role, use_candidate=use_candidate)
    has_investigation = any(
        item["mapping"].kind == "investigation" and item["available"]
        for item in selected
    )
    if not has_investigation:
        return list(load_project_tools(spec).verifiable_tools() or [])

    from .investigation import load_role_investigation_tools

    return load_role_investigation_tools(
        spec,
        role=normalized_role,
        use_candidate=use_candidate,
    )


def load_project_role_instance(
    spec: ProjectSpec,
    role: str,
    adapter: Any,
) -> Optional[Any]:
    if role == "judge":
        from .judge_protocol import ProjectJudge

        module = load_project_judge(spec)
        protocol = ProjectJudge
    elif role == "attribute":
        from .attribute_protocol import ProjectAttribute

        module = load_project_attribute(spec)
        protocol = ProjectAttribute
    elif role == "mock":
        from .mock_protocol import ProjectMock

        module = load_project_mock(spec)
        protocol = ProjectMock
    else:
        raise ValueError(f"unsupported project role: {role}")
    if module is None:
        return None

    candidates = [
        value
        for value in vars(module).values()
        if inspect.isclass(value)
        and value.__module__ == module.__name__
        and issubclass(value, protocol)
        and value is not protocol
    ]
    if len(candidates) != 1:
        source = getattr(module, "__file__", module.__name__)
        raise TypeError(f"{source} must define exactly one {protocol.__name__} subclass")

    role_class = candidates[0]
    parameters = list(inspect.signature(role_class).parameters.values())
    if [parameter.name for parameter in parameters] == ["spec"]:
        return role_class(spec)
    if [parameter.name for parameter in parameters] == ["spec", "adapter"]:
        return role_class(spec, adapter)
    raise TypeError(f"{role_class.__name__} constructor must be (spec) or (spec, adapter)")


def load_adapter(spec: ProjectSpec) -> ProjectAdapter:
    adapter_path = spec.adapter_path()
    module_name = f"impl_project_{spec.project_id}_adapter"
    module_spec = importlib.util.spec_from_file_location(module_name, adapter_path)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"cannot load adapter: {adapter_path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    adapter_cls = getattr(module, "Adapter")
    return adapter_cls(spec)


def load_field_provider(spec: ProjectSpec) -> Optional[Any]:
    """根据 ProjectSpec 声明动态加载项目专属字段定义 provider，未声明则返回 None。

    项目在 project.yaml 里声明 field_provider_module + field_provider_class，
    核心代码无需对 project_id 做分支判断。
    """
    field_provider = spec.field_provider_config
    module = str(field_provider.get("module") or "")
    class_name = str(field_provider.get("class") or "")
    if not module or not class_name:
        return None
    module_path = spec.field_provider_path()
    if not module_path.exists():
        return None
    module_name = f"impl_project_{spec.project_id}_field_provider"
    module_spec = importlib.util.spec_from_file_location(module_name, module_path)
    if module_spec is None or module_spec.loader is None:
        return None
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    provider_cls = getattr(module, class_name, None)
    if provider_cls is None:
        return None
    return provider_cls(spec)


def load_project_document(spec: ProjectSpec, key: str) -> str:
    if key not in spec.document_paths:
        return ""
    path = spec.project_document_path(key, must_exist=False)
    if path is None:
        return ""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")
