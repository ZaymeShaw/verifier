from impl.core.attribute_protocol import ProjectAttribute
from impl.core.schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace
from impl.projects.deerflow.attribute import DeerflowAttribute, _deerflow_integrity_probes


def _judge(status="not_fulfilled", *, expected=None, actual=None):
    return JudgeResult(
        trace_id="trace-1",
        project_id="deerflow",
        overall_fulfillment={"status": status},
        expected=expected,
        actual=actual,
    )


def _ai(content, tool_calls=None):
    return {
        "metadata": {},
        "content": {"type": "ai", "content": content, "tool_calls": list(tool_calls or [])},
    }


def test_deerflow_probe_compares_each_turn_raw_and_extracted_message():
    plan = """执行计划：
1. 目标：提升转化
2. 策略：分层触达
3. 执行阶段：下周启动
4. 指标：转化率"""
    trace = RunTrace(
        trace_id="trace-1",
        project_id="deerflow",
        input={"query": "制定计划"},
        normalized_request={"query": "制定计划"},
        turn_records=[
            {
                "call_status": "succeeded",
                "raw_response": [{"thread_id": "t-1"}, [_ai(plan, [])]],
                "extracted_output": {
                    "reply_text": plan,
                    "tool_calls": [{"name": "ask_clarification", "args": {}}],
                    "scripts_called": [],
                    "stage": "clarification",
                },
            }
        ],
    )

    probes = _deerflow_integrity_probes(trace, _judge())
    turn_probe = probes[0]

    assert turn_probe["raw_reply_text"] == plan
    assert turn_probe["raw_tool_names"] == []
    assert turn_probe["extracted_tool_names"] == ["ask_clarification"]
    assert turn_probe["raw_vs_extracted_tool_calls_match"] is False
    assert turn_probe["inferred_stage"] == "clarification"
    assert turn_probe["stage_inference_rule"] == "current_message_ask_clarification"


def test_deerflow_probe_records_controller_error_as_separate_runtime_evidence():
    trace = RunTrace(
        trace_id="trace-1",
        project_id="deerflow",
        interaction_controller_status="error",
        interaction_controller_error="mock decision parse failed",
        stop_reason="decision_error",
        completion_status="incomplete",
    )

    probes = _deerflow_integrity_probes(trace, _judge())

    assert probes == [{
        "probe_id": "deerflow_interaction_controller",
        "controller_status": "error",
        "controller_error": "mock decision parse failed",
        "stop_reason": "decision_error",
        "completion_status": "incomplete",
    }]


def test_deerflow_strong_attribution_is_downgraded_without_runtime_evidence():
    attribute = DeerflowAttribute(ProjectSpec(project_id="deerflow", name="deerflow"))
    trace = RunTrace(trace_id="trace-1", project_id="deerflow")
    result = AttributeResult(
        trace_id="trace-1",
        project_id="deerflow",
        evidence=["model hypothesis only"],
        evidence_strength="strong",
    )

    normalized = attribute.normalize_result(trace, _judge(), result)

    assert normalized.evidence_strength == "weak"


def test_common_attribute_gate_rejects_strong_failure_attribution_without_probes_or_runtime_checks():
    class MinimalAttribute(ProjectAttribute):
        def build_context(self, trace, judge_result):
            return {"runtime_checks": {}}

    attribute = MinimalAttribute(ProjectSpec(project_id="demo", name="demo"))
    result = AttributeResult(trace_id="trace-1", project_id="demo", evidence_strength="strong")

    validated = attribute._validate_attribute_output(result, {"probe_results": [], "runtime_checks": {}}, _judge())

    assert validated.evidence_strength == "weak"



def test_deerflow_raw_message_presence_alone_does_not_justify_strong_code_attribution():
    reply = "已生成营销计划。"
    trace = RunTrace(
        trace_id="trace-1",
        project_id="deerflow",
        extracted_output={"reply_text": reply, "tool_calls": [], "stage": "intent"},
        turn_records=[{
            "call_status": "succeeded",
            "raw_response": [[_ai(reply, [])]],
            "extracted_output": {"reply_text": reply, "tool_calls": [], "stage": "intent"},
        }],
    )
    result = AttributeResult(
        trace_id="trace-1",
        project_id="deerflow",
        suspected_locations=["reply_extraction"],
        evidence_strength="strong",
    )

    normalized = DeerflowAttribute(ProjectSpec(project_id="deerflow", name="deerflow")).normalize_result(
        trace,
        _judge(expected={"stage": "planning"}, actual=trace.extracted_output),
        result,
    )

    assert normalized.evidence_strength == "weak"


def test_deerflow_strong_code_attribution_requires_matching_probe_location():
    reply = "已生成营销计划。"
    trace = RunTrace(
        trace_id="trace-1",
        project_id="deerflow",
        extracted_output={
            "reply_text": reply,
            "tool_calls": [{"name": "ask_clarification", "args": {}}],
            "stage": "clarification",
        },
        turn_records=[{
            "call_status": "succeeded",
            "raw_response": [[_ai(reply, [])]],
            "extracted_output": {
                "reply_text": reply,
                "tool_calls": [{"name": "ask_clarification", "args": {}}],
                "stage": "clarification",
            },
        }],
    )
    attribute = DeerflowAttribute(ProjectSpec(project_id="deerflow", name="deerflow"))
    judge = _judge(expected={"tool_calls": []}, actual=trace.extracted_output)

    supported = attribute.normalize_result(
        trace,
        judge,
        AttributeResult(
            trace_id="trace-1",
            project_id="deerflow",
            suspected_locations=["tool_call_extraction"],
            evidence_strength="strong",
        ),
    )
    unsupported = attribute.normalize_result(
        trace,
        judge,
        AttributeResult(
            trace_id="trace-1",
            project_id="deerflow",
            suspected_locations=["reply_extraction"],
            evidence_strength="strong",
        ),
    )

    assert supported.evidence_strength == "strong"
    assert unsupported.evidence_strength == "weak"


def test_deerflow_reply_probe_ignores_surrounding_whitespace_normalization():
    reply = "已生成营销计划。"
    trace = RunTrace(
        trace_id="trace-1",
        project_id="deerflow",
        extracted_output={"reply_text": reply, "tool_calls": [], "stage": "intent"},
        turn_records=[{
            "call_status": "succeeded",
            "raw_response": [[_ai(f"{reply}\n", [])]],
            "extracted_output": {"reply_text": reply, "tool_calls": [], "stage": "intent"},
        }],
    )

    normalized = DeerflowAttribute(ProjectSpec(project_id="deerflow", name="deerflow")).normalize_result(
        trace,
        _judge(expected={"reply_text": reply}, actual=trace.extracted_output),
        AttributeResult(
            trace_id="trace-1",
            project_id="deerflow",
            suspected_locations=["reply_extraction"],
            evidence_strength="strong",
        ),
    )

    assert normalized.evidence_strength == "weak"


def test_deerflow_strong_code_attribution_requires_every_claimed_location_to_be_supported():
    reply = "已生成营销计划。"
    trace = RunTrace(
        trace_id="trace-1",
        project_id="deerflow",
        extracted_output={
            "reply_text": reply,
            "tool_calls": [{"name": "ask_clarification", "args": {}}],
            "stage": "clarification",
        },
        turn_records=[{
            "call_status": "succeeded",
            "raw_response": [[_ai(reply, [])]],
            "extracted_output": {
                "reply_text": reply,
                "tool_calls": [{"name": "ask_clarification", "args": {}}],
                "stage": "clarification",
            },
        }],
    )

    normalized = DeerflowAttribute(ProjectSpec(project_id="deerflow", name="deerflow")).normalize_result(
        trace,
        _judge(expected={"tool_calls": []}, actual=trace.extracted_output),
        AttributeResult(
            trace_id="trace-1",
            project_id="deerflow",
            suspected_locations=["tool_call_extraction", "reply_extraction"],
            evidence_strength="strong",
        ),
    )

    assert normalized.evidence_strength == "weak"


def test_common_attribute_gate_treats_failed_probe_as_missing_evidence():
    class MinimalAttribute(ProjectAttribute):
        def build_context(self, trace, judge_result):
            return {}

    attribute = MinimalAttribute(ProjectSpec(project_id="demo", name="demo"))
    result = AttributeResult(trace_id="trace-1", project_id="demo", evidence_strength="strong")

    validated = attribute._validate_attribute_output(
        result,
        {"probe_results": [{"probe_status": "failed", "probe_error": "timeout"}], "runtime_checks": {}},
        _judge(),
    )

    assert validated.evidence_strength == "weak"


def test_common_attribute_gate_keeps_fulfilled_fast_path_strong():
    class MinimalAttribute(ProjectAttribute):
        def build_context(self, trace, judge_result):
            return {}

    attribute = MinimalAttribute(ProjectSpec(project_id="demo", name="demo"))
    result = AttributeResult(trace_id="trace-1", project_id="demo", evidence_strength="strong")

    validated = attribute._validate_attribute_output(
        result,
        {"probe_results": [], "runtime_checks": {}},
        _judge("fulfilled"),
    )

    assert validated.evidence_strength == "strong"


def test_attribute_summary_is_recomputed_after_evidence_strength_downgrade(monkeypatch):
    class MinimalAttribute(ProjectAttribute):
        def build_context(self, trace, judge_result):
            return {"runtime_checks": {}}

    def fake_attribute_failure(**_kwargs):
        return AttributeResult(
            trace_id="trace-1",
            project_id="demo",
            expectation_attributions=[{
                "expectation_id": "deliver-plan",
                "fulfillment_status": "not_fulfilled",
            }],
            root_cause_hypothesis="unverified model hypothesis",
            evidence_strength="strong",
            summary={"is_formal_attribution": True, "is_complete": True},
        )

    monkeypatch.setattr("impl.core.attribute.attribute_failure", fake_attribute_failure)
    result = MinimalAttribute(ProjectSpec(project_id="demo", name="demo")).attribute_failure(
        RunTrace(trace_id="trace-1", project_id="demo"),
        _judge(),
    )

    assert result.evidence_strength == "weak"
    assert result.summary["is_formal_attribution"] is False
    assert result.summary["is_complete"] is False
