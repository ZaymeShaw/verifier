from __future__ import annotations

from pathlib import Path

import pytest

from impl.core.config import ConfigError, resolve_runtime_config
from impl.core.llm_client import LlmClient
from impl.core.structured_output import FREE_TEXT_OUTPUT


def _resolved(tmp_path: Path, *, model: str = "deepseek-v4-flash"):
    source = Path(__file__).resolve().parents[1] / "impl" / "config.yaml"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        source.read_text(encoding="utf-8").replace("model: deepseek-v4-pro", f"model: {model}", 1),
        encoding="utf-8",
    )
    return resolve_runtime_config(config_path=config_path, dotenv_path=tmp_path / ".env", environ={})


def test_llm_client_inherits_resolved_public_model(tmp_path):
    resolved = _resolved(tmp_path)

    client = LlmClient(config=resolved.llm, api_key="test-key")

    assert client.model == "deepseek-v4-flash"
    assert client.base_url == resolved.llm.base_url
    assert client.temperature == resolved.llm.temperature
    assert client.max_attempts == resolved.llm.max_attempts


def test_llm_role_policy_stays_explicit_when_public_model_changes(tmp_path):
    resolved = _resolved(tmp_path)

    client = LlmClient(config=resolved.llm, api_key="test-key", role="live_stub")

    assert client.model == "deepseek-chat"
    assert client.reasoning_effort == "low"


def test_llm_client_fails_before_request_when_required_credential_is_missing(tmp_path):
    resolved = _resolved(tmp_path)
    client = LlmClient(config=resolved.llm)

    with pytest.raises(ConfigError, match="llm.api_key"):
        client.complete_json("system", "user", output_spec=FREE_TEXT_OUTPUT)
