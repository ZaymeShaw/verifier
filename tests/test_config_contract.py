from __future__ import annotations

from pathlib import Path

import pytest

from impl.core.config import ConfigError, resolve_runtime_config
from impl.core.config_bootstrap import parse_dotenv, render_env_example
from impl.core.config_check import check_runtime_config_contract


BASE_CONFIG = """
schema_version: 1

python:
  executable: python

server:
  host: 127.0.0.1
  port: 8020

uat:
  host: 127.0.0.1
  port: 8021

browser:
  driver_path: chromedriver

llm:
  provider: deepseek
  model: deepseek-v4-pro
  base_url: https://api.deepseek.com/v1/chat/completions
  temperature: 0
  reasoning_effort: max
  max_attempts: 2
  retry_delay_seconds: 2
  role_policies:
    live_stub:
      model: deepseek-chat
      reasoning_effort: low

embedding:
  provider: bailian
  model: text-embedding-v4
  dimensions: 1024
  retrieval_top_k: 8
  trust_env_proxy: false

environment:
  variables:
    DEEPSEEK_API_KEY:
      bind: llm.api_key
      type: string
      required: true
      secret: true
      description: verifier default LLM credential
      legacy_aliases:
        - name: LLM_API_KEY
          remove_after: P5
    LLM_MODEL:
      bind: llm.model
      type: string
      required: false
      secret: false
      description: temporary model override
    VERIFIER_PORT:
      bind: server.port
      type: integer
      required: false
      secret: false
      description: server port override
"""


def _write_config(tmp_path: Path, text: str = BASE_CONFIG) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_resolver_applies_registered_precedence_and_tracks_sources(tmp_path):
    config_path = _write_config(tmp_path)
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "DEEPSEEK_API_KEY=dotenv-secret\n"
        "LLM_MODEL=dotenv-model\n"
        "VERIFIER_PORT=18020\n",
        encoding="utf-8",
    )

    resolved = resolve_runtime_config(
        config_path=config_path,
        dotenv_path=dotenv_path,
        environ={"LLM_MODEL": "process-model"},
        cli_overrides={"llm.model": "cli-model"},
    )

    assert resolved.llm.model == "cli-model"
    assert resolved.llm.api_key == "dotenv-secret"
    assert resolved.server.port == 18020
    assert resolved.source_for("llm.model").kind == "cli"
    assert resolved.source_for("llm.api_key").kind == "dotenv"
    assert resolved.source_for("server.port").kind == "dotenv"


def test_resolver_rejects_unknown_yaml_fields(tmp_path):
    config_path = _write_config(tmp_path, BASE_CONFIG + "\nunknown_section: true\n")

    with pytest.raises(ConfigError, match="unknown field.*unknown_section"):
        resolve_runtime_config(config_path=config_path, dotenv_path=tmp_path / ".env", environ={})


def test_resolver_rejects_duplicate_yaml_keys(tmp_path):
    config_path = _write_config(
        tmp_path,
        BASE_CONFIG.replace("  model: deepseek-v4-pro\n", "  model: deepseek-v4-pro\n  model: duplicate\n"),
    )

    with pytest.raises(ConfigError, match="duplicate key.*model"):
        resolve_runtime_config(config_path=config_path, dotenv_path=tmp_path / ".env", environ={})


def test_resolver_revalidates_port_after_environment_override(tmp_path):
    config_path = _write_config(tmp_path)

    with pytest.raises(ConfigError, match="server.port"):
        resolve_runtime_config(
            config_path=config_path,
            dotenv_path=tmp_path / ".env",
            environ={"VERIFIER_PORT": "70000"},
        )


def test_resolver_rejects_provider_values_without_a_consumer_implementation(tmp_path):
    config_path = _write_config(
        tmp_path,
        BASE_CONFIG.replace("provider: deepseek", "provider: unimplemented-provider", 1),
    )

    with pytest.raises(ConfigError, match="llm.provider.*unsupported"):
        resolve_runtime_config(
            config_path=config_path,
            dotenv_path=tmp_path / ".env",
            environ={},
        )


@pytest.mark.parametrize(
    "line, message",
    [
        ("export LLM_MODEL=foo\n", "export"),
        ("LLM_MODEL =foo\n", "KEY=value"),
        ("LLM_MODEL=${OTHER}\n", "interpolation"),
        ("LLM_MODEL=foo # comment\n", "inline comments"),
        ("LLM_MODEL=one\nLLM_MODEL=two\n", "duplicate"),
    ],
)
def test_dotenv_parser_rejects_unsupported_syntax(tmp_path, line, message):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(line, encoding="utf-8")

    with pytest.raises(ConfigError, match=message):
        parse_dotenv(dotenv_path)


def test_dotenv_parser_supports_comments_quotes_and_literal_hash(tmp_path):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "# local values\n"
        'DEEPSEEK_API_KEY="abc # literal"\n'
        "LLM_MODEL=deepseek-v4-flash\n",
        encoding="utf-8",
    )

    assert parse_dotenv(dotenv_path) == {
        "DEEPSEEK_API_KEY": "abc # literal",
        "LLM_MODEL": "deepseek-v4-flash",
    }


def test_legacy_alias_is_centralized_warned_and_conflict_safe(tmp_path):
    config_path = _write_config(tmp_path)

    resolved = resolve_runtime_config(
        config_path=config_path,
        dotenv_path=tmp_path / ".env",
        environ={"LLM_API_KEY": "legacy-secret"},
    )

    assert resolved.llm.api_key == "legacy-secret"
    assert resolved.source_for("llm.api_key").kind == "legacy_process_env"
    assert any("LLM_API_KEY" in warning for warning in resolved.warnings)

    with pytest.raises(ConfigError, match="both canonical.*DEEPSEEK_API_KEY.*LLM_API_KEY"):
        resolve_runtime_config(
            config_path=config_path,
            dotenv_path=tmp_path / ".env",
            environ={"DEEPSEEK_API_KEY": "new", "LLM_API_KEY": "old"},
        )


def test_missing_required_secret_is_reported_without_blocking_non_llm_config(tmp_path):
    config_path = _write_config(tmp_path)

    resolved = resolve_runtime_config(
        config_path=config_path,
        dotenv_path=tmp_path / ".env",
        environ={},
    )

    assert resolved.server.port == 8020
    assert resolved.llm.api_key == ""
    assert resolved.missing_required == ("llm.api_key",)
    with pytest.raises(ConfigError, match="llm.api_key"):
        resolved.require("llm")


def test_redacted_config_never_exposes_secret(tmp_path):
    config_path = _write_config(tmp_path)
    resolved = resolve_runtime_config(
        config_path=config_path,
        dotenv_path=tmp_path / ".env",
        environ={"DEEPSEEK_API_KEY": "super-secret"},
    )

    rendered = str(resolved.redacted_dict())
    assert "super-secret" not in rendered
    assert "***" in rendered


def test_role_policy_is_explicit_and_inherits_public_defaults(tmp_path):
    config_path = _write_config(tmp_path)
    resolved = resolve_runtime_config(
        config_path=config_path,
        dotenv_path=tmp_path / ".env",
        environ={},
    )

    policy = resolved.llm.policy_for("live_stub")
    assert policy.model == "deepseek-chat"
    assert policy.reasoning_effort == "low"
    assert resolved.llm.policy_for("judge").model == "deepseek-v4-pro"
    assert resolved.llm.policy_for("judge").reasoning_effort == "max"


def test_env_example_is_derived_and_keeps_secrets_empty(tmp_path):
    config_path = _write_config(tmp_path)
    resolved = resolve_runtime_config(
        config_path=config_path,
        dotenv_path=tmp_path / ".env",
        environ={},
    )

    example = render_env_example(resolved.environment)

    assert "DEEPSEEK_API_KEY=" in example
    assert "verifier default LLM credential" in example
    assert "LLM_MODEL=" in example
    assert "legacy alias" not in example.lower()


def test_repository_public_config_contract_has_no_consumer_bypass():
    root = Path(__file__).resolve().parents[1]

    report = check_runtime_config_contract(root=root, environ={})

    assert report.ok, report.to_dict()
