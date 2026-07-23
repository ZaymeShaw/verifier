from __future__ import annotations

import os
import threading
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional

from .config_bootstrap import parse_dotenv
from .config_schema import (
    AttributeCompactionConfig,
    AttributeConfig,
    BrowserConfig,
    ConfigError,
    ConfigValueSource,
    ContextConfig,
    EmbeddingConfig,
    EnvironmentVariableSpec,
    ExecutionConfig,
    JudgeConfig,
    LlmCapabilities,
    LlmConfig,
    LlmRolePolicyOverride,
    PythonConfig,
    ParsedRuntimeConfig,
    RuntimeConfig,
    ServerConfig,
    UatConfig,
    SUPPORTED_LLM_PROVIDERS,
    SUPPORTED_LLM_PROTOCOLS,
    convert_environment_value,
    load_yaml_document,
    parse_runtime_document,
    openai_compatible_base_url,
)
from .path_contract import PathContractError, PathResolver, PathRoots, PathScope


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "impl" / "config.yaml"
DOTENV_PATH = ROOT / ".env"

_RUNTIME_CONFIG: Optional[RuntimeConfig] = None
_RUNTIME_CONFIG_LOCK = threading.Lock()


def resolve_runtime_config(
    *,
    config_path: Optional[Path] = None,
    dotenv_path: Optional[Path] = None,
    environ: Optional[Mapping[str, str]] = None,
    cli_overrides: Optional[Mapping[str, Any]] = None,
) -> RuntimeConfig:
    """Resolve the public configuration through one deterministic precedence chain."""
    config_path = CONFIG_PATH if config_path is None else config_path
    dotenv_path = DOTENV_PATH if dotenv_path is None else dotenv_path
    verifier_root = config_path.resolve().parent.parent
    parsed = parse_runtime_document(load_yaml_document(config_path))
    process_environment = dict(os.environ if environ is None else environ)
    dotenv = parse_dotenv(dotenv_path)
    accepted_names = parsed.environment.accepted_names() | _discover_product_environment_names(config_path)
    unknown_dotenv = sorted(set(dotenv) - accepted_names)
    if unknown_dotenv:
        raise ConfigError(f"unregistered dotenv variable: {unknown_dotenv[0]}")

    values = _base_values(parsed)
    yaml_source = config_path.name
    sources = {
        field_path: ConfigValueSource(kind="yaml", name=f"{yaml_source}#{field_path}")
        for field_path in values
        if field_path not in {"llm.api_key", "embedding.api_key"}
    }
    for role, policy in parsed.llm.role_policies.items():
        for field_name in ("provider", "model", "base_url", "temperature", "reasoning_effort"):
            if getattr(policy, field_name) is not None:
                field_path = f"llm.role_policies.{role}.{field_name}"
                sources[field_path] = ConfigValueSource(kind="yaml", name=f"{yaml_source}#{field_path}")
    by_binding: dict[str, EnvironmentVariableSpec] = {}
    for variable in parsed.environment.variables.values():
        by_binding[variable.bind] = variable
        selected = _select_environment_value(variable, process_environment, dotenv)
        if selected is None:
            continue
        raw_value, source_kind, source_name = selected
        values[variable.bind] = convert_environment_value(variable, raw_value)
        sources[variable.bind] = ConfigValueSource(
            kind=source_kind,
            name=source_name,
            secret=variable.secret,
        )

    for field_path, raw_value in (cli_overrides or {}).items():
        variable = by_binding.get(field_path)
        if variable is None:
            raise ConfigError(f"CLI override is not registered for field {field_path}")
        if variable.secret:
            raise ConfigError(f"secret field {field_path} cannot be passed through CLI")
        values[field_path] = convert_environment_value(variable, str(raw_value))
        sources[field_path] = ConfigValueSource(kind="cli", name=field_path, secret=False)

    for field_path in ("server.port", "uat.port"):
        if int(values[field_path]) > 65535:
            raise ConfigError(f"invalid resolved field {field_path}: expected port between 1 and 65535")
    if values["llm.provider"] not in SUPPORTED_LLM_PROVIDERS:
        raise ConfigError(
            f"invalid resolved field llm.provider: unsupported value {values['llm.provider']!r}"
        )
    if values["llm.protocol"] not in SUPPORTED_LLM_PROTOCOLS:
        raise ConfigError(
            f"invalid resolved field llm.protocol: unsupported value {values['llm.protocol']!r}"
        )
    values["llm.base_url"] = openai_compatible_base_url(
        values["llm.base_url"],
        "llm.base_url",
    )
    for field_path in ("context.data_root", "context.store_root"):
        values[field_path] = _resolve_common_runtime_path(
            values[field_path],
            field_path=field_path,
            source=sources[field_path],
            verifier_root=verifier_root,
        )

    missing_required_values = {
        variable.bind
        for variable in parsed.environment.variables.values()
        if (
            variable.required
            or (
                variable.required_when is not None
                and values.get(variable.required_when.field) == variable.required_when.equals
            )
        )
        and values.get(variable.bind) in {None, ""}
    }
    missing_required = tuple(sorted(missing_required_values))
    role_policies = _apply_role_policy_overrides(parsed, values)
    return RuntimeConfig(
        schema_version=parsed.schema_version,
        python=PythonConfig(executable=str(values["python.executable"])),
        server=ServerConfig(host=str(values["server.host"]), port=int(values["server.port"])),
        uat=UatConfig(host=str(values["uat.host"]), port=int(values["uat.port"])),
        browser=BrowserConfig(driver_path=str(values["browser.driver_path"])),
        llm=LlmConfig(
            protocol=str(values["llm.protocol"]),
            provider=str(values["llm.provider"]),
            model=str(values["llm.model"]),
            base_url=str(values["llm.base_url"]),
            api_key=str(values["llm.api_key"]),
            temperature=float(values["llm.temperature"]),
            reasoning_effort=str(values["llm.reasoning_effort"]),
            request_timeout_seconds=float(values["llm.request_timeout_seconds"]),
            max_attempts=int(values["llm.max_attempts"]),
            retry_delay_seconds=float(values["llm.retry_delay_seconds"]),
            capabilities=LlmCapabilities(
                json_mode=bool(values["llm.capabilities.json_mode"]),
                tool_calls=bool(values["llm.capabilities.tool_calls"]),
                context_window_tokens=int(values["llm.capabilities.context_window_tokens"]),
            ),
            role_policies=role_policies,
        ),
        embedding=EmbeddingConfig(
            enabled=bool(values["embedding.enabled"]),
            provider=str(values["embedding.provider"]),
            model=str(values["embedding.model"]),
            api_key=str(values["embedding.api_key"]),
            dimensions=int(values["embedding.dimensions"]),
            retrieval_top_k=int(values["embedding.retrieval_top_k"]),
            trust_env_proxy=bool(values["embedding.trust_env_proxy"]),
        ),
        execution=ExecutionConfig(
            case_retry_attempts=int(values["execution.case_retry_attempts"]),
            batch_concurrency_default=int(values["execution.batch_concurrency_default"]),
            batch_concurrency_max=int(values["execution.batch_concurrency_max"]),
            batch_event_history_limit=int(values["execution.batch_event_history_limit"]),
        ),
        context=ContextConfig(
            data_root=str(values["context.data_root"]),
            store_root=str(values["context.store_root"]),
            max_records_per_project=int(values["context.max_records_per_project"]),
            candidate_limit=int(values["context.candidate_limit"]),
            load_limit=int(values["context.load_limit"]),
            content_char_budget=int(values["context.content_char_budget"]),
            query_limit=int(values["context.query_limit"]),
            top_k_per_query=int(values["context.top_k_per_query"]),
        ),
        judge=JudgeConfig(raw_response_max_chars=int(values["judge.raw_response_max_chars"])),
        attribute=AttributeConfig(
            tool_call_limit=int(values["attribute.tool_call_limit"]),
            investigation_error_chars=int(values["attribute.investigation_error_chars"]),
            finalization_prompt_char_budget=int(values["attribute.finalization_prompt_char_budget"]),
            review_prompt_char_budget=int(values["attribute.review_prompt_char_budget"]),
            compaction=AttributeCompactionConfig(
                list_item_limit=int(values["attribute.compaction.list_item_limit"]),
                attribute_result_chars=int(values["attribute.compaction.attribute_result_chars"]),
                project_context_chars=int(values["attribute.compaction.project_context_chars"]),
                trace_input_chars=int(values["attribute.compaction.trace_input_chars"]),
                trace_normalized_request_chars=int(values["attribute.compaction.trace_normalized_request_chars"]),
                trace_output_chars=int(values["attribute.compaction.trace_output_chars"]),
                trace_execution_chars=int(values["attribute.compaction.trace_execution_chars"]),
                trace_error_chars=int(values["attribute.compaction.trace_error_chars"]),
                judge_business_expectations_chars=int(values["attribute.compaction.judge_business_expectations_chars"]),
                judge_fulfillment_assessments_chars=int(values["attribute.compaction.judge_fulfillment_assessments_chars"]),
                judge_gap_chars=int(values["attribute.compaction.judge_gap_chars"]),
                judge_reasoning_chars=int(values["attribute.compaction.judge_reasoning_chars"]),
            ),
        ),
        environment=parsed.environment,
        sources=MappingProxyType(dict(sources)),
        warnings=(),
        missing_required=missing_required,
    )


def _discover_product_environment_names(config_path: Path) -> frozenset[str]:
    """Discover project/knowledge registrations without loading either config domain."""
    root = config_path.parent.parent if config_path.parent.name == "impl" else config_path.parent
    names: set[str] = set()
    for pattern in ("impl/projects/*/project.yaml", "projects/*/project.yaml"):
        for path in root.glob(pattern):
            try:
                document = load_yaml_document(path)
            except (ConfigError, OSError):
                continue
            variables = ((document.get("environment") or {}).get("variables") or {})
            if not isinstance(variables, dict):
                continue
            for name, raw_variable in variables.items():
                if isinstance(name, str):
                    names.add(name)
                if not isinstance(raw_variable, dict):
                    continue
    return frozenset(names)


def _base_values(parsed: ParsedRuntimeConfig) -> dict[str, Any]:
    return {
        "python.executable": parsed.python.executable,
        "server.host": parsed.server.host,
        "server.port": parsed.server.port,
        "uat.host": parsed.uat.host,
        "uat.port": parsed.uat.port,
        "browser.driver_path": parsed.browser.driver_path,
        "llm.protocol": parsed.llm.protocol,
        "llm.provider": parsed.llm.provider,
        "llm.model": parsed.llm.model,
        "llm.base_url": parsed.llm.base_url,
        "llm.api_key": "",
        "llm.temperature": parsed.llm.temperature,
        "llm.reasoning_effort": parsed.llm.reasoning_effort,
        "llm.request_timeout_seconds": parsed.llm.request_timeout_seconds,
        "llm.max_attempts": parsed.llm.max_attempts,
        "llm.retry_delay_seconds": parsed.llm.retry_delay_seconds,
        "llm.role_policies.live_stub.model": _role_policy_default_model(parsed, "live_stub"),
        "llm.capabilities.json_mode": parsed.llm.capabilities.json_mode,
        "llm.capabilities.tool_calls": parsed.llm.capabilities.tool_calls,
        "llm.capabilities.context_window_tokens": parsed.llm.capabilities.context_window_tokens,
        "embedding.provider": parsed.embedding.provider,
        "embedding.enabled": parsed.embedding.enabled,
        "embedding.model": parsed.embedding.model,
        "embedding.api_key": "",
        "embedding.dimensions": parsed.embedding.dimensions,
        "embedding.retrieval_top_k": parsed.embedding.retrieval_top_k,
        "embedding.trust_env_proxy": parsed.embedding.trust_env_proxy,
        "execution.case_retry_attempts": parsed.execution.case_retry_attempts,
        "execution.batch_concurrency_default": parsed.execution.batch_concurrency_default,
        "execution.batch_concurrency_max": parsed.execution.batch_concurrency_max,
        "execution.batch_event_history_limit": parsed.execution.batch_event_history_limit,
        "context.data_root": parsed.context.data_root,
        "context.store_root": parsed.context.store_root,
        "context.max_records_per_project": parsed.context.max_records_per_project,
        "context.candidate_limit": parsed.context.candidate_limit,
        "context.load_limit": parsed.context.load_limit,
        "context.content_char_budget": parsed.context.content_char_budget,
        "context.query_limit": parsed.context.query_limit,
        "context.top_k_per_query": parsed.context.top_k_per_query,
        "judge.raw_response_max_chars": parsed.judge.raw_response_max_chars,
        "attribute.finalization_prompt_char_budget": parsed.attribute.finalization_prompt_char_budget,
        "attribute.review_prompt_char_budget": parsed.attribute.review_prompt_char_budget,
        "attribute.tool_call_limit": parsed.attribute.tool_call_limit,
        "attribute.investigation_error_chars": parsed.attribute.investigation_error_chars,
        "attribute.compaction.list_item_limit": parsed.attribute.compaction.list_item_limit,
        "attribute.compaction.attribute_result_chars": parsed.attribute.compaction.attribute_result_chars,
        "attribute.compaction.project_context_chars": parsed.attribute.compaction.project_context_chars,
        "attribute.compaction.trace_input_chars": parsed.attribute.compaction.trace_input_chars,
        "attribute.compaction.trace_normalized_request_chars": parsed.attribute.compaction.trace_normalized_request_chars,
        "attribute.compaction.trace_output_chars": parsed.attribute.compaction.trace_output_chars,
        "attribute.compaction.trace_execution_chars": parsed.attribute.compaction.trace_execution_chars,
        "attribute.compaction.trace_error_chars": parsed.attribute.compaction.trace_error_chars,
        "attribute.compaction.judge_business_expectations_chars": parsed.attribute.compaction.judge_business_expectations_chars,
        "attribute.compaction.judge_fulfillment_assessments_chars": parsed.attribute.compaction.judge_fulfillment_assessments_chars,
        "attribute.compaction.judge_gap_chars": parsed.attribute.compaction.judge_gap_chars,
        "attribute.compaction.judge_reasoning_chars": parsed.attribute.compaction.judge_reasoning_chars,
    }


def _role_policy_default_model(parsed: ParsedRuntimeConfig, role: str) -> str:
    policy = parsed.llm.role_policies.get(role)
    if policy is None or policy.model is None:
        return ""
    return policy.model


def _apply_role_policy_overrides(
    parsed: ParsedRuntimeConfig,
    values: dict[str, Any],
) -> Mapping[str, LlmRolePolicyOverride]:
    """Rebuild role policies after applying environment-registered overrides.

    Only ``live_stub.model`` is currently exposed through the environment
    registry; the override replaces the YAML model while preserving every other
    field of the role policy.
    """
    role_policies: dict[str, LlmRolePolicyOverride] = dict(parsed.llm.role_policies)
    stub_model = str(values.get("llm.role_policies.live_stub.model") or "")
    if "live_stub" in role_policies and stub_model:
        existing = role_policies["live_stub"]
        if stub_model != (existing.model or ""):
            role_policies["live_stub"] = LlmRolePolicyOverride(
                provider=existing.provider,
                model=stub_model,
                base_url=existing.base_url,
                temperature=existing.temperature,
                reasoning_effort=existing.reasoning_effort,
            )
    return MappingProxyType(role_policies)


def _select_environment_value(
    variable: EnvironmentVariableSpec,
    process_environment: Mapping[str, str],
    dotenv: Mapping[str, str],
) -> Optional[tuple[str, str, str]]:
    if variable.name in process_environment:
        return process_environment[variable.name], "process_env", variable.name
    if variable.name in dotenv:
        return dotenv[variable.name], "dotenv", variable.name
    return None


def _resolve_common_runtime_path(
    value: Any,
    *,
    field_path: str,
    source: ConfigValueSource,
    verifier_root: Path,
) -> str:
    text = str(value)
    candidate = Path(text)
    if candidate.is_absolute():
        if source.kind == "yaml":
            raise ConfigError(f"PATH_ABSOLUTE_CONFIG at {field_path}: absolute YAML paths are forbidden")
        return str(candidate.resolve())
    try:
        return str(
            PathResolver(PathRoots(verifier_repo=verifier_root)).resolve(
                text,
                field_path=field_path,
                allowed_scopes={PathScope.VERIFIER_REPO},
                must_exist=False,
            ).physical
        )
    except PathContractError as exc:
        if source.kind != "yaml":
            raise ConfigError(
                f"{field_path} supplied by {source.kind} must be an absolute machine path"
            ) from exc
        raise ConfigError(str(exc)) from exc


def initialize_runtime_config(
    *,
    cli_overrides: Optional[Mapping[str, Any]] = None,
    force: bool = False,
) -> RuntimeConfig:
    """Resolve and freeze process configuration before runtime consumers start."""
    global _RUNTIME_CONFIG
    with _RUNTIME_CONFIG_LOCK:
        if _RUNTIME_CONFIG is not None and not force:
            if cli_overrides:
                raise ConfigError("runtime config is already initialized; CLI overrides must be applied at startup")
            return _RUNTIME_CONFIG
        resolved = resolve_runtime_config(cli_overrides=cli_overrides)
        _RUNTIME_CONFIG = resolved
        return resolved


def get_runtime_config() -> RuntimeConfig:
    return initialize_runtime_config()


def reset_runtime_config_for_tests() -> None:
    global _RUNTIME_CONFIG
    with _RUNTIME_CONFIG_LOCK:
        _RUNTIME_CONFIG = None


def get_python_config() -> PythonConfig:
    return get_runtime_config().python


def get_server_config() -> ServerConfig:
    return get_runtime_config().server


def get_uat_config() -> UatConfig:
    return get_runtime_config().uat


def get_browser_config() -> BrowserConfig:
    return get_runtime_config().browser


def get_llm_config() -> LlmConfig:
    return get_runtime_config().llm


def get_embedding_config() -> EmbeddingConfig:
    return get_runtime_config().embedding


def resolve_batch_concurrency(value: Optional[int] = None) -> int:
    """Resolve batch concurrency through the public execution configuration."""
    execution = get_runtime_config().execution
    selected = execution.batch_concurrency_default if value is None else int(value)
    return max(1, min(selected, execution.batch_concurrency_max))


def get_uat_base_url(scheme: str = "http") -> str:
    config = get_uat_config()
    return f"{scheme}://{config.host}:{config.port}"


def get_server_base_url(scheme: str = "http") -> str:
    config = get_server_config()
    return f"{scheme}://{config.host}:{config.port}"
