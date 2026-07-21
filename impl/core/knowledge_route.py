from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .config import ROOT
from .config_schema import ConfigError, EnvironmentRegistry, _parse_environment, load_yaml_document


KNOWLEDGE_ROOT = ROOT / "projects"
DOCUMENT_TYPES = {
    "startup",
    "api",
    "environment",
    "requirements",
    "judge_boundary",
    "attribution",
    "checklist",
    "reference",
}
INTERACTION_TYPES = {"single_turn", "multi_turn"}
READY_VALUES = {"output", "reference"}
_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")
_PLACEHOLDER = re.compile(r"^\$\{([A-Z][A-Z0-9_]*)\}$")


@dataclass(frozen=True)
class KnowledgeDocument:
    document_id: str
    path: str
    type: str
    required: bool
    description: str


@dataclass(frozen=True)
class ProjectKnowledgeRoute:
    schema_version: int
    project_id: str
    name: str
    description: str
    documents: Mapping[str, KnowledgeDocument]
    source_repository: str
    interaction: str
    ready: tuple[str, ...]
    environment: EnvironmentRegistry
    root: Path

    def document_path(self, document_id: str) -> Path:
        try:
            document = self.documents[document_id]
        except KeyError as exc:
            raise ConfigError(f"knowledge document is not registered: {document_id}") from exc
        return (self.root / document.path).resolve()


def load_project_knowledge_route(
    project_id: str,
    *,
    knowledge_root: Path = KNOWLEDGE_ROOT,
) -> ProjectKnowledgeRoute:
    route_root = knowledge_root / project_id
    path = route_root / "project.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"project knowledge route not found: {path}")
    return parse_project_knowledge_route(load_yaml_document(path), project_id=project_id, route_root=route_root)


def parse_project_knowledge_route(
    data: Mapping[str, Any],
    *,
    project_id: str | None,
    route_root: Path,
) -> ProjectKnowledgeRoute:
    root = _mapping(data, "knowledge route")
    _unknown(root, {"schema_version", "project", "documents", "source", "onboarding", "environment"}, "")
    version = _integer(_required(root, "schema_version", ""), "schema_version")
    if version != 1:
        raise ConfigError(f"unsupported knowledge route schema_version {version}")
    project = _mapping(_required(root, "project", ""), "project")
    _unknown(project, {"id", "name", "description"}, "project")
    route_id = _string(_required(project, "id", "project"), "project.id")
    if project_id is not None and route_id != project_id:
        raise ConfigError(f"project.id {route_id!r} must match knowledge route directory {project_id!r}")

    documents_data = _mapping(_required(root, "documents", ""), "documents")
    if not documents_data:
        raise ConfigError("invalid field documents: expected non-empty mapping")
    documents: dict[str, KnowledgeDocument] = {}
    for document_id, raw_document in documents_data.items():
        if not isinstance(document_id, str) or not _SNAKE_CASE.fullmatch(document_id):
            raise ConfigError(f"invalid document id {document_id!r}: expected snake_case")
        path = f"documents.{document_id}"
        document = _mapping(raw_document, path)
        _unknown(document, {"path", "type", "required", "description"}, path)
        relative = _relative_path(_required(document, "path", path), f"{path}.path")
        document_type = _choice(_required(document, "type", path), f"{path}.type", DOCUMENT_TYPES)
        required = _boolean(_required(document, "required", path), f"{path}.required")
        target = (route_root / relative).resolve()
        if not target.is_relative_to(route_root.resolve()):
            raise ConfigError(f"knowledge document escapes route directory: {target}")
        if required and not target.is_file():
            raise ConfigError(f"required knowledge document not found: {target}")
        if target.is_file():
            _validate_front_matter(target, document_type)
        documents[document_id] = KnowledgeDocument(
            document_id=document_id,
            path=relative,
            type=document_type,
            required=required,
            description=_string(_required(document, "description", path), f"{path}.description"),
        )

    onboarding = _mapping(_required(root, "onboarding", ""), "onboarding")
    _unknown(onboarding, {"interaction", "ready"}, "onboarding")
    interaction = _choice(_required(onboarding, "interaction", "onboarding"), "onboarding.interaction", INTERACTION_TYPES)
    ready = _string_list(_required(onboarding, "ready", "onboarding"), "onboarding.ready")
    unknown_ready = sorted(set(ready) - READY_VALUES)
    if unknown_ready:
        raise ConfigError(f"invalid onboarding.ready value {unknown_ready[0]!r}")

    environment = _parse_environment(root["environment"]) if "environment" in root else EnvironmentRegistry(MappingProxyType({}))
    source_repository = ""
    if "source" in root:
        source = _mapping(root["source"], "source")
        _unknown(source, {"repository"}, "source")
        source_repository = _string(_required(source, "repository", "source"), "source.repository")
        match = _PLACEHOLDER.fullmatch(source_repository)
        if match is None:
            raise ConfigError("source.repository must use a registered ${VAR} reference")
        variable = environment.variables.get(match.group(1))
        if variable is None or variable.bind != "source.repository" or variable.type != "path":
            raise ConfigError(f"source.repository variable {match.group(1)} must bind source.repository as path")
    for variable in environment.variables.values():
        if variable.bind != "source.repository":
            raise ConfigError(f"unsupported knowledge route environment bind: {variable.bind}")
    return ProjectKnowledgeRoute(
        schema_version=version,
        project_id=route_id,
        name=_string(_required(project, "name", "project"), "project.name"),
        description=_string(_required(project, "description", "project"), "project.description"),
        documents=MappingProxyType(documents),
        source_repository=source_repository,
        interaction=interaction,
        ready=tuple(ready),
        environment=environment,
        root=route_root,
    )


def _validate_front_matter(path: Path, document_type: str) -> None:
    text = path.read_text(encoding="utf-8", errors="strict")
    if not text.startswith("---\n"):
        return
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ConfigError(f"invalid Markdown front matter: {path}")
    import yaml

    metadata = yaml.safe_load(text[4:end]) or {}
    if not isinstance(metadata, dict):
        raise ConfigError(f"invalid Markdown front matter mapping: {path}")
    if metadata.get("doc_type") != document_type:
        raise ConfigError(f"front matter doc_type in {path} must be {document_type!r}")
    if metadata.get("schema_version") != 1:
        raise ConfigError(f"front matter schema_version in {path} must be 1")


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"invalid field {path}: expected mapping")
    return dict(value)


def _unknown(data: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        name = f"{path}.{unknown[0]}" if path else unknown[0]
        raise ConfigError(f"unknown field {name}")


def _required(data: Mapping[str, Any], key: str, path: str) -> Any:
    if key not in data:
        name = f"{path}.{key}" if path else key
        raise ConfigError(f"missing required field {name}")
    return data[key]


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip() or value.strip() == "暂无":
        raise ConfigError(f"invalid field {path}: expected non-empty string")
    return value.strip()


def _integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"invalid field {path}: expected positive integer")
    return value


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"invalid field {path}: expected boolean")
    return value


def _choice(value: Any, path: str, choices: set[str]) -> str:
    text = _string(value, path)
    if text not in choices:
        raise ConfigError(f"invalid field {path}: unsupported value {text!r}; expected one of {sorted(choices)}")
    return text


def _string_list(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ConfigError(f"invalid field {path}: expected list of strings")
    if len(value) != len(set(value)):
        raise ConfigError(f"invalid field {path}: duplicate values")
    return list(value)


def _relative_path(value: Any, path: str) -> str:
    text = _string(value, path)
    candidate = Path(text)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ConfigError(f"invalid field {path}: expected route-relative path")
    return candidate.as_posix()
