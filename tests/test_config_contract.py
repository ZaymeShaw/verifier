from __future__ import annotations

import json
from pathlib import Path

import pytest

from impl.core.config import ConfigError, resolve_runtime_config
from impl.core.config_bootstrap import parse_dotenv, render_env_example
from impl.core.config_check import (
    ConfigCheckReport,
    _check_extra_consumers,
    _probe_llm_capabilities,
    _run_full_gates,
    _scan_legacy_projectspec_consumers,
    _scan_public_config_bypasses,
    _scan_repository_secrets,
    check_runtime_config_contract,
)


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
  protocol: openai_compatible
  provider: deepseek
  model: deepseek-v4-pro
  base_url: https://api.deepseek.com/v1
  temperature: 0
  reasoning_effort: max
  request_timeout_seconds: 120
  max_attempts: 2
  retry_delay_seconds: 2
  capabilities:
    json_mode: true
    tool_calls: true
    context_window_tokens: 131072
  role_policies:
    live_stub:
      model: deepseek-chat
      reasoning_effort: low

embedding:
  enabled: true
  provider: bailian
  model: text-embedding-v4
  dimensions: 1024
  retrieval_top_k: 8
  trust_env_proxy: false

execution:
  case_retry_attempts: 3
  batch_concurrency_default: 4
  batch_concurrency_max: 8
  batch_event_history_limit: 200

context:
  data_root: verifier://impl/data/context_runtime
  store_root: verifier://impl/data/context_store
  max_records_per_project: 200
  candidate_limit: 20
  load_limit: 8
  content_char_budget: 100000
  query_limit: 4
  top_k_per_query: 5

judge:
  raw_response_max_chars: 4000

attribute:
  tool_call_limit: 8
  investigation_error_chars: 2000
  finalization_prompt_char_budget: 160000
  review_prompt_char_budget: 180000
  compaction:
    list_item_limit: 20
    attribute_result_chars: 12000
    project_context_chars: 4000
    trace_input_chars: 1200
    trace_normalized_request_chars: 1200
    trace_output_chars: 10000
    trace_execution_chars: 2500
    trace_error_chars: 1200
    judge_business_expectations_chars: 3000
    judge_fulfillment_assessments_chars: 4000
    judge_gap_chars: 1500
    judge_reasoning_chars: 2000

environment:
  variables:
    DEEPSEEK_API_KEY:
      bind: llm.api_key
      type: string
      required: true
      secret: true
      description: verifier default LLM credential
    BAILIAN_API_KEY:
      bind: embedding.api_key
      type: string
      required: false
      required_when:
        field: embedding.enabled
        equals: true
      secret: true
      description: conditional embedding credential
    EMBEDDING_ENABLED:
      bind: embedding.enabled
      type: boolean
      required: false
      secret: false
      description: embedding capability switch
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


def test_resolver_requires_supported_llm_protocol(tmp_path):
    config_path = _write_config(
        tmp_path,
        BASE_CONFIG.replace("protocol: openai_compatible", "protocol: provider_native", 1),
    )

    with pytest.raises(ConfigError, match="llm.protocol.*unsupported"):
        resolve_runtime_config(
            config_path=config_path,
            dotenv_path=tmp_path / ".env",
            environ={},
        )


def test_resolver_rejects_operation_path_as_llm_base_url(tmp_path):
    config_path = _write_config(
        tmp_path,
        BASE_CONFIG.replace(
            "https://api.deepseek.com/v1",
            "https://api.deepseek.com/v1/chat/completions",
            1,
        ),
    )

    with pytest.raises(ConfigError, match="llm.base_url.*API root URL"):
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


def test_removed_legacy_alias_is_rejected_in_dotenv_and_ignored_in_process_env(tmp_path):
    config_path = _write_config(tmp_path)
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("LLM_API_KEY=legacy-secret\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="unregistered dotenv variable: LLM_API_KEY"):
        resolve_runtime_config(
            config_path=config_path,
            dotenv_path=dotenv_path,
            environ={},
        )

    resolved = resolve_runtime_config(
        config_path=config_path,
        dotenv_path=tmp_path / "missing.env",
        environ={"LLM_API_KEY": "legacy-secret"},
    )
    assert resolved.llm.api_key == ""


def test_missing_required_secret_is_reported_without_blocking_non_llm_config(tmp_path):
    config_path = _write_config(tmp_path)

    resolved = resolve_runtime_config(
        config_path=config_path,
        dotenv_path=tmp_path / ".env",
        environ={},
    )

    assert resolved.server.port == 8020
    assert resolved.llm.api_key == ""
    assert resolved.missing_required == ("embedding.api_key", "llm.api_key")
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
    assert policy.protocol == "openai_compatible"
    assert policy.model == "deepseek-chat"
    assert policy.reasoning_effort == "low"
    assert resolved.llm.policy_for("judge").model == "deepseek-v4-pro"
    assert resolved.llm.policy_for("judge").reasoning_effort == "max"


def test_llm_capability_probe_checks_json_and_tools_without_exposing_key(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    resolved = resolve_runtime_config(
        config_path=config_path,
        dotenv_path=tmp_path / ".env",
        environ={"DEEPSEEK_API_KEY": "probe-secret"},
    )
    responses = [
        {"choices": [{"message": {"content": '{"ok": true}'}}]},
        {"choices": [{"message": {"tool_calls": [{"id": "call-1"}]}}]},
        {"choices": [{"message": {"content": '{"ok": true}'}}]},
    ]
    requests = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            import json

            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, **_kwargs):
        import json

        requests.append(json.loads(request.data.decode("utf-8")))
        return Response(responses.pop(0))

    monkeypatch.setattr("impl.core.config_check.urllib.request.urlopen", fake_urlopen)

    issues = _probe_llm_capabilities(resolved)

    assert issues == []
    assert requests[-1]["reasoning_effort"] == "max"


def test_full_config_gate_reports_failed_subcheck(monkeypatch, tmp_path):
    completed = type("Completed", (), {"returncode": 1, "stdout": "line one\nfailed evidence\n"})()
    monkeypatch.setattr("impl.core.config_check.subprocess.run", lambda *_args, **_kwargs: completed)

    issues = _run_full_gates(tmp_path)

    assert len(issues) == 4
    assert all(issue.code == "full_gate_failed" for issue in issues)
    assert all("failed evidence" in issue.message for issue in issues)


def test_full_config_gate_passes_one_frozen_environment_to_every_subprocess(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(
        "DOTENV_ONLY=dotenv-value\nOVERRIDDEN=dotenv-value\n",
        encoding="utf-8",
    )
    captured = []

    def completed(*_args, **kwargs):
        captured.append(kwargs["env"])
        return type("Completed", (), {"returncode": 0, "stdout": "ok\n"})()

    monkeypatch.setattr("impl.core.config_check.subprocess.run", completed)

    issues = _run_full_gates(
        tmp_path,
        environ={"PROCESS_ONLY": "process-value", "OVERRIDDEN": "process-value"},
    )

    assert issues == []
    assert len(captured) == 4
    assert captured == [{
        "DOTENV_ONLY": "dotenv-value",
        "PROCESS_ONLY": "process-value",
        "OVERRIDDEN": "process-value",
    }] * 4


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

    bypass_codes = {
        "public_env_bypass",
        "unregistered_env_bypass",
        "llm_config_bypass",
        "deployment_config_fallback",
        "PATH_CONSTRUCTION_BYPASS",
        "PATH_WRITER_BYPASS",
        "PATH_SCHEMA_BYPASS",
    }
    assert not [
        issue for issue in report.issues if issue.code in bypass_codes
    ], report.to_dict()
    assert not report.issues, report.to_dict()


def test_config_check_rejects_provider_specific_and_constructor_bypasses(tmp_path):
    core = tmp_path / "impl" / "core"
    core.mkdir(parents=True)
    (core / "provider_bypass.py").write_text(
        "from agno.models.deepseek import DeepSeek\n"
        "model = DeepSeek(id='hard-coded')\n"
        "client = LlmClient(api_key='hard-coded')\n",
        encoding="utf-8",
    )

    issues = _scan_public_config_bypasses(tmp_path, {"DEEPSEEK_API_KEY"})

    assert any(issue.code == "public_config_fallback" for issue in issues)
    assert any(issue.code == "llm_config_bypass" for issue in issues)


def test_config_check_scans_cli_and_project_modules_for_registered_env_bypass(tmp_path):
    cli = tmp_path / "impl" / "cli.py"
    cli.parent.mkdir(parents=True)
    cli.write_text("import os\nvalue = os.getenv('LLM_MODEL')\n", encoding="utf-8")

    issues = _scan_public_config_bypasses(tmp_path, {"LLM_MODEL"})

    assert any(issue.code == "public_env_bypass" and issue.path == str(cli) for issue in issues)


def test_config_check_rejects_unregistered_environment_reads(tmp_path):
    consumer = tmp_path / "impl" / "projects" / "demo" / "live.py"
    consumer.parent.mkdir(parents=True)
    consumer.write_text("import os\nvalue = os.getenv('NEW_PRODUCT_SETTING')\n", encoding="utf-8")

    issues = _scan_public_config_bypasses(tmp_path, set())

    assert any(issue.code == "unregistered_env_bypass" and issue.path == str(consumer) for issue in issues)


def test_config_check_rejects_project_config_constants_in_live_schema(tmp_path):
    live_schema = tmp_path / "impl" / "projects" / "demo" / "live_schema.py"
    live_schema.parent.mkdir(parents=True)
    live_schema.write_text(
        "READY = ['output']\n"
        "SCENARIO_ENUM = ['happy_path']\n"
        "API_ENDPOINT = '/api/demo'\n"
        "IS_PROVIDED_OUTPUT = True\n",
        encoding="utf-8",
    )

    issues = _scan_public_config_bypasses(tmp_path, set())

    assert [issue.code for issue in issues].count("live_schema_config_bypass") == 4


def test_config_check_rejects_numeric_endpoint_discovery_timeout(tmp_path):
    consumer = tmp_path / "impl" / "core" / "endpoint_discovery.py"
    consumer.parent.mkdir(parents=True)
    consumer.write_text("response = urlopen(request, timeout=10.0)\n", encoding="utf-8")

    issues = _scan_public_config_bypasses(tmp_path, set())

    assert any(issue.code == "deployment_config_fallback" for issue in issues)


def test_config_check_rejects_deployment_field_fallbacks(tmp_path):
    consumer = tmp_path / "impl" / "projects" / "demo" / "live.py"
    consumer.parent.mkdir(parents=True)
    consumer.write_text(
        "method = spec.api.get('method') or 'POST'\n"
        "timeout = spec.api.get('timeout', 30)\n",
        encoding="utf-8",
    )

    issues = _scan_public_config_bypasses(tmp_path, set())

    assert [issue.code for issue in issues].count("deployment_config_fallback") == 2


def test_config_check_rejects_removed_projectspec_compatibility_views(tmp_path):
    consumer = tmp_path / "impl" / "projects" / "demo" / "live.py"
    consumer.parent.mkdir(parents=True)
    consumer.write_text(
        "ready = spec.common.get('ready')\n"
        "service = self.spec.api\n"
        "draft = getattr(project_spec, 'mock_draft', {})\n"
        "def read(config: ProjectSpec):\n"
        "    alias = config\n"
        "    return alias.documents\n"
        "context = getattr(spec, 'extra', {}).get('context')\n",
        encoding="utf-8",
    )

    issues = _scan_legacy_projectspec_consumers(tmp_path)

    assert [(issue.code, issue.line) for issue in issues] == [
        ("PROJECTSPEC_COMPAT_BYPASS", 1),
        ("PROJECTSPEC_COMPAT_BYPASS", 2),
        ("PROJECTSPEC_COMPAT_BYPASS", 3),
        ("PROJECTSPEC_COMPAT_BYPASS", 6),
        ("PROJECTSPEC_COMPAT_BYPASS", 7),
    ]


def test_config_check_accepts_canonical_projectspec_sections(tmp_path):
    consumer = tmp_path / "impl" / "projects" / "demo" / "live.py"
    consumer.parent.mkdir(parents=True)
    consumer.write_text(
        "ready = spec.runtime.get('ready')\n"
        "service = self.spec.service('primary')\n"
        "draft = project_spec.role_draft('mock')\n",
        encoding="utf-8",
    )

    assert _scan_legacy_projectspec_consumers(tmp_path) == []


def test_config_check_rejects_secret_literals_in_yaml_and_source(tmp_path):
    config = tmp_path / "impl" / "projects" / "demo" / "project.yaml"
    config.parent.mkdir(parents=True)
    sensitive_field = "api_" + "key"
    sensitive_value = "committed-" + "secret"
    config.write_text(f"service:\n  {sensitive_field}: {sensitive_value}\n", encoding="utf-8")
    source = tmp_path / "impl" / "consumer.py"
    source.write_text(("pass" + "word") + f' = "{sensitive_value}-value"\n', encoding="utf-8")

    issues = _scan_repository_secrets(tmp_path, [config])

    assert {issue.code for issue in issues} == {"secret_in_config", "secret_in_source"}


def test_config_check_scans_secret_literals_in_json_artifacts(tmp_path):
    artifact = tmp_path / "report" / "trace.json"
    artifact.parent.mkdir(parents=True)
    sensitive_field = "api_" + "key"
    sensitive_value = "sk-live-" + "1234567890abcdef"
    artifact.write_text(json.dumps({sensitive_field: sensitive_value}) + "\n", encoding="utf-8")

    issues = _scan_repository_secrets(tmp_path, [])

    assert any(issue.code == "secret_in_source" and issue.path == str(artifact) for issue in issues)


def test_config_check_requires_declared_extra_consumer_to_exist_and_read_field(tmp_path):
    consumer = tmp_path / "impl" / "projects" / "demo" / "consumer.py"
    consumer.parent.mkdir(parents=True)
    consumer.write_text("VALUE = 1\n", encoding="utf-8")
    document = {
        "project": {},
        "runtime": {
            "extra": {
                "session_reuse": {
                    "description": "demo",
                    "value_type": "boolean",
                    "schema_version": 1,
                    "consumers": ["impl.projects.demo.consumer"],
                    "value": True,
                }
            }
        },
        "verifier": {},
    }
    report = ConfigCheckReport()

    _check_extra_consumers(report, tmp_path, "demo", tmp_path / "project.yaml", document, {})

    assert [issue.code for issue in report.issues] == ["extra_consumer_unwired"]
