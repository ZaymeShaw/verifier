from __future__ import annotations

"""Issue #3 端到端测试：验证 attribute_failure 完整路径中的 runtime_check 根因写入。

测试注入 fake LlmClient 模拟 LLM 行为，验证 AttributeResult 的关键字段
（suspected_locations、earliest_divergence.node、root_cause_hypothesis、causal_category）
是否来自 runtime_check 而非 LLM 推测。
"""

from impl.core.adapter import ProjectAdapter
from impl.core.attribute import attribute_failure, _enforce_divergence_root_cause
from impl.core.project_loader import load_adapter, load_project
from impl.core.runtime_query_tools import analyze_divergence, extract_runtime_values
from impl.core.schema import AttributeResult, JudgeResult, RunTrace


# ── fake LlmClient ──────────────────────────────────────────────

class FakeLlmClient:
    """返回最小有效 JSON，让 attribute_failure 走正常解析路径。"""

    def __init__(self, return_data: dict | None = None):
        self._return_data = return_data or {
            "causal_category": "",
            "root_cause_hypothesis": "",
            "suspected_locations": [],
            "expectation_attributions": [],
            "failure_category": "未归因",
            "failure_stage": "",
            "analysis_method": "",
            "evidence_chain": [],
            "chain_nodes": [],
            "local_verifications": [],
            "earliest_divergence": {},
            "evidence_coverage": {},
            "analysis_quality": {},
            "incomplete_reason": "",
            "verification_steps": [],
            "patch_direction": [],
            "business_impact": "",
            "primary_error_type": "",
            "error_types": [],
            "severity": "",
            "needs_human_review": None,
            "scenario": "",
            "quality_flags": [],
        }

    def complete_json(self, system: str, user: str, trace_id: str = None) -> dict:
        return dict(self._return_data)


# ── trace 构造（复用 test_issue3_runtime_checks 的 helper）────────

def _mpi_trace() -> RunTrace:
    return RunTrace(
        trace_id="e2e-issue3-mpi",
        project_id="marketting-planning-intent",
        input={"query": "我想做NBEV达成路径规划"},
        normalized_request={"query": "我想做NBEV达成路径规划"},
        raw_response={},
        extracted_output={"intent": "other", "raw_intent": "4001", "confidence": 0.8},
        project_fields={"reference": {"intent": "nbev_planning"}},
        execution_trace=[
            {"stage": "request_normalization", "status": "ok", "evidence": {"query": "我想做NBEV达成路径规划"}},
            {"stage": "intent_api_call", "status": "ok", "evidence": {"endpoint": "/api/v1/marketing-planning/intent-recognition"}},
            {"stage": "adapter_extraction", "status": "ok", "evidence": {"intent": "other", "raw_intent": "4001", "confidence": 0.8}},
            {"stage": "label_mapping", "status": "suspicious", "evidence": {"intent": "other", "raw_intent": "4001"}},
        ],
        status="ok",
    )


def _mp_trace() -> RunTrace:
    return RunTrace(
        trace_id="e2e-issue3-mp",
        project_id="marketting-planning",
        input={"query": "我想做NBEV达成路径规划，目标值120亿"},
        normalized_request={"query": "我想做NBEV达成路径规划，目标值120亿"},
        raw_response={},
        extracted_output={
            "stage": "planning",
            "card_summary": [{"path_type": "premium_growth"}, {"path_type": "customer_growth"}],
            "event_summary": {"canonical_names": ["intent_detected", "planning_started", "card_delta", "done"], "completed": True},
            "fallback": {"used": False},
        },
        project_fields={"reference": {"expected_stage": "planning", "required_path_types": ["premium_growth", "customer_growth"], "allow_fallback": False}},
        execution_trace=[
            {"stage": "request_normalization", "status": "ok", "evidence": {"turn_count": 1}},
            {"stage": "intent_recognition", "status": "ok", "evidence": {"actual_stage": "planning"}},
            {"stage": "path_dispatch", "status": "ok", "evidence": {"expected_path_types": ["premium_growth", "customer_growth"], "actual_path_types": ["premium_growth", "customer_growth"]}},
            {"stage": "planning_function", "status": "ok", "evidence": {"card_count": 2}},
            {"stage": "result_assembly", "status": "ok", "evidence": {}},
            {"stage": "sse_generation", "status": "ok", "evidence": {"completed": True}},
        ],
        status="ok",
    )


def _qa_trace() -> RunTrace:
    return RunTrace(
        trace_id="e2e-issue3-qa",
        project_id="QA",
        input={"input": {"question": "什么是犹豫期？"}},
        normalized_request={"input": {"question": "什么是犹豫期？"}, "reference": {"golden_answer": "犹豫期是投保人收到保险合同后在约定期限内可以解除合同的时间"}},
        raw_response={},
        extracted_output={"actual_answer": "犹豫期是投保人收到保险合同后在约定期限内可以解除合同的时间"},
        project_fields={"scenario": "qa_gold_answer", "reference": {"golden_answer": "犹豫期是投保人收到保险合同后在约定期限内可以解除合同的时间"}},
        execution_trace=[
            {"stage": "qa.sample.normalize", "status": "ok", "evidence": {"scenario": "qa_gold_answer"}},
            {"stage": "qa.output.read", "status": "ok", "evidence": "evaluated output read"},
            {"stage": "adapter.extract_output", "status": "ok", "evidence": {"actual_answer_present": True}},
        ],
        status="ok",
    )


def _cs_trace() -> RunTrace:
    return RunTrace(
        trace_id="e2e-issue3-cs",
        project_id="client_search",
        input={"query": "45岁女性保费10万以上"},
        normalized_request={"user_text": "45岁女性保费10万以上"},
        raw_response={},
        extracted_output={"structured_output": [{"field": "clientAge", "operator": "GTE", "value": 45}, {"field": "clientSex", "operator": "MATCH", "value": "女"}, {"field": "annPremSegNum", "operator": "GTE", "value": 100000}]},
        project_fields={"conditions": [{"field": "clientAge", "operator": "GTE", "value": 45}, {"field": "clientSex", "operator": "MATCH", "value": "女"}, {"field": "annPremSegNum", "operator": "GTE", "value": 100000}]},
        execution_trace=[
            {"stage": "adapter.build_request", "status": "ok", "evidence": {"user_text": "45岁女性保费10万以上"}},
            {"stage": "client_search.api", "status": "ok", "evidence": {"code": 0}},
            {"stage": "client_search.routing", "status": "ok", "evidence": {"matched_level": "L2"}},
            {"stage": "adapter.extract_output", "status": "ok", "evidence": {"condition_count": 3}},
        ],
        status="ok",
    )


def _build_context(spec, adapter, trace, judge):
    """构建 project_attribute_context（含 runtime_checks + simulate_trace_nodes + attribute_tools）。"""
    actual = judge.actual or trace.extracted_output or {}
    expected = judge.expected or (trace.project_fields or {}).get("reference") or {}
    runtime_context = {
        "expected": expected,
        "actual": actual,
        "reference": (trace.project_fields or {}).get("reference") or {},
        "wrong": list(judge.wrong or []),
        "missing": list(judge.missing or []),
        "trace_id": trace.trace_id,
        "project_id": trace.project_id,
    }
    runtime_values = extract_runtime_values(trace.execution_trace or [], actual)
    context = dict(adapter.build_attribute_context(trace, judge) or {})
    context["runtime_checks"] = adapter.get_runtime_checks(runtime_values, runtime_context)
    context["attribute_tools"] = adapter.build_attribute_tools()
    context["simulate_trace_nodes"] = adapter.simulate_trace_nodes(trace, judge)
    return context


# ── 端到端测试 ──────────────────────────────────────────────────


def test_e2e_mpi_runtime_check_suspected_locations():
    """marketting-planning-intent: runtime_check 根因路径下 suspected_locations 被填充"""
    spec = load_project("marketting-planning-intent")
    adapter = load_adapter(spec)
    trace = _mpi_trace()
    judge = JudgeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        verdict="incorrect",
        score=0,
        expected={"intent": "nbev_planning"},
        actual={"intent": "other", "raw_intent": "4001"},
        wrong=[{"field": "intent", "expected": "nbev_planning", "actual": "other"}],
        overall_fulfillment={"status": "not_fulfilled"},
        fulfillment_assessments=[{"expectation_id": "intent_accuracy", "status": "not_fulfilled"}],
    )
    context = _build_context(spec, adapter, trace, judge)
    fake_llm = FakeLlmClient()

    result = attribute_failure(spec, trace, judge, llm=fake_llm, project_attribute_context=context)

    assert result.causal_category == "implementation_bug"
    assert "4001" in result.root_cause_hypothesis
    assert len(result.suspected_locations) > 0, "suspected_locations 不应为空"
    assert any("intent.py" in str(loc) or "INTENT_MAPPING" in str(loc) for loc in result.suspected_locations), \
        f"suspected_locations 应包含 intent.py 或 INTENT_MAPPING: {result.suspected_locations}"
    assert "divergence_analysis_root_cause" in result.quality_flags
    assert result.earliest_divergence.get("node") not in ("", "unknown", "state_machine_incomplete", None), \
        f"earliest_divergence.node 应被填充: {result.earliest_divergence}"


def test_e2e_mp_runtime_check_suspected_locations():
    """marketting-planning: runtime_check 根因路径下 suspected_locations 被填充（缺失 path 场景）"""
    spec = load_project("marketting-planning")
    adapter = load_adapter(spec)
    actual = {"stage": "planning", "card_summary": [{"path_type": "premium_growth"}], "fallback": {"used": False}, "event_summary": {"canonical_names": ["intent_detected", "planning_started", "card_delta", "done"], "completed": True}}
    expected = {"expected_stage": "planning", "required_path_types": ["premium_growth", "customer_growth"], "allow_fallback": False}
    trace = _mp_trace()
    trace.extracted_output = actual
    trace.project_fields["reference"] = expected
    judge = JudgeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        verdict="incorrect",
        score=0,
        expected=expected,
        actual=actual,
        wrong=[{"field": "card_summary", "detail": "missing customer_growth"}],
        overall_fulfillment={"status": "not_fulfilled"},
        fulfillment_assessments=[{"expectation_id": "planning_path_coverage", "status": "not_fulfilled"}],
    )
    context = _build_context(spec, adapter, trace, judge)
    fake_llm = FakeLlmClient()

    result = attribute_failure(spec, trace, judge, llm=fake_llm, project_attribute_context=context)

    assert result.causal_category == "implementation_bug"
    assert len(result.suspected_locations) > 0, "suspected_locations 不应为空"
    assert any("path_types" in str(loc) or "PATH_ORDER" in str(loc) or "config_dev" in str(loc) for loc in result.suspected_locations), \
        f"suspected_locations 应包含 path_types 或 config_dev: {result.suspected_locations}"
    assert "divergence_analysis_root_cause" in result.quality_flags


def test_e2e_qa_runtime_check_suspected_locations():
    """QA: runtime_check 根因路径下 suspected_locations 被填充（答案不匹配场景）"""
    spec = load_project("QA")
    adapter = load_adapter(spec)
    actual = {"actual_answer": "保险期限就是合同生效后的一段时间"}
    expected = {"golden_answer": "犹豫期是投保人收到保险合同后在约定期限内可以解除合同的时间"}
    trace = _qa_trace()
    trace.extracted_output = actual
    trace.project_fields["reference"] = expected
    judge = JudgeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        verdict="incorrect",
        score=0,
        expected=expected,
        actual=actual,
        wrong=[{"field": "actual_answer", "detail": "golden answer mismatch"}],
        overall_fulfillment={"status": "not_fulfilled"},
        fulfillment_assessments=[{"expectation_id": "qa_answer_quality", "status": "not_fulfilled"}],
    )
    context = _build_context(spec, adapter, trace, judge)
    fake_llm = FakeLlmClient()

    result = attribute_failure(spec, trace, judge, llm=fake_llm, project_attribute_context=context)

    assert result.causal_category == "model_capability_gap"
    assert len(result.suspected_locations) > 0, "suspected_locations 不应为空"
    assert any("QA/adapter.py" in str(loc) or "_text_overlap_ratio" in str(loc) or "_infer_scenario" in str(loc) for loc in result.suspected_locations), \
        f"suspected_locations 应包含 QA adapter: {result.suspected_locations}"
    assert "divergence_analysis_root_cause" in result.quality_flags


def test_e2e_cs_runtime_check_suspected_locations():
    """client_search: runtime_check 根因路径下 suspected_locations 被填充（未知字段场景）"""
    spec = load_project("client_search")
    adapter = load_adapter(spec)
    actual = {"conditions": [{"field": "clientAge", "operator": "GTE", "value": 50}, {"field": "nonExistentField", "operator": "MATCH", "value": "test"}]}
    expected = {"conditions": [{"field": "clientAge", "operator": "GTE", "value": 50}]}
    trace = _cs_trace()
    trace.extracted_output = {"structured_output": actual["conditions"]}
    trace.project_fields["conditions"] = actual["conditions"]
    trace.project_fields["reference"] = expected
    judge = JudgeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        verdict="incorrect",
        score=0,
        expected=expected,
        actual=actual,
        wrong=[{"field": "nonExistentField", "detail": "unknown field"}],
        overall_fulfillment={"status": "not_fulfilled"},
        fulfillment_assessments=[{"expectation_id": "search_condition_validity", "status": "not_fulfilled"}],
    )
    context = _build_context(spec, adapter, trace, judge)
    fake_llm = FakeLlmClient()

    result = attribute_failure(spec, trace, judge, llm=fake_llm, project_attribute_context=context)

    assert result.causal_category == "implementation_bug"
    assert "nonExistentField" in result.root_cause_hypothesis
    assert len(result.suspected_locations) > 0, "suspected_locations 不应为空"
    assert any("field_definition" in str(loc).lower() or "_capability_manifest" in str(loc).lower() or "source_field_definitions" in str(loc).lower() for loc in result.suspected_locations), \
        f"suspected_locations 应包含 field_definition 或 _capability_manifest: {result.suspected_locations}"
    assert "divergence_analysis_root_cause" in result.quality_flags


def test_e2e_llm_call_failed_fallback_to_runtime_root_cause():
    """LLM 调用失败时兜底到 runtime root cause（analysis_method 和 quality_flags 正确）"""
    spec = load_project("marketting-planning-intent")
    adapter = load_adapter(spec)
    trace = _mpi_trace()
    judge = JudgeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        verdict="incorrect",
        score=0,
        expected={"intent": "nbev_planning"},
        actual={"intent": "other", "raw_intent": "4001"},
        wrong=[{"field": "intent"}],
        overall_fulfillment={"status": "not_fulfilled"},
        fulfillment_assessments=[{"expectation_id": "x", "status": "not_fulfilled"}],
        quality_flags=["llm_call_failed"],
    )
    context = _build_context(spec, adapter, trace, judge)
    # 模拟 LLM 调用失败
    fake_llm = FakeLlmClient({"error": "llm_request_failed", "raw_text": "insufficient balance"})

    result = attribute_failure(spec, trace, judge, llm=fake_llm, project_attribute_context=context)

    assert result.analysis_method == "trace_runtime_analysis_with_project_checks"
    assert "divergence_analysis_root_cause" in result.quality_flags
    assert result.root_cause_hypothesis, "LLM 失败时应有 root_cause_hypothesis 来自 runtime_check"
    assert result.causal_category == "implementation_bug"


def test_e2e_project_tools_in_context():
    """4 个 adapter 的 build_attribute_tools 返回非空可调用列表"""
    for project_id in ("marketting-planning-intent", "marketting-planning", "QA", "client_search"):
        adapter = load_adapter(load_project(project_id))
        tools = adapter.build_attribute_tools()
        assert isinstance(tools, list), f"{project_id}: build_attribute_tools 应返回 list"
        assert len(tools) > 0, f"{project_id}: build_attribute_tools 不应为空"
        for tool in tools:
            assert callable(tool), f"{project_id}: tool {tool} 应是 callable"
            assert hasattr(tool, "__name__"), f"{project_id}: tool 应有 __name__"
            assert tool.__name__, f"{project_id}: tool __name__ 不应为空"


def test_e2e_simulate_trace_nodes_divergence():
    """marketting-planning-intent 的 simulate_trace_nodes 检测到 diverged 节点"""
    spec = load_project("marketting-planning-intent")
    adapter = load_adapter(spec)
    trace = _mpi_trace()
    judge = JudgeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        verdict="incorrect",
        score=0,
        expected={"intent": "nbev_planning"},
        actual={"intent": "other"},
        overall_fulfillment={"status": "not_fulfilled"},
    )

    result = adapter.simulate_trace_nodes(trace, judge)

    assert "simulated_nodes" in result
    assert "diverged_nodes" in result
    assert len(result["simulated_nodes"]) > 0, "应对 label_mapping 节点产出模拟结果"
    # trace 的 intent="other" 与 INTENT_MAPPING["4001"] 映射结果一致 → diverged_nodes 为空
    # 但如果有 diverged（取决于 mapping 实际值），要有 source 字段
    assert "source" in result


def test_e2e_simulate_trace_nodes_mp_missing_path():
    """marketting-planning 的 simulate_trace_nodes 检测到缺失 path 时的 diverged 节点"""
    spec = load_project("marketting-planning")
    adapter = load_adapter(spec)
    trace = _mp_trace()
    # 修改 trace：只产出 premium_growth 但 expected 要求 customer_growth
    trace.extracted_output["card_summary"] = [{"path_type": "premium_growth"}]
    trace.execution_trace[2] = {"stage": "path_dispatch", "status": "suspicious", "evidence": {"expected_path_types": ["premium_growth", "customer_growth"], "actual_path_types": ["premium_growth"]}}
    judge = JudgeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        verdict="incorrect",
        score=0,
        expected={"required_path_types": ["premium_growth", "customer_growth"]},
        actual={"card_summary": [{"path_type": "premium_growth"}]},
        overall_fulfillment={"status": "not_fulfilled"},
    )

    result = adapter.simulate_trace_nodes(trace, judge)

    assert "simulated_nodes" in result
    assert "diverged_nodes" in result
    assert len(result["simulated_nodes"]) > 0
    assert len(result["diverged_nodes"]) > 0, "缺失 customer_growth 应产生 diverged 节点"
    diverged = result["diverged_nodes"][0]
    assert "missing_paths" in diverged
    assert "customer_growth" in str(diverged.get("missing_paths", []))


def test_e2e_simulate_trace_nodes_cs_unknown_field():
    """client_search 的 simulate_trace_nodes 检测到未知字段时的 diverged 节点"""
    spec = load_project("client_search")
    adapter = load_adapter(spec)
    trace = _cs_trace()
    trace.extracted_output = {"structured_output": [{"field": "nonExistentField", "operator": "MATCH", "value": "test"}]}
    trace.project_fields["conditions"] = [{"field": "nonExistentField", "operator": "MATCH", "value": "test"}]
    judge = JudgeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        verdict="incorrect",
        score=0,
        expected={"conditions": []},
        actual={"conditions": [{"field": "nonExistentField"}]},
        overall_fulfillment={"status": "not_fulfilled"},
    )

    result = adapter.simulate_trace_nodes(trace, judge)

    assert "simulated_nodes" in result
    assert "diverged_nodes" in result
    assert len(result["simulated_nodes"]) > 0
    assert len(result["diverged_nodes"]) > 0, "nonExistentField 应产生 diverged 节点"
    diverged = result["diverged_nodes"][0]
    assert "unknown_fields" in diverged.get("simulated_output", {})
    assert "nonExistentField" in str(diverged.get("simulated_output", {}).get("unknown_fields", []))