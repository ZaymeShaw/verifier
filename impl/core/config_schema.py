from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse


ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
ROLE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
SUPPORTED_LLM_PROVIDERS = frozenset({"deepseek"})
SUPPORTED_EMBEDDING_PROVIDERS = frozenset({"bailian"})


class ConfigError(ValueError):
    """Raised when verifier runtime configuration violates the public contract."""


class _UniqueKeyLoaderError(ConfigError):
    pass


def _mapping(value: Any, field_path: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"invalid field {field_path}: expected mapping")
    return dict(value)


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], field_path: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        path = f"{field_path}.{unknown[0]}" if field_path else unknown[0]
        raise ConfigError(f"unknown field {path}")


def _required(data: Mapping[str, Any], name: str, field_path: str) -> Any:
    if name not in data:
        path = f"{field_path}.{name}" if field_path else name
        raise ConfigError(f"missing required field {path}")
    return data[name]


def _string(value: Any, field_path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"invalid field {field_path}: expected non-empty string")
    return value.strip()


def _optional_string(value: Any, field_path: str) -> Optional[str]:
    if value is None:
        return None
    return _string(value, field_path)


def _integer(value: Any, field_path: str, *, minimum: int, maximum: Optional[int] = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"invalid field {field_path}: expected integer")
    if value < minimum or (maximum is not None and value > maximum):
        suffix = f" between {minimum} and {maximum}" if maximum is not None else f" >= {minimum}"
        raise ConfigError(f"invalid field {field_path}: expected integer{suffix}")
    return value


def _number(value: Any, field_path: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"invalid field {field_path}: expected number")
    number = float(value)
    if number < minimum:
        raise ConfigError(f"invalid field {field_path}: expected number >= {minimum}")
    return number


def _boolean(value: Any, field_path: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"invalid field {field_path}: expected boolean")
    return value


def _url(value: Any, field_path: str) -> str:
    text = _string(value, field_path)
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"invalid field {field_path}: expected http(s) URL")
    return text


def _choice(value: Any, field_path: str, choices: frozenset[str]) -> str:
    text = _string(value, field_path)
    if text not in choices:
        raise ConfigError(f"invalid field {field_path}: unsupported value {text!r}; expected one of {sorted(choices)}")
    return text


@dataclass(frozen=True)
class ConfigValueSource:
    kind: str
    name: str
    secret: bool = False


@dataclass(frozen=True)
class EnvironmentVariableSpec:
    name: str
    bind: str
    type: str
    required: bool
    secret: bool
    description: str


@dataclass(frozen=True)
class EnvironmentRegistry:
    variables: Mapping[str, EnvironmentVariableSpec]

    def accepted_names(self) -> frozenset[str]:
        return frozenset(self.variables)


@dataclass(frozen=True)
class PythonConfig:
    executable: str


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int


@dataclass(frozen=True)
class UatConfig:
    host: str
    port: int


@dataclass(frozen=True)
class BrowserConfig:
    driver_path: str


@dataclass(frozen=True)
class LlmRolePolicy:
    provider: str
    model: str
    base_url: str
    temperature: float
    reasoning_effort: str


@dataclass(frozen=True)
class LlmRolePolicyOverride:
    provider: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    temperature: Optional[float] = None
    reasoning_effort: Optional[str] = None


@dataclass(frozen=True)
class LlmConfig:
    provider: str
    model: str
    base_url: str
    api_key: str
    temperature: float
    reasoning_effort: str
    max_attempts: int
    retry_delay_seconds: float
    role_policies: Mapping[str, LlmRolePolicyOverride] = field(default_factory=dict)

    def policy_for(self, role: str) -> LlmRolePolicy:
        override = self.role_policies.get(str(role or ""), LlmRolePolicyOverride())
        return LlmRolePolicy(
            provider=override.provider or self.provider,
            model=override.model or self.model,
            base_url=override.base_url or self.base_url,
            temperature=self.temperature if override.temperature is None else override.temperature,
            reasoning_effort=override.reasoning_effort or self.reasoning_effort,
        )


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str
    model: str
    api_key: str
    dimensions: int
    retrieval_top_k: int
    trust_env_proxy: bool


@dataclass(frozen=True)
class ExecutionConfig:
    case_retry_attempts: int
    batch_concurrency_default: int
    batch_concurrency_max: int
    batch_event_history_limit: int


@dataclass(frozen=True)
class ContextConfig:
    data_root: str
    store_root: str
    max_records_per_project: int
    candidate_limit: int
    load_limit: int
    content_char_budget: int
    query_limit: int
    top_k_per_query: int


@dataclass(frozen=True)
class JudgeConfig:
    raw_response_max_chars: int


@dataclass(frozen=True)
class RuntimeConfig:
    schema_version: int
    python: PythonConfig
    server: ServerConfig
    uat: UatConfig
    browser: BrowserConfig
    llm: LlmConfig
    embedding: EmbeddingConfig
    execution: ExecutionConfig
    context: ContextConfig
    judge: JudgeConfig
    environment: EnvironmentRegistry
    sources: Mapping[str, ConfigValueSource]
    warnings: tuple[str, ...] = ()
    missing_required: tuple[str, ...] = ()

    def source_for(self, field_path: str) -> ConfigValueSource:
        try:
            return self.sources[field_path]
        except KeyError as exc:
            raise ConfigError(f"no resolved source for field {field_path}") from exc

    def require(self, component: str) -> None:
        prefix = f"{component}."
        missing = [path for path in self.missing_required if path == component or path.startswith(prefix)]
        if missing:
            raise ConfigError(f"missing required configuration for {component}: {', '.join(missing)}")

    def redacted_dict(self) -> Dict[str, Any]:
        role_policies = {
            role: {
                key: value
                for key, value in {
                    "provider": policy.provider,
                    "model": policy.model,
                    "base_url": policy.base_url,
                    "temperature": policy.temperature,
                    "reasoning_effort": policy.reasoning_effort,
                }.items()
                if value is not None
            }
            for role, policy in sorted(self.llm.role_policies.items())
        }
        return {
            "schema_version": self.schema_version,
            "python": {"executable": self.python.executable},
            "server": {"host": self.server.host, "port": self.server.port},
            "uat": {"host": self.uat.host, "port": self.uat.port},
            "browser": {"driver_path": self.browser.driver_path},
            "llm": {
                "provider": self.llm.provider,
                "model": self.llm.model,
                "base_url": self.llm.base_url,
                "api_key": "***" if self.llm.api_key else "",
                "temperature": self.llm.temperature,
                "reasoning_effort": self.llm.reasoning_effort,
                "max_attempts": self.llm.max_attempts,
                "retry_delay_seconds": self.llm.retry_delay_seconds,
                "role_policies": role_policies,
            },
            "embedding": {
                "provider": self.embedding.provider,
                "model": self.embedding.model,
                "api_key": "***" if self.embedding.api_key else "",
                "dimensions": self.embedding.dimensions,
                "retrieval_top_k": self.embedding.retrieval_top_k,
                "trust_env_proxy": self.embedding.trust_env_proxy,
            },
            "execution": {
                "case_retry_attempts": self.execution.case_retry_attempts,
                "batch_concurrency_default": self.execution.batch_concurrency_default,
                "batch_concurrency_max": self.execution.batch_concurrency_max,
                "batch_event_history_limit": self.execution.batch_event_history_limit,
            },
            "context": {
                "data_root": self.context.data_root,
                "store_root": self.context.store_root,
                "max_records_per_project": self.context.max_records_per_project,
                "candidate_limit": self.context.candidate_limit,
                "load_limit": self.context.load_limit,
                "content_char_budget": self.context.content_char_budget,
                "query_limit": self.context.query_limit,
                "top_k_per_query": self.context.top_k_per_query,
            },
            "judge": {"raw_response_max_chars": self.judge.raw_response_max_chars},
            "sources": {
                path: {"kind": source.kind, "name": source.name, "secret": source.secret}
                for path, source in sorted(self.sources.items())
            },
            "warnings": list(self.warnings),
            "missing_required": list(self.missing_required),
        }

    def fingerprint(self) -> str:
        payload = json.dumps(self.redacted_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:12]


@dataclass(frozen=True)
class ParsedRuntimeConfig:
    schema_version: int
    python: PythonConfig
    server: ServerConfig
    uat: UatConfig
    browser: BrowserConfig
    llm: LlmConfig
    embedding: EmbeddingConfig
    execution: ExecutionConfig
    context: ContextConfig
    judge: JudgeConfig
    environment: EnvironmentRegistry


def load_yaml_document(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"runtime config not found: {path}")
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment contract
        raise ConfigError("runtime config requires PyYAML") from exc

    class UniqueKeyLoader(yaml.SafeLoader):
        pass

    def construct_mapping(loader: Any, node: Any, deep: bool = False) -> Dict[str, Any]:
        mapping: Dict[str, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in mapping:
                raise _UniqueKeyLoaderError(f"duplicate key {key!r} at line {key_node.start_mark.line + 1}")
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    UniqueKeyLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_mapping,
    )
    try:
        loaded = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigError(f"failed to parse {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ConfigError(f"invalid {path}: expected mapping at document root")
    return dict(loaded)


def parse_runtime_document(data: Mapping[str, Any]) -> ParsedRuntimeConfig:
    root = _mapping(data, "config")
    _reject_unknown(
        root,
        {"schema_version", "python", "server", "uat", "browser", "llm", "embedding", "execution", "context", "judge", "environment"},
        "",
    )
    schema_version = _integer(_required(root, "schema_version", ""), "schema_version", minimum=1, maximum=1)

    python_data = _mapping(_required(root, "python", ""), "python")
    _reject_unknown(python_data, {"executable"}, "python")
    python = PythonConfig(executable=_string(_required(python_data, "executable", "python"), "python.executable"))

    server_data = _mapping(_required(root, "server", ""), "server")
    _reject_unknown(server_data, {"host", "port"}, "server")
    server = ServerConfig(
        host=_string(_required(server_data, "host", "server"), "server.host"),
        port=_integer(_required(server_data, "port", "server"), "server.port", minimum=1, maximum=65535),
    )

    uat_data = _mapping(_required(root, "uat", ""), "uat")
    _reject_unknown(uat_data, {"host", "port"}, "uat")
    uat = UatConfig(
        host=_string(_required(uat_data, "host", "uat"), "uat.host"),
        port=_integer(_required(uat_data, "port", "uat"), "uat.port", minimum=1, maximum=65535),
    )

    browser_data = _mapping(_required(root, "browser", ""), "browser")
    _reject_unknown(browser_data, {"driver_path"}, "browser")
    browser = BrowserConfig(
        driver_path=_string(
            _required(browser_data, "driver_path", "browser"),
            "browser.driver_path",
        )
    )

    llm_data = _mapping(_required(root, "llm", ""), "llm")
    _reject_unknown(
        llm_data,
        {
            "provider",
            "model",
            "base_url",
            "temperature",
            "reasoning_effort",
            "max_attempts",
            "retry_delay_seconds",
            "role_policies",
        },
        "llm",
    )
    role_policies = _parse_role_policies(llm_data.get("role_policies") or {})
    llm = LlmConfig(
        provider=_choice(
            _required(llm_data, "provider", "llm"),
            "llm.provider",
            SUPPORTED_LLM_PROVIDERS,
        ),
        model=_string(_required(llm_data, "model", "llm"), "llm.model"),
        base_url=_url(_required(llm_data, "base_url", "llm"), "llm.base_url"),
        api_key="",
        temperature=_number(_required(llm_data, "temperature", "llm"), "llm.temperature"),
        reasoning_effort=_string(_required(llm_data, "reasoning_effort", "llm"), "llm.reasoning_effort"),
        max_attempts=_integer(_required(llm_data, "max_attempts", "llm"), "llm.max_attempts", minimum=1),
        retry_delay_seconds=_number(
            _required(llm_data, "retry_delay_seconds", "llm"),
            "llm.retry_delay_seconds",
        ),
        role_policies=MappingProxyType(role_policies),
    )

    embedding_data = _mapping(_required(root, "embedding", ""), "embedding")
    _reject_unknown(
        embedding_data,
        {"provider", "model", "dimensions", "retrieval_top_k", "trust_env_proxy"},
        "embedding",
    )
    embedding = EmbeddingConfig(
        provider=_choice(
            _required(embedding_data, "provider", "embedding"),
            "embedding.provider",
            SUPPORTED_EMBEDDING_PROVIDERS,
        ),
        model=_string(_required(embedding_data, "model", "embedding"), "embedding.model"),
        api_key="",
        dimensions=_integer(
            _required(embedding_data, "dimensions", "embedding"),
            "embedding.dimensions",
            minimum=1,
        ),
        retrieval_top_k=_integer(
            _required(embedding_data, "retrieval_top_k", "embedding"),
            "embedding.retrieval_top_k",
            minimum=1,
        ),
        trust_env_proxy=_boolean(
            _required(embedding_data, "trust_env_proxy", "embedding"),
            "embedding.trust_env_proxy",
        ),
    )

    execution_data = _mapping(_required(root, "execution", ""), "execution")
    _reject_unknown(execution_data, {"case_retry_attempts", "batch_concurrency_default", "batch_concurrency_max", "batch_event_history_limit"}, "execution")
    execution = ExecutionConfig(
        case_retry_attempts=_integer(_required(execution_data, "case_retry_attempts", "execution"), "execution.case_retry_attempts", minimum=1),
        batch_concurrency_default=_integer(_required(execution_data, "batch_concurrency_default", "execution"), "execution.batch_concurrency_default", minimum=1),
        batch_concurrency_max=_integer(_required(execution_data, "batch_concurrency_max", "execution"), "execution.batch_concurrency_max", minimum=1),
        batch_event_history_limit=_integer(_required(execution_data, "batch_event_history_limit", "execution"), "execution.batch_event_history_limit", minimum=1),
    )
    if execution.batch_concurrency_default > execution.batch_concurrency_max:
        raise ConfigError("execution.batch_concurrency_default cannot exceed batch_concurrency_max")

    context_data = _mapping(_required(root, "context", ""), "context")
    _reject_unknown(context_data, {"data_root", "store_root", "max_records_per_project", "candidate_limit", "load_limit", "content_char_budget", "query_limit", "top_k_per_query"}, "context")
    context = ContextConfig(
        data_root=_string(_required(context_data, "data_root", "context"), "context.data_root"),
        store_root=_string(_required(context_data, "store_root", "context"), "context.store_root"),
        max_records_per_project=_integer(_required(context_data, "max_records_per_project", "context"), "context.max_records_per_project", minimum=1),
        candidate_limit=_integer(_required(context_data, "candidate_limit", "context"), "context.candidate_limit", minimum=1),
        load_limit=_integer(_required(context_data, "load_limit", "context"), "context.load_limit", minimum=1),
        content_char_budget=_integer(_required(context_data, "content_char_budget", "context"), "context.content_char_budget", minimum=1),
        query_limit=_integer(_required(context_data, "query_limit", "context"), "context.query_limit", minimum=1),
        top_k_per_query=_integer(_required(context_data, "top_k_per_query", "context"), "context.top_k_per_query", minimum=1),
    )

    judge_data = _mapping(_required(root, "judge", ""), "judge")
    _reject_unknown(judge_data, {"raw_response_max_chars"}, "judge")
    judge = JudgeConfig(
        raw_response_max_chars=_integer(_required(judge_data, "raw_response_max_chars", "judge"), "judge.raw_response_max_chars", minimum=1)
    )

    environment = _parse_environment(_required(root, "environment", ""))
    _validate_bindings(environment)
    return ParsedRuntimeConfig(
        schema_version=schema_version,
        python=python,
        server=server,
        uat=uat,
        browser=browser,
        llm=llm,
        embedding=embedding,
        execution=execution,
        context=context,
        judge=judge,
        environment=environment,
    )


def _parse_role_policies(value: Any) -> Dict[str, LlmRolePolicyOverride]:
    data = _mapping(value, "llm.role_policies")
    result: Dict[str, LlmRolePolicyOverride] = {}
    allowed = {"provider", "model", "base_url", "temperature", "reasoning_effort"}
    for role, raw_policy in data.items():
        if not isinstance(role, str) or not ROLE_NAME_PATTERN.fullmatch(role):
            raise ConfigError(f"invalid field llm.role_policies.{role}: expected snake_case role id")
        policy = _mapping(raw_policy, f"llm.role_policies.{role}")
        _reject_unknown(policy, allowed, f"llm.role_policies.{role}")
        if not policy:
            raise ConfigError(f"invalid field llm.role_policies.{role}: empty role policy")
        result[role] = LlmRolePolicyOverride(
            provider=(
                _choice(
                    policy["provider"],
                    f"llm.role_policies.{role}.provider",
                    SUPPORTED_LLM_PROVIDERS,
                )
                if "provider" in policy
                else None
            ),
            model=_optional_string(policy.get("model"), f"llm.role_policies.{role}.model"),
            base_url=_url(policy["base_url"], f"llm.role_policies.{role}.base_url") if "base_url" in policy else None,
            temperature=_number(policy["temperature"], f"llm.role_policies.{role}.temperature") if "temperature" in policy else None,
            reasoning_effort=_optional_string(
                policy.get("reasoning_effort"),
                f"llm.role_policies.{role}.reasoning_effort",
            ),
        )
    return result


def _parse_environment(value: Any) -> EnvironmentRegistry:
    environment_data = _mapping(value, "environment")
    _reject_unknown(environment_data, {"variables"}, "environment")
    variables_data = _mapping(_required(environment_data, "variables", "environment"), "environment.variables")
    variables: Dict[str, EnvironmentVariableSpec] = {}
    accepted_names: set[str] = set()
    for name, raw_variable in variables_data.items():
        if not isinstance(name, str) or not ENV_NAME_PATTERN.fullmatch(name):
            raise ConfigError(f"invalid environment variable name {name!r}")
        variable_data = _mapping(raw_variable, f"environment.variables.{name}")
        _reject_unknown(
            variable_data,
            {"bind", "type", "required", "secret", "description"},
            f"environment.variables.{name}",
        )
        variable = EnvironmentVariableSpec(
            name=name,
            bind=_string(_required(variable_data, "bind", f"environment.variables.{name}"), f"environment.variables.{name}.bind"),
            type=_string(_required(variable_data, "type", f"environment.variables.{name}"), f"environment.variables.{name}.type"),
            required=_boolean(_required(variable_data, "required", f"environment.variables.{name}"), f"environment.variables.{name}.required"),
            secret=_boolean(_required(variable_data, "secret", f"environment.variables.{name}"), f"environment.variables.{name}.secret"),
            description=_string(
                _required(variable_data, "description", f"environment.variables.{name}"),
                f"environment.variables.{name}.description",
            ),
        )
        if name in accepted_names:
            raise ConfigError(f"duplicate environment variable {name}")
        accepted_names.add(name)
        variables[name] = variable
    if not variables:
        raise ConfigError("invalid field environment.variables: expected non-empty mapping")
    return EnvironmentRegistry(variables=MappingProxyType(variables))


def _validate_bindings(environment: EnvironmentRegistry) -> None:
    allowed_bindings = {
        "python.executable",
        "server.host",
        "server.port",
        "uat.host",
        "uat.port",
        "browser.driver_path",
        "llm.provider",
        "llm.model",
        "llm.base_url",
        "llm.api_key",
        "llm.temperature",
        "llm.reasoning_effort",
        "llm.max_attempts",
        "llm.retry_delay_seconds",
        "embedding.provider",
        "embedding.model",
        "embedding.api_key",
        "embedding.dimensions",
        "embedding.retrieval_top_k",
        "embedding.trust_env_proxy",
        "context.data_root",
        "context.store_root",
    }
    seen_bindings: set[str] = set()
    supported_types = {"string", "integer", "number", "boolean", "path", "url"}
    for variable in environment.variables.values():
        if variable.bind not in allowed_bindings:
            raise ConfigError(f"invalid bind target for {variable.name}: {variable.bind}")
        if variable.bind in seen_bindings:
            raise ConfigError(f"multiple environment variables bind the same field: {variable.bind}")
        seen_bindings.add(variable.bind)
        if variable.type not in supported_types:
            raise ConfigError(f"unsupported environment type for {variable.name}: {variable.type}")
        if variable.secret and variable.bind not in {"llm.api_key", "embedding.api_key"}:
            raise ConfigError(f"secret variable {variable.name} cannot bind visible field {variable.bind}")


def convert_environment_value(variable: EnvironmentVariableSpec, raw_value: str) -> Any:
    field_path = f"environment variable {variable.name}"
    if variable.type == "string":
        if not raw_value.strip():
            raise ConfigError(f"invalid {field_path}: expected non-empty string")
        return raw_value.strip()
    if variable.type == "path":
        if not raw_value:
            raise ConfigError(f"invalid {field_path}: expected non-empty {variable.type}")
        return raw_value
    if variable.type == "url":
        return _url(raw_value, field_path)
    if variable.type == "integer":
        try:
            return _integer(int(raw_value), field_path, minimum=1)
        except ValueError as exc:
            raise ConfigError(f"invalid {field_path}: expected integer") from exc
    if variable.type == "number":
        try:
            return _number(float(raw_value), field_path)
        except ValueError as exc:
            raise ConfigError(f"invalid {field_path}: expected number") from exc
    if variable.type == "boolean":
        lowered = raw_value.lower()
        if lowered not in {"true", "false"}:
            raise ConfigError(f"invalid {field_path}: expected true or false")
        return lowered == "true"
    raise ConfigError(f"unsupported environment type for {variable.name}: {variable.type}")
