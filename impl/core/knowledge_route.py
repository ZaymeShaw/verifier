from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .config import ROOT
from .config_bootstrap import parse_dotenv
from .config_schema import (
    ConfigError,
    ConfigValueSource,
    EnvironmentRegistry,
    _parse_environment,
    convert_environment_value,
    load_yaml_document,
)
from .path_contract import (
    PathContractError,
    PathResolver,
    PathRoots,
    PathScope,
    canonical_prefixed_path,
)


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
_DOCUMENT_TOPICS = {
    "startup": {
        "前置条件": r"前置|准备|依赖|prerequisite",
        "启动方式": r"启动|运行|start",
        "健康检查": r"健康|health",
        "成功信号": r"成功|可用|ready",
        "常见失败": r"失败|故障|错误|排查|failure",
    },
    "api": {
        "endpoint": r"endpoint|端点|接口|路径",
        "method": r"method|\b(?:GET|POST|PUT|PATCH|DELETE)\b",
        "请求": r"请求|request",
        "响应": r"响应|response|返回",
        "错误语义": r"错误|失败|error",
    },
    "environment": {
        "变量名": r"变量|environment|[A-Z][A-Z0-9_]{2,}",
        "用途": r"用途|purpose",
        "是否必填": r"必填|required",
        "是否为秘密": r"秘密|secret",
    },
    "requirements": {
        "业务目标": r"业务目标|目标|purpose",
        "范围": r"范围|边界|scope",
        "非目标": r"非目标|不包括|不负责|out[ -]of[ -]scope",
        "核心场景": r"核心场景|场景|scenario",
    },
    "judge_boundary": {
        "可评价范围": r"可评价|纳入.*评价|评估.*范围",
        "不可评价范围": r"不可评价|不评估|不纳入",
        "外部依赖责任": r"外部依赖|下游|责任",
    },
    "attribution": {
        "证据来源": r"证据来源|可用证据",
        "证据限制": r"证据限制|限制",
        "无法归因处理": r"无法归因|不可归因|证据不足",
    },
    "checklist": {
        "检查项": r"检查项|check",
        "通过条件": r"通过条件|成功条件",
        "失败证据": r"失败证据|失败条件",
    },
    "reference": {
        "资料来源": r"资料来源|来源|source",
        "用途": r"用途|用于|purpose",
        "适用范围": r"适用范围|适用于|范围|scope",
    },
}


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
    source_repository_reference: str
    interaction: str
    ready: tuple[str, ...]
    environment: EnvironmentRegistry
    root: Path
    config_sources: Mapping[str, ConfigValueSource]
    missing_required: tuple[str, ...] = ()
    path_warnings: tuple[str, ...] = ()
    path_roots: PathRoots | None = None
    path_resolver: PathResolver | None = None

    def document_path(self, document_id: str) -> Path:
        try:
            document = self.documents[document_id]
        except KeyError as exc:
            raise ConfigError(f"knowledge document is not registered: {document_id}") from exc
        if self.path_resolver is None:
            raise ConfigError(f"knowledge route has no PathResolver: {self.project_id}")
        try:
            return self.path_resolver.resolve(
                document.path,
                field_path=f"documents.{document_id}.path",
                allowed_scopes={PathScope.KNOWLEDGE_ROUTE},
                expected_type="file",
            ).physical
        except PathContractError as exc:
            raise ConfigError(str(exc)) from exc


def load_project_knowledge_route(
    project_id: str,
    *,
    knowledge_root: Path = KNOWLEDGE_ROOT,
    dotenv_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
    verifier_root: Path | None = None,
) -> ProjectKnowledgeRoute:
    knowledge_root = Path(knowledge_root).resolve()
    resolved_verifier_root = Path(verifier_root or knowledge_root.parent).resolve()
    route_root = knowledge_root / project_id
    path = route_root / "project.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"project knowledge route not found: {path}")
    parsed = parse_project_knowledge_route(load_yaml_document(path), project_id=project_id, route_root=route_root)
    return _resolve_knowledge_environment(
        parsed,
        dotenv_path=dotenv_path or resolved_verifier_root / ".env",
        environ=os.environ if environ is None else environ,
        verifier_root=resolved_verifier_root,
    )


def parse_project_knowledge_route(
    data: Mapping[str, Any],
    *,
    project_id: str | None,
    route_root: Path,
    path_warnings: list[str] | None = None,
) -> ProjectKnowledgeRoute:
    warnings = path_warnings if path_warnings is not None else []
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
        try:
            relative = canonical_prefixed_path(
                _required(document, "path", path),
                field_path=f"{path}.path",
                allowed_scopes={PathScope.KNOWLEDGE_ROUTE},
            )
        except PathContractError as exc:
            raise ConfigError(str(exc)) from exc
        document_type = _choice(_required(document, "type", path), f"{path}.type", DOCUMENT_TYPES)
        required = _boolean(_required(document, "required", path), f"{path}.required")
        resolver = PathResolver(PathRoots(knowledge_route=route_root))
        try:
            target = resolver.resolve(
                relative,
                field_path=f"{path}.path",
                allowed_scopes={PathScope.KNOWLEDGE_ROUTE},
                expected_type="file",
                must_exist=False,
            ).physical
        except PathContractError as exc:
            raise ConfigError(str(exc)) from exc
        if not target.is_file():
            if required:
                raise ConfigError(f"required knowledge document not found: {target}")
            # 可选资料不存在时不保留虚构路由项。
            continue
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
        if variable.secret:
            raise ConfigError("source.repository path cannot be registered as secret")
    for variable in environment.variables.values():
        if variable.bind != "source.repository":
            raise ConfigError(f"unsupported knowledge route environment bind: {variable.bind}")
    path_roots = PathRoots(knowledge_route=route_root)
    return ProjectKnowledgeRoute(
        schema_version=version,
        project_id=route_id,
        name=_string(_required(project, "name", "project"), "project.name"),
        description=_string(_required(project, "description", "project"), "project.description"),
        documents=MappingProxyType(documents),
        source_repository=source_repository,
        source_repository_reference=source_repository,
        interaction=interaction,
        ready=tuple(ready),
        environment=environment,
        root=route_root,
        config_sources=MappingProxyType(
            {"source.repository": ConfigValueSource("knowledge_yaml", "source.repository")}
            if source_repository
            else {}
        ),
        path_warnings=tuple(warnings),
        path_roots=path_roots,
        path_resolver=PathResolver(path_roots),
    )


def _resolve_knowledge_environment(
    route: ProjectKnowledgeRoute,
    *,
    dotenv_path: Path,
    environ: Mapping[str, str],
    verifier_root: Path,
) -> ProjectKnowledgeRoute:
    """Resolve registered knowledge-route values without exposing other config layers."""
    base_roots = PathRoots(
        verifier_repo=verifier_root,
        knowledge_route=route.root,
    )
    if not route.source_repository_reference:
        return replace(
            route,
            path_roots=base_roots,
            path_resolver=PathResolver(base_roots),
        )
    dotenv = parse_dotenv(dotenv_path)
    match = _PLACEHOLDER.fullmatch(route.source_repository_reference)
    if match is None:  # parse_project_knowledge_route already rejects this shape
        raise ConfigError("source.repository must use a registered ${VAR} reference")
    variable = route.environment.variables[match.group(1)]
    raw_value = environ.get(variable.name)
    source_kind = "process_environment"
    if raw_value in (None, ""):
        raw_value = dotenv.get(variable.name)
        source_kind = "dotenv"
    if raw_value in (None, ""):
        missing = (variable.bind,) if variable.required else ()
        return replace(
            route,
            source_repository="",
            missing_required=missing,
            path_roots=base_roots,
            path_resolver=PathResolver(base_roots),
        )
    resolved = str(convert_environment_value(variable, raw_value))
    repository = Path(resolved)
    if not repository.is_absolute():
        raise ConfigError(f"knowledge source.repository must resolve to an absolute path: {route.project_id}")
    if not repository.is_dir():
        raise ConfigError(f"knowledge source.repository is not a readable directory: {route.project_id}")
    return replace(
        route,
        source_repository=str(repository.resolve()),
        config_sources=MappingProxyType({
            "source.repository": ConfigValueSource(source_kind, variable.name, variable.secret)
        }),
        missing_required=(),
        path_roots=PathRoots(
            verifier_repo=verifier_root,
            business_source=repository.resolve(),
            knowledge_route=route.root,
        ),
        path_resolver=PathResolver(PathRoots(
            verifier_repo=verifier_root,
            business_source=repository.resolve(),
            knowledge_route=route.root,
        )),
    )


def _validate_front_matter(path: Path, document_type: str) -> None:
    text = path.read_text(encoding="utf-8", errors="strict")
    _validate_minimum_contract(path, document_type, text)
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


def _validate_minimum_contract(path: Path, document_type: str, text: str) -> None:
    topics = _DOCUMENT_TOPICS[document_type]
    missing = [name for name, pattern in topics.items() if re.search(pattern, text, re.IGNORECASE) is None]
    if missing:
        raise ConfigError(
            f"knowledge document {path} does not satisfy {document_type} minimum contract; missing: {', '.join(missing)}"
        )


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
