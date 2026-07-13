from __future__ import annotations

from dataclasses import fields
from types import SimpleNamespace

import pytest

from impl.core import pipeline
from impl.core.project_loader import load_project_attribute, load_project_judge, load_project_role_instance
from impl.core.schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace
from impl.core.schema.attribute import AttributeResult as AttributeResultSchema
from impl.core.schema.judge import JudgeResult as JudgeResultSchema
from impl.projects.client_search import attribute as client_search_attribute
import importlib.util
from pathlib import Path

_MPI_ATTRIBUTE_PATH = Path(__file__).resolve().parents[1] / "impl" / "projects" / "marketting-planning-intent" / "attribute.py"
_MPI_ATTRIBUTE_SPEC = importlib.util.spec_from_file_location("test_marketting_planning_intent_attribute", _MPI_ATTRIBUTE_PATH)
assert _MPI_ATTRIBUTE_SPEC is not None and _MPI_ATTRIBUTE_SPEC.loader is not None
mpi_attribute = importlib.util.module_from_spec(_MPI_ATTRIBUTE_SPEC)
_MPI_ATTRIBUTE_SPEC.loader.exec_module(mpi_attribute)


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
    assert getattr(module, "ClientSearchAttribute", None) is not None


def test_project_loader_instantiates_existing_attribute_draft_protocol():
    spec = ProjectSpec(
        project_id="client_search",
        name="client_search",
        root="impl/projects/client_search",
        attribute_draft={"enabled": True, "module": "draft/attribute.py"},
    )
    adapter = SimpleNamespace()

    instance = load_project_role_instance(spec, "attribute", adapter)

    from impl.core.attribute_protocol import ProjectAttribute
    assert isinstance(instance, ProjectAttribute)
    assert instance._adapter is adapter


def test_project_loader_rejects_nonstandard_role_constructor(tmp_path):
    draft_dir = tmp_path / "draft"
    draft_dir.mkdir()
    (draft_dir / "attribute.py").write_text(
        "from impl.core.attribute_protocol import ProjectAttribute\n"
        "class DraftAttribute(ProjectAttribute):\n"
        "    def __init__(self, spec, tools):\n"
        "        super().__init__(spec)\n"
        "    def build_context(self, trace, judge_result):\n"
        "        return {}\n",
        encoding="utf-8",
    )
    spec = ProjectSpec(
        project_id="demo",
        name="demo",
        root=str(tmp_path),
        attribute_draft={"enabled": True, "module": "draft/attribute.py"},
    )

    with pytest.raises(TypeError, match="constructor must be"):
        load_project_role_instance(spec, "attribute", SimpleNamespace())


def test_project_loader_uses_draft_judge_protocol_when_enabled(tmp_path):
    draft_dir = tmp_path / "draft"
    draft_dir.mkdir()
    (draft_dir / "judge.py").write_text(
        "from impl.core.judge_protocol import ProjectJudge\n"
        "class DraftJudge(ProjectJudge):\n"
        "    def build_context(self, trace):\n"
        "        return {}\n",
        encoding="utf-8",
    )
    spec = ProjectSpec(
        project_id="demo",
        name="demo",
        root=str(tmp_path),
        judge_draft={"enabled": True, "module": "draft/judge.py"},
    )

    instance = load_project_role_instance(spec, "judge", SimpleNamespace())

    from impl.core.judge_protocol import ProjectJudge
    assert isinstance(instance, ProjectJudge)


def test_project_loader_rejects_unsafe_draft_role_paths():
    attribute_spec = ProjectSpec(
        project_id="client_search",
        name="client_search",
        root="impl/projects/client_search",
        attribute_draft={"enabled": True, "module": "../attribute.py"},
    )
    judge_spec = ProjectSpec(
        project_id="client_search",
        name="client_search",
        root="impl/projects/client_search",
        judge_draft={"enabled": True, "module": "/tmp/judge.py"},
    )

    with pytest.raises(ValueError):
        load_project_attribute(attribute_spec)
    with pytest.raises(ValueError):
        load_project_judge(judge_spec)


def test_project_loader_fails_when_enabled_draft_module_is_missing():
    spec = ProjectSpec(
        project_id="client_search",
        name="client_search",
        root="impl/projects/client_search",
        judge_draft={"enabled": True, "module": "draft/missing.py"},
    )

    with pytest.raises(FileNotFoundError, match="enabled judge draft module not found"):
        load_project_judge(spec)


def test_existing_attribute_drafts_preserve_production_gates_and_tools():
    from impl.projects.QA.draft.attribute import QAAttribute
    from impl.projects.client_search.draft.attribute import ClientSearchAttribute

    qa = QAAttribute(ProjectSpec(project_id="QA", name="QA"), SimpleNamespace())
    qa_trace = RunTrace(trace_id="qa-draft", project_id="QA")
    qa_judge = JudgeResult(
        trace_id="qa-draft",
        project_id="QA",
        overall_fulfillment={"status": "not_evaluable"},
        evidence=["missing_semantic_evidence"],
    )
    qa_context = qa.build_context(qa_trace, qa_judge)
    qa_result = qa.normalize_result(
        qa_trace,
        qa_judge,
        AttributeResult(trace_id="qa-draft", project_id="QA", evidence_strength="strong"),
    )

    assert "chain_nodes_to_check" in qa_context
    assert "runtime_checks" in qa_context
    assert qa_result.evidence_strength == "none"

    client_spec = ProjectSpec(project_id="client_search", name="client_search", root="impl/projects/client_search")
    client = ClientSearchAttribute(client_spec, SimpleNamespace())
    client_context = client.build_context(
        RunTrace(trace_id="client-draft", project_id="client_search"),
        JudgeResult(
            trace_id="client-draft",
            project_id="client_search",
            overall_fulfillment={"status": "not_fulfilled"},
        ),
    )

    assert isinstance(client_context["tools"], list)


def test_pipeline_prefers_enabled_draft_attribute_protocol(monkeypatch):
    spec = ProjectSpec(
        project_id="demo",
        name="demo",
        root="impl/projects/demo",
        attribute_draft={"enabled": True, "module": "draft/attribute.py"},
    )
    adapter = SimpleNamespace(attribute=lambda: (_ for _ in ()).throw(AssertionError("production adapter attribute used")))

    from impl.core.attribute_protocol import ProjectAttribute

    class DraftAttribute(ProjectAttribute):
        def build_context(self, trace, judge_result):
            return {}

        def normalize_result(self, trace, judge_result, result):
            result.evidence = ["draft_attribute"]
            return result

    draft = DraftAttribute(spec)
    monkeypatch.setattr(pipeline, "load_project", lambda project_id: spec)
    monkeypatch.setattr(pipeline, "load_adapter", lambda spec_arg: adapter)
    monkeypatch.setattr(pipeline, "load_project_role_instance", lambda spec_arg, role, adapter_arg: draft)
    monkeypatch.setattr(
        draft,
        "_run_llm_attribute",
        lambda trace, judge_result, context: AttributeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            evidence_strength="weak",
        ),
    )

    trace = RunTrace(trace_id="trace-draft", project_id="demo")
    judge = JudgeResult(trace_id="trace-draft", project_id="demo", overall_fulfillment={"status": "not_fulfilled"})
    result = pipeline.attribute("demo", trace, judge)

    assert result.evidence == ["draft_attribute"]


def test_pipeline_prefers_enabled_draft_judge_protocol(monkeypatch):
    spec = ProjectSpec(
        project_id="demo",
        name="demo",
        root="impl/projects/demo",
        judge_draft={"enabled": True, "module": "draft/judge.py"},
    )
    adapter = SimpleNamespace(judge=lambda: (_ for _ in ()).throw(AssertionError("production adapter judge used")))

    from impl.core.judge_protocol import ProjectJudge

    class DraftJudge(ProjectJudge):
        def build_context(self, trace):
            return {}

        def pre_judge(self, trace, expected_intent=None):
            return JudgeResult(
                trace_id=trace.trace_id,
                project_id=trace.project_id,
                overall_fulfillment={"status": "fulfilled"},
                evidence=["draft_judge"],
            )

    draft = DraftJudge(spec)
    monkeypatch.setattr(pipeline, "load_project", lambda project_id: spec)
    monkeypatch.setattr(pipeline, "load_adapter", lambda spec_arg: adapter)
    monkeypatch.setattr(pipeline, "load_project_role_instance", lambda spec_arg, role, adapter_arg: draft)
    monkeypatch.setattr(pipeline, "ready_from_spec", lambda spec_arg: [])
    monkeypatch.setattr(pipeline, "_enforce_judge_live_schema", lambda project_id, trace, result: result)

    result = pipeline.judge("demo", RunTrace(trace_id="trace-draft", project_id="demo"))

    assert result.evidence == ["draft_judge"]



def test_project_loader_rejects_draft_symlink_outside_project(tmp_path):
    draft_dir = tmp_path / "draft"
    draft_dir.mkdir()
    outside = tmp_path.parent / f"{tmp_path.name}-outside.py"
    outside.write_text("def judge_trace(*args, **kwargs):\n    return None\n", encoding="utf-8")
    (draft_dir / "judge.py").symlink_to(outside)
    spec = ProjectSpec(
        project_id="demo",
        name="demo",
        root=str(tmp_path),
        judge_draft={"enabled": True, "module": "draft/judge.py"},
    )

    with pytest.raises(ValueError, match="must resolve under"):
        load_project_judge(spec)


def test_pipeline_rejects_adapter_without_judge_protocol(monkeypatch):
    spec = ProjectSpec(project_id="demo", name="demo", root="impl/projects/demo")
    adapter = SimpleNamespace()
    monkeypatch.setattr(pipeline, "load_project", lambda project_id: spec)
    monkeypatch.setattr(pipeline, "load_adapter", lambda spec_arg: adapter)
    monkeypatch.setattr(pipeline, "ready_from_spec", lambda spec_arg: [])

    with pytest.raises(AttributeError):
        pipeline.judge("demo", RunTrace(trace_id="trace-1", project_id="demo"), expected_intent="intent")


def test_pipeline_rejects_adapter_without_attribute_protocol(monkeypatch):
    spec = ProjectSpec(project_id="demo", name="demo", root="impl/projects/demo")
    adapter = SimpleNamespace()
    monkeypatch.setattr(pipeline, "load_project", lambda project_id: spec)
    monkeypatch.setattr(pipeline, "load_adapter", lambda spec_arg: adapter)

    trace = RunTrace(trace_id="trace-1", project_id="demo")
    judge = JudgeResult(trace_id="trace-1", project_id="demo", overall_fulfillment={"status": "not_fulfilled"})
    with pytest.raises(AttributeError):
        pipeline.attribute("demo", trace, judge)


def test_marketting_planning_intent_attribute_module_injects_project_strategy(monkeypatch):
    spec = ProjectSpec(project_id="marketting-planning-intent", name="marketting-planning-intent", root="impl/projects/marketting-planning-intent")
    trace = RunTrace(
        trace_id="trace-intent-1",
        project_id="marketting-planning-intent",
        reference_contract={"intent": "nbev_planning", "required_slots": ["target_value"], "min_confidence": 0.8},
        extracted_output={"intent": "other", "confidence": 0.4},
        project_fields={
            "intent_evidence": {
                "raw_intent": "other",
                "slots": {},
                "entities": [],
                "fallback": True,
                "errors": ["low confidence"],
            }
        },
    )
    judge = JudgeResult(trace_id="trace-intent-1", project_id="marketting-planning-intent", overall_fulfillment={"status": "not_fulfilled"})
    adapter = SimpleNamespace(
        build_attribute_context=lambda trace_arg, judge_arg: {"source_config_paths": {"project_doc:source_demand": "/tmp/marketplan-demand.md"}},
        get_runtime_checks=lambda runtime_values, runtime_context: {"intent": "mismatch"},
        apply_attribution_probes=lambda trace_arg, judge_arg, result: result,
        normalize_attribute_result=lambda trace_arg, judge_arg, result: result,
    )
    context = mpi_attribute.MarketingIntentAttribute(spec).build_context(trace, judge)

    assert context["tool_call_limit"] == 4
    assert "marketting-planning-intent 项目的 attribute agent" in context["system_prompt_override"]
    strategy = context["user_prompt_extras"]["project_attribute_strategy"]
    assert strategy["project"] == "marketting-planning-intent"
    assert strategy["business_chain"] == ["request_normalization", "intent_api_call", "adapter_extraction", "label_mapping"]
    assert "intent_contract_probe" in strategy["evidence_contract"]
    probe = context["user_prompt_extras"]["intent_contract_probe"]
    assert probe["expected_intent"] == "nbev_planning"
    assert probe["actual_intent"] == "other"
    assert probe["missing_required_slots"] == ["target_value"]
    assert probe["fallback_observed"] is True


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
    from impl.core.project_loader import load_project_tools

    context = client_search_attribute.ClientSearchAttribute(
        spec,
        load_project_tools(spec).verifiable_tools(),
    ).build_context(trace, judge)

    assert context["tool_call_limit"] == 6
    assert "client_search 项目的 attribute agent" in context["system_prompt_override"]
    strategy = context["user_prompt_extras"]["project_attribute_strategy"]
    assert strategy["project"] == "client_search"
    assert "client_search_parse" in strategy["business_chain"]
    assert "runtime_checks" in strategy["evidence_contract"]
    assert context["user_prompt_extras"]["application_boundary"]["judge_scope"] == "parser_condition_semantics_only"


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
