from __future__ import annotations

import copy
import ast
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
from .path_contract import (
    PathContractError,
    PathResolver,
    PathRoots,
    PathScope,
    PrefixedPath,
    canonical_prefixed_path,
    parse_prefixed_path,
)
from .schema import ProjectSpec


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
    require_values: bool = False,
    verifier_root: Path | None = None,
) -> ProjectSpec:
    projects_dir = Path(projects_dir).resolve()
    resolved_verifier_root = Path(verifier_root or ROOT).resolve()
    project_root = projects_dir / project_id
    config_path = project_root / "project.yaml"
    if not config_path.is_file():
        raise FileNotFoundError(f"project config not found: {config_path}")
    document = load_yaml_document(config_path)
    warnings: list[str] = []
    parsed, registry = parse_project_document(
        document,
        project_id=project_id,
        project_root=project_root,
        path_warnings=warnings,
    )
    resolved = copy.deepcopy(parsed)
    sources = _yaml_sources(resolved)
    values = parse_dotenv(dotenv_path or resolved_verifier_root / ".env")
    process_environment = os.environ if environ is None else environ
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
    source_repository = str(
        ((((resolved.get("project") or {}).get("resources") or {}).get("source") or {}).get("repository") or "")
    )
    path_roots = PathRoots(
        verifier_repo=resolved_verifier_root,
        business_source=Path(source_repository) if source_repository else None,
        project_package=project_root,
        knowledge_route=resolved_verifier_root / "projects" / project_id,
    )
    path_resolver = PathResolver(path_roots)
    _validate_resolved_paths(resolved, path_resolver)
    spec = _build_project_spec(
        resolved,
        project_root=project_root,
        environment=registry,
        sources=MappingProxyType(sources),
        warnings=warnings,
        path_roots=path_roots,
        path_resolver=path_resolver,
        missing_required=tuple(sorted(
            variable.bind
            for variable in registry.variables.values()
            if variable.required and not _binding_has_value(resolved, variable.bind)
        )),
    )
    if require_values:
        spec.require()
    return spec


def parse_project_document(
    data: Mapping[str, Any],
    *,
    project_id: str | None,
    project_root: Path,
    path_warnings: list[str] | None = None,
) -> tuple[dict[str, Any], EnvironmentRegistry]:
    root = _mapping(data, "project config")
    _unknown(root, {"schema_version", "project", "runtime", "verifier", "environment", "metadata"}, "")
    version = _integer(_required(root, "schema_version", ""), "schema_version", minimum=1)
    if version not in SUPPORTED_PROJECT_SCHEMA_VERSIONS:
        raise ConfigError(f"unsupported project schema_version {version}")

    warnings = path_warnings if path_warnings is not None else []
    project = _parse_project(_required(root, "project", ""), project_id, project_root, warnings)
    runtime = _parse_runtime(_required(root, "runtime", ""))
    verifier = _parse_verifier(_required(root, "verifier", ""), project_root, warnings)
    metadata = _parse_metadata(_required(root, "metadata", ""), warnings)
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
    _validate_project_contract(parsed, registry)
    _validate_extra_schemas(parsed, project_root)
    return parsed, registry


def _parse_project(
    value: Any,
    expected_id: str | None,
    project_root: Path,
    path_warnings: list[str],
) -> dict[str, Any]:
    data = _mapping(value, "project")
    _unknown(data, {"id", "name", "description", "capabilities", "resources", "taxonomies", "extra"}, "project")
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
        result["resources"] = _parse_resources(resources, project_root, path_warnings)
    if "taxonomies" in data:
        result["taxonomies"] = _parse_taxonomies(data["taxonomies"])
    if "extra" in data:
        result["extra"] = _parse_extra(data["extra"], "project.extra")
    return result


def _parse_taxonomies(value: Any) -> dict[str, Any]:
    data = _mapping(value, "project.taxonomies")
    _unknown(data, {"intent"}, "project.taxonomies")
    result: dict[str, Any] = {}
    if "intent" in data:
        intent = _mapping(data["intent"], "project.taxonomies.intent")
        _unknown(intent, {"labels", "descriptions"}, "project.taxonomies.intent")
        labels = _string_list(
            _required(intent, "labels", "project.taxonomies.intent"),
            "project.taxonomies.intent.labels",
        )
        descriptions: dict[str, str] = {}
        if "descriptions" in intent:
            raw_descriptions = _mapping(
                intent["descriptions"],
                "project.taxonomies.intent.descriptions",
            )
            descriptions = {
                _string(key, f"project.taxonomies.intent.descriptions.{key}"): _string(
                    description,
                    f"project.taxonomies.intent.descriptions.{key}",
                )
                for key, description in raw_descriptions.items()
            }
        result["intent"] = {"labels": labels, "descriptions": descriptions}
    return result


def _parse_resources(value: Any, project_root: Path, path_warnings: list[str]) -> dict[str, Any]:
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
                parsed_paths[key] = _prefixed_path(
                    raw_path,
                    f"project.resources.source.paths.{key}",
                    allowed_scopes={PathScope.BUSINESS_SOURCE},
                )
            parsed_source["paths"] = parsed_paths
        result["source"] = parsed_source
    if "documents" in data:
        documents = _mapping(data["documents"], "project.resources.documents")
        parsed_documents: dict[str, str] = {}
        for key, raw_path in documents.items():
            _snake_id(key, f"project.resources.documents.{key}")
            prefixed = _prefixed_path(
                raw_path,
                f"project.resources.documents.{key}",
                allowed_scopes={PathScope.PROJECT_PACKAGE},
            )
            _resolve_config_path(
                prefixed,
                field_path=f"project.resources.documents.{key}",
                roots=PathRoots(project_package=project_root),
                allowed_scopes={PathScope.PROJECT_PACKAGE},
                expected_type="file",
            )
            parsed_documents[key] = prefixed
        result["documents"] = parsed_documents
    return result


def _parse_runtime(value: Any) -> dict[str, Any]:
    data = _mapping(value, "runtime")
    _unknown(data, {"mode", "application", "local_deployment", "interaction", "ready", "services", "mock_cases", "adapter", "batch_persistence", "extra"}, "runtime")
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
    if "application" in data:
        result["application"] = _parse_application_contract(data["application"])
    if "local_deployment" in data:
        local = _mapping(data["local_deployment"], "runtime.local_deployment")
        _unknown(local, {"enabled"}, "runtime.local_deployment")
        result["local_deployment"] = {
            "enabled": _boolean(_required(local, "enabled", "runtime.local_deployment"), "runtime.local_deployment.enabled")
        }
    if "services" in data:
        result["services"] = _parse_services(data["services"])
    if "mock_cases" in data:
        mock_cases = _mapping(data["mock_cases"], "runtime.mock_cases")
        _unknown(mock_cases, {"source", "default_scenarios"}, "runtime.mock_cases")
        result["mock_cases"] = {
            "source": _choice(
                _required(mock_cases, "source", "runtime.mock_cases"),
                "runtime.mock_cases.source",
                {"fixture", "dynamic"},
            )
        }
        if "default_scenarios" in mock_cases:
            result["mock_cases"]["default_scenarios"] = _string_list(
                mock_cases["default_scenarios"],
                "runtime.mock_cases.default_scenarios",
            )
    if "adapter" in data:
        result["adapter"] = _parse_adapter_contract(data["adapter"])
    if "batch_persistence" in data:
        result["batch_persistence"] = _parse_batch_persistence(data["batch_persistence"])
    if "extra" in data:
        result["extra"] = _parse_extra(data["extra"], "runtime.extra")
    return result


def _parse_application_contract(value: Any) -> dict[str, Any]:
    path = "runtime.application"
    data = _mapping(value, path)
    _unknown(data, {"interface", "start_run", "boundary"}, path)
    interface_path = f"{path}.interface"
    interface = _mapping(_required(data, "interface", path), interface_path)
    _unknown(interface, {"shape", "source"}, interface_path)
    return {
        "interface": {
            "shape": _string(_required(interface, "shape", interface_path), f"{interface_path}.shape"),
            "source": _string(_required(interface, "source", interface_path), f"{interface_path}.source"),
        },
        "start_run": _string(_required(data, "start_run", path), f"{path}.start_run"),
        "boundary": _string(_required(data, "boundary", path), f"{path}.boundary"),
    }


def _parse_adapter_contract(value: Any) -> dict[str, Any]:
    path = "runtime.adapter"
    data = _mapping(value, path)
    _unknown(data, {"request_construction", "output_extraction", "reference_handling"}, path)

    request_path = f"{path}.request_construction"
    request = _mapping(_required(data, "request_construction", path), request_path)
    _unknown(request, {"builder", "required_inputs"}, request_path)

    output_path = f"{path}.output_extraction"
    output = _mapping(_required(data, "output_extraction", path), output_path)
    _unknown(output, {"extractor", "normalized_output"}, output_path)

    reference_path = f"{path}.reference_handling"
    reference = _mapping(_required(data, "reference_handling", path), reference_path)
    _unknown(reference, {"source_priority", "alignment"}, reference_path)

    return {
        "request_construction": {
            "builder": _string(_required(request, "builder", request_path), f"{request_path}.builder"),
            "required_inputs": _string_list(
                _required(request, "required_inputs", request_path),
                f"{request_path}.required_inputs",
            ),
        },
        "output_extraction": {
            "extractor": _string(_required(output, "extractor", output_path), f"{output_path}.extractor"),
            "normalized_output": _string(
                _required(output, "normalized_output", output_path),
                f"{output_path}.normalized_output",
            ),
        },
        "reference_handling": {
            "source_priority": _string_list(
                _required(reference, "source_priority", reference_path),
                f"{reference_path}.source_priority",
            ),
            "alignment": _string(
                _required(reference, "alignment", reference_path),
                f"{reference_path}.alignment",
            ),
        },
    }


def _parse_batch_persistence(value: Any) -> dict[str, str]:
    path = "runtime.batch_persistence"
    data = _mapping(value, path)
    _unknown(data, {"case_shape", "transient_results"}, path)
    return {
        "case_shape": _string(_required(data, "case_shape", path), f"{path}.case_shape"),
        "transient_results": _string(
            _required(data, "transient_results", path),
            f"{path}.transient_results",
        ),
    }


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
    _unknown(data, {"base_url", "endpoint", "method", "timeout_seconds", "enabled", "healthcheck", "stream"}, path)
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
    if "stream" in data:
        stream_path = f"{path}.stream"
        stream = _mapping(data["stream"], stream_path)
        _unknown(stream, {"event_aliases", "terminal_events"}, stream_path)
        aliases = _mapping(
            _required(stream, "event_aliases", stream_path),
            f"{stream_path}.event_aliases",
        )
        parsed_aliases: dict[str, list[str]] = {}
        for canonical_name, raw_names in aliases.items():
            _snake_id(canonical_name, f"{stream_path}.event_aliases.{canonical_name}")
            parsed_aliases[canonical_name] = _string_list(
                raw_names,
                f"{stream_path}.event_aliases.{canonical_name}",
            )
        result["stream"] = {
            "event_aliases": parsed_aliases,
            "terminal_events": _string_list(
                _required(stream, "terminal_events", stream_path),
                f"{stream_path}.terminal_events",
            ),
        }
    return result


def _parse_verifier(value: Any, project_root: Path, path_warnings: list[str]) -> dict[str, Any]:
    data = _mapping(value, "verifier")
    _unknown(data, {"attribution", "field_provider", "endpoint_discovery", "roles", "assets", "scenarios", "judge", "presentation", "check_rules", "extra"}, "verifier")
    attribution = _mapping(_required(data, "attribution", "verifier"), "verifier.attribution")
    _unknown(attribution, {"enabled", "trace"}, "verifier.attribution")
    result: dict[str, Any] = {
        "attribution": {
            "enabled": _boolean(_required(attribution, "enabled", "verifier.attribution"), "verifier.attribution.enabled")
        }
    }
    if "trace" in attribution:
        trace_path = "verifier.attribution.trace"
        trace = _mapping(attribution["trace"], trace_path)
        _unknown(trace, {"document", "trace_nodes"}, trace_path)
        result["attribution"]["trace"] = {
            "document": _string(_required(trace, "document", trace_path), f"{trace_path}.document"),
            "trace_nodes": _string_list(
                _required(trace, "trace_nodes", trace_path),
                f"{trace_path}.trace_nodes",
            ),
        }
    if "field_provider" in data:
        provider = _mapping(data["field_provider"], "verifier.field_provider")
        _unknown(provider, {"module", "class"}, "verifier.field_provider")
        result["field_provider"] = {
            "module": _prefixed_path(
                _required(provider, "module", "verifier.field_provider"),
                "verifier.field_provider.module",
                allowed_scopes={PathScope.PROJECT_PACKAGE},
            ),
            "class": _string(_required(provider, "class", "verifier.field_provider"), "verifier.field_provider.class"),
        }
    if "endpoint_discovery" in data:
        result["endpoint_discovery"] = _parse_endpoint_discovery(data["endpoint_discovery"], path_warnings)
    if "roles" in data:
        result["roles"] = _parse_roles(data["roles"], path_warnings)
    if "assets" in data:
        result["assets"] = _parse_assets(data["assets"], path_warnings)
    if "scenarios" in data:
        result["scenarios"] = _parse_scenarios(data["scenarios"])
    if "judge" in data:
        result["judge"] = _parse_judge(data["judge"])
    if "presentation" in data:
        result["presentation"] = _parse_presentation(data["presentation"])
    if "check_rules" in data:
        result["check_rules"] = _parse_check_rules(data["check_rules"])
    if "extra" in data:
        result["extra"] = _parse_extra(data["extra"], "verifier.extra")
    return result


def _parse_check_rules(value: Any) -> dict[str, Any]:
    path = "verifier.check_rules"
    data = _mapping(value, path)
    _unknown(data, {"require_scenario", "scenario_requirements", "core_forbidden_markers", "evidence"}, path)
    result: dict[str, Any] = {}
    if "require_scenario" in data:
        result["require_scenario"] = _boolean(data["require_scenario"], f"{path}.require_scenario")
    if "scenario_requirements" in data:
        requirements = _mapping(data["scenario_requirements"], f"{path}.scenario_requirements")
        parsed: dict[str, Any] = {}
        for scenario, raw_requirement in requirements.items():
            _snake_id(scenario, f"{path}.scenario_requirements.{scenario}")
            requirement = _mapping(raw_requirement, f"{path}.scenario_requirements.{scenario}")
            _unknown(
                requirement,
                {"reference_field", "input_field", "data_quality_flag"},
                f"{path}.scenario_requirements.{scenario}",
            )
            parsed[scenario] = {
                key: _string(item, f"{path}.scenario_requirements.{scenario}.{key}")
                for key, item in requirement.items()
            }
        result["scenario_requirements"] = parsed
    if "core_forbidden_markers" in data:
        result["core_forbidden_markers"] = _string_list(
            data["core_forbidden_markers"],
            f"{path}.core_forbidden_markers",
        )
    if "evidence" in data:
        evidence_path = f"{path}.evidence"
        evidence = _mapping(data["evidence"], evidence_path)
        _unknown(evidence, {"documents", "tests"}, evidence_path)
        result["evidence"] = {
            "documents": _string_list(
                _required(evidence, "documents", evidence_path),
                f"{evidence_path}.documents",
            ),
            "tests": _string_list(
                _required(evidence, "tests", evidence_path),
                f"{evidence_path}.tests",
            ),
        }
    return result


def _parse_scenarios(value: Any) -> dict[str, Any]:
    path = "verifier.scenarios"
    data = _mapping(value, path)
    _unknown(data, {"allowed", "interactive"}, path)
    result = {
        "allowed": _string_list(_required(data, "allowed", path), f"{path}.allowed"),
    }
    if "interactive" in data:
        result["interactive"] = _string_list(data["interactive"], f"{path}.interactive")
    return result


def _parse_judge(value: Any) -> dict[str, Any]:
    path = "verifier.judge"
    data = _mapping(value, path)
    _unknown(data, {"score_dimensions", "error_taxonomy", "boundary"}, path)
    result: dict[str, Any] = {}
    if "score_dimensions" in data:
        result["score_dimensions"] = _string_list(
            data["score_dimensions"],
            f"{path}.score_dimensions",
        )
    if "error_taxonomy" in data:
        result["error_taxonomy"] = _string_list(
            data["error_taxonomy"],
            f"{path}.error_taxonomy",
        )
    if "boundary" in data:
        boundary_path = f"{path}.boundary"
        boundary = _mapping(data["boundary"], boundary_path)
        _unknown(boundary, {"document", "gate"}, boundary_path)
        result["boundary"] = {
            "document": _string(_required(boundary, "document", boundary_path), f"{boundary_path}.document"),
            "gate": _string(_required(boundary, "gate", boundary_path), f"{boundary_path}.gate"),
        }
    if not result:
        raise ConfigError(f"invalid field {path}: expected at least one judge contract field")
    return result


def _parse_endpoint_discovery(value: Any, path_warnings: list[str]) -> dict[str, Any]:
    path = "verifier.endpoint_discovery"
    data = _mapping(value, path)
    _unknown(data, {"enabled", "framework", "source_roots", "route_prefix", "scan_patterns", "exclude_patterns", "blacklist"}, path)
    result = {
        "enabled": _boolean(_required(data, "enabled", path), f"{path}.enabled"),
        "framework": _choice(_required(data, "framework", path), f"{path}.framework", {"fastapi", "flask", "grpc", "generic"}),
        "source_roots": [
            _prefixed_path(
                item,
                f"{path}.source_roots[{index}]",
                allowed_scopes={PathScope.BUSINESS_SOURCE},
            )
            for index, item in enumerate(
                _string_list(_required(data, "source_roots", path), f"{path}.source_roots")
            )
        ],
        "scan_patterns": _string_list(_required(data, "scan_patterns", path), f"{path}.scan_patterns"),
        "exclude_patterns": _string_list(_required(data, "exclude_patterns", path), f"{path}.exclude_patterns"),
        "route_prefix": (
            _endpoint(data["route_prefix"], f"{path}.route_prefix")
            if data.get("route_prefix") not in (None, "")
            else ""
        ),
    }
    blacklist = _mapping(_required(data, "blacklist", path), f"{path}.blacklist")
    _unknown(blacklist, {"methods", "route_keywords"}, f"{path}.blacklist")
    result["blacklist"] = {
        "methods": _string_list(_required(blacklist, "methods", f"{path}.blacklist"), f"{path}.blacklist.methods"),
        "route_keywords": _string_list(_required(blacklist, "route_keywords", f"{path}.blacklist"), f"{path}.blacklist.route_keywords"),
    }
    return result


def _parse_roles(value: Any, path_warnings: list[str]) -> dict[str, Any]:
    data = _mapping(value, "verifier.roles")
    result: dict[str, Any] = {}
    for role, raw_role in data.items():
        _snake_id(role, f"verifier.roles.{role}")
        role_data = _mapping(raw_role, f"verifier.roles.{role}")
        _unknown(role_data, {"tool_call_limit", "draft"}, f"verifier.roles.{role}")
        parsed_role: dict[str, Any] = {}
        if "tool_call_limit" in role_data:
            if role != "attribute":
                raise ConfigError(f"verifier.roles.{role}.tool_call_limit is only valid for attribute")
            parsed_role["tool_call_limit"] = _integer(
                role_data["tool_call_limit"],
                f"verifier.roles.{role}.tool_call_limit",
                minimum=1,
            )
        if "draft" in role_data:
            draft = _mapping(role_data["draft"], f"verifier.roles.{role}.draft")
            _unknown(draft, {"enabled", "module", "reason", "tool_call_limit"}, f"verifier.roles.{role}.draft")
            parsed_draft = {
                "enabled": _boolean(_required(draft, "enabled", f"verifier.roles.{role}.draft"), f"verifier.roles.{role}.draft.enabled"),
                "module": _prefixed_path(
                    _required(draft, "module", f"verifier.roles.{role}.draft"),
                    f"verifier.roles.{role}.draft.module",
                    allowed_scopes={PathScope.PROJECT_PACKAGE},
                ),
            }
            if "reason" in draft:
                parsed_draft["reason"] = _string(draft["reason"], f"verifier.roles.{role}.draft.reason")
            if "tool_call_limit" in draft:
                if role != "attribute":
                    raise ConfigError(f"verifier.roles.{role}.draft.tool_call_limit is only valid for attribute")
                parsed_draft["tool_call_limit"] = _integer(
                    draft["tool_call_limit"],
                    f"verifier.roles.{role}.draft.tool_call_limit",
                    minimum=1,
                )
            if not _prefixed_location(parsed_draft["module"], f"verifier.roles.{role}.draft.module").startswith("draft/"):
                raise ConfigError(f"verifier.roles.{role}.draft.module must stay under draft/")
            parsed_role["draft"] = parsed_draft
        if not parsed_role:
            raise ConfigError(f"verifier.roles.{role} must define a role policy or draft")
        result[role] = parsed_role
    return result


def _parse_assets(value: Any, path_warnings: list[str]) -> list[dict[str, Any]]:
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
            "production_path": _prefixed_path(
                _required(asset, "production_path", path),
                f"{path}.production_path",
                allowed_scopes={PathScope.PROJECT_PACKAGE},
            ),
        }
        if _prefixed_location(parsed["production_path"], f"{path}.production_path").startswith("draft/"):
            raise ConfigError(f"{path}.production_path must stay outside draft/")
        if "candidate_path" in asset:
            raw_candidate_path = asset["candidate_path"]
            candidate_path = (
                ""
                if raw_candidate_path == ""
                else _string(raw_candidate_path, f"{path}.candidate_path")
            )
            parsed["candidate_path"] = (
                _prefixed_path(
                    candidate_path,
                    f"{path}.candidate_path",
                    allowed_scopes={PathScope.PROJECT_PACKAGE},
                )
                if candidate_path
                else ""
            )
            if parsed["candidate_path"] and not _prefixed_location(
                parsed["candidate_path"], f"{path}.candidate_path"
            ).startswith("draft/"):
                raise ConfigError(f"{path}.candidate_path must stay under draft/")
        if "replace" in asset:
            parsed["replace"] = _boolean(asset["replace"], f"{path}.replace")
        result.append(parsed)
    return result


_PRESENTATION_FIELDS = {
    "stages",
    "dimensions",
    "path_types",
    "error_taxonomy",
    "frontend_view",
    "extra",
}


def _parse_presentation(value: Any) -> dict[str, Any]:
    data = _mapping(value, "verifier.presentation")
    _unknown(data, _PRESENTATION_FIELDS, "verifier.presentation")
    result: dict[str, Any] = {}
    list_fields = _PRESENTATION_FIELDS - {"extra", "frontend_view"}
    for key in list_fields:
        if key in data:
            result[key] = _string_list(data[key], f"verifier.presentation.{key}")
    if "extra" in data:
        result["extra"] = _parse_extra(data["extra"], "verifier.presentation.extra")
    if "frontend_view" in data:
        frontend_path = "verifier.presentation.frontend_view"
        frontend = _mapping(data["frontend_view"], frontend_path)
        _unknown(frontend, {"live", "summary"}, frontend_path)
        result["frontend_view"] = {
            "live": _string(_required(frontend, "live", frontend_path), f"{frontend_path}.live"),
            "summary": _string(_required(frontend, "summary", frontend_path), f"{frontend_path}.summary"),
        }
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


def _parse_metadata(value: Any, path_warnings: list[str]) -> dict[str, Any]:
    data = _mapping(value, "metadata")
    _unknown(data, {"initialized_from", "source_revision", "accepted_proposal_sha256"}, "metadata")
    initialized_from = _prefixed_path(
        _required(data, "initialized_from", "metadata"),
        "metadata.initialized_from",
        allowed_scopes={PathScope.KNOWLEDGE_ROUTE},
    )
    revision = data.get("source_revision")
    if revision is not None and not isinstance(revision, str):
        raise ConfigError("invalid field metadata.source_revision: expected string or null")
    result = {"initialized_from": initialized_from, "source_revision": revision}
    if "accepted_proposal_sha256" in data:
        proposal_hash = _string(
            data["accepted_proposal_sha256"],
            "metadata.accepted_proposal_sha256",
        )
        if not re.fullmatch(r"[0-9a-f]{64}", proposal_hash):
            raise ConfigError(
                "invalid field metadata.accepted_proposal_sha256: expected lowercase sha256"
            )
        result["accepted_proposal_sha256"] = proposal_hash
    return result


def _validate_mode_contract(runtime: Mapping[str, Any]) -> None:
    mode = runtime["mode"]
    services = runtime.get("services") or {}
    local = (runtime.get("local_deployment") or {}).get("enabled") is True
    primary = services.get("primary") or {}
    if mode == "uploaded_output_evaluation":
        if services:
            raise ConfigError("runtime.services is forbidden for uploaded_output_evaluation")
        if "local_deployment" in runtime:
            raise ConfigError("runtime.local_deployment is forbidden for uploaded_output_evaluation")
        if "output" not in runtime["ready"]:
            raise ConfigError("uploaded_output_evaluation requires runtime.ready to include output")
        return
    if mode == "existing_service_required" and not primary:
        raise ConfigError("existing_service_required requires runtime.services.primary")
    if mode == "existing_service_optional" and not primary and "output" not in runtime["ready"]:
        raise ConfigError("existing_service_optional without runtime.services.primary requires runtime.ready to include output")
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
        expected_type = _project_binding_type(variable.bind)
        if expected_type is not None and variable.type != expected_type:
            raise ConfigError(
                f"invalid type for {variable.name}: {variable.bind} requires environment type {expected_type}"
            )


def _project_binding_type(bind: str) -> str | None:
    if bind == "project.resources.source.repository":
        return "path"
    if bind.endswith(".base_url"):
        return "url"
    if bind.endswith(".timeout_seconds") or bind.endswith(".request_timeout_seconds") or bind.endswith(".interval_seconds") or bind.endswith(".startup_timeout_seconds"):
        return "number"
    return None


def _validate_project_contract(document: Mapping[str, Any], registry: EnvironmentRegistry) -> None:
    """Validate cross-section requirements that cannot be owned by one parser."""
    project = document["project"]
    runtime = document["runtime"]
    verifier = document["verifier"]
    source = ((project.get("resources") or {}).get("source") or {})
    repository_declared = "repository" in source
    repository_bound = any(
        variable.bind == "project.resources.source.repository"
        for variable in registry.variables.values()
    )
    discovery_enabled = (verifier.get("endpoint_discovery") or {}).get("enabled") is True
    local_enabled = (runtime.get("local_deployment") or {}).get("enabled") is True
    default_scenarios = list((runtime.get("mock_cases") or {}).get("default_scenarios") or [])
    scenario_contract = verifier.get("scenarios") or {}
    declared_scenarios = list(scenario_contract.get("allowed") or [])
    interactive_scenarios = list(scenario_contract.get("interactive") or [])
    required_contracts = {
        "runtime.application": runtime.get("application"),
        "runtime.adapter": runtime.get("adapter"),
        "runtime.batch_persistence": runtime.get("batch_persistence"),
        "verifier.attribution.trace": (verifier.get("attribution") or {}).get("trace"),
        "verifier.judge.boundary": (verifier.get("judge") or {}).get("boundary"),
        "verifier.presentation.frontend_view": (verifier.get("presentation") or {}).get("frontend_view"),
        "verifier.check_rules.evidence": (verifier.get("check_rules") or {}).get("evidence"),
    }
    missing_contracts = [path for path, contract in required_contracts.items() if not contract]
    if missing_contracts:
        raise ConfigError(f"missing required project contract {missing_contracts[0]}")
    unknown_scenarios = sorted(set(default_scenarios) - set(declared_scenarios))
    if unknown_scenarios:
        raise ConfigError(
            "runtime.mock_cases.default_scenarios must be declared in "
            f"verifier.scenarios.allowed: {unknown_scenarios[0]}"
        )
    unknown_interactive = sorted(set(interactive_scenarios) - set(declared_scenarios))
    if unknown_interactive:
        raise ConfigError(
            "verifier.scenarios.interactive must be declared in "
            f"verifier.scenarios.allowed: {unknown_interactive[0]}"
        )
    if interactive_scenarios and (runtime.get("interaction") or {}).get("mode") != "multi_turn":
        raise ConfigError(
            "verifier.scenarios.interactive requires runtime.interaction.mode multi_turn"
        )
    if declared_scenarios and not default_scenarios:
        raise ConfigError(
            "verifier.scenarios.allowed requires explicit runtime.mock_cases.default_scenarios"
        )
    intent = ((project.get("taxonomies") or {}).get("intent") or {})
    labels = set(intent.get("labels") or [])
    unknown_descriptions = sorted(set((intent.get("descriptions") or {})) - labels)
    if unknown_descriptions:
        raise ConfigError(
            "project.taxonomies.intent.descriptions must reference a declared label: "
            f"{unknown_descriptions[0]}"
        )
    scenario_requirements = ((verifier.get("check_rules") or {}).get("scenario_requirements") or {})
    unknown_requirements = sorted(set(scenario_requirements) - set(declared_scenarios))
    if unknown_requirements:
        raise ConfigError(
            "verifier.check_rules.scenario_requirements must reference "
            f"verifier.scenarios.allowed: {unknown_requirements[0]}"
        )
    if (discovery_enabled or local_enabled) and not repository_declared:
        raise ConfigError(
            "endpoint discovery and local deployment require project.resources.source.repository"
        )
    if (discovery_enabled or local_enabled) and not source.get("repository") and not repository_bound:
        raise ConfigError(
            "empty project.resources.source.repository requires a registered environment binding"
        )


def _validate_extra_schemas(document: Mapping[str, Any], project_root: Path) -> None:
    extras = list(_iter_project_extras(document))
    if not extras:
        return
    schema_path = project_root / "extra_schema.py"
    if not schema_path.is_file():
        raise ConfigError(f"project extra fields require project schema: {schema_path}")
    schemas = _literal_extra_schemas(schema_path)
    for field_path, item in extras:
        schema = schemas.get(field_path)
        if not isinstance(schema, dict):
            raise ConfigError(f"missing EXTRA_SCHEMAS entry for {field_path} in {schema_path}")
        if schema.get("value_type") != item.get("value_type"):
            raise ConfigError(f"extra schema value_type mismatch for {field_path}")
        value = item.get("value")
        if item.get("value_type") == "path":
            prefix_names = schema.get("allowed_prefixes")
            if not isinstance(prefix_names, list) or not prefix_names:
                raise ConfigError(f"extra path schema must declare allowed_prefixes for {field_path}")
            try:
                scopes = {
                    next(scope for scope in PathScope if scope.prefix == str(prefix))
                    for prefix in prefix_names
                }
            except StopIteration as exc:
                raise ConfigError(f"extra path schema has unknown allowed_prefixes for {field_path}") from exc
            item["value"] = _prefixed_path(
                value,
                f"{field_path}.value",
                allowed_scopes=scopes,
            )
            value = item["value"]
        if isinstance(value, dict):
            required_keys = set(schema.get("required_keys") or [])
            allowed_keys = set(schema.get("allowed_keys") or [])
            missing = sorted(required_keys - set(value))
            unknown = sorted(set(value) - allowed_keys) if allowed_keys else []
            if missing:
                raise ConfigError(f"extra field {field_path} missing schema key {missing[0]}")
            if unknown:
                raise ConfigError(f"extra field {field_path} has unknown schema key {unknown[0]}")
            for key, expected_type in (schema.get("properties") or {}).items():
                if key in value:
                    _validate_extra_value(value[key], str(expected_type), f"{field_path}.value.{key}")


def _iter_project_extras(document: Mapping[str, Any]):
    sections = (
        ("project.extra", ((document.get("project") or {}).get("extra") or {})),
        ("runtime.extra", ((document.get("runtime") or {}).get("extra") or {})),
        ("verifier.extra", ((document.get("verifier") or {}).get("extra") or {})),
        (
            "verifier.presentation.extra",
            ((((document.get("verifier") or {}).get("presentation") or {}).get("extra") or {})),
        ),
    )
    for section, fields in sections:
        if isinstance(fields, Mapping):
            for field_id, item in fields.items():
                if isinstance(field_id, str) and isinstance(item, Mapping):
                    yield f"{section}.{field_id}", item


def _literal_extra_schemas(path: Path) -> dict[str, Any]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise ConfigError(f"invalid project extra schema {path}: {exc}") from exc
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == "EXTRA_SCHEMAS" for target in targets):
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, TypeError) as exc:
                    raise ConfigError(f"EXTRA_SCHEMAS in {path} must be a literal mapping") from exc
                if not isinstance(value, dict):
                    raise ConfigError(f"EXTRA_SCHEMAS in {path} must be a mapping")
                return value
    raise ConfigError(f"project extra schema must define EXTRA_SCHEMAS: {path}")


def _validate_resolved_paths(document: Mapping[str, Any], resolver: PathResolver) -> None:
    repository = str((((document.get("project") or {}).get("resources") or {}).get("source") or {}).get("repository") or "")
    if repository:
        path = Path(repository)
        if not path.is_absolute():
            raise ConfigError("project.resources.source.repository must resolve to an absolute path")
    local = (((document.get("runtime") or {}).get("local_deployment") or {}).get("enabled") is True)
    if local:
        _resolve_with_resolver(
            resolver,
            "project://scripts/start.sh",
            field_path="runtime.local_deployment.start_script",
            allowed_scopes={PathScope.PROJECT_PACKAGE},
            expected_type="executable",
        )
    verifier = document.get("verifier") or {}
    role_configs = verifier.get("roles") or {}
    for role, role_config in role_configs.items():
        draft = (role_config or {}).get("draft") or {}
        if not draft:
            continue
        _resolve_with_resolver(
            resolver,
            str(draft.get("module") or ""),
            field_path=f"verifier.roles.{role}.draft.module",
            allowed_scopes={PathScope.PROJECT_PACKAGE},
            expected_type="file",
        )
    for asset in verifier.get("assets") or []:
        if asset.get("enabled") is not True:
            continue
        draft_selected = any(
            (((role_configs.get(role) or {}).get("draft") or {}).get("enabled") is True)
            for role in asset.get("roles") or []
        )
        selected = asset.get("candidate_path") if draft_selected and asset.get("candidate_path") else asset.get("production_path")
        try:
            _resolve_with_resolver(
                resolver,
                str(selected or ""),
                field_path=f"verifier.assets.{asset.get('asset_id')}",
                allowed_scopes={PathScope.PROJECT_PACKAGE},
            )
        except ConfigError as exc:
            if not draft_selected and asset.get("candidate_path"):
                # A candidate-only physical implementation is unavailable to
                # Current until promotion; this is not a broken production
                # dependency and must not prevent the baseline from loading.
                continue
            source = "candidate_path" if draft_selected and asset.get("candidate_path") else "production_path"
            raise ConfigError(
                f"enabled verifier asset {asset.get('asset_id')} {source} is invalid: {exc}"
            ) from exc


def _build_project_spec(
    data: Mapping[str, Any],
    *,
    project_root: Path,
    environment: EnvironmentRegistry,
    sources: Mapping[str, ConfigValueSource],
    warnings: list[str],
    path_roots: PathRoots,
    path_resolver: PathResolver,
    missing_required: tuple[str, ...],
) -> ProjectSpec:
    project = dict(data["project"])
    runtime = dict(data["runtime"])
    verifier = dict(data["verifier"])
    return ProjectSpec(
        project_id=project["id"],
        name=project["name"],
        description=project["description"],
        capabilities=list(project.get("capabilities") or []),
        schema_version=int(data["schema_version"]),
        project=project,
        runtime=runtime,
        verifier=verifier,
        environment=environment,
        metadata={**dict(data["metadata"]), "warnings": warnings},
        config_sources=sources,
        missing_required=missing_required,
        path_roots=path_roots,
        path_resolver=path_resolver,
    )

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


def _prefixed_path(
    value: Any,
    path: str,
    *,
    allowed_scopes: set[PathScope],
) -> str:
    try:
        return canonical_prefixed_path(
            value,
            field_path=path,
            allowed_scopes=allowed_scopes,
        )
    except PathContractError as exc:
        raise ConfigError(str(exc)) from exc


def _prefixed_location(value: str, path: str) -> str:
    try:
        parsed = parse_prefixed_path(
            value,
            field_path=path,
            allowed_scopes=set(PathScope),
        )
    except PathContractError as exc:
        raise ConfigError(str(exc)) from exc
    return parsed.location


def _resolve_config_path(
    value: str,
    *,
    field_path: str,
    roots: PathRoots,
    allowed_scopes: set[PathScope],
    expected_type: str = "any",
) -> Path:
    return _resolve_with_resolver(
        PathResolver(roots),
        value,
        field_path=field_path,
        allowed_scopes=allowed_scopes,
        expected_type=expected_type,
    )


def _resolve_with_resolver(
    resolver: PathResolver,
    value: str | PrefixedPath,
    *,
    field_path: str,
    allowed_scopes: set[PathScope],
    expected_type: str = "any",
) -> Path:
    try:
        return resolver.resolve(
            value,
            field_path=field_path,
            allowed_scopes=allowed_scopes,
            expected_type=expected_type,
        ).physical
    except PathContractError as exc:
        raise ConfigError(str(exc)) from exc


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
