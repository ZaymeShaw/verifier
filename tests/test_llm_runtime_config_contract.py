from __future__ import annotations

from pathlib import Path

import pytest

from impl.core import llm_client as llm_module
from impl.core.config import ConfigError, resolve_runtime_config
from impl.core.llm_client import LlmClient, chat_completions_url
from impl.core.structured_output import FREE_TEXT_OUTPUT


def _resolved(tmp_path: Path, *, model: str = "deepseek-v4-flash", api_key: str = ""):
    source = Path(__file__).resolve().parents[1] / "impl" / "config.yaml"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        source.read_text(encoding="utf-8").replace("model: deepseek-v4-pro", f"model: {model}", 1),
        encoding="utf-8",
    )
    environ = {"DEEPSEEK_API_KEY": api_key} if api_key else {}
    return resolve_runtime_config(
        config_path=config_path,
        dotenv_path=tmp_path / ".env",
        environ=environ,
    )


def test_llm_client_inherits_resolved_public_model(tmp_path):
    resolved = _resolved(tmp_path, api_key="test-key")

    client = LlmClient(config=resolved.llm)

    assert client.model == "deepseek-v4-flash"
    assert client.protocol == "openai_compatible"
    assert client.base_url == resolved.llm.base_url
    assert client.temperature == resolved.llm.temperature
    assert client.max_attempts == resolved.llm.max_attempts
    assert client.request_timeout_seconds == resolved.llm.request_timeout_seconds


def test_llm_role_policy_stays_explicit_when_public_model_changes(tmp_path):
    resolved = _resolved(tmp_path, api_key="test-key")

    client = LlmClient(config=resolved.llm, role="live_stub")

    assert client.model == "deepseek-chat"
    assert client.reasoning_effort == "low"


def test_llm_client_fails_before_request_when_required_credential_is_missing(tmp_path):
    resolved = _resolved(tmp_path)
    client = LlmClient(config=resolved.llm)

    with pytest.raises(ConfigError, match="llm.api_key"):
        client.complete_json("system", "user", output_spec=FREE_TEXT_OUTPUT)


def test_llm_client_builds_openai_compatible_model_with_explicit_credential(tmp_path, monkeypatch):
    captured = {}

    def fake_openai_like(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(llm_module, "OpenAILike", fake_openai_like)
    resolved = _resolved(tmp_path, api_key="explicit-deepseek-key")
    client = LlmClient(config=resolved.llm)

    client.build_model()

    assert captured["id"] == "deepseek-v4-flash"
    assert captured["provider"] == "deepseek"
    assert captured["api_key"] == "explicit-deepseek-key"
    assert captured["base_url"] == "https://api.deepseek.com/v1"
    assert captured["timeout"] == 120
    assert captured["supports_native_structured_outputs"] is False
    assert captured["supports_json_schema_outputs"] is False


def test_llm_client_blocks_undeclared_model_capabilities(tmp_path):
    source = Path(__file__).resolve().parents[1] / "impl" / "config.yaml"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        source.read_text(encoding="utf-8").replace("json_mode: true", "json_mode: false", 1),
        encoding="utf-8",
    )
    resolved = resolve_runtime_config(
        config_path=config_path,
        dotenv_path=tmp_path / ".env",
        environ={"DEEPSEEK_API_KEY": "test-key"},
    )

    with pytest.raises(ConfigError, match="json_mode"):
        LlmClient(config=resolved.llm).complete_json("system", "user", output_spec=FREE_TEXT_OUTPUT)


def test_chat_completions_url_is_derived_from_api_root():
    assert (
        chat_completions_url("https://api.deepseek.com/v1/")
        == "https://api.deepseek.com/v1/chat/completions"
    )
