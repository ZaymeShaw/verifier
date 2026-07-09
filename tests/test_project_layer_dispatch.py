from __future__ import annotations

from dataclasses import fields
from types import SimpleNamespace

import pytest

from impl.core import pipeline
from impl.core.project_loader import load_project_attribute, load_project_judge
from impl.core.schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace
from impl.core.schema.attribute import AttributeResult as AttributeResultSchema
from impl.core.schema.judge import JudgeResult as JudgeResultSchema
from impl.projects.client_search import attribute as client_search_attribute


def test_project_loader_returns_optional_project_modules():
    client_spec = ProjectSpec(project_id="client_search", name="client_search", root="impl/projects/client_search")
    absent_spec = ProjectSpec(project_id="absent", name="absent", root="impl/projects/absent")

    assert load_project_judge(client_spec) is not None
    assert load_project_attribute(client_spec) is not None
    assert load_project_judge(absent_spec) is None
    assert load_project_attribute(absent_spec) is None


def test_project_loader_uses_draft_attribute_only_when_project_yaml_enables_it():
    spec = ProjectSpec(
        project_id="client_search",
        name="client_search",
        root="impl/projects/client_search",
        attribute_draft={"enabled": True, "module": "draft/attribute.py"},
    )

    module = load_project_attribute(spec)

    assert module is not None
    assert getattr(module, "attribute_failure", None) is not None


def test_project_loader_rejects_unsafe_draft_attribute_path():
    spec = ProjectSpec(
        project_id="client_search",
        name="client_search",
        root="impl/projects/client_search",
        attribute_draft={"enabled": True, "module": "../attribute.py"},
    )

    with pytest.raises(ValueError):
        load_project_attribute(spec)


def test_pipeline_judge_dispatches_to_project_module(monkeypatch):
    spec = ProjectSpec(project_id="demo", name="demo", root="impl/projects/demo")
    adapter = SimpleNamespace()
    module = SimpleNamespace()

    def project_judge(spec_arg, adapter_arg, trace_arg, expected_intent=None):
        assert spec_arg is spec
        assert adapter_arg is adapter
        assert trace_arg.trace_id == "trace-1"
        assert expected_intent == "intent"
        return JudgeResult(
            trace_id=trace_arg.trace_id,
            project_id=spec_arg.project_id,
            overall_fulfillment={"status": "fulfilled"},
            expected={"answer": "ok"},
            actual={"answer": "ok"},
            evidence=["project_judge"],
        )

    module.judge_trace = project_judge
    monkeypatch.setattr(pipeline, "load_project", lambda project_id: spec)
    monkeypatch.setattr(pipeline, "load_adapter", lambda spec_arg: adapter)
    monkeypatch.setattr(pipeline, "load_project_judge", lambda spec_arg: module)
    monkeypatch.setattr(pipeline, "ready_from_spec", lambda spec_arg: [])
    monkeypatch.setattr(pipeline, "_enforce_judge_live_schema", lambda project_id, trace, result: result)
    monkeypatch.setattr(pipeline, "_run_core_judge", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("core fallback should not run")))

    result = pipeline.judge("demo", RunTrace(trace_id="trace-1", project_id="demo"), expected_intent="intent")

    assert result.evidence == ["project_judge"]
    assert result.overall_fulfillment["status"] == "fulfilled"


def test_pipeline_attribute_dispatches_to_project_module(monkeypatch):
    spec = ProjectSpec(project_id="demo", name="demo", root="impl/projects/demo")
    adapter = SimpleNamespace()
    module = SimpleNamespace()

    def project_attribute(spec_arg, adapter_arg, trace_arg, judge_arg):
        assert spec_arg is spec
        assert adapter_arg is adapter
        assert trace_arg.trace_id == "trace-1"
        assert judge_arg.trace_id == "trace-1"
        return AttributeResult(
            trace_id=trace_arg.trace_id,
            project_id=spec_arg.project_id,
            root_cause_hypothesis="project attribute path",
            evidence=["project_attribute"],
            evidence_strength="strong",
        )

    module.attribute_failure = project_attribute
    monkeypatch.setattr(pipeline, "load_project", lambda project_id: spec)
    monkeypatch.setattr(pipeline, "load_adapter", lambda spec_arg: adapter)
    monkeypatch.setattr(pipeline, "load_project_attribute", lambda spec_arg: module)
    monkeypatch.setattr(pipeline, "_run_core_attribute", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("core fallback should not run")))

    trace = RunTrace(trace_id="trace-1", project_id="demo")
    judge = JudgeResult(trace_id="trace-1", project_id="demo", overall_fulfillment={"status": "not_fulfilled"})
    result = pipeline.attribute("demo", trace, judge)

    assert result.root_cause_hypothesis == "project attribute path"
    assert result.evidence_strength == "strong"


def test_client_search_attribute_module_injects_project_strategy(monkeypatch):
    spec = ProjectSpec(project_id="client_search", name="client_search", root="impl/projects/client_search")
    trace = RunTrace(
        trace_id="trace-1",
        project_id="client_search",
        extracted_output={"conditions": [], "matched_patterns": []},
    )
    judge = JudgeResult(trace_id="trace-1", project_id="client_search", overall_fulfillment={"status": "not_fulfilled"})
    tool = SimpleNamespace(name="search_api")
    adapter = SimpleNamespace(
        get_verifiable_tools=lambda: [tool],
        _boundary_from_trace=lambda trace_arg: {"judge_scope": "parser_condition_semantics_only"},
        _condition_comparison=lambda trace_arg: {"outputs": {"missing": ["age"]}},
        _source_config_paths=lambda: {"source_field_definitions": "/tmp/fields.yaml"},
        _capability_manifest=lambda: {"clientAge": {"operators": ["GTE"]}},
    )
    captured = {}

    def fake_protocol(spec_arg, adapter_arg, trace_arg, judge_arg, project_attribute_context=None):
        captured.update(project_attribute_context or {})
        return AttributeResult(
            trace_id=trace_arg.trace_id,
            project_id=spec_arg.project_id,
            root_cause_hypothesis="captured project strategy",
            evidence=["strategy"],
            evidence_strength="strong",
        )

    monkeypatch.setattr(client_search_attribute, "run_project_attribute_protocol", fake_protocol)

    result = client_search_attribute.attribute_failure(spec, adapter, trace, judge)

    assert result.root_cause_hypothesis == "captured project strategy"
    assert captured["tools"] == [tool]
    assert captured["tool_call_limit"] == 6
    assert "client_search 项目的 attribute agent" in captured["system_prompt_override"]
    strategy = captured["user_prompt_extras"]["project_attribute_strategy"]
    assert strategy["project"] == "client_search"
    assert "client_search_parse" in strategy["business_chain"]
    assert "runtime_checks" in strategy["evidence_contract"]
    assert captured["user_prompt_extras"]["application_boundary"]["judge_scope"] == "parser_condition_semantics_only"


def test_minimal_protocol_schemas_do_not_regain_removed_fields():
    judge_fields = {field.name for field in fields(JudgeResultSchema)}
    attribute_fields = {field.name for field in fields(AttributeResultSchema)}

    assert "verdict" not in judge_fields
    assert "verdict_derivation" not in judge_fields
    assert "consumer_contract" not in judge_fields
    assert "evaluation_boundary" not in judge_fields

    assert "causal_category" not in attribute_fields
    assert "chain_nodes" not in attribute_fields
    assert "incomplete_reason" not in attribute_fields
    assert "analysis_quality" not in attribute_fields
    assert "verification_steps" not in attribute_fields
    assert "patch_direction" not in attribute_fields
