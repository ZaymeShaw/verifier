from types import SimpleNamespace

import pytest

from impl.core.attribute import _finalization_system_prompt
from impl.core.attribute import attribute_failure
from impl.core.attribute_reviewer import _REVIEW_SYSTEM_PROMPT

from impl.core.attribute_environment import AttributeExecutionEnvironment, normalize_attribute_tools
from impl.core.attribute import _default_system_prompt
from impl.core.attribute_reviewer import review_attribute_result
from impl.core.context.tools import GuardedContextTools
from impl.core.context.errors import ContextValidationError
from impl.core.attribute_protocol import ProjectAttribute
from impl.core.summary import summary_from_attribution
from impl.core import context_store
from impl.core.schema import AttributeResult, AttributionFinding, EvidenceRef, FulfillmentAssessment, JudgeResult, ProjectSpec, RunTrace
from impl.core.schema.context import ContextRecord
from impl.tools import ToolResult, VerifiableTool
from impl.tools.source_retrieval import ProjectSourceFileProvider, create_source_search_tools


def _judge():
    return JudgeResult(
        trace_id="trace-1", project_id="demo",
        fulfillment_assessments=[FulfillmentAssessment(expectation_id="stage", status="not_fulfilled")],
        expected={"stage": "planning"}, actual={"stage": "unknown"},
        overall_fulfillment={"status": "not_fulfilled"},
    )


def _finding():
    return AttributionFinding(
        finding_id="finding-stage",
        affected_expectation_ids=["stage"],
        conclusion="当前路由规则把该输入映射为 unknown。",
        evidence=[EvidenceRef(
            ref_id="ev-stage", source="context_unit", kind="runtime_result",
            stage="attribute-round-1-finalization", summary="运行材料记录了 unknown 映射。",
            location="cu-stage", payload=None,
            metadata={"source_hash": "sha256:value", "trace_id": "trace-1", "case_id": ""},
        )],
    )


def test_attribute_tool_assembly_bridges_verifiable_tools():
    def execute(**_kwargs):
        return ToolResult(tool_id="demo.check", status="succeeded")
    [tool] = normalize_attribute_tools([VerifiableTool(tool_id="demo.check", description="check fact", parameters={}, execute_fn=execute)])
    assert tool.name == "demo_check"


def test_attribute_tool_assembly_rejects_unknown_objects():
    with pytest.raises(TypeError, match="Attribute tools"):
        normalize_attribute_tools([object()])


def test_context_tool_schema_uses_json_arrays_and_prompt_separates_source_keys():
    assert "max_length=4" in GuardedContextTools.search_context_units.__annotations__["queries"]
    assert "max_length=8" in GuardedContextTools.load_context_units.__annotations__["unit_ids"]
    prompt = _default_system_prompt(8)
    assert "source_file_catalog 中的 key" in prompt
    assert "绝不是 ContextUnit ID" in prompt
    assert "一次 search 最多 4 条" in prompt


def test_source_search_discovers_unregistered_technical_location(tmp_path):
    source = tmp_path / "intent_router.py"
    source.write_text("UNKNOWN_STAGE = 'unknown'\ndef route(stage):\n    return UNKNOWN_STAGE\n", encoding="utf-8")
    provider = ProjectSourceFileProvider(SimpleNamespace(root=str(tmp_path), source_project=str(tmp_path), documents={}, adapter="", application={}, endpoint_discovery={}))
    [search_tool] = create_source_search_tools(provider)
    result = search_tool.execute_fn(query="UNKNOWN_STAGE")
    assert result.actual["matches"][0]["line"] == 1


def test_source_search_can_return_bounded_context_without_full_file(tmp_path):
    source = tmp_path / "rules.yaml"
    source.write_text(
        "rules:\n  - name: exact-name\n    patterns:\n      - name=(.+)\n    field: client_name\nother: ignored\n",
        encoding="utf-8",
    )
    provider = ProjectSourceFileProvider(SimpleNamespace(
        root=str(tmp_path), source_project=str(tmp_path), documents={}, adapter="", application={}, endpoint_discovery={}
    ))
    [search_tool] = create_source_search_tools(provider)

    result = search_tool.execute_fn(query="exact-name", max_results=1, context_lines=3)

    [match] = result.actual["matches"]
    assert match["start_line"] == 1
    assert match["end_line"] == 5
    assert "field: client_name" in match["text"]
    assert "other: ignored" not in match["text"]


class _TwoRoundAttribute(ProjectAttribute):
    def __init__(self, spec):
        super().__init__(spec)
        self.rounds = []

    def build_context(self, trace, judge_result):
        return {}

    def run_attribute_round(self, trace, judge_result, context):
        self.rounds.append({"round": context["_attribute_round"], "issues": context.get("review_issues")})
        return AttributeResult(trace.trace_id, trace.project_id, findings=[_finding()])


def test_review_issue_is_returned_to_main_executor_then_can_pass(monkeypatch):
    attribute = _TwoRoundAttribute(ProjectSpec(project_id="demo", name="demo", attribute_draft={"enabled": True}))
    attribute.configure_execution_environment(AttributeExecutionEnvironment())
    reviews = iter([{"passed": False, "issues": [{"target": "finding-stage", "problem": "缺少路由输入证据"}]}, {"passed": True, "issues": []}])
    monkeypatch.setattr(attribute, "_run_attribute_review", lambda *_args: next(reviews))
    result = attribute.attribute_failure(RunTrace(trace_id="trace-1", project_id="demo"), _judge())
    assert len(attribute.rounds) == 2
    assert attribute.rounds[1]["issues"][0]["target"] == "finding-stage"
    assert len(result.findings) == 1
    audit = attribute._attribute_execution_environment.last_context["_attribute_review_audit"]
    assert [item["passed"] for item in audit] == [False, True]
    assert audit[0]["issues"][0]["problem"] == "缺少路由输入证据"


def test_second_failed_review_removes_unproved_findings(monkeypatch):
    attribute = _TwoRoundAttribute(ProjectSpec(project_id="demo", name="demo", attribute_draft={"enabled": True}))
    attribute.configure_execution_environment(AttributeExecutionEnvironment())
    monkeypatch.setattr(attribute, "_run_attribute_review", lambda *_args: {"passed": False, "issues": [{"target": "finding-stage", "problem": "证据不能证明因果连接"}]})
    result = attribute.attribute_failure(RunTrace(trace_id="trace-1", project_id="demo"), _judge())
    assert result.findings == []
    assert "证据不能证明因果连接" in result.unresolved_reason
    assert result.summary["is_formal_attribution"] is False


def test_nonempty_unresolved_reason_prevents_complete_attribution_summary():
    result = {
        "findings": [{
            "finding_id": "finding-stage",
            "affected_expectation_ids": ["stage"],
            "conclusion": "已确认路由规则产生 unknown。",
        }],
        "unresolved_reason": "仍未验证部署版本是否使用同一规则。",
    }

    summary = summary_from_attribution(result, ["stage"], judge_status="not_fulfilled")

    assert summary["attribution_status"] == "partial"
    assert summary["is_complete"] is False
    assert summary["summary_text"] == (
        "已确认路由规则产生 unknown。\n仍未验证部署版本是否使用同一规则。"
    )


class _FakeContextRun:
    def __init__(self):
        self.loaded_ids = ["cu-stage"]

    def debug_snapshot(self):
        return {"context_debug": {"loaded_ids": list(self.loaded_ids), "content_hashes": {"cu-stage": "sha256:value"}}}

    def load_context_units(self, unit_ids):
        assert unit_ids == ["cu-stage"]
        return [SimpleNamespace(id="cu-stage", name="stage runtime", description="runtime output", content="stage=unknown")]

    def context_unit_catalog(self):
        return [{"context_unit_id": "cu-stage", "name": "stage runtime", "description": "runtime output"}]


class _FakeRegistry:
    def get(self, unit_id):
        if unit_id != "cu-stage":
            return None
        return {
            "record": SimpleNamespace(
                name="stage runtime", description="runtime output",
                unit_type="runtime_result", source_type="probe",
            ),
            "source_hash": "sha256:value",
        }

    def get_many(self, unit_ids):
        return {unit_id: self.get(unit_id) for unit_id in unit_ids if self.get(unit_id) is not None}


class _FakeRuntime:
    def __init__(self):
        self.registry = _FakeRegistry()
        self.registered = []

    def register_context_unit(self, record):
        self.registered.append(record)
        return {"action": "created"}


class _RetryRuntime(_FakeRuntime):
    def __init__(self, *, always_fail=False):
        super().__init__()
        self.attempts = 0
        self.always_fail = always_fail

    def register_context_unit(self, record):
        self.attempts += 1
        if self.always_fail or self.attempts == 1:
            raise RuntimeError("embedding unavailable")
        return super().register_context_unit(record)


class _InvalidEmbeddingRuntime(_FakeRuntime):
    def __init__(self):
        super().__init__()
        self.attempts = 0

    def register_context_unit(self, _record):
        self.attempts += 1
        raise ContextValidationError("embedding vector contains NaN or infinity")


def test_finalization_reloads_investigated_context_and_materializes_evidence():
    environment = AttributeExecutionEnvironment(
        main_context_run=_FakeContextRun(),
        context_runtime=SimpleNamespace(registry=_FakeRegistry()),
        trace=RunTrace(trace_id="trace-1", project_id="demo"),
    )
    context = environment.assemble({})
    context["_attribute_round"] = 1
    assert all(getattr(tool, "__name__", "") != "finalize_attribution" for tool in context["tools"])
    finalize = context["_attribute_finalize"]
    assert finalize()[0]["content"] == "stage=unknown"
    findings = context["_attribute_materialize_findings"]([{
        "finding_id": "finding-stage",
        "affected_expectation_ids": ["stage"],
        "conclusion": "路由规则产生 unknown。",
        "evidence": [{"context_unit_id": "cu-stage", "reason": "材料记录 stage=unknown。"}],
    }], ["stage"])
    assert findings[0].evidence[0].location == "cu-stage"
    assert findings[0].evidence[0].payload is None
    assert findings[0].evidence[0].metadata["source_hash"] == "sha256:value"
    review_result = AttributeResult("trace-1", "demo", findings=findings)
    bundle = context["_attribute_review_bundle"](review_result)
    assert bundle["available_context_units"] == [{
        "context_unit_id": "cu-stage",
        "name": "stage runtime",
        "description": "runtime output",
    }]
    assert bundle["cited_evidence_context_units"][0]["content"] == "stage=unknown"
    assert "review_tools" not in bundle


def test_finalization_is_runtime_driven_and_has_no_id_parameter():
    environment = AttributeExecutionEnvironment(
        main_context_run=_FakeContextRun(),
        context_runtime=SimpleNamespace(registry=_FakeRegistry()),
        trace=RunTrace(trace_id="trace-1", project_id="demo"),
    )
    context = environment.assemble({})
    context["_attribute_round"] = 1
    finalize = context["_attribute_finalize"]
    assert finalize()[0]["id"] == "cu-stage"
    with pytest.raises(TypeError):
        finalize(["source-file-key"])


def test_finalization_enforces_content_budget_across_load_chunks():
    class ChunkedContextRun:
        def __init__(self):
            self.loaded_ids = ["cu-1", "cu-2"]

        def debug_snapshot(self):
            return {"context_debug": {
                "loaded_ids": list(self.loaded_ids),
                "content_hashes": {},
                "policy": {"load_limit": 1, "content_char_budget": 7},
            }}

        def load_context_units(self, unit_ids):
            return [SimpleNamespace(id=unit_ids[0], name=unit_ids[0], description="", content="12345")]

        def context_unit_catalog(self):
            return []

    environment = AttributeExecutionEnvironment(
        main_context_run=ChunkedContextRun(),
        context_runtime=SimpleNamespace(registry=_FakeRegistry()),
        trace=RunTrace(trace_id="trace-1", project_id="demo"),
    )
    context = environment.assemble({})
    context["_attribute_round"] = 1

    with pytest.raises(ValueError, match="exceeds policy budget 7"):
        context["_attribute_finalize"]()


def test_reviewer_receives_catalog_entries_beyond_first_twenty(monkeypatch):
    captured = {}

    class ReviewClient:
        def complete_json(self, _system, user, **_kwargs):
            captured.update(__import__("json").loads(user))
            return {"passed": True, "issues": []}

    monkeypatch.setattr(
        "impl.core.attribute_reviewer.project_llm_client",
        lambda *_args, **_kwargs: ReviewClient(),
    )
    catalog = [
        {"context_unit_id": f"cu-{index}", "name": f"unit-{index}", "description": f"desc-{index}"}
        for index in range(25)
    ]
    tool_catalog = [{"name": f"tool-{index}", "description": f"tool-desc-{index}"} for index in range(25)]
    source_catalog = [{"key": f"source-{index}", "description": f"source-desc-{index}"} for index in range(25)]
    result = AttributeResult("trace-1", "demo", findings=[_finding()])
    review = review_attribute_result(
        spec=ProjectSpec(project_id="demo", name="demo"),
        trace=RunTrace(trace_id="trace-1", project_id="demo"),
        judge=_judge(),
        result=result,
        project_context={"_attribute_review_bundle": lambda _result: {
            "cited_evidence_context_units": [],
            "available_context_units": catalog,
            "available_tools": tool_catalog,
            "available_source_resources": source_catalog,
        }},
        round_number=1,
    )

    assert review == {"passed": True, "issues": []}
    received = captured["evidence_review_bundle"]["available_context_units"]
    assert len(received) == 25
    assert received[-1]["context_unit_id"] == "cu-24"
    assert captured["evidence_review_bundle"]["available_tools"][-1]["name"] == "tool-24"
    assert captured["evidence_review_bundle"]["available_source_resources"][-1]["key"] == "source-24"


def test_reviewer_rejects_oversized_bundle_without_silent_truncation(monkeypatch):
    monkeypatch.setattr(
        "impl.core.attribute_reviewer.project_llm_client",
        lambda *_args, **_kwargs: pytest.fail("oversized reviewer prompt must not call the LLM"),
    )
    result = AttributeResult("trace-1", "demo", findings=[_finding()])
    review = review_attribute_result(
        spec=ProjectSpec(project_id="demo", name="demo"),
        trace=RunTrace(trace_id="trace-1", project_id="demo"),
        judge=_judge(),
        result=result,
        project_context={
            "review_prompt_char_budget": 100,
            "_attribute_review_bundle": lambda _result: {
                "cited_evidence_context_units": [{"content": "x" * 500}],
                "available_context_units": [],
                "available_tools": [],
                "available_source_resources": [],
            },
        },
        round_number=1,
    )

    assert review["passed"] is False
    assert "未被静默截断" in review["infrastructure_error"]


def test_reviewer_loads_more_than_policy_limit_in_chunks():
    class ChunkedReviewContextRun:
        def __init__(self):
            self.calls = []

        def debug_snapshot(self):
            return {"context_debug": {"policy": {"load_limit": 2}}}

        def load_context_units(self, unit_ids):
            assert len(unit_ids) <= 2
            self.calls.append(list(unit_ids))
            return [
                SimpleNamespace(id=unit_id, name=unit_id, description="evidence", content=f"content:{unit_id}")
                for unit_id in unit_ids
            ]

        def context_unit_catalog(self):
            return []

    context_run = ChunkedReviewContextRun()
    environment = AttributeExecutionEnvironment(
        main_context_run=context_run,
        context_runtime=SimpleNamespace(registry=_FakeRegistry()),
        trace=RunTrace(trace_id="trace-1", project_id="demo"),
    )
    context = environment.assemble({})
    findings = [AttributionFinding(
        finding_id="finding-many-evidence",
        affected_expectation_ids=["stage"],
        conclusion="verified",
        evidence=[EvidenceRef(
            ref_id=f"ev-{index}", source="context_unit", kind="probe", stage="finalization",
            summary="evidence", location=f"cu-{index}", payload=None,
        ) for index in range(5)],
    )]

    bundle = context["_attribute_review_bundle"](AttributeResult("trace-1", "demo", findings=findings))

    assert context_run.calls == [["cu-0", "cu-1"], ["cu-2", "cu-3"], ["cu-4"]]
    assert len(bundle["cited_evidence_context_units"]) == 5


def test_verifiable_tool_result_is_registered_as_dynamic_context_unit():
    runtime = _FakeRuntime()
    environment = AttributeExecutionEnvironment(
        context_runtime=runtime,
        trace=RunTrace(trace_id="trace-1", project_id="demo", case_id="case-1"),
        execution_run_id="attribute-run-current",
    )

    def execute(**_kwargs):
        return ToolResult(tool_id="demo.probe", status="succeeded", actual={"stage": "unknown"})

    [tool] = environment._contextualize_verifiable_tools([
        VerifiableTool(tool_id="demo.probe", description="probe stage", parameters={}, execute_fn=execute)
    ], "main")
    result = tool.entrypoint()
    assert runtime.registered[0].tags["case_id"] == "case-1"
    assert runtime.registered[0].tags["run_id"] == "attribute-run-current"
    assert result.actual["context_unit_id"] == runtime.registered[0].id
    assert "无需重复 Load" in tool.description


def test_main_tool_material_is_immediately_recorded_as_investigated():
    runtime = _FakeRuntime()
    class TrackingContextRun:
        def __init__(self):
            self.loaded = []

        def load_context_units(self, unit_ids):
            self.loaded.extend(unit_ids)
            return []

    context_run = TrackingContextRun()
    environment = AttributeExecutionEnvironment(
        context_runtime=runtime,
        main_context_run=context_run,
        trace=RunTrace(trace_id="trace-1", project_id="demo", case_id="case-1"),
    )

    def execute(**_kwargs):
        return ToolResult(tool_id="demo.probe", status="succeeded", actual={"stage": "unknown"})

    [tool] = environment._contextualize_verifiable_tools([
        VerifiableTool(tool_id="demo.probe", description="probe stage", parameters={}, execute_fn=execute)
    ], "main")
    result = tool.entrypoint()

    assert result.actual["context_unit_id"] in context_run.loaded


def test_dynamic_context_registration_records_one_failure_then_clears_it_after_exact_success():
    runtime = _RetryRuntime()
    environment = AttributeExecutionEnvironment(
        context_runtime=runtime,
        trace=RunTrace(trace_id="trace-1", project_id="demo", case_id="case-1"),
    )

    def execute(**_kwargs):
        return ToolResult(tool_id="demo.probe", status="succeeded", actual={"stage": "unknown"})

    [tool] = environment._contextualize_verifiable_tools([
        VerifiableTool(tool_id="demo.probe", description="probe stage", parameters={}, execute_fn=execute)
    ], "main")
    first = tool.entrypoint()
    assert runtime.attempts == 1
    assert "context_unit_id" not in first.actual
    assert environment.registration_errors[0]["attempts"] == "1"

    result = tool.entrypoint()
    assert runtime.attempts == 2
    assert result.actual["context_unit_id"] == runtime.registered[0].id
    assert environment.registration_errors == []


def test_tool_result_survives_failed_context_registration_but_cannot_be_evidence():
    runtime = _RetryRuntime(always_fail=True)
    environment = AttributeExecutionEnvironment(
        context_runtime=runtime,
        trace=RunTrace(trace_id="trace-1", project_id="demo", case_id="case-1"),
    )

    def execute(**_kwargs):
        return ToolResult(tool_id="demo.probe", status="succeeded", actual={"stage": "unknown"})

    [tool] = environment._contextualize_verifiable_tools([
        VerifiableTool(tool_id="demo.probe", description="probe stage", parameters={}, execute_fn=execute)
    ], "main")
    result = tool.entrypoint()
    assert runtime.attempts == 1
    assert result.status == "succeeded"
    assert result.actual["stage"] == "unknown"
    assert "context_unit_id" not in result.actual
    failure = result.outputs["evidence_registration_error"]
    assert failure == {
        "material": "main_tool_demo_probe",
        "stage": "context_unit_registration",
        "error_type": "RuntimeError",
        "reason": "embedding unavailable",
        "attempts": "1",
    }


def test_invalid_embedding_is_not_retried_as_a_context_registration():
    runtime = _InvalidEmbeddingRuntime()
    environment = AttributeExecutionEnvironment(
        context_runtime=runtime,
        trace=RunTrace(trace_id="trace-1", project_id="demo", case_id="case-1"),
    )
    catalog = environment._register_dynamic_materials({"probe": {"stage": "unknown"}})

    assert catalog == []
    assert runtime.attempts == 1
    assert environment.registration_errors[0]["error_type"] == "ContextValidationError"
    assert environment.registration_errors[0]["attempts"] == "1"


def test_reviewer_infrastructure_failure_returns_no_formal_attribution(monkeypatch):
    attribute = _TwoRoundAttribute(ProjectSpec(project_id="demo", name="demo", attribute_draft={"enabled": True}))
    attribute.configure_execution_environment(AttributeExecutionEnvironment())
    monkeypatch.setattr(attribute, "_run_attribute_review", lambda *_args: {
        "passed": False,
        "issues": [],
        "infrastructure_error": "review model timeout",
    })
    result = attribute.attribute_failure(RunTrace(trace_id="trace-1", project_id="demo"), _judge())
    assert len(attribute.rounds) == 1
    assert result.findings == []
    assert "独立审查未完成" in result.unresolved_reason
    assert "review model timeout" in result.summary["summary_text"]
    audit = attribute._attribute_execution_environment.last_context["_attribute_review_audit"]
    assert audit == [{
        "round": 1,
        "finding_ids": ["finding-stage"],
        "passed": False,
        "issues": [],
        "infrastructure_error": "review model timeout",
    }]


def test_project_normalize_cannot_forge_post_finalization_finding():
    before = AttributeResult("trace-1", "demo", findings=[_finding()])
    forged = AttributeResult("trace-1", "demo", findings=[_finding(), AttributionFinding(
        "forged", ["stage"], "未经 Finalization 的结论", [_finding().evidence[0]],
    )])
    with pytest.raises(ValueError, match="may not add findings"):
        _TwoRoundAttribute._assert_normalize_subset(before, forged)


def test_context_store_keeps_multiple_review_loop_records_in_same_second(tmp_path, monkeypatch):
    monkeypatch.setattr(context_store, "STORE_DIR", tmp_path)
    common = dict(trace_id="trace-1", project_id="demo", caller="attribute", messages=[], created_at="2026-07-19T12:00:00Z")
    context_store.save_context(ContextRecord(record_id="round-one", **common))
    context_store.save_context(ContextRecord(record_id="round-two", **common))
    assert len(context_store.load_contexts_by_trace("demo", "trace-1")) == 2


def test_invalid_investigation_summary_still_enters_finalization_with_registered_materials():
    class TwoStageClient:
        def __init__(self):
            self.calls = 0

        def complete_json(self, _system, user, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ValueError("investigation output is markdown, not JSON")
            payload = __import__("json").loads(user)
            assert payload["investigation_summary"] == ""
            assert "not JSON" in payload["investigation_output_error"]
            assert payload["finalized_context_units"][0]["id"] == "cu-stage"
            return {
                "findings": [{
                    "finding_id": "finding-stage",
                    "affected_expectation_ids": ["stage"],
                    "conclusion": "当前路由规则把该输入映射为 unknown。",
                    "evidence": [{"context_unit_id": "cu-stage", "reason": "记录了 unknown 输出。"}],
                }],
                "unresolved_reason": "",
            }

    context = {
        "_attribute_finalize": lambda: [{
            "id": "cu-stage", "name": "stage result", "description": "", "content": {"stage": "unknown"}
        }],
        "_attribute_materialize_findings": lambda _findings, _failed_ids: [_finding()],
    }

    result = attribute_failure(
        ProjectSpec(project_id="demo", name="demo"),
        RunTrace(trace_id="trace-1", project_id="demo"),
        _judge(),
        llm=TwoStageClient(),
        project_attribute_context=context,
    )

    assert [finding.finding_id for finding in result.findings] == ["finding-stage"]
    assert result.unresolved_reason == ""


def test_finalization_and_reviewer_reject_derived_evidence_without_primary_material():
    assert "必须同时引用承载原始业务事实的 ContextUnit" in _finalization_system_prompt()
    assert "Tool 参数和由模型转写的 source_quote 不是原始证据" in _REVIEW_SYSTEM_PROMPT
    assert "必须在 unresolved_reason 中明确保留" in _finalization_system_prompt()
    assert "知道在哪段" in _REVIEW_SYSTEM_PROMPT
