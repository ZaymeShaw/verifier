from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from impl.core import llm_client as llm_module
from impl.core.config import ConfigError, resolve_runtime_config
from impl.core.config_schema import LlmFallback
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
    assert client.request_timeout_seconds == resolved.llm.request_timeout_seconds


def test_llm_clients_share_router_health_for_identical_endpoint_pool(tmp_path):
    resolved = _resolved(tmp_path, model="shared-router-model", api_key="primary-key")
    config = replace(
        resolved.llm,
        fallbacks=(
            LlmFallback(
                base_url="https://fallback.example.test/v1",
                model="fallback-model",
                api_key="fallback-key",
            ),
        ),
    )

    first = LlmClient(config=config)
    second = LlmClient(config=config)

    assert first.llm_router is second.llm_router
    primary = first.llm_router.endpoints[0]
    first.llm_router.record_failure(primary)
    first.llm_router.record_failure(primary)
    assert second.llm_router.select().name == "fallback1"

    different = LlmClient(config=replace(config, model="different-router-model"))
    assert different.llm_router is not first.llm_router


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
    assert captured["base_url"] == resolved.llm.base_url
    assert captured["timeout"] == resolved.llm.request_timeout_seconds
    assert captured["max_retries"] == 0
    assert captured["supports_native_structured_outputs"] is False
    assert captured["supports_json_schema_outputs"] is False


def test_bypass_proxy_for_loopback_keeps_remote_proxy(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "example.com")
    monkeypatch.setenv("no_proxy", "")
    llm_module._bypass_proxy_for_loopback()
    assert "127.0.0.1" in llm_module.os.environ["NO_PROXY"].split(",")
    assert "localhost" in llm_module.os.environ["NO_PROXY"].split(",")
    assert "example.com" in llm_module.os.environ["NO_PROXY"].split(",")
    assert "127.0.0.1" in llm_module.os.environ["no_proxy"].split(",")


@pytest.mark.parametrize('temperature', [0, 1, 0.3])
def test_endpoint_probe_uses_real_short_completion(monkeypatch, temperature):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            message = type("Message", (), {"content": "OK"})()
            choice = type("Choice", (), {"message": message, "finish_reason": "stop"})()
            return type("Response", (), {"choices": [choice]})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

        def close(self):
            captured['closed'] = True

    monkeypatch.setattr(llm_module, "OpenAI", FakeOpenAI)
    endpoint = llm_module.LlmEndpoint(
        name="primary",
        base_url="https://example.test/v1",
        model="test-model",
        api_key="test-key",
        temperature=temperature,
    )

    assert LlmClient._endpoint_probe(endpoint) is True
    assert captured["model"] == "test-model"
    assert captured["max_tokens"] == 4
    assert captured["temperature"] == temperature
    assert "Health probe" in captured["messages"][0]["content"]
    # 探活 HTTP 超时必须与路由器等待探活结果的时长一致，否则 HTTP 层先超时仍会被记成端点不健康
    assert captured["client"]["timeout"] == llm_module.DEFAULT_PROBE_WAIT_SECONDS
    assert captured['closed']


def test_endpoint_probe_accepts_reasoning_token_as_generation_evidence(monkeypatch):
    class FakeCompletions:
        def create(self, **kwargs):
            message = type(
                "Message",
                (),
                {"content": "", "reasoning_content": "We need answer."},
            )()
            choice = type(
                "Choice", (), {"message": message, "finish_reason": "length"}
            )()
            return type("Response", (), {"choices": [choice]})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

        def close(self):
            pass

    monkeypatch.setattr(llm_module, "OpenAI", FakeOpenAI)
    endpoint = llm_module.LlmEndpoint(
        name="primary",
        base_url="https://example.test/v1",
        model="reasoning-model",
        api_key="test-key",
    )

    assert LlmClient._endpoint_probe(endpoint) is True


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


def test_openai_like_adapter_canonicalizes_exact_registered_logical_tool_id(monkeypatch):
    from agno.models.openai.like import OpenAILike
    from impl.core.llm_client import _parse_tool_calls_with_aliases

    parsed = [{"type": "function", "function": {"name": "investigation.search_index", "arguments": "{}"}}]
    # 真实 agno 2.3.21 的 OpenAIChat.parse_tool_calls 是 @staticmethod（只收 tool_calls_data），
    # 替身必须同形，否则锁的是"必须传 self"的旧假设。
    monkeypatch.setattr(OpenAILike, "parse_tool_calls", staticmethod(lambda data: parsed))
    model = OpenAILike(id="test", api_key="test", base_url="http://localhost/v1")
    model.logical_tool_aliases = {"investigation.search_index": "investigation_search_index"}

    result = _parse_tool_calls_with_aliases(model, [])

    assert result[0]["function"]["name"] == "investigation_search_index"


def test_openai_like_adapter_does_not_fuzz_unknown_tool_name(monkeypatch):
    from agno.models.openai.like import OpenAILike
    from impl.core.llm_client import _parse_tool_calls_with_aliases

    parsed = [{"type": "function", "function": {"name": "investigation.search-index", "arguments": "{}"}}]
    # 真实 agno 2.3.21 的 OpenAIChat.parse_tool_calls 是 @staticmethod（只收 tool_calls_data），
    # 替身必须同形，否则锁的是"必须传 self"的旧假设。
    monkeypatch.setattr(OpenAILike, "parse_tool_calls", staticmethod(lambda data: parsed))
    model = OpenAILike(id="test", api_key="test", base_url="http://localhost/v1")
    model.logical_tool_aliases = {"investigation.search_index": "investigation_search_index"}

    result = _parse_tool_calls_with_aliases(model, [])

    assert result[0]["function"]["name"] == "investigation.search-index"
