from __future__ import annotations

import os
import threading
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional

from .config_bootstrap import parse_dotenv
from .config_schema import (
    BrowserConfig,
    ConfigError,
    ConfigValueSource,
    ContextConfig,
    EmbeddingConfig,
    EnvironmentVariableSpec,
    ExecutionConfig,
    JudgeConfig,
    LlmConfig,
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

    missing_required = tuple(
        sorted(
            variable.bind
            for variable in parsed.environment.variables.values()
            if variable.required and values.get(variable.bind) in {None, ""}
        )
    )
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
            max_attempts=int(values["llm.max_attempts"]),
            retry_delay_seconds=float(values["llm.retry_delay_seconds"]),
            role_policies=parsed.llm.role_policies,
        ),
        embedding=EmbeddingConfig(
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
        "llm.max_attempts": parsed.llm.max_attempts,
        "llm.retry_delay_seconds": parsed.llm.retry_delay_seconds,
        "embedding.provider": parsed.embedding.provider,
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
    }


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


def get_uat_base_url(scheme: str = "http") -> str:
    config = get_uat_config()
    return f"{scheme}://{config.host}:{config.port}"


def get_server_base_url(scheme: str = "http") -> str:
    config = get_server_config()
    return f"{scheme}://{config.host}:{config.port}"
