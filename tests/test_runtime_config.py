from __future__ import annotations

import pytest

from impl.core import config as runtime_config


def test_runtime_config_loads_defaults(monkeypatch):
    for name in (
        "PYTHON_EXECUTABLE",
        "VERIFIER_HOST",
        "VERIFIER_PORT",
        "VERIFIER_UAT_HOST",
        "VERIFIER_UAT_PORT",
        "LLM_PROVIDER",
        "LLM_MODEL",
        "LLM_BASE_URL",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_API_KEY",
        "LLM_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(runtime_config, "ENV_MD_PATH", runtime_config.ROOT / "missing-env.md")

    loaded = runtime_config.get_runtime_config()

    assert loaded.python.executable == "python"
    assert loaded.server.host == "127.0.0.1"
    assert loaded.server.port == 8020
    assert loaded.uat.host == "127.0.0.1"
    assert loaded.uat.port == 8021
    assert loaded.llm.provider == "deepseek"
    assert loaded.llm.model == "deepseek-v4-pro"
    assert loaded.llm.base_url == "https://api.deepseek.com/v1/chat/completions"
    assert loaded.llm.api_key_env == ("DEEPSEEK_API_KEY", "LLM_API_KEY")
    assert loaded.llm.api_key == ""


def test_runtime_config_env_overrides(monkeypatch):
    monkeypatch.setenv("PYTHON_EXECUTABLE", "/tmp/python")
    monkeypatch.setenv("VERIFIER_HOST", "0.0.0.0")
    monkeypatch.setenv("VERIFIER_PORT", "18020")
    monkeypatch.setenv("VERIFIER_UAT_HOST", "localhost")
    monkeypatch.setenv("VERIFIER_UAT_PORT", "18021")
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.setenv("LLM_MODEL", "custom-model")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://deepseek.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "fallback-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "primary-key")

    loaded = runtime_config.get_runtime_config()

    assert loaded.python.executable == "/tmp/python"
    assert loaded.server.host == "0.0.0.0"
    assert loaded.server.port == 18020
    assert loaded.uat.host == "localhost"
    assert loaded.uat.port == 18021
    assert loaded.llm.provider == "custom"
    assert loaded.llm.model == "custom-model"
    assert loaded.llm.base_url == "https://deepseek.example/v1"
    assert loaded.llm.api_key == "primary-key"


def test_runtime_config_invalid_port(monkeypatch):
    monkeypatch.setenv("VERIFIER_PORT", "not-a-port")

    with pytest.raises(runtime_config.ConfigError, match="server.port"):
        runtime_config.get_runtime_config()


def test_uat_base_url_uses_uat_config(monkeypatch):
    monkeypatch.setenv("VERIFIER_UAT_HOST", "localhost")
    monkeypatch.setenv("VERIFIER_UAT_PORT", "19090")

    assert runtime_config.get_uat_base_url() == "http://localhost:19090"
