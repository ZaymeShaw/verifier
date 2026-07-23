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
    "EMBEDDING_ENABLED",
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
    assert loaded.llm.request_timeout_seconds == 120
    assert loaded.llm.capabilities.json_mode is True
    assert loaded.llm.capabilities.tool_calls is True
    assert loaded.attribute.finalization_prompt_char_budget == 160000
    assert loaded.attribute.review_prompt_char_budget == 180000
    assert loaded.attribute.tool_call_limit == 8
    assert loaded.attribute.investigation_error_chars == 2000
    assert loaded.attribute.compaction.trace_output_chars == 10000
    assert loaded.attribute.compaction.list_item_limit == 20
    assert loaded.embedding.model == "text-embedding-v4"
    assert loaded.embedding.enabled is True
    assert "embedding.api_key" in loaded.missing_required


def test_embedding_secret_is_conditionally_required(monkeypatch):
    monkeypatch.setenv("EMBEDDING_ENABLED", "false")

    loaded = runtime_config.get_runtime_config()

    assert loaded.embedding.enabled is False
    assert "embedding.api_key" not in loaded.missing_required


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


def test_runtime_config_overrides_live_stub_model_via_env(monkeypatch):
    monkeypatch.setenv("LLM_LIVE_STUB_MODEL", "cheap-stub-model")

    loaded = runtime_config.get_runtime_config()

    policy = loaded.llm.policy_for("live_stub")
    assert policy.model == "cheap-stub-model"
    assert policy.reasoning_effort == "low"
    assert loaded.llm.policy_for("judge").model == "deepseek-v4-pro"


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


def test_batch_concurrency_uses_configured_default_and_max(monkeypatch):
    configured = runtime_config.get_runtime_config()

    assert runtime_config.resolve_batch_concurrency() == configured.execution.batch_concurrency_default
    assert runtime_config.resolve_batch_concurrency(1000) == configured.execution.batch_concurrency_max
    assert runtime_config.resolve_batch_concurrency(0) == 1
