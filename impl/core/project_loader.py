from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, List

from .adapter import ProjectAdapter
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
            elif value.startswith("[") or value.startswith("{"):
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    pass
            if isinstance(parent, dict):
                parent[key] = parsed
    return data


def list_projects() -> List[str]:
    if not PROJECTS_DIR.exists():
        return []
    return sorted(path.name for path in PROJECTS_DIR.iterdir() if (path / "project.yaml").exists())


def load_project(project_id: str) -> ProjectSpec:
    project_root = PROJECTS_DIR / project_id
    cfg_path = project_root / "project.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(f"project config not found: {cfg_path}")
    data = load_simple_yaml(cfg_path)
    return ProjectSpec(
        project_id=str(data.get("project_id") or project_id),
        name=str(data.get("name") or project_id),
        description=str(data.get("description") or ""),
        adapter=str(data.get("adapter") or "adapter.py"),
        capabilities=list(data.get("capabilities") or []),
        documents=dict(data.get("documents") or {}),
        api=dict(data.get("api") or {}),
        application=dict(data.get("application") or {}),
        frontend_extensions=dict(data.get("frontend_extensions") or {}),
        root=str(project_root),
    )


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


def load_project_document(spec: ProjectSpec, key: str) -> str:
    rel = spec.documents.get(key)
    if not rel:
        return ""
    path = Path(spec.root) / rel
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")
