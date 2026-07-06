from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "impl" / "config.yaml"
ENV_MD_PATH = ROOT / "env.md"

DEFAULT_PYTHON_EXECUTABLE = "python"
DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_SERVER_PORT = 8020
DEFAULT_UAT_HOST = "127.0.0.1"
DEFAULT_UAT_PORT = 8021
DEFAULT_LLM_PROVIDER = "deepseek"
DEFAULT_LLM_MODEL = "deepseek-v4-pro"
DEFAULT_LLM_BASE_URL = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_LLM_API_KEY_ENV = ["DEEPSEEK_API_KEY", "LLM_API_KEY"]


class ConfigError(ValueError):
    """Raised when runtime configuration is malformed."""


@dataclass(frozen=True)
class PythonConfig:
    executable: str = DEFAULT_PYTHON_EXECUTABLE


@dataclass(frozen=True)
class ServerConfig:
    host: str = DEFAULT_SERVER_HOST
    port: int = DEFAULT_SERVER_PORT


@dataclass(frozen=True)
class UatConfig:
    host: str = DEFAULT_UAT_HOST
    port: int = DEFAULT_UAT_PORT


@dataclass(frozen=True)
class LlmConfig:
    provider: str = DEFAULT_LLM_PROVIDER
    model: str = DEFAULT_LLM_MODEL
    base_url: str = DEFAULT_LLM_BASE_URL
    api_key_env: tuple[str, ...] = tuple(DEFAULT_LLM_API_KEY_ENV)
    api_key: str = ""


@dataclass(frozen=True)
class RuntimeConfig:
    python: PythonConfig
    server: ServerConfig
    uat: UatConfig
    llm: LlmConfig


def _load_yaml_config(path: Path = CONFIG_PATH) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise ConfigError("Runtime config requires PyYAML. Install pyyaml before loading impl/config.yaml.") from exc
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ConfigError(f"Failed to parse {path}: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError(f"Invalid {path}: expected a mapping at the top level.")
    return loaded


def _section(data: Dict[str, Any], name: str) -> Dict[str, Any]:
    value = data.get(name) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"Invalid config {name}: expected a mapping.")
    return value


def _string_value(value: Any, default: str, field: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        raise ConfigError(f"Invalid config {field}: expected a non-empty string.")
    return text


def _env_string(name: str, current: str) -> str:
    value = os.environ.get(name)
    return current if value is None or value == "" else value


def _port_value(value: Any, default: int, field: str) -> int:
    if value is None:
        return default
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid config {field}: expected port between 1 and 65535.") from exc
    if port < 1 or port > 65535:
        raise ConfigError(f"Invalid config {field}: expected port between 1 and 65535.")
    return port


def _env_port(name: str, current: int, field: str) -> int:
    value = os.environ.get(name)
    return current if value is None or value == "" else _port_value(value, current, field)


def _api_key_env(value: Any) -> List[str]:
    if value is None:
        return list(DEFAULT_LLM_API_KEY_ENV)
    if not isinstance(value, list):
        raise ConfigError("Invalid config llm.api_key_env: expected a list of non-empty strings.")
    names = []
    for item in value:
        name = str(item).strip()
        if not name:
            raise ConfigError("Invalid config llm.api_key_env: expected a list of non-empty strings.")
        names.append(name)
    if not names:
        raise ConfigError("Invalid config llm.api_key_env: expected a list of non-empty strings.")
    return names


def load_env_md_value(prefixes: Any, path: Optional[Path] = None) -> str:
    if path is None:
        path = ENV_MD_PATH
    if not path.exists():
        return ""
    normalized = tuple(prefix.lower() for prefix in prefixes)
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        lowered = line.lower()
        if not lowered.startswith(normalized):
            continue
        if "：" in line:
            return line.split("：", 1)[1].strip()
        if ":" in line:
            return line.split(":", 1)[1].strip()
    return ""


def load_env_md_key() -> str:
    return load_env_md_value(("deepseek key",))


def load_bailian_env_md_key() -> str:
    return load_env_md_value(("百炼key",))


def _resolve_api_key(names: List[str]) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return load_env_md_key()


def get_runtime_config() -> RuntimeConfig:
    data = _load_yaml_config()

    python_data = _section(data, "python")
    server_data = _section(data, "server")
    uat_data = _section(data, "uat")
    llm_data = _section(data, "llm")

    python_executable = _env_string(
        "PYTHON_EXECUTABLE",
        _string_value(python_data.get("executable"), DEFAULT_PYTHON_EXECUTABLE, "python.executable"),
    )

    server_host = _env_string(
        "VERIFIER_HOST",
        _string_value(server_data.get("host"), DEFAULT_SERVER_HOST, "server.host"),
    )
    server_port = _env_port(
        "VERIFIER_PORT",
        _port_value(server_data.get("port"), DEFAULT_SERVER_PORT, "server.port"),
        "server.port",
    )

    uat_host = _env_string(
        "VERIFIER_UAT_HOST",
        _string_value(uat_data.get("host"), DEFAULT_UAT_HOST, "uat.host"),
    )
    uat_port = _env_port(
        "VERIFIER_UAT_PORT",
        _port_value(uat_data.get("port"), DEFAULT_UAT_PORT, "uat.port"),
        "uat.port",
    )

    api_key_env = _api_key_env(llm_data.get("api_key_env"))
    llm_provider = _env_string(
        "LLM_PROVIDER",
        _string_value(llm_data.get("provider"), DEFAULT_LLM_PROVIDER, "llm.provider"),
    )
    llm_model = _env_string(
        "LLM_MODEL",
        _string_value(llm_data.get("model"), DEFAULT_LLM_MODEL, "llm.model"),
    )
    llm_base_url = _string_value(llm_data.get("base_url"), DEFAULT_LLM_BASE_URL, "llm.base_url")
    llm_base_url = _env_string("LLM_BASE_URL", llm_base_url)
    llm_base_url = _env_string("DEEPSEEK_BASE_URL", llm_base_url)

    return RuntimeConfig(
        python=PythonConfig(executable=python_executable),
        server=ServerConfig(host=server_host, port=server_port),
        uat=UatConfig(host=uat_host, port=uat_port),
        llm=LlmConfig(
            provider=llm_provider,
            model=llm_model,
            base_url=llm_base_url,
            api_key_env=tuple(api_key_env),
            api_key=_resolve_api_key(api_key_env),
        ),
    )


def get_python_config() -> PythonConfig:
    return get_runtime_config().python


def get_server_config() -> ServerConfig:
    return get_runtime_config().server


def get_uat_config() -> UatConfig:
    return get_runtime_config().uat


def get_llm_config() -> LlmConfig:
    return get_runtime_config().llm


def get_uat_base_url(scheme: str = "http") -> str:
    config = get_uat_config()
    return f"{scheme}://{config.host}:{config.port}"
