from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional

from .adapter_v2 import ProjectAdapter
from .schema import ProjectSpec

ROOT = Path(__file__).resolve().parents[1]
PROJECTS_DIR = ROOT / "projects"


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "None"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def load_simple_yaml(path: Path) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    stack: List[tuple[int, Any]] = [(-1, data)]
    lines = [
        (len(raw_line) - len(raw_line.lstrip(" ")), raw_line.strip())
        for raw_line in path.read_text(encoding="utf-8").splitlines()
        if raw_line.strip() and not raw_line.lstrip().startswith("#")
    ]

    for idx, (indent, line) in enumerate(lines):
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if line.startswith("- "):
            rest = line[2:]
            # Check if this is a list item with nested dict (e.g., "- field: value")
            if ":" in rest:
                # This is a dict item in a list
                item_dict = {}
                if isinstance(parent, list):
                    parent.append(item_dict)
                    stack.append((indent, item_dict))
                # Parse the first key-value pair
                key, value = rest.split(":", 1)
                item_dict[key.strip()] = _parse_scalar(value.strip())
            else:
                # Simple scalar list item
                item = _parse_scalar(rest)
                if isinstance(parent, list):
                    parent.append(item)
            continue

        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()

        if value == "":
            # Look ahead to determine if next line is list or dict
            next_container: Any = {}
            if idx + 1 < len(lines):
                next_indent, next_line = lines[idx + 1]
                if next_indent > indent and next_line.startswith("- "):
                    next_container = []
            if isinstance(parent, dict):
                parent[key] = next_container
            stack.append((indent, next_container))
        else:
            parsed = _parse_scalar(value)
            if value == "[]":
                parsed = []
            elif value == "{}":
                parsed = {}
            elif value.startswith("[") and value.endswith("]"):
                inner = value[1:-1].strip()
                if not inner:
                    parsed = []
                else:
                    # flow-style scalar list: [a, b, c] → ['a','b','c']；JSON 合法值优先
                    try:
                        parsed = json.loads(value)
                    except json.JSONDecodeError:
                        items = [item.strip() for item in inner.split(",") if item.strip()]
                        parsed = [_parse_scalar(item) for item in items]
            elif value.startswith("{") and value.endswith("}"):
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    pass
            if isinstance(parent, dict):
                parent[key] = parsed
    return data


def _merged_common(data: Dict[str, Any]) -> Dict[str, Any]:
    common = dict(data.get("common") or {})

    if data.get("api") and not common.get("api"):
        common["api"] = dict(data.get("api") or {})

    application = dict(data.get("application") or {})
    source = dict(common.get("source") or {})
    if not source.get("repo") and application.get("external_repo"):
        source["repo"] = application.get("external_repo")
    common["source"] = source

    start = dict(common.get("start") or {})
    if not start.get("command") and application.get("start"):
        start["command"] = application.get("start")
    common["start"] = start

    return common


def _default_documents(project_root: Path) -> Dict[str, str]:
    candidates = {
        "application": "application.md",
        "mock": "mock.md",
        "evaluation": "evaluation.md",
        "judge_boundary": "judge_boundary.md",
        "attribution": "attribution.md",
        "checklist": "checklist.md",
        "implementation_standard": "implementation_standard.md",
    }
    return {key: rel for key, rel in candidates.items() if (project_root / rel).exists()}


def list_projects() -> List[str]:
    if not PROJECTS_DIR.exists():
        return []
    return sorted(path.name for path in PROJECTS_DIR.iterdir() if (path / "project.yaml").exists())


def _resolve_source_project(data: Dict[str, Any], project_root: Path) -> str:
    """解析用户侧项目目录为绝对路径。

    impl 侧运行时不依赖用户侧 project.yaml，但 LLM 可据此查找需求材料。
    """
    rel = data.get("source_project")
    if not rel:
        return ""
    path = Path(str(rel))
    if not path.is_absolute():
        path = (project_root / path).resolve()
    return str(path) if path.exists() else ""


def load_project(project_id: str) -> ProjectSpec:
    project_root = PROJECTS_DIR / project_id
    cfg_path = project_root / "project.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(f"project config not found: {cfg_path}")
    data = load_simple_yaml(cfg_path)
    common = _merged_common(data)
    documents = _default_documents(project_root)
    documents.update(dict(data.get("documents") or {}))
    return ProjectSpec(
        project_id=str(data.get("project_id") or project_id),
        name=str(data.get("name") or project_id),
        description=str(data.get("description") or ""),
        adapter="adapter.py",
        field_provider_module=str(data.get("field_provider_module") or ""),
        field_provider_class=str(data.get("field_provider_class") or ""),
        capabilities=list(data.get("capabilities") or []),
        common=common,
        extra=dict(data.get("extra") or {}),
        documents=documents,
        api=dict(common.get("api") or data.get("api") or {}),
        application=dict(data.get("application") or {}),
        frontend_extensions=dict(data.get("frontend_extensions") or {}),
        endpoint_discovery=dict(data.get("endpoint_discovery") or {}),
        attribute_draft=dict(data.get("attribute_draft") or {}),
        judge_draft=dict(data.get("judge_draft") or {}),
        root=str(project_root),
        source_project=_resolve_source_project(data, project_root),
    )


def _load_project_module(spec: ProjectSpec, filename: str, role: str) -> Optional[ModuleType]:
    """Load optional project-layer protocol module.

    spec/info-volume.md: core only defines the protocol and dispatch seam.  Project
    judge/attribute strategies live in impl/projects/<project>/{role}.py when a
    project opts in. A draft role is loaded only when project.yaml explicitly
    enables <role>_draft for manual validation; default production never auto-loads draft.
    """
    module_path = Path(spec.root) / filename
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
    draft_cfg = getattr(spec, f"{role}_draft", {})
    if not isinstance(draft_cfg, dict) or draft_cfg.get("enabled") is not True:
        return None
    module = str(draft_cfg.get("module") or f"draft/{role}.py")
    module_path = Path(module)
    if module_path.is_absolute() or ".." in module_path.parts or module_path.parts[:1] != ("draft",):
        raise ValueError(f"{role}_draft.module must be a relative path under draft/")
    draft_root = (Path(spec.root) / "draft").resolve()
    resolved_module = (Path(spec.root) / module_path).resolve()
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


def load_project_attribute(spec: ProjectSpec) -> Optional[ModuleType]:
    draft_filename = _safe_draft_role_filename(spec, "attribute")
    if draft_filename:
        return _load_project_module(spec, draft_filename, "attribute_draft")
    return _load_project_module(spec, "attribute.py", "attribute")


def load_project_tools(spec: ProjectSpec) -> Any:
    module_path = Path(spec.root) / "tools.py"
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
    adapter_path = Path(spec.root) / spec.adapter
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
    if not spec.field_provider_module or not spec.field_provider_class:
        return None
    module_path = Path(spec.root) / spec.field_provider_module
    if not module_path.exists():
        return None
    module_name = f"impl_project_{spec.project_id}_field_provider"
    module_spec = importlib.util.spec_from_file_location(module_name, module_path)
    if module_spec is None or module_spec.loader is None:
        return None
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    provider_cls = getattr(module, spec.field_provider_class, None)
    if provider_cls is None:
        return None
    return provider_cls(spec)


def load_project_document(spec: ProjectSpec, key: str) -> str:
    rel = spec.documents.get(key)
    if not rel:
        return ""
    path = Path(spec.root) / rel
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")
