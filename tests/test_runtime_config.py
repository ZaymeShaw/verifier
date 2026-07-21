from __future__ import annotations

import pytest

from impl.core import config as runtime_config


PUBLIC_ENV_NAMES = (
    "PYTHON_EXECUTABLE",
    "VERIFIER_HOST",
    "VERIFIER_PORT",
    "VERIFIER_UAT_HOST",
    "VERIFIER_UAT_PORT",
    "CHROMEDRIVER_PATH",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_BASE_URL",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_API_KEY",
    "LLM_API_KEY",
    "OPENAI_API_KEY",
    "BAILIAN_API_KEY",
    "DASHSCOPE_API_KEY",
    "BAILIAN_EMBEDDING_MODEL",
    "BAILIAN_EMBEDDING_TRUST_ENV_PROXY",
)


@pytest.fixture(autouse=True)
def isolated_runtime_config(monkeypatch, tmp_path):
    for name in PUBLIC_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(runtime_config, "DOTENV_PATH", tmp_path / ".env")
    runtime_config.reset_runtime_config_for_tests()
    yield
    runtime_config.reset_runtime_config_for_tests()


def test_runtime_config_loads_yaml_defaults():
    loaded = runtime_config.get_runtime_config()

    assert loaded.schema_version == 1
    assert loaded.python.executable == "python"
    assert loaded.server.host == "127.0.0.1"
    assert loaded.server.port == 8020
    assert loaded.uat.host == "127.0.0.1"
    assert loaded.uat.port == 8021
    assert loaded.browser.driver_path == "chromedriver"
    assert loaded.llm.protocol == "openai_compatible"
    assert loaded.llm.provider == "deepseek"
    assert loaded.llm.model == "deepseek-v4-pro"
    assert loaded.llm.base_url == "https://api.deepseek.com/v1"
    assert loaded.llm.api_key == ""
    assert loaded.embedding.model == "text-embedding-v4"


def test_runtime_config_registered_env_overrides(monkeypatch):
    monkeypatch.setenv("PYTHON_EXECUTABLE", "/tmp/python")
    monkeypatch.setenv("VERIFIER_HOST", "0.0.0.0")
    monkeypatch.setenv("VERIFIER_PORT", "18020")
    monkeypatch.setenv("VERIFIER_UAT_HOST", "localhost")
    monkeypatch.setenv("VERIFIER_UAT_PORT", "18021")
    monkeypatch.setenv("CHROMEDRIVER_PATH", "/tmp/chromedriver")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM_MODEL", "custom-model")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "primary-key")

    loaded = runtime_config.get_runtime_config()

    assert loaded.python.executable == "/tmp/python"
    assert loaded.server.host == "0.0.0.0"
    assert loaded.server.port == 18020
    assert loaded.uat.host == "localhost"
    assert loaded.uat.port == 18021
    assert loaded.browser.driver_path == "/tmp/chromedriver"
    assert loaded.llm.provider == "deepseek"
    assert loaded.llm.model == "custom-model"
    assert loaded.llm.base_url == "https://llm.example/v1"
    assert loaded.llm.api_key == "primary-key"


def test_runtime_config_invalid_port(monkeypatch):
    monkeypatch.setenv("VERIFIER_PORT", "not-a-port")

    with pytest.raises(runtime_config.ConfigError, match="VERIFIER_PORT"):
        runtime_config.get_runtime_config()


def test_runtime_config_rejects_unimplemented_provider_override(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "unimplemented-provider")

    with pytest.raises(runtime_config.ConfigError, match="llm.provider.*unsupported"):
        runtime_config.get_runtime_config()


def test_uat_base_url_uses_uat_config(monkeypatch):
    monkeypatch.setenv("VERIFIER_UAT_HOST", "localhost")
    monkeypatch.setenv("VERIFIER_UAT_PORT", "19090")

    assert runtime_config.get_uat_base_url() == "http://localhost:19090"


def test_runtime_config_is_frozen_for_process_lifetime(monkeypatch):
    first = runtime_config.get_runtime_config()
    monkeypatch.setenv("LLM_MODEL", "changed-after-start")

    assert runtime_config.get_runtime_config() is first
    assert runtime_config.get_runtime_config().llm.model == "deepseek-v4-pro"


def test_runtime_initialization_does_not_mutate_openai_api_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    loaded = runtime_config.get_runtime_config()

    assert loaded.llm.api_key == "deepseek-key"
    assert loaded.llm.protocol == "openai_compatible"
    assert "OPENAI_API_KEY" not in runtime_config.os.environ
