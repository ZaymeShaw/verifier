from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlparse

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
from .schema import ProjectSpec, RoleAssetMapping


PROJECTS_DIR = ROOT / "impl" / "projects"
SUPPORTED_PROJECT_SCHEMA_VERSIONS = {1}
RUNTIME_MODES = {
    "existing_service_required",
    "existing_service_optional",
    "uploaded_output_evaluation",
}
INTERACTION_MODES = {"single_turn", "multi_turn"}
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
READY_VALUES = {"output", "reference"}
EXTRA_TYPES = {"string", "integer", "number", "boolean", "path", "url", "list", "mapping"}
_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")


def resolve_project_config(
    project_id: str,
    *,
    projects_dir: Path = PROJECTS_DIR,
    dotenv_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ProjectSpec:
    project_root = projects_dir / project_id
    config_path = project_root / "project.yaml"
    if not config_path.is_file():
        raise FileNotFoundError(f"project config not found: {config_path}")
    document = load_yaml_document(config_path)
    parsed, registry = parse_project_document(document, project_id=project_id, project_root=project_root)
    resolved = copy.deepcopy(parsed)
    sources = _yaml_sources(resolved)
    values = parse_dotenv(dotenv_path or ROOT / ".env")
    process_environment = os.environ if environ is None else environ
    warnings: list[str] = []
    for variable in registry.variables.values():
        raw_value: str | None = None
        source: ConfigValueSource | None = None
        if variable.name in process_environment:
            raw_value = process_environment[variable.name]
            source = ConfigValueSource("process_environment", variable.name, variable.secret)
        elif variable.name in values:
            raw_value = values[variable.name]
            source = ConfigValueSource("dotenv", variable.name, variable.secret)
        if raw_value is None or raw_value == "":
            if variable.required and not _binding_has_value(resolved, variable.bind):
                warnings.append(f"missing required project value {variable.bind} ({variable.name})")
            continue
        _set_binding(resolved, variable.bind, convert_environment_value(variable, raw_value))
        sources[variable.bind] = source or ConfigValueSource("unknown", variable.name, variable.secret)
    _validate_resolved_paths(resolved, project_root)
    return _build_project_spec(
        resolved,
        project_root=project_root,
        environment=registry,
        sources=MappingProxyType(sources),
        warnings=warnings,
    )


def parse_project_document(
    data: Mapping[str, Any],
    *,
    project_id: str | None,
    project_root: Path,
) -> tuple[dict[str, Any], EnvironmentRegistry]:
    root = _mapping(data, "project config")
    _unknown(root, {"schema_version", "project", "runtime", "verifier", "environment", "metadata"}, "")
    version = _integer(_required(root, "schema_version", ""), "schema_version", minimum=1)
    if version not in SUPPORTED_PROJECT_SCHEMA_VERSIONS:
        raise ConfigError(f"unsupported project schema_version {version}")

    project = _parse_project(_required(root, "project", ""), project_id, project_root)
    runtime = _parse_runtime(_required(root, "runtime", ""))
    verifier = _parse_verifier(_required(root, "verifier", ""), project_root)
    metadata = _parse_metadata(_required(root, "metadata", ""))
    registry = _parse_environment(root["environment"]) if "environment" in root else _empty_registry()
    parsed = {
        "schema_version": version,
        "project": project,
        "runtime": runtime,
        "verifier": verifier,
        "metadata": metadata,
    }
    if registry.variables:
        parsed["environment"] = root["environment"]
    _validate_mode_contract(runtime)
    _validate_environment_bindings(parsed, registry)
    return parsed, registry


def _parse_project(value: Any, expected_id: str | None, project_root: Path) -> dict[str, Any]:
    data = _mapping(value, "project")
    _unknown(data, {"id", "name", "description", "capabilities", "resources", "extra"}, "project")
    project_id = _string(_required(data, "id", "project"), "project.id")
    if expected_id is not None and project_id != expected_id:
        raise ConfigError(f"project.id {project_id!r} must match directory {expected_id!r}")
    capabilities = _string_list(_required(data, "capabilities", "project"), "project.capabilities")
    result: dict[str, Any] = {
        "id": project_id,
        "name": _string(_required(data, "name", "project"), "project.name"),
        "description": _string(_required(data, "description", "project"), "project.description"),
        "capabilities": capabilities,
    }
    resources = data.get("resources")
    if resources is not None:
        result["resources"] = _parse_resources(resources, project_root)
    if "extra" in data:
        result["extra"] = _parse_extra(data["extra"], "project.extra")
    return result


def _parse_resources(value: Any, project_root: Path) -> dict[str, Any]:
    data = _mapping(value, "project.resources")
    _unknown(data, {"source", "documents"}, "project.resources")
    result: dict[str, Any] = {}
    if "source" in data:
        source = _mapping(data["source"], "project.resources.source")
        _unknown(source, {"repository", "paths"}, "project.resources.source")
        repository = source.get("repository", "")
        if not isinstance(repository, str):
            raise ConfigError("invalid field project.resources.source.repository: expected string")
        parsed_source: dict[str, Any] = {"repository": repository}
        if "paths" in source:
            paths = _mapping(source["paths"], "project.resources.source.paths")
            parsed_paths: dict[str, str] = {}
            for key, raw_path in paths.items():
                _snake_id(key, f"project.resources.source.paths.{key}")
                parsed_paths[key] = _relative_path(raw_path, f"project.resources.source.paths.{key}")
            parsed_source["paths"] = parsed_paths
        result["source"] = parsed_source
    if "documents" in data:
        documents = _mapping(data["documents"], "project.resources.documents")
        parsed_documents: dict[str, str] = {}
        for key, raw_path in documents.items():
            _snake_id(key, f"project.resources.documents.{key}")
            relative = _relative_path(raw_path, f"project.resources.documents.{key}")
            target = (project_root / relative).resolve()
            if not target.is_relative_to(project_root.resolve()):
                raise ConfigError(f"project.resources.documents.{key} escapes project directory")
            if not target.is_file():
                raise ConfigError(f"project document not found: {target}")
            parsed_documents[key] = relative
        result["documents"] = parsed_documents
    return result


def _parse_runtime(value: Any) -> dict[str, Any]:
    data = _mapping(value, "runtime")
    _unknown(data, {"mode", "local_deployment", "interaction", "ready", "services", "extra"}, "runtime")
    mode = _choice(_required(data, "mode", "runtime"), "runtime.mode", RUNTIME_MODES)
    interaction_data = _mapping(_required(data, "interaction", "runtime"), "runtime.interaction")
    _unknown(interaction_data, {"mode"}, "runtime.interaction")
    interaction = {
        "mode": _choice(
            _required(interaction_data, "mode", "runtime.interaction"),
            "runtime.interaction.mode",
            INTERACTION_MODES,
        )
    }
    ready = _string_list(_required(data, "ready", "runtime"), "runtime.ready")
    unknown_ready = sorted(set(ready) - READY_VALUES)
    if unknown_ready:
        raise ConfigError(f"invalid field runtime.ready: unsupported value {unknown_ready[0]!r}")
    result: dict[str, Any] = {"mode": mode, "interaction": interaction, "ready": ready}
    if "local_deployment" in data:
        local = _mapping(data["local_deployment"], "runtime.local_deployment")
        _unknown(local, {"enabled"}, "runtime.local_deployment")
        result["local_deployment"] = {
            "enabled": _boolean(_required(local, "enabled", "runtime.local_deployment"), "runtime.local_deployment.enabled")
        }
    if "services" in data:
        result["services"] = _parse_services(data["services"])
    if "extra" in data:
        result["extra"] = _parse_extra(data["extra"], "runtime.extra")
    return result


def _parse_services(value: Any) -> dict[str, Any]:
    data = _mapping(value, "runtime.services")
    _unknown(data, {"primary", "dependencies"}, "runtime.services")
    result: dict[str, Any] = {}
    if "primary" in data:
        result["primary"] = _parse_service(data["primary"], "runtime.services.primary")
    if "dependencies" in data:
        dependencies = _mapping(data["dependencies"], "runtime.services.dependencies")
        parsed: dict[str, Any] = {}
        for service_id, service in dependencies.items():
            _snake_id(service_id, f"runtime.services.dependencies.{service_id}")
            parsed[service_id] = _parse_service(service, f"runtime.services.dependencies.{service_id}")
        result["dependencies"] = parsed
    return result


def _parse_service(value: Any, path: str) -> dict[str, Any]:
    data = _mapping(value, path)
    _unknown(data, {"base_url", "endpoint", "method", "timeout_seconds", "enabled", "healthcheck"}, path)
    result = {
        "base_url": _url(_required(data, "base_url", path), f"{path}.base_url"),
        "endpoint": _endpoint(_required(data, "endpoint", path), f"{path}.endpoint"),
        "method": _choice(_required(data, "method", path), f"{path}.method", HTTP_METHODS),
        "timeout_seconds": _number(_required(data, "timeout_seconds", path), f"{path}.timeout_seconds", minimum=0.001),
    }
    if "enabled" in data:
        result["enabled"] = _boolean(data["enabled"], f"{path}.enabled")
    if "healthcheck" in data:
        health = _mapping(data["healthcheck"], f"{path}.healthcheck")
        _unknown(
            health,
            {"endpoint", "request_timeout_seconds", "interval_seconds", "startup_timeout_seconds"},
            f"{path}.healthcheck",
        )
        result["healthcheck"] = {
            "endpoint": _endpoint(_required(health, "endpoint", f"{path}.healthcheck"), f"{path}.healthcheck.endpoint"),
            "request_timeout_seconds": _number(_required(health, "request_timeout_seconds", f"{path}.healthcheck"), f"{path}.healthcheck.request_timeout_seconds", minimum=0.001),
            "interval_seconds": _number(_required(health, "interval_seconds", f"{path}.healthcheck"), f"{path}.healthcheck.interval_seconds", minimum=0.001),
            "startup_timeout_seconds": _number(_required(health, "startup_timeout_seconds", f"{path}.healthcheck"), f"{path}.healthcheck.startup_timeout_seconds", minimum=0.001),
        }
    return result


def _parse_verifier(value: Any, project_root: Path) -> dict[str, Any]:
    data = _mapping(value, "verifier")
    _unknown(data, {"attribution", "field_provider", "endpoint_discovery", "roles", "assets", "presentation", "extra"}, "verifier")
    attribution = _mapping(_required(data, "attribution", "verifier"), "verifier.attribution")
    _unknown(attribution, {"enabled"}, "verifier.attribution")
    result: dict[str, Any] = {
        "attribution": {
            "enabled": _boolean(_required(attribution, "enabled", "verifier.attribution"), "verifier.attribution.enabled")
        }
    }
    if "field_provider" in data:
        provider = _mapping(data["field_provider"], "verifier.field_provider")
        _unknown(provider, {"module", "class"}, "verifier.field_provider")
        result["field_provider"] = {
            "module": _relative_path(_required(provider, "module", "verifier.field_provider"), "verifier.field_provider.module"),
            "class": _string(_required(provider, "class", "verifier.field_provider"), "verifier.field_provider.class"),
        }
    if "endpoint_discovery" in data:
        result["endpoint_discovery"] = _parse_endpoint_discovery(data["endpoint_discovery"])
    if "roles" in data:
        result["roles"] = _parse_roles(data["roles"])
    if "assets" in data:
        result["assets"] = _parse_assets(data["assets"])
    if "presentation" in data:
        result["presentation"] = _parse_presentation(data["presentation"])
    if "extra" in data:
        result["extra"] = _parse_extra(data["extra"], "verifier.extra")
    return result


def _parse_endpoint_discovery(value: Any) -> dict[str, Any]:
    path = "verifier.endpoint_discovery"
    data = _mapping(value, path)
    _unknown(data, {"enabled", "framework", "source_roots", "route_prefix", "scan_patterns", "exclude_patterns", "blacklist"}, path)
    result = {
        "enabled": _boolean(_required(data, "enabled", path), f"{path}.enabled"),
        "framework": _choice(_required(data, "framework", path), f"{path}.framework", {"fastapi", "flask", "grpc", "generic"}),
        "source_roots": [_relative_path(item, f"{path}.source_roots") for item in _string_list(_required(data, "source_roots", path), f"{path}.source_roots")],
    }
    for key in ("scan_patterns", "exclude_patterns"):
        if key in data:
            result[key] = _string_list(data[key], f"{path}.{key}")
    if "route_prefix" in data:
        result["route_prefix"] = _endpoint(data["route_prefix"], f"{path}.route_prefix")
    if "blacklist" in data:
        blacklist = _mapping(data["blacklist"], f"{path}.blacklist")
        _unknown(blacklist, {"methods", "route_keywords"}, f"{path}.blacklist")
        result["blacklist"] = {
            "methods": _string_list(blacklist.get("methods", []), f"{path}.blacklist.methods"),
            "route_keywords": _string_list(blacklist.get("route_keywords", []), f"{path}.blacklist.route_keywords"),
        }
    return result


def _parse_roles(value: Any) -> dict[str, Any]:
    data = _mapping(value, "verifier.roles")
    result: dict[str, Any] = {}
    for role, raw_role in data.items():
        _snake_id(role, f"verifier.roles.{role}")
        role_data = _mapping(raw_role, f"verifier.roles.{role}")
        _unknown(role_data, {"draft"}, f"verifier.roles.{role}")
        draft = _mapping(_required(role_data, "draft", f"verifier.roles.{role}"), f"verifier.roles.{role}.draft")
        _unknown(draft, {"enabled", "module", "reason"}, f"verifier.roles.{role}.draft")
        parsed = {
            "enabled": _boolean(_required(draft, "enabled", f"verifier.roles.{role}.draft"), f"verifier.roles.{role}.draft.enabled"),
            "module": _relative_path(_required(draft, "module", f"verifier.roles.{role}.draft"), f"verifier.roles.{role}.draft.module"),
        }
        if "reason" in draft:
            parsed["reason"] = _string(draft["reason"], f"verifier.roles.{role}.draft.reason")
        if not parsed["module"].startswith("draft/"):
            raise ConfigError(f"verifier.roles.{role}.draft.module must stay under draft/")
        result[role] = {"draft": parsed}
    return result


def _parse_assets(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ConfigError("invalid field verifier.assets: expected list")
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, raw_asset in enumerate(value):
        path = f"verifier.assets[{index}]"
        asset = _mapping(raw_asset, path)
        _unknown(asset, {"asset_id", "kind", "enabled", "roles", "production_path", "candidate_path", "replace"}, path)
        asset_id = _string(_required(asset, "asset_id", path), f"{path}.asset_id")
        _snake_id(asset_id, f"{path}.asset_id")
        if asset_id in ids:
            raise ConfigError(f"duplicate verifier asset_id {asset_id!r}")
        ids.add(asset_id)
        parsed = {
            "asset_id": asset_id,
            "kind": _choice(_required(asset, "kind", path), f"{path}.kind", {"tool", "context", "context_builder", "investigation", "other"}),
            "enabled": _boolean(_required(asset, "enabled", path), f"{path}.enabled"),
            "roles": _string_list(_required(asset, "roles", path), f"{path}.roles"),
            "production_path": _relative_path(_required(asset, "production_path", path), f"{path}.production_path"),
        }
        if "candidate_path" in asset:
            parsed["candidate_path"] = _relative_path(asset["candidate_path"], f"{path}.candidate_path")
        if "replace" in asset:
            parsed["replace"] = _boolean(asset["replace"], f"{path}.replace")
        result.append(parsed)
    return result


_PRESENTATION_FIELDS = {
    "scenarios",
    "interactive_scenarios",
    "stages",
    "dimensions",
    "path_types",
    "intent_labels",
    "intent_descriptions",
    "score_dimensions",
    "error_taxonomy",
    "core_forbidden_markers",
    "event_aliases",
    "terminal_events",
    "extra",
}


def _parse_presentation(value: Any) -> dict[str, Any]:
    data = _mapping(value, "verifier.presentation")
    _unknown(data, _PRESENTATION_FIELDS, "verifier.presentation")
    result: dict[str, Any] = {}
    list_fields = _PRESENTATION_FIELDS - {"intent_descriptions", "event_aliases", "extra"}
    for key in list_fields:
        if key in data:
            result[key] = _string_list(data[key], f"verifier.presentation.{key}")
    for key in ("intent_descriptions", "event_aliases"):
        if key in data:
            result[key] = _mapping(data[key], f"verifier.presentation.{key}")
    if "extra" in data:
        result["extra"] = _parse_extra(data["extra"], "verifier.presentation.extra")
    return result


def _parse_extra(value: Any, path: str) -> dict[str, Any]:
    data = _mapping(value, path)
    result: dict[str, Any] = {}
    for field_id, raw_item in data.items():
        _snake_id(field_id, f"{path}.{field_id}")
        item_path = f"{path}.{field_id}"
        item = _mapping(raw_item, item_path)
        _unknown(item, {"description", "value_type", "schema_version", "consumers", "value"}, item_path)
        value_type = _choice(_required(item, "value_type", item_path), f"{item_path}.value_type", EXTRA_TYPES)
        consumers = _string_list(_required(item, "consumers", item_path), f"{item_path}.consumers")
        if not consumers:
            raise ConfigError(f"invalid field {item_path}.consumers: expected non-empty list")
        raw_value = _required(item, "value", item_path)
        _validate_extra_value(raw_value, value_type, f"{item_path}.value")
        result[field_id] = {
            "description": _string(_required(item, "description", item_path), f"{item_path}.description"),
            "value_type": value_type,
            "schema_version": _integer(_required(item, "schema_version", item_path), f"{item_path}.schema_version", minimum=1),
            "consumers": consumers,
            "value": raw_value,
        }
    return result


def _parse_metadata(value: Any) -> dict[str, Any]:
    data = _mapping(value, "metadata")
    _unknown(data, {"initialized_from", "source_revision"}, "metadata")
    initialized_from = _relative_path(_required(data, "initialized_from", "metadata"), "metadata.initialized_from", allow_parent=True)
    revision = data.get("source_revision")
    if revision is not None and not isinstance(revision, str):
        raise ConfigError("invalid field metadata.source_revision: expected string or null")
    return {"initialized_from": initialized_from, "source_revision": revision}


def _validate_mode_contract(runtime: Mapping[str, Any]) -> None:
    mode = runtime["mode"]
    services = runtime.get("services") or {}
    local = (runtime.get("local_deployment") or {}).get("enabled") is True
    primary = services.get("primary") or {}
    if mode == "uploaded_output_evaluation":
        if services:
            raise ConfigError("runtime.services is forbidden for uploaded_output_evaluation")
        if local:
            raise ConfigError("runtime.local_deployment cannot be enabled for uploaded_output_evaluation")
        if "output" not in runtime["ready"]:
            raise ConfigError("uploaded_output_evaluation requires runtime.ready to include output")
        return
    if mode == "existing_service_required" and not primary:
        raise ConfigError("existing_service_required requires runtime.services.primary")
    if local and not primary.get("healthcheck"):
        raise ConfigError("local deployment requires runtime.services.primary.healthcheck")


def _validate_environment_bindings(document: Mapping[str, Any], registry: EnvironmentRegistry) -> None:
    seen: set[str] = set()
    for variable in registry.variables.values():
        if variable.bind.startswith("environment.") or variable.bind.startswith("metadata."):
            raise ConfigError(f"invalid project environment bind target: {variable.bind}")
        if variable.bind in seen:
            raise ConfigError(f"multiple environment variables bind the same project field: {variable.bind}")
        seen.add(variable.bind)
        if not _binding_exists(document, variable.bind):
            raise ConfigError(f"invalid project environment bind target for {variable.name}: {variable.bind}")


def _validate_resolved_paths(document: Mapping[str, Any], project_root: Path) -> None:
    repository = str((((document.get("project") or {}).get("resources") or {}).get("source") or {}).get("repository") or "")
    if repository:
        path = Path(repository)
        if not path.is_absolute():
            raise ConfigError("project.resources.source.repository must resolve to an absolute path")
    local = (((document.get("runtime") or {}).get("local_deployment") or {}).get("enabled") is True)
    if local:
        start_script = project_root / "scripts" / "start.sh"
        if not start_script.is_file():
            raise ConfigError(f"local deployment start script not found: {start_script}")
        if start_script.stat().st_mode & 0o111 == 0:
            raise ConfigError(f"local deployment start script is not executable: {start_script}")


def _build_project_spec(
    data: Mapping[str, Any],
    *,
    project_root: Path,
    environment: EnvironmentRegistry,
    sources: Mapping[str, ConfigValueSource],
    warnings: list[str],
) -> ProjectSpec:
    project = dict(data["project"])
    runtime = dict(data["runtime"])
    verifier = dict(data["verifier"])
    resources = project.get("resources") or {}
    source = resources.get("source") or {}
    documents = dict(resources.get("documents") or {})
    primary = dict((runtime.get("services") or {}).get("primary") or {})
    api = {
        key: value
        for key, value in {
            "base_url": primary.get("base_url"),
            "endpoint": primary.get("endpoint"),
            "method": primary.get("method"),
            "timeout": primary.get("timeout_seconds"),
        }.items()
        if value is not None
    }
    dependencies = (runtime.get("services") or {}).get("dependencies") or {}
    application = {
        "mode": runtime.get("mode"),
        "external_repo": source.get("repository") or "",
    }
    if dependencies:
        application.update(dependencies)
    presentation = _flatten_extra(dict(verifier.get("presentation") or {}))
    presentation.update(_flatten_extra(dict(verifier.get("extra") or {})))
    field_provider = verifier.get("field_provider") or {}
    roles = verifier.get("roles") or {}
    assets = [
        RoleAssetMapping(
            asset_id=item["asset_id"],
            kind=item["kind"],
            enabled=item["enabled"],
            roles=list(item["roles"]),
            production_path=item["production_path"],
            candidate_path=str(item.get("candidate_path") or ""),
            replace=item.get("replace") is True,
        )
        for item in verifier.get("assets") or []
    ]
    ready = list(runtime.get("ready") or [])
    mock_cases = _extra_value(runtime.get("extra") or {}, "mock_cases")
    common = {"ready": ready}
    if mock_cases is not None:
        common["mock_cases"] = mock_cases
    source_repository = str(source.get("repository") or "")
    return ProjectSpec(
        project_id=project["id"],
        name=project["name"],
        description=project["description"],
        capabilities=list(project.get("capabilities") or []),
        common=common,
        documents=documents,
        api=api,
        application=application,
        frontend_extensions=presentation,
        endpoint_discovery=dict(verifier.get("endpoint_discovery") or {}),
        attribute_draft=dict((roles.get("attribute") or {}).get("draft") or {}),
        judge_draft=dict((roles.get("judge") or {}).get("draft") or {}),
        mock_draft=dict((roles.get("mock") or {}).get("draft") or {}),
        live_draft=dict((roles.get("live") or {}).get("draft") or {}),
        role_assets=assets,
        field_provider_module=str(field_provider.get("module") or ""),
        field_provider_class=str(field_provider.get("class") or ""),
        root=str(project_root),
        source_project=source_repository,
        schema_version=int(data["schema_version"]),
        project=project,
        runtime=runtime,
        verifier=verifier,
        environment=environment,
        metadata={**dict(data["metadata"]), "warnings": warnings},
        config_sources=sources,
    )


def _flatten_extra(data: dict[str, Any]) -> dict[str, Any]:
    extra = data.pop("extra", {}) or {}
    for key, item in extra.items():
        data[key] = item.get("value") if isinstance(item, dict) else item
    return data


def _extra_value(data: Mapping[str, Any], key: str) -> Any:
    item = data.get(key)
    return item.get("value") if isinstance(item, dict) else None


def _yaml_sources(value: Any, prefix: str = "") -> dict[str, ConfigValueSource]:
    result: dict[str, ConfigValueSource] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            result.update(_yaml_sources(item, path))
    elif isinstance(value, list):
        result[prefix] = ConfigValueSource("project_yaml", prefix)
    else:
        result[prefix] = ConfigValueSource("project_yaml", prefix)
    return result


def _empty_registry() -> EnvironmentRegistry:
    return EnvironmentRegistry(variables=MappingProxyType({}))


def _set_binding(document: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    target: dict[str, Any] = document
    for part in parts[:-1]:
        child = target.get(part)
        if not isinstance(child, dict):
            raise ConfigError(f"invalid bind target {path}")
        target = child
    if parts[-1] not in target:
        raise ConfigError(f"invalid bind target {path}")
    target[parts[-1]] = value


def _binding_exists(document: Mapping[str, Any], path: str) -> bool:
    target: Any = document
    for part in path.split("."):
        if not isinstance(target, Mapping) or part not in target:
            return False
        target = target[part]
    return True


def _binding_has_value(document: Mapping[str, Any], path: str) -> bool:
    target: Any = document
    for part in path.split("."):
        if not isinstance(target, Mapping) or part not in target:
            return False
        target = target[part]
    return target not in (None, "", [], {})


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
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"invalid field {path}: expected non-empty string")
    return value.strip()


def _integer(value: Any, path: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigError(f"invalid field {path}: expected integer >= {minimum}")
    return value


def _number(value: Any, path: str, *, minimum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < minimum:
        raise ConfigError(f"invalid field {path}: expected number >= {minimum}")
    return float(value)


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
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ConfigError(f"invalid field {path}: expected list of non-empty strings")
    result = [item.strip() for item in value]
    if len(result) != len(set(result)):
        raise ConfigError(f"invalid field {path}: duplicate values")
    return result


def _url(value: Any, path: str) -> str:
    text = _string(value, path)
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"invalid field {path}: expected http(s) URL")
    return text.rstrip("/")


def _endpoint(value: Any, path: str) -> str:
    text = _string(value, path)
    if not text.startswith("/"):
        raise ConfigError(f"invalid field {path}: endpoint must start with /")
    return text


def _relative_path(value: Any, path: str, *, allow_parent: bool = False) -> str:
    text = _string(value, path)
    candidate = Path(text)
    if candidate.is_absolute() or (not allow_parent and ".." in candidate.parts):
        raise ConfigError(f"invalid field {path}: expected portable relative path")
    return candidate.as_posix()


def _snake_id(value: Any, path: str) -> str:
    text = _string(value, path)
    if not _SNAKE_CASE.fullmatch(text):
        raise ConfigError(f"invalid field {path}: expected snake_case id")
    return text


def _validate_extra_value(value: Any, value_type: str, path: str) -> None:
    checks = {
        "string": lambda item: isinstance(item, str),
        "path": lambda item: isinstance(item, str),
        "url": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "list": lambda item: isinstance(item, list),
        "mapping": lambda item: isinstance(item, dict),
    }
    if not checks[value_type](value):
        raise ConfigError(f"invalid field {path}: expected {value_type}")
