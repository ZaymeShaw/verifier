from __future__ import annotations

import argparse
import ast
import json
import math
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping, Optional

from .config import ROOT, resolve_runtime_config
from .active_artifacts import DEFAULT_ACTIVE_ARTIFACT_REGISTRY
from .config_bootstrap import effective_environment_snapshot, render_env_example
from .config_schema import ConfigError, EnvironmentRegistry, EnvironmentVariableSpec, _parse_environment, load_yaml_document
from .knowledge_route import load_project_knowledge_route
from .project_config import parse_project_document, resolve_project_config
from .runtime_preflight import probe_runtime_capabilities


_PERSONAL_PATH = re.compile(r"/(?:Users|home)/[^/\s]+/")
_SECRET_FIELD = re.compile(r"(?:api[_-]?key|access[_-]?token|password|secret|credential)", re.IGNORECASE)
_SOURCE_SECRET = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|password|secret|credential)\s*=\s*['\"]([^'\"\n]{8,})['\"]"
)
_DOCUMENT_SECRET_VALUE = re.compile(
    r"(?i)(?:密码|口令|password|api[_-]?key|access[_-]?token|credential)\s*[:：=]\s*(?!\$\{|<|\*{3})\S{4,}"
)
_STRUCTURED_SECRET = re.compile(
    r"(?i)[\"']?(?:api[_-]?key|access[_-]?token|password|secret|credential)[\"']?"
    r"\s*:\s*[\"']([^\"'\n]{8,})[\"']"
)
_SECRET_SCAN_SUFFIXES = frozenset({".py", ".sh", ".yaml", ".yml", ".json", ".md", ".toml", ".txt"})
_DEPLOYMENT_FALLBACK = re.compile(
    r"\.get\(\s*['\"](?:base_url|endpoint|method|timeout|timeout_seconds|model|api_key)['\"]"
    r"(?:\s*,|\s*\)\s*or)"
)
_LIVE_SCHEMA_CONFIG_NAMES = frozenset({
    "READY",
    "SCENARIO_ENUM",
    "INTENT_LABELS",
    "API_ENDPOINT",
    "API_INTENT_ENDPOINT",
    "IS_PROVIDED_OUTPUT",
})
_LEGACY_PROJECTSPEC_FIELDS = frozenset({
    "adapter",
    "common",
    "api",
    "application",
    "frontend_extensions",
    "source_project",
    "documents",
    "endpoint_discovery",
    "extra",
    "attribute_draft",
    "judge_draft",
    "mock_draft",
    "live_draft",
    "role_assets",
    "root",
    "field_provider_module",
    "field_provider_class",
})


@dataclass(frozen=True)
class ConfigCheckIssue:
    code: str
    message: str
    path: str = ""
    line: int = 0


@dataclass
class ConfigCheckReport:
    ok: bool = True
    issues: list[ConfigCheckIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fingerprint: str = ""

    def add(self, issue: ConfigCheckIssue) -> None:
        if issue in self.issues:
            return
        self.ok = False
        self.issues.append(issue)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "fingerprint": self.fingerprint,
            "issues": [issue.__dict__ for issue in self.issues],
            "warnings": list(self.warnings),
        }


def check_runtime_config_contract(
    *,
    root: Path = ROOT,
    environ: Optional[Mapping[str, str]] = None,
    require_runtime_secrets: bool = False,
    probe_llm: bool = False,
    full: bool = False,
    changed_from: str | None = None,
) -> ConfigCheckReport:
    report = ConfigCheckReport()
    config_path = root / "impl" / "config.yaml"
    dotenv_path = root / ".env"
    try:
        resolved = resolve_runtime_config(
            config_path=config_path,
            dotenv_path=dotenv_path,
            environ=environ,
        )
    except ConfigError as exc:
        report.add(ConfigCheckIssue(code="config_invalid", message=str(exc), path=str(config_path)))
        return report

    report.fingerprint = resolved.fingerprint()
    report.warnings.extend(resolved.warnings)
    runtime_capability = probe_runtime_capabilities(resolved, root=root, environ=environ)
    if runtime_capability.ok:
        report.warnings.append(
            "runtime_capability: "
            f"python={runtime_capability.python_executable} "
            f"python_version={runtime_capability.python_version} "
            f"agno={runtime_capability.agno_version}"
        )
    else:
        report.add(ConfigCheckIssue(
            code="runtime_capability_failed",
            message=runtime_capability.error,
            path=str(config_path),
        ))
    if resolved.missing_required:
        message = f"missing required runtime values: {', '.join(resolved.missing_required)}"
        if require_runtime_secrets:
            report.add(ConfigCheckIssue(code="required_value_missing", message=message))
        else:
            report.warnings.append(message)

    project_registries: dict[str, EnvironmentRegistry] = {}
    knowledge_registries: dict[str, EnvironmentRegistry] = {}
    independent_registries = _load_independent_tool_registries(report, root)
    extra_occurrences: dict[str, list[tuple[str, str]]] = {}
    impl_projects = {
        path.parent.name: path
        for path in sorted((root / "impl" / "projects").glob("*/project.yaml"))
    }
    knowledge_projects = {
        path.parent.name: path
        for path in sorted((root / "projects").glob("*/project.yaml"))
    }
    if set(impl_projects) != set(knowledge_projects):
        missing_impl = sorted(set(knowledge_projects) - set(impl_projects))
        missing_route = sorted(set(impl_projects) - set(knowledge_projects))
        report.add(
            ConfigCheckIssue(
                code="project_route_mismatch",
                message=f"impl-only={missing_route}; knowledge-only={missing_impl}",
                path=str(root / "projects"),
            )
        )
    for project_id, config_file in impl_projects.items():
        try:
            project_document = load_yaml_document(config_file)
            spec = resolve_project_config(
                project_id,
                projects_dir=root / "impl" / "projects",
                dotenv_path=dotenv_path,
                environ=environ,
                verifier_root=root,
            )
            project_registries[project_id] = spec.environment or EnvironmentRegistry(MappingProxyType({}))
            report.warnings.extend(spec.metadata.get("warnings") or [])
            if spec.missing_required:
                message = f"{project_id} missing required project values: {', '.join(spec.missing_required)}"
                if require_runtime_secrets:
                    report.add(ConfigCheckIssue("required_project_value_missing", message, str(config_file)))
                else:
                    report.warnings.append(message)
            if spec.attribution_enabled and not resolved.embedding.enabled:
                report.add(ConfigCheckIssue(
                    "attribution_embedding_disabled",
                    f"{project_id} enables attribution but public embedding is disabled",
                    str(config_file),
                ))
            _check_extra_consumers(report, root, project_id, config_file, project_document, extra_occurrences)
        except (ConfigError, OSError) as exc:
            report.add(ConfigCheckIssue(code="project_config_invalid", message=str(exc), path=str(config_file)))
        for line, value in _personal_paths(config_file.read_text(encoding="utf-8")):
            report.add(ConfigCheckIssue("personal_path", f"project config contains personal path: {value}", str(config_file), line))
    for project_id, route_file in knowledge_projects.items():
        try:
            route = load_project_knowledge_route(
                project_id,
                knowledge_root=root / "projects",
                dotenv_path=dotenv_path,
                environ=environ,
            )
            knowledge_registries[project_id] = route.environment
            report.warnings.extend(route.path_warnings)
            if route.missing_required:
                message = f"{project_id} missing required knowledge values: {', '.join(route.missing_required)}"
                if require_runtime_secrets:
                    report.add(ConfigCheckIssue("required_knowledge_value_missing", message, str(route_file)))
                else:
                    report.warnings.append(message)
            _check_routed_document_safety(report, route_file, route)
        except (ConfigError, OSError) as exc:
            report.add(ConfigCheckIssue(code="knowledge_route_invalid", message=str(exc), path=str(route_file)))
        for line, value in _personal_paths(route_file.read_text(encoding="utf-8")):
            report.add(ConfigCheckIssue("personal_path", f"knowledge route contains personal path: {value}", str(route_file), line))
    _check_cross_layer_environments(report, project_registries, knowledge_registries)
    _report_duplicate_extras(report, extra_occurrences)
    for issue in _validate_path_migration_ledger(root, set(impl_projects)):
        report.add(issue)

    template_path = root / "impl" / "projects" / "project.template.yaml"
    try:
        parse_project_document(load_yaml_document(template_path), project_id=None, project_root=template_path.parent)
    except (ConfigError, OSError) as exc:
        report.add(ConfigCheckIssue("project_template_invalid", str(exc), str(template_path)))

    for line, value in _personal_paths(config_path.read_text(encoding="utf-8")):
        report.add(
            ConfigCheckIssue(
                code="personal_path",
                message=f"public config contains a developer-specific absolute path: {value}",
                path=str(config_path),
                line=line,
            )
        )

    gitignore_path = root / ".gitignore"
    ignored = {
        line.strip()
        for line in gitignore_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    } if gitignore_path.is_file() else set()
    if ".env" not in ignored:
        report.add(
            ConfigCheckIssue(
                code="dotenv_not_ignored",
                message="repository root .env must be ignored by Git",
                path=str(gitignore_path),
            )
        )

    env_example_path = root / ".env.example"
    combined_environment = _combined_environment(
        report,
        resolved.environment,
        project_registries,
        knowledge_registries,
        independent_registries,
    )
    expected_example = render_env_example(combined_environment)
    actual_example = env_example_path.read_text(encoding="utf-8") if env_example_path.is_file() else ""
    if actual_example != expected_example:
        report.add(
            ConfigCheckIssue(
                code="env_example_stale",
                message=".env.example must be generated from impl/config.yaml",
                path=str(env_example_path),
            )
        )

    for issue in _scan_public_config_bypasses(root, combined_environment.accepted_names()):
        report.add(issue)
    for issue in _scan_legacy_projectspec_consumers(root):
        report.add(issue)
    for issue in _scan_path_construction_bypasses(root):
        report.add(issue)
    for issue in _scan_portable_writer_bypasses(root):
        report.add(issue)
    for issue in _scan_active_path_artifacts(root, environ=environ):
        report.add(issue)
    changed_issues, changed_summary = _scan_changed_and_untracked_files(
        root,
        base_ref=changed_from,
    )
    for issue in changed_issues:
        report.add(issue)
    report.warnings.append(changed_summary)
    for issue in _scan_repository_secrets(root, [config_path, *impl_projects.values(), *knowledge_projects.values()]):
        report.add(issue)
    for issue in _scan_independent_tool_runtime_imports(root, _independent_tool_config_paths(root)):
        report.add(issue)
    if not resolved.llm.capabilities.json_mode:
        report.add(ConfigCheckIssue("llm_capability_missing", "public LLM must declare json_mode capability", str(config_path)))
    if not resolved.llm.capabilities.tool_calls:
        report.add(ConfigCheckIssue("llm_capability_missing", "public LLM must declare tool_calls capability", str(config_path)))
    required_context_tokens = math.ceil(max(
        resolved.attribute.finalization_prompt_char_budget,
        resolved.attribute.review_prompt_char_budget,
    ) / 2) + 4096
    if resolved.llm.capabilities.context_window_tokens < required_context_tokens:
        report.add(ConfigCheckIssue(
            "llm_context_window_insufficient",
            "declared model context window is smaller than verifier's configured prompt budget",
            str(config_path),
        ))
    if probe_llm:
        for issue in _probe_llm_capabilities(resolved):
            report.add(issue)
    if full:
        post_issues, post_summary = _run_full_gates_with_post_scan(
            root,
            environ=environ,
            changed_from=changed_from,
        )
        existing = {
            (issue.code, issue.message, issue.path, issue.line)
            for issue in report.issues
        }
        for issue in post_issues:
            key = (issue.code, issue.message, issue.path, issue.line)
            if key not in existing:
                report.add(issue)
                existing.add(key)
        report.warnings.append(f"post_full_{post_summary}")
    return report


def _probe_llm_capabilities(resolved: object) -> list[ConfigCheckIssue]:
    """Probe the configured OpenAI-compatible model without logging credentials or content."""
    llm = resolved.llm
    if not llm.api_key:
        return [ConfigCheckIssue("llm_probe_missing_key", "--probe-llm requires the registered llm.api_key value")]
    endpoint = f"{llm.base_url.rstrip('/')}/chat/completions"
    common = {
        "model": llm.model,
        "temperature": 0,
        "max_tokens": 64,
    }
    probes = (
        (
            "json_mode",
            {
                **common,
                "messages": [{"role": "user", "content": "Return exactly one JSON object with key ok and boolean true."}],
                "response_format": {"type": "json_object"},
            },
        ),
        (
            "tool_calls",
            {
                **common,
                "messages": [{"role": "user", "content": "Call the capability_probe tool once with ok=true."}],
                "tools": [{
                    "type": "function",
                    "function": {
                        "name": "capability_probe",
                        "description": "Validate tool calling support.",
                        "parameters": {
                            "type": "object",
                            "properties": {"ok": {"type": "boolean"}},
                            "required": ["ok"],
                        },
                    },
                }],
            },
        ),
        (
            "reasoning",
            {
                **common,
                "messages": [{"role": "user", "content": "Return exactly one JSON object with key ok and boolean true."}],
                "response_format": {"type": "json_object"},
                "reasoning_effort": llm.reasoning_effort,
            },
        ),
    )
    issues: list[ConfigCheckIssue] = []
    for capability, payload in probes:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {llm.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=float(llm.request_timeout_seconds)) as response:
                body = json.loads(response.read().decode("utf-8"))
            message = (((body.get("choices") or [{}])[0]).get("message") or {})
            if capability in {"json_mode", "reasoning"}:
                content = message.get("content")
                parsed = json.loads(content) if isinstance(content, str) else content
                passed = isinstance(parsed, dict) and parsed.get("ok") is True
            else:
                passed = bool(message.get("tool_calls"))
            if not passed:
                issues.append(ConfigCheckIssue("llm_capability_probe_failed", f"configured model failed {capability} probe"))
        except urllib.error.HTTPError as exc:
            provider_error = _safe_provider_error(exc)
            issues.append(ConfigCheckIssue(
                "llm_capability_probe_failed",
                f"configured model failed {capability} probe: HTTP {exc.code}{provider_error}",
            ))
        except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            issues.append(ConfigCheckIssue(
                "llm_capability_probe_failed",
                f"configured model failed {capability} probe: {type(exc).__name__}",
            ))
    return issues


def _safe_provider_error(exc: urllib.error.HTTPError) -> str:
    """Return a bounded provider diagnostic while excluding headers and credentials."""
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except Exception:
        return ""
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return ""
    error_type = str(error.get("type") or error.get("code") or "").strip()
    message = re.sub(r"\s+", " ", str(error.get("message") or "")).strip()[:240]
    details = ": ".join(item for item in (error_type, message) if item)
    return f" ({details})" if details else ""


def _run_full_gates(
    root: Path,
    environ: Mapping[str, str] | None = None,
    *,
    environment_is_frozen: bool = False,
) -> list[ConfigCheckIssue]:
    effective_environment = (
        environ
        if environment_is_frozen and environ is not None
        else effective_environment_snapshot(root / ".env", environ)
    )
    commands = (
        ("adapter_compliance", [sys.executable, "scripts/check_adapter_compliance.py"]),
        ("protocol_compliance", [sys.executable, "scripts/verify_protocol_compliance.py"]),
        ("mock_check", [sys.executable, "-m", "impl.cli", "mock-check"]),
        (
            "minimal_run_chain",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_project_live_smoke.py::test_qa_live_run_provided_smoke",
                "tests/test_project_config_contract.py::test_mode_contract_distinguishes_uploaded_output_and_service_projects",
            ],
        ),
    )
    issues: list[ConfigCheckIssue] = []
    for gate, command in commands:
        completed = subprocess.run(
            command,
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=dict(effective_environment),
            check=False,
        )
        if completed.returncode != 0:
            tail = " | ".join((completed.stdout or "").splitlines()[-3:])
            issues.append(ConfigCheckIssue("full_gate_failed", f"{gate} failed: {tail}", str(root)))
    return issues


def _run_full_gates_with_post_scan(
    root: Path,
    *,
    environ: Mapping[str, str] | None,
    changed_from: str | None,
) -> tuple[list[ConfigCheckIssue], str]:
    """Run executable gates, then inspect artifacts created by those commands."""
    effective_environment = effective_environment_snapshot(root / ".env", environ)
    issues = list(_run_full_gates(
        root,
        effective_environment,
        environment_is_frozen=True,
    ))
    frozen_dotenv = root / ".config-check-frozen-environment"
    issues.extend(_scan_active_path_artifacts(
        root,
        environ=effective_environment,
        dotenv_path=frozen_dotenv,
    ))
    changed_issues, changed_summary = _scan_changed_and_untracked_files(
        root,
        base_ref=changed_from,
    )
    issues.extend(changed_issues)
    return issues, changed_summary


def _check_cross_layer_environments(
    report: ConfigCheckReport,
    project_registries: Mapping[str, EnvironmentRegistry],
    knowledge_registries: Mapping[str, EnvironmentRegistry],
) -> None:
    for project_id in sorted(set(project_registries) & set(knowledge_registries)):
        impl_variables = project_registries[project_id].variables
        route_variables = knowledge_registries[project_id].variables
        for name in sorted(set(impl_variables) & set(route_variables)):
            impl = impl_variables[name]
            route = route_variables[name]
            # The formal runtime may require a business root while the human
            # knowledge route remains usable without it. Type and secrecy are
            # shared; requiredness belongs to the consuming layer.
            if (impl.type, impl.secret) != (route.type, route.secret):
                report.add(
                    ConfigCheckIssue(
                        code="environment_contract_mismatch",
                        message=f"{name} has inconsistent type/secret across project and knowledge route",
                        path=project_id,
                    )
                )


def _combined_environment(
    report: ConfigCheckReport,
    public: EnvironmentRegistry,
    project_registries: Mapping[str, EnvironmentRegistry],
    knowledge_registries: Mapping[str, EnvironmentRegistry],
    independent_registries: Mapping[str, EnvironmentRegistry] | None = None,
) -> EnvironmentRegistry:
    variables: dict[str, EnvironmentVariableSpec] = dict(public.variables)
    owners: dict[str, str] = {name: "public" for name in variables}
    for layer, registries in (
        ("project", project_registries),
        ("knowledge", knowledge_registries),
        ("tool", independent_registries or {}),
    ):
        for project_id, registry in registries.items():
            for name, variable in registry.variables.items():
                existing = variables.get(name)
                if existing is None:
                    variables[name] = variable
                    owners[name] = f"{layer}:{project_id}"
                    continue
                same_project_pair = owners[name] in {f"project:{project_id}", f"knowledge:{project_id}"}
                compatible = (existing.type, existing.secret) == (
                    variable.type,
                    variable.secret,
                )
                if not same_project_pair or not compatible:
                    report.add(
                        ConfigCheckIssue(
                            code="environment_name_duplicate",
                            message=f"{name} is defined by both {owners[name]} and {layer}:{project_id}",
                        )
                    )
                elif layer == "project":
                    variables[name] = variable
                    owners[name] = f"project:{project_id}"
    return EnvironmentRegistry(variables=MappingProxyType(variables))


_LEDGER_SCOPES = frozenset({
    "business_source",
    "verifier_repo",
    "project_package",
    "knowledge_route",
    "artifact_package",
    "non_file",
})
_LEDGER_LIFECYCLES = frozenset({
    "config_input",
    "runtime_only",
    "derived_active",
    "derived_historical",
})
_LEDGER_DISPOSITIONS = frozenset({"migrate", "split", "delete", "handoff"})
_LEDGER_TARGET_KINDS = frozenset({
    "yaml_field",
    "logical_path_ref",
    "non_file_schema",
    "historical_only",
})


def _validate_path_migration_ledger(
    root: Path,
    project_ids: set[str],
) -> list[ConfigCheckIssue]:
    """Validate the historical migration ledger without using it at runtime."""
    path = root / "spec" / "adapter" / "config-prefixpath-20260721-ledger.yaml"
    if not path.is_file():
        return [ConfigCheckIssue(
            "PATH_LEDGER_INVALID",
            "required 20260721 path migration ledger is missing",
            str(path),
        )]
    try:
        document = load_yaml_document(path)
    except (ConfigError, OSError) as exc:
        return [ConfigCheckIssue("PATH_LEDGER_INVALID", str(exc), str(path))]

    issues: list[ConfigCheckIssue] = []

    def invalid(message: str) -> None:
        issues.append(ConfigCheckIssue("PATH_LEDGER_INVALID", message, str(path)))

    if document.get("schema_version") != 2:
        invalid("ledger schema_version must be 2")
    if str(document.get("baseline") or "") != "20260721":
        invalid("ledger baseline must be 20260721")

    probes = document.get("probes")
    if not isinstance(probes, Mapping) or not probes:
        invalid("ledger probes must be a non-empty mapping")
        probes = {}
    else:
        for probe_id, target in probes.items():
            if not isinstance(probe_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", probe_id):
                invalid(f"invalid probe id: {probe_id!r}")
                continue
            if not isinstance(target, str) or not target.startswith("tests/"):
                invalid(f"probe {probe_id!r} must name a tests/ pytest node")
                continue
            test_file = root / target.split("::", 1)[0]
            if not test_file.is_file():
                invalid(f"probe {probe_id!r} target does not exist: {target}")

    entries = document.get("entries")
    if not isinstance(entries, list) or not entries:
        invalid("ledger entries must be a non-empty list")
        return issues

    seen_ids: set[str] = set()
    covered_projects: set[str] = set()
    known_projects = set(project_ids) | {"public"}
    for index, entry in enumerate(entries):
        pointer = f"entries[{index}]"
        if not isinstance(entry, Mapping):
            invalid(f"{pointer} must be a mapping")
            continue
        entry_id = entry.get("entry_id")
        if not isinstance(entry_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", entry_id):
            invalid(f"{pointer}.entry_id is invalid")
        elif entry_id in seen_ids:
            invalid(f"duplicate ledger entry_id: {entry_id}")
        else:
            seen_ids.add(entry_id)

        project_id = entry.get("project")
        if project_id not in known_projects:
            invalid(f"{pointer}.project is unknown: {project_id!r}")
        elif isinstance(project_id, str):
            covered_projects.add(project_id)
        if not isinstance(entry.get("historical_location"), str) or not entry.get("historical_location"):
            invalid(f"{pointer}.historical_location is required")
        if entry.get("semantic_scope") not in _LEDGER_SCOPES:
            invalid(f"{pointer}.semantic_scope is invalid")
        if entry.get("lifecycle") not in _LEDGER_LIFECYCLES:
            invalid(f"{pointer}.lifecycle is invalid")
        if entry.get("disposition") not in _LEDGER_DISPOSITIONS:
            invalid(f"{pointer}.disposition is invalid")
        consumers = entry.get("consumers")
        if not isinstance(consumers, list) or not all(isinstance(item, str) and item for item in consumers):
            invalid(f"{pointer}.consumers must be a list of consumer ids")
        probe_id = entry.get("probe_id")
        if not isinstance(probe_id, str) or probe_id not in probes:
            invalid(f"{pointer}.probe_id does not reference a declared probe")
        _validate_ledger_target(invalid, pointer, project_id, entry.get("canonical_target"))

        compatibility = entry.get("compatibility")
        if not isinstance(compatibility, Mapping):
            invalid(f"{pointer}.compatibility must be a mapping")
        else:
            status = compatibility.get("status")
            if status not in {"none", "removed", "retained"}:
                invalid(f"{pointer}.compatibility.status is invalid")
            if status == "retained":
                if not isinstance(compatibility.get("owner"), str) or not compatibility.get("owner"):
                    invalid(f"{pointer}.compatibility.owner is required while retained")
                condition = compatibility.get("deletion_condition")
                delete_by = compatibility.get("delete_by")
                if not (isinstance(condition, str) and condition) and not (
                    isinstance(delete_by, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", delete_by)
                ):
                    invalid(
                        f"{pointer}.compatibility requires deletion_condition or YYYY-MM-DD delete_by"
                    )

    missing = sorted(project_ids - covered_projects)
    if missing:
        invalid(f"ledger has no per-project entries for: {', '.join(missing)}")
    return issues


def _validate_ledger_target(
    invalid,
    pointer: str,
    project_id: object,
    target: object,
) -> None:
    if not isinstance(target, Mapping):
        invalid(f"{pointer}.canonical_target must be a mapping")
        return
    kind = target.get("kind")
    if kind not in _LEDGER_TARGET_KINDS:
        invalid(f"{pointer}.canonical_target.kind is invalid")
        return
    if kind == "logical_path_ref":
        if target.get("location_scope") not in _LEDGER_SCOPES - {"non_file"}:
            invalid(f"{pointer}.canonical_target.location_scope is invalid")
        if not isinstance(target.get("field"), str) or not target.get("field"):
            invalid(f"{pointer}.canonical_target.field is required")
        return
    value = target.get("value")
    if not isinstance(value, str) or not value:
        invalid(f"{pointer}.canonical_target.value is required")
        return
    if kind != "yaml_field":
        return
    allowed_prefixes = ["impl/config.yaml#"]
    if isinstance(project_id, str) and project_id != "public":
        allowed_prefixes.extend((
            f"impl/projects/{project_id}/project.yaml#",
            f"projects/{project_id}/project.yaml#",
        ))
    if not any(value.startswith(prefix) for prefix in allowed_prefixes):
        invalid(f"{pointer}.canonical_target.value is outside the project's formal YAML")


def _scan_public_config_bypasses(root: Path, registered_names: Iterable[str]) -> list[ConfigCheckIssue]:
    names = frozenset(registered_names)
    issues: list[ConfigCheckIssue] = []
    scan_roots = [root / "impl", root / "scripts"]
    excluded = {
        (root / "impl" / "core" / "config.py").resolve(),
        (root / "impl" / "core" / "config_schema.py").resolve(),
        (root / "impl" / "core" / "config_bootstrap.py").resolve(),
        (root / "impl" / "core" / "config_check.py").resolve(),
        (root / "impl" / "core" / "project_config.py").resolve(),
    }
    for scan_root in scan_roots:
        if not scan_root.exists():
            continue
        for path in sorted(scan_root.rglob("*.py")):
            if path.resolve() in excluded:
                continue
            try:
                text = path.read_text(encoding="utf-8")
                tree = ast.parse(text, filename=str(path))
            except (OSError, SyntaxError) as exc:
                issues.append(
                    ConfigCheckIssue(
                        code="scan_failed",
                        message=str(exc),
                        path=str(path),
                    )
                )
                continue
            visitor = _EnvironmentReadVisitor(names)
            visitor.visit(tree)
            for line, name, registered in visitor.reads:
                issues.append(
                    ConfigCheckIssue(
                        code="public_env_bypass" if registered else "unregistered_env_bypass",
                        message=(
                            f"registered variable {name} must be read by its resolver"
                            if registered
                            else f"environment variable {name} must be registered before product code can consume it"
                        ),
                        path=str(path),
                        line=line,
                    )
                )
            for line, field_name in visitor.llm_client_overrides:
                issues.append(
                    ConfigCheckIssue(
                        code="llm_config_bypass",
                        message=f"LlmClient {field_name} must come from resolved configuration",
                        path=str(path),
                        line=line,
                    )
                )
            for line, marker in _forbidden_markers(text):
                issues.append(
                    ConfigCheckIssue(
                        code="public_config_fallback",
                        message=f"forbidden public config fallback marker: {marker}",
                        path=str(path),
                        line=line,
                    )
                )
            for match in _DEPLOYMENT_FALLBACK.finditer(text):
                issues.append(
                    ConfigCheckIssue(
                        code="deployment_config_fallback",
                        message="deployment fields must be required from typed configuration, not consumer fallbacks",
                        path=str(path),
                        line=text.count("\n", 0, match.start()) + 1,
                    )
                )
            if path.name == "live_schema.py":
                for line, name in _assigned_names(tree):
                    if name in _LIVE_SCHEMA_CONFIG_NAMES:
                        issues.append(ConfigCheckIssue(
                            code="live_schema_config_bypass",
                            message=f"{name} belongs to ProjectSpec and must not be declared in live_schema.py",
                            path=str(path),
                            line=line,
                        ))
            if path.name == "endpoint_discovery.py":
                for line in _numeric_timeout_calls(tree):
                    issues.append(ConfigCheckIssue(
                        code="deployment_config_fallback",
                        message="endpoint discovery timeout must come from ProjectSpec service configuration",
                        path=str(path),
                        line=line,
                    ))
            for line, value in _personal_paths(text):
                issues.append(
                    ConfigCheckIssue(
                        code="personal_path",
                        message=f"runtime consumer contains a developer-specific absolute path: {value}",
                        path=str(path),
                        line=line,
                    )
                )
    return issues


def _scan_active_path_artifacts(
    root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path | None = None,
) -> list[ConfigCheckIssue]:
    if dotenv_path is None:
        failures = DEFAULT_ACTIVE_ARTIFACT_REGISTRY.validate(root, environ=environ)
    else:
        context = DEFAULT_ACTIVE_ARTIFACT_REGISTRY.context(
            root,
            environ=environ,
            dotenv_path=dotenv_path,
        )
        failures = DEFAULT_ACTIVE_ARTIFACT_REGISTRY.validate_context(context)
    return [
        ConfigCheckIssue(
            code=failure.code,
            message=failure.message,
            path=str(failure.path),
        )
        for failure in failures
    ]


def _scan_changed_and_untracked_files(
    root: Path,
    *,
    base_ref: str | None = None,
) -> tuple[list[ConfigCheckIssue], str]:
    """Establish the supplemental Git boundary and audit its filesystem edges.

    Content checks stay authoritative in the full-tree YAML, registry, and AST
    scans.  This layer proves which changed/untracked files those scans had to
    cover and catches repository escapes or unreadable formal inputs.
    """
    root = Path(root).resolve()
    try:
        worktree = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        return [], f"changed_file_scan_unavailable: {exc}"
    if worktree.returncode != 0 or worktree.stdout.strip() != "true":
        return [], "changed_file_scan_unavailable: not a Git worktree; current-tree checks applied"

    commands: list[list[str]] = [
        ["git", "diff", "--name-only", "-z", "--diff-filter=ACMRTUXB"],
        ["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRTUXB"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    ]
    if base_ref:
        commands.append([
            "git", "diff", "--name-only", "-z", "--diff-filter=ACMRTUXB",
            f"{base_ref}...HEAD",
        ])

    relative_names: set[str] = set()
    issues: list[ConfigCheckIssue] = []
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            diagnostic = completed.stderr.decode("utf-8", errors="replace").strip()[:240]
            issues.append(ConfigCheckIssue(
                "PATH_SCAN_FAILED",
                f"changed-file boundary failed for {' '.join(command[1:3])}: {diagnostic}",
                str(root),
            ))
            continue
        for raw in completed.stdout.split(b"\0"):
            if raw:
                relative_names.add(raw.decode("utf-8", errors="surrogateescape"))

    for relative in sorted(relative_names):
        candidate = root / relative
        lexical = candidate.absolute()
        if not lexical.is_relative_to(root):
            issues.append(ConfigCheckIssue(
                "PATH_TRAVERSAL",
                "Git changed-file entry escapes the repository root",
                relative,
            ))
            continue
        if candidate.is_symlink():
            resolved = candidate.resolve(strict=False)
            if not resolved.is_relative_to(root):
                issues.append(ConfigCheckIssue(
                    "PATH_SYMLINK_ESCAPE",
                    "changed/untracked symbolic link escapes the repository root",
                    str(candidate),
                ))
            continue
        if not candidate.exists() or not candidate.is_file():
            continue
        if _is_formal_changed_input(root, candidate):
            try:
                content = candidate.read_bytes()
            except OSError as exc:
                issues.append(ConfigCheckIssue(
                    "PATH_SCAN_FAILED",
                    f"changed/untracked formal input is unreadable: {exc}",
                    str(candidate),
                ))
                continue
            if candidate.suffix == ".py":
                issues.extend(_scan_python_source_contract(root, candidate, content=content))
    boundary = f"changed_file_scan: inspected {len(relative_names)} changed/untracked path(s)"
    if base_ref:
        boundary += f" including {base_ref}...HEAD"
    return issues, boundary


def _is_formal_changed_input(root: Path, path: Path) -> bool:
    relative = path.relative_to(root)
    parts = relative.parts
    if relative == Path("impl/config.yaml"):
        return True
    if (
        len(parts) == 4
        and parts[:2] == ("impl", "projects")
        and parts[-1] == "project.yaml"
    ):
        return True
    if len(parts) == 3 and parts[0] == "projects" and parts[-1] == "project.yaml":
        return True
    if path.suffix in {".py", ".json", ".yaml", ".yml"}:
        return bool(parts and parts[0] in {"impl", "scripts", ".agents"})
    return False


def _scan_path_construction_bypasses(root: Path) -> list[ConfigCheckIssue]:
    """Find project consumers that rebuild configured roots instead of using PathResolver."""
    issues: list[ConfigCheckIssue] = []
    scan_roots = (
        root / "impl",
        root / ".agents" / "skills" / "draft" / "scripts",
    )
    paths = sorted(
        path
        for scan_root in scan_roots
        if scan_root.exists()
        for path in scan_root.rglob("*.py")
    )
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            issues.append(ConfigCheckIssue("PATH_SCAN_FAILED", str(exc), str(path)))
            continue
        visitor = _ConfiguredRootJoinVisitor(set())
        visitor.visit(tree)
        for line, configured_field in visitor.findings:
            issues.append(ConfigCheckIssue(
                code="PATH_CONSTRUCTION_BYPASS",
                message=f"consumer constructs a physical path from {configured_field}; use resolver-backed accessors",
                path=str(path),
                line=line,
            ))
    return issues


def _scan_legacy_projectspec_consumers(root: Path) -> list[ConfigCheckIssue]:
    """Reject production consumers that reintroduce removed ProjectSpec views."""
    issues: list[ConfigCheckIssue] = []
    scan_roots = (
        root / "impl",
        root / ".agents" / "skills" / "draft" / "scripts",
    )
    paths = sorted(
        path
        for scan_root in scan_roots
        if scan_root.exists()
        for path in scan_root.rglob("*.py")
    )
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            issues.append(ConfigCheckIssue("PATH_SCAN_FAILED", str(exc), str(path)))
            continue
        visitor = _LegacyProjectSpecVisitor()
        visitor.visit(tree)
        for line, field_name in visitor.findings:
            issues.append(ConfigCheckIssue(
                "PROJECTSPEC_COMPAT_BYPASS",
                f"consumer reads removed ProjectSpec.{field_name}; use project/runtime/verifier",
                str(path),
                line,
            ))
    return issues


class _LegacyProjectSpecVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.findings: list[tuple[int, str]] = []
        self.known_names: list[set[str]] = [{"spec", "project_spec"}]

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        names = {"spec", "project_spec"}
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            if argument.arg in {"spec", "project_spec"} or _annotation_names_project_spec(argument.annotation):
                names.add(argument.arg)
        self.known_names.append(names)
        self.generic_visit(node)
        self.known_names.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._is_spec(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.known_names[-1].add(target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if (
            isinstance(node.target, ast.Name)
            and (
                (node.value is not None and self._is_spec(node.value))
                or _annotation_names_project_spec(node.annotation)
            )
        ):
            self.known_names[-1].add(node.target.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in _LEGACY_PROJECTSPEC_FIELDS and self._is_spec(node.value):
            self._add(node.lineno, node.attr)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and self._is_spec(node.args[0])
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and node.args[1].value in _LEGACY_PROJECTSPEC_FIELDS
        ):
            self._add(node.lineno, node.args[1].value)
        self.generic_visit(node)

    def _add(self, line: int, field_name: str) -> None:
        finding = (line, field_name)
        if finding not in self.findings:
            self.findings.append(finding)

    def _is_spec(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.known_names[-1]
        if isinstance(node, ast.Attribute):
            return node.attr in {"spec", "project_spec"}
        return False


def _annotation_names_project_spec(annotation: ast.AST | None) -> bool:
    if annotation is None:
        return False
    return any(
        isinstance(item, ast.Name) and item.id == "ProjectSpec"
        or isinstance(item, ast.Attribute) and item.attr == "ProjectSpec"
        for item in ast.walk(annotation)
    )


class _ConfiguredRootJoinVisitor(ast.NodeVisitor):
    def __init__(self, compatibility_functions: set[str]) -> None:
        self.compatibility_functions = compatibility_functions
        self.function_stack: list[str] = []
        self.alias_stack: list[dict[str, str]] = [{}]
        self.findings: list[tuple[int, str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(node.name)
        self.alias_stack.append({})
        self.generic_visit(node)
        self.alias_stack.pop()
        self.function_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign) -> None:
        field = _configured_root_path_call(node.value)
        if field is not None:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.alias_stack[-1][target.id] = field
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        field = _configured_root_path_call(node.value) if node.value is not None else None
        if field is not None and isinstance(node.target, ast.Name):
            self.alias_stack[-1][node.target.id] = field
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        # The originating Path(spec.root/source_project) call is itself the
        # violation.  Visiting children reports that source once without also
        # duplicating every subsequent ``/`` join derived from the same alias.
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        field = _configured_root_path_call(node)
        if field is not None and not self._is_compatibility_function():
            finding = (node.lineno, field)
            if finding not in self.findings:
                self.findings.append(finding)
        self.generic_visit(node)

    def _root_origin(self, node: ast.AST) -> str | None:
        while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            node = node.left
        direct = _configured_root_path_call(node)
        if direct is not None:
            return direct
        if isinstance(node, ast.Name):
            return self.alias_stack[-1].get(node.id)
        return None

    def _is_compatibility_function(self) -> bool:
        return bool(
            self.function_stack
            and self.function_stack[-1] in self.compatibility_functions
        )


def _configured_root_path_call(node: ast.AST) -> str | None:
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        node = node.left
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "resolve"
        and not node.args
    ):
        node = node.func.value
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "Path":
        return None
    if len(node.args) != 1:
        return None
    argument = node.args[0]
    if not isinstance(argument, ast.Attribute) or argument.attr not in {"root", "source_project"}:
        return None
    if argument.attr == "source_project":
        return "*.source_project"
    owner = argument.value
    if isinstance(owner, ast.Name) and owner.id == "spec":
        return f"spec.{argument.attr}"
    if (
        isinstance(owner, ast.Attribute)
        and owner.attr == "spec"
        and isinstance(owner.value, ast.Name)
        and owner.value.id == "self"
    ):
        return f"self.spec.{argument.attr}"
    return None


def _scan_portable_writer_bypasses(root: Path) -> list[ConfigCheckIssue]:
    issues: list[ConfigCheckIssue] = []
    for path in _repository_python_sources(root):
        issues.extend(_scan_python_source_contract(root, path))
    return issues


def _repository_python_sources(root: Path) -> list[Path]:
    excluded_parts = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "vendor",
    }
    return sorted(
        path
        for path in root.rglob("*.py")
        if path.is_file()
        and not any(part in excluded_parts for part in path.relative_to(root).parts)
    )


def _source_execution_domain(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    parts = relative.parts
    if not parts:
        return "unknown"
    if parts[0] == "impl":
        if len(parts) >= 2 and parts[1] == "checklist":
            return "independent_tool"
        return "formal_product"
    if parts[:4] == (".agents", "skills", "draft", "scripts"):
        return "formal_producer"
    if parts[0] in {
        "hooks",
        "scripts",
        ".agents",
        ".claude",
        ".codex",
        ".superpowers",
        "search-test-case",
    }:
        return "independent_tool"
    if (
        parts[0] == "tests"
        or path.name == "conftest.py"
        or len(parts) == 1
        and (
            path.name.startswith(("test_", "_test_", "_check_"))
            or path.name == "create_test_data.py"
        )
    ):
        return "test_fixture"
    if parts[0] in {"docs", "report", "issues", "projects", "spec", "data", "tmp"}:
        return "document_or_data"
    return "unknown"


def _scan_python_source_contract(
    root: Path,
    path: Path,
    *,
    content: bytes | None = None,
) -> list[ConfigCheckIssue]:
    domain = _source_execution_domain(root, path)
    if domain in {"independent_tool", "test_fixture", "document_or_data"}:
        return []
    relative = path.relative_to(root).as_posix()
    exempt_writer_modules = {
        "impl/core/portable_artifact.py",
        "impl/core/active_artifacts.py",
    }
    try:
        text = content.decode("utf-8") if content is not None else path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        return [ConfigCheckIssue("PATH_SCAN_FAILED", str(exc), str(path))]

    issues: list[ConfigCheckIssue] = []
    writer = _PortableWriterVisitor()
    writer.visit(tree)
    if writer.findings and domain == "unknown":
        issues.append(ConfigCheckIssue(
            "PATH_EXECUTION_DOMAIN_UNCLASSIFIED",
            "structured writer belongs to an unclassified executable source domain",
            str(path),
            writer.findings[0],
        ))
    elif relative not in exempt_writer_modules:
        for line in writer.findings:
            issues.append(ConfigCheckIssue(
                "PATH_WRITER_BYPASS",
                "structured active artifact must use a registered family writer",
                str(path),
                line,
            ))

    absolute_paths = _AbsolutePathLiteralVisitor()
    absolute_paths.visit(tree)
    for line, value in absolute_paths.findings:
        issues.append(ConfigCheckIssue(
            "PATH_ABSOLUTE_LITERAL",
            f"formal source contains a machine path literal; bind it through .env: {value}",
            str(path),
            line,
        ))

    if relative != "impl/core/frontend_view.py":
        presentation = _PresentationConsumerVisitor()
        presentation.visit(tree)
        for line in presentation.findings:
            issues.append(ConfigCheckIssue(
                "PRESENTATION_BEHAVIOR_BYPASS",
                "only frontend/report projection may consume ProjectSpec.presentation",
                str(path),
                line,
            ))
    return issues


class _AbsolutePathLiteralVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.findings: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        function_name = ""
        if isinstance(node.func, ast.Name):
            function_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            function_name = node.func.attr
        if function_name in {"Path", "open"} and node.args:
            value = _absolute_string_literal(node.args[0])
            if value is not None:
                self._add(node.lineno, value)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        value = _absolute_string_literal(node.value)
        if value is not None and any(_path_like_assignment(target) for target in node.targets):
            self._add(node.lineno, value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        value = _absolute_string_literal(node.value) if node.value is not None else None
        if value is not None and _path_like_assignment(node.target):
            self._add(node.lineno, value)
        self.generic_visit(node)

    def _add(self, line: int, value: str) -> None:
        finding = (line, value)
        if finding not in self.findings:
            self.findings.append(finding)


def _absolute_string_literal(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return None
    value = node.value
    if value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value):
        return value
    return None


def _path_like_assignment(node: ast.AST) -> bool:
    name = ""
    if isinstance(node, ast.Name):
        name = node.id
    elif isinstance(node, ast.Attribute):
        name = node.attr
    return bool(re.search(r"(?:^|_)(?:path|root|dir|directory)$", name, re.IGNORECASE))


class _PresentationConsumerVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.findings: list[int] = []

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "presentation" and _looks_like_project_spec(node.value):
            if node.lineno not in self.findings:
                self.findings.append(node.lineno)
        self.generic_visit(node)


def _looks_like_project_spec(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in {"spec", "project_spec"}
    return isinstance(node, ast.Attribute) and node.attr in {"spec", "project_spec"}


class _PortableWriterVisitor(ast.NodeVisitor):
    _SERIALIZER_FUNCTIONS = {"dump", "dumps", "safe_dump"}

    def __init__(self) -> None:
        self.serializer_modules = {"json": "json", "yaml": "yaml"}
        self.serializer_functions: dict[str, tuple[str, str]] = {}
        self.low_level_writer_types = {"PortableArtifactWriter"}
        self.serialized_names: list[set[str]] = [set()]
        self.writer_names: list[set[str]] = [set()]
        self.findings: list[int] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name in {"json", "yaml"}:
                self.serializer_modules[alias.asname or alias.name] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module in {"json", "yaml"}:
            for alias in node.names:
                if alias.name in self._SERIALIZER_FUNCTIONS:
                    self.serializer_functions[alias.asname or alias.name] = (
                        node.module,
                        alias.name,
                    )
        for alias in node.names:
            if alias.name == "PortableArtifactWriter":
                self.low_level_writer_types.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.serialized_names.append(set())
        self.writer_names.append(set())
        self.generic_visit(node)
        self.writer_names.pop()
        self.serialized_names.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign) -> None:
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if self._is_serialized_value(node.value):
            self.serialized_names[-1].update(names)
        if self._constructs_low_level_writer(node.value):
            self.writer_names[-1].update(names)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.value is not None:
            if self._is_serialized_value(node.value):
                self.serialized_names[-1].add(node.target.id)
            if self._constructs_low_level_writer(node.value):
                self.writer_names[-1].add(node.target.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        raw_write = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {"write", "write_text", "write_bytes"}
            and bool(node.args)
            and self._is_serialized_value(node.args[0])
        )
        raw_dump = self._serializer_writes_to_stream(node)
        direct_portable_writer = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "write_json"
            and (
                self._constructs_low_level_writer(node.func.value)
                or isinstance(node.func.value, ast.Name)
                and node.func.value.id in self.writer_names[-1]
            )
        )
        if (raw_write or raw_dump or direct_portable_writer) and node.lineno not in self.findings:
            self.findings.append(node.lineno)
        self.generic_visit(node)

    def _is_serialized_value(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name) and node.id in self.serialized_names[-1]:
            return True
        return any(
            isinstance(item, ast.Call) and self._serializer_returns_text(item)
            for item in ast.walk(node)
        )

    def _serializer_call_info(self, node: ast.Call) -> tuple[str, str] | None:
        if isinstance(node.func, ast.Name) and node.func.id in self.serializer_functions:
            return self.serializer_functions[node.func.id]
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in self.serializer_modules
            and node.func.attr in self._SERIALIZER_FUNCTIONS
        ):
            return self.serializer_modules[node.func.value.id], node.func.attr
        return None

    def _serializer_writes_to_stream(self, node: ast.Call) -> bool:
        info = self._serializer_call_info(node)
        if info is None:
            return False
        module, name = info
        if module == "json" and name == "dump":
            return len(node.args) >= 2 or any(
                keyword.arg == "fp" for keyword in node.keywords
            )
        if module == "yaml" and name in {"dump", "safe_dump"}:
            return len(node.args) >= 2 or any(
                keyword.arg == "stream" for keyword in node.keywords
            )
        return False

    def _serializer_returns_text(self, node: ast.Call) -> bool:
        info = self._serializer_call_info(node)
        if info is None:
            return False
        module, name = info
        if name == "dumps":
            return True
        return (
            module == "yaml"
            and name in {"dump", "safe_dump"}
            and not self._serializer_writes_to_stream(node)
        )

    def _constructs_low_level_writer(self, node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in self.low_level_writer_types
        )


def _check_routed_document_safety(report: ConfigCheckReport, route_file: Path, route: object) -> None:
    for document in route.documents.values():
        path = route.document_path(document.document_id)
        text = path.read_text(encoding="utf-8")
        for line, value in _personal_paths(text):
            report.add(ConfigCheckIssue(
                "personal_path",
                f"routed knowledge document contains personal path: {value}",
                str(path),
                line,
            ))
        for match in _DOCUMENT_SECRET_VALUE.finditer(text):
            report.add(ConfigCheckIssue(
                "secret_in_knowledge",
                "routed knowledge document contains a secret-like literal; register a variable instead",
                str(path),
                text.count("\n", 0, match.start()) + 1,
            ))


def _independent_tool_config_paths(root: Path) -> list[Path]:
    paths = {
        *root.glob("hooks/**/config*.yaml"),
        *root.glob("hooks/**/config*.yml"),
        *root.glob("impl/projects/*/draft_config.yaml"),
        *root.glob(".agents/skills/**/config*.yaml"),
        *root.glob(".agents/skills/**/config*.yml"),
    }
    return sorted(path for path in paths if path.is_file())


def _load_independent_tool_registries(
    report: ConfigCheckReport,
    root: Path,
) -> dict[str, EnvironmentRegistry]:
    registries: dict[str, EnvironmentRegistry] = {}
    for path in _independent_tool_config_paths(root):
        try:
            document = load_yaml_document(path)
            if "environment" not in document:
                continue
            registries[path.relative_to(root).as_posix()] = _parse_environment(document["environment"])
        except (ConfigError, OSError) as exc:
            report.add(ConfigCheckIssue("tool_environment_invalid", str(exc), str(path)))
    return registries


def _iter_extra_fields(document: Mapping[str, object]):
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
                    yield section, field_id, item


def _check_extra_consumers(
    report: ConfigCheckReport,
    root: Path,
    project_id: str,
    config_file: Path,
    document: Mapping[str, object],
    occurrences: dict[str, list[tuple[str, str]]],
) -> None:
    for section, field_id, item in _iter_extra_fields(document):
        signature = json.dumps(
            {"description": item.get("description"), "value_type": item.get("value_type")},
            ensure_ascii=False,
            sort_keys=True,
        )
        occurrences.setdefault(field_id, []).append((project_id, signature))
        for consumer in item.get("consumers") or []:
            if not isinstance(consumer, str) or not consumer.startswith("impl."):
                report.add(ConfigCheckIssue(
                    "extra_consumer_invalid",
                    f"{section}.{field_id} consumer must be a repository module: {consumer!r}",
                    str(config_file),
                ))
                continue
            module_path = root.joinpath(*consumer.split(".")).with_suffix(".py")
            package_path = root.joinpath(*consumer.split("."), "__init__.py")
            target = module_path if module_path.is_file() else package_path
            if not target.is_file():
                report.add(ConfigCheckIssue(
                    "extra_consumer_missing",
                    f"{section}.{field_id} consumer module not found: {consumer}",
                    str(config_file),
                ))
                continue
            if field_id not in target.read_text(encoding="utf-8"):
                report.add(ConfigCheckIssue(
                    "extra_consumer_unwired",
                    f"{section}.{field_id} is not referenced by declared consumer {consumer}",
                    str(target),
                ))


def _report_duplicate_extras(
    report: ConfigCheckReport,
    occurrences: Mapping[str, list[tuple[str, str]]],
) -> None:
    for field_id, items in sorted(occurrences.items()):
        projects = sorted({project_id for project_id, _ in items})
        signatures = {signature for _, signature in items}
        if len(projects) >= 2 and len(signatures) == 1:
            report.warnings.append(
                f"extra_duplicate_semantics: {field_id} appears with the same annotation in {', '.join(projects)}; review promotion to a formal field"
            )


def _scan_repository_secrets(root: Path, config_files: Iterable[Path]) -> list[ConfigCheckIssue]:
    issues: list[ConfigCheckIssue] = []
    for path in config_files:
        try:
            document = load_yaml_document(path)
        except (ConfigError, OSError):
            continue
        for field_path, value in _walk_mapping(document):
            field_name = field_path.rsplit(".", 1)[-1]
            if _SECRET_FIELD.search(field_name) and isinstance(value, str) and value and not value.startswith("${"):
                issues.append(ConfigCheckIssue(
                    "secret_in_config",
                    f"secret-like field {field_path} must be supplied through a registered environment variable",
                    str(path),
                ))
    seen: set[tuple[Path, int]] = set()
    for path, line, text in _repository_secret_candidates(root):
        for pattern in (_SOURCE_SECRET, _STRUCTURED_SECRET):
            for match in pattern.finditer(text):
                value = str(match.group(1) or "")
                marker = (path, line)
                if marker in seen or _placeholder_secret(value):
                    continue
                seen.add(marker)
                issues.append(ConfigCheckIssue(
                    "secret_in_source",
                    "secret-like literal must not be committed to repository text",
                    str(path),
                    line,
                ))
    return issues


def _repository_secret_candidates(root: Path) -> list[tuple[Path, int, str]]:
    pattern = "api[_-]?key|access[_-]?token|password|secret|credential"
    try:
        completed = subprocess.run(
            [
                "git", "grep", "-n", "-I", "-E", pattern, "--",
                "*.py", "*.sh", "*.yaml", "*.yml", "*.json", "*.md", "*.toml", "*.txt",
            ],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        completed = None
    if completed is not None and completed.returncode in {0, 1}:
        candidates: list[tuple[Path, int, str]] = []
        for item in completed.stdout.splitlines():
            parts = item.split(":", 2)
            if len(parts) != 3 or not parts[1].isdigit():
                continue
            candidates.append((root / parts[0], int(parts[1]), parts[2]))
        return candidates
    candidates = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _SECRET_SCAN_SUFFIXES:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(lines, 1):
            if re.search(pattern, line, re.IGNORECASE):
                candidates.append((path, line_number, line))
    return candidates


def _placeholder_secret(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized or normalized.startswith(("${", "***", "<")):
        return True
    exact_placeholders = {
        "example",
        "placeholder",
        "dummy",
        "probe-secret",
        "super-secret",
        "legacy-secret",
        "hard-coded",
        "explicit-deepseek-key",
    }
    placeholder_prefixes = ("your-", "example-", "placeholder-", "dummy-", "test-")
    return normalized in exact_placeholders or normalized.startswith(placeholder_prefixes)


def _walk_mapping(value: object, prefix: str = ""):
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield from _walk_mapping(item, path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_mapping(item, f"{prefix}[{index}]")
    else:
        yield prefix, value


def _scan_independent_tool_runtime_imports(
    root: Path,
    config_paths: Iterable[Path],
) -> list[ConfigCheckIssue]:
    relative_paths = tuple(path.relative_to(root).as_posix() for path in config_paths)
    if not relative_paths:
        return []
    issues: list[ConfigCheckIssue] = []
    for path in sorted((root / "impl").rglob("*.py")):
        if path.resolve() == (root / "impl" / "core" / "config_check.py").resolve():
            continue
        text = path.read_text(encoding="utf-8")
        for marker in relative_paths:
            basename = Path(marker).name
            if marker in text or (basename != "config.yaml" and basename in text):
                issues.append(ConfigCheckIssue(
                    "independent_tool_runtime_import",
                    f"product runtime must not load independent tool config {marker}",
                    str(path),
                ))
    return issues


class _EnvironmentReadVisitor(ast.NodeVisitor):
    def __init__(self, names: frozenset[str]):
        self.names = names
        self.reads: list[tuple[int, str, bool]] = []
        self.llm_client_overrides: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        if _is_os_getenv(node.func) or _is_os_environ_get(node.func):
            name = _literal_name(node.args[0]) if node.args else None
            if name is not None:
                self.reads.append((node.lineno, str(name), name in self.names))
        if _call_name(node.func) == "LlmClient":
            for keyword in node.keywords:
                if keyword.arg in {"api_key", "base_url", "model"}:
                    self.llm_client_overrides.append((node.lineno, keyword.arg))
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if _is_os_environ(node.value):
            name = _literal_name(node.slice)
            if name is not None:
                self.reads.append((node.lineno, str(name), name in self.names))
        self.generic_visit(node)


def _assigned_names(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        targets: list[ast.AST] = []
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = list(node.targets) if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                found.append((node.lineno, target.id))
    return found


def _numeric_timeout_calls(tree: ast.AST) -> list[int]:
    found: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "timeout" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, (int, float)):
                found.append(node.lineno)
    return found


def _is_os_getenv(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "getenv"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _is_os_environ(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _is_os_environ_get(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "get" and _is_os_environ(node.value)


def _literal_name(node: ast.AST) -> Optional[str]:
    return str(node.value) if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _forbidden_markers(text: str) -> list[tuple[int, str]]:
    markers = (
        "load_env_md_key",
        "load_bailian_env_md_key",
        "MODEL_DEFAULT",
        "BASE_URL_DEFAULT",
        "from agno.models.deepseek import",
        "DeepSeek(",
    )
    found: list[tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        for marker in markers:
            if marker in line:
                found.append((line_number, marker))
    return found


def _personal_paths(text: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        match = _PERSONAL_PATH.search(line)
        if match:
            found.append((line_number, match.group(0).rstrip("/")))
    return found


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the verifier configuration contract")
    parser.add_argument("--require-runtime-secrets", action="store_true")
    parser.add_argument("--probe-llm", action="store_true", help="call the configured model to verify JSON and tool capabilities")
    parser.add_argument("--full", action="store_true", help="also run adapter, protocol, mock and minimal run-chain gates")
    parser.add_argument(
        "--changed-from",
        help="also inspect the merge diff from this checked-out Git base revision",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    report = check_runtime_config_contract(
        require_runtime_secrets=args.require_runtime_secrets or args.probe_llm,
        probe_llm=args.probe_llm,
        full=args.full,
        changed_from=args.changed_from,
    )
    if args.as_json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"config-check: {'ok' if report.ok else 'failed'} ({report.fingerprint or 'unresolved'})")
        for warning in report.warnings:
            print(f"warning: {warning}")
        for issue in report.issues:
            location = f"{issue.path}:{issue.line}" if issue.line else issue.path
            print(f"error[{issue.code}] {location}: {issue.message}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
