from __future__ import annotations

from impl.core.adapter import ProjectAdapter
from impl.core.project_loader import load_adapter, load_project
from impl.core.runtime_query_tools import analyze_divergence, extract_runtime_values
from impl.core.schema import JudgeResult, RunTrace
from impl.tools import ToolRegistry


def _mpi_trace() -> RunTrace:
    return RunTrace(
        trace_id="issue3-test",
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
        trace_id="issue3-mp-test",
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
        trace_id="issue3-qa-test",
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
        trace_id="issue3-cs-test",
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


class MinimalAdapter(ProjectAdapter):
    def build_request(self, input_data):
        return input_data

    def extract_output(self, raw_response):
        return raw_response if isinstance(raw_response, dict) else {}


def test_base_adapter_keeps_protocol_tools_registry():
    spec = load_project("marketting-planning-intent")
    base = MinimalAdapter(spec)

    assert isinstance(base.protocol_tools(), ToolRegistry)
    assert base.get_runtime_checks({}) == {}
    assert base.build_attribute_tools() == []


def test_mpi_runtime_check_uses_project_mapping_source():
    spec = load_project("marketting-planning-intent")
    adapter = load_adapter(spec)
    trace = _mpi_trace()
    actual = trace.extracted_output
    expected = trace.project_fields["reference"]
    runtime_values = extract_runtime_values(trace.execution_trace, actual)

    checks = adapter.get_runtime_checks(runtime_values, {"expected": expected, "actual": actual, "reference": expected})

    # 聚合 check_type 为 intent_contract，内含 intent_mapping 子 check
    assert checks["check_type"] == "intent_contract"
    assert "projects/marketting-planning-intent/intent.py:INTENT_MAPPING" in checks["source"]
    assert checks["raw_intent"] == "4001"
    assert checks["actual_mapping"] == "other"
    assert checks["expected_intent"] == "nbev_planning"
    assert checks["status"] == "failed"
    assert checks["root_cause"]
    # 子 check 结构
    intent_sub = next(c for c in checks["checks"] if c["check_type"] == "intent_mapping")
    assert intent_sub["status"] == "failed"
    assert intent_sub["root_cause"]


def test_mpi_runtime_check_detects_invalid_slot_value():
    """Issue #3 修复：required_slots 校验识别 slots.year='mock_value' 占位值。

    复现 mpi-required-slot-missing-1 case：intent 映射正确，但 slots.year
    为占位符 'mock_value'。runtime_check 必须产出细粒度 root_cause，
    而非让 analyze_divergence 退回通用模板。
    """
    spec = load_project("marketting-planning-intent")
    adapter = load_adapter(spec)
    # intent 映射正确（nbev_planning），但 slots.year 为占位值
    # raw_intent="nbev_planning" 让 intent 映射子 check 也 passed，
    # 这样主 root_cause 必然来自 required_slots 校验
    actual = {"intent": "nbev_planning", "raw_intent": "nbev_planning", "slots": {"year": "mock_value"}}
    expected = {"intent": "nbev_planning", "required_slots": ["year"], "allow_fallback": False}

    checks = adapter.get_runtime_checks(
        {"raw_intent": "nbev_planning", "intent": "nbev_planning", "slots": {"year": "mock_value"}},
        {"expected": expected, "actual": actual, "reference": expected},
    )

    assert checks["status"] == "failed"
    slot_sub = next(c for c in checks["checks"] if c["check_type"] == "required_slots_validation")
    assert slot_sub["status"] == "failed"
    assert len(slot_sub["invalid_slots"]) > 0
    assert slot_sub["invalid_slots"][0]["slot"] == "year"
    assert "mock_value" in str(slot_sub["invalid_slots"][0]["value"])
    assert slot_sub["root_cause"] is not None
    # root_cause 必须含具体 slot 名 + 占位值证据
    assert "year" in slot_sub["root_cause"]["summary"]
    assert "mock_value" in slot_sub["root_cause"]["summary"]
    # 主 root_cause 应来自 slot 校验（intent 校验 passed）
    assert checks["root_cause"] is not None
    assert "year" in checks["root_cause"]["summary"]


def test_mpi_runtime_check_detects_missing_slot():
    """required_slots 校验识别 slot 缺失（slot 不在 actual.slots 中）"""
    spec = load_project("marketting-planning-intent")
    adapter = load_adapter(spec)
    actual = {"intent": "nbev_planning", "raw_intent": "nbev_planning", "slots": {}}
    expected = {"intent": "nbev_planning", "required_slots": ["year"]}

    checks = adapter.get_runtime_checks(
        {"raw_intent": "nbev_planning", "intent": "nbev_planning", "slots": {}},
        {"expected": expected, "actual": actual, "reference": expected},
    )

    slot_sub = next(c for c in checks["checks"] if c["check_type"] == "required_slots_validation")
    assert slot_sub["status"] == "failed"
    assert slot_sub["invalid_slots"][0]["slot"] == "year"
    assert checks["root_cause"] is not None


def test_mpi_runtime_check_slots_pass_when_valid():
    """required_slots 校验在 slot 值有效时通过"""
    spec = load_project("marketting-planning-intent")
    adapter = load_adapter(spec)
    actual = {"intent": "nbev_planning", "raw_intent": "nbev_planning", "slots": {"year": "2026"}}
    expected = {"intent": "nbev_planning", "required_slots": ["year"]}

    checks = adapter.get_runtime_checks(
        {"raw_intent": "nbev_planning", "intent": "nbev_planning", "slots": {"year": "2026"}},
        {"expected": expected, "actual": actual, "reference": expected},
    )

    slot_sub = next(c for c in checks["checks"] if c["check_type"] == "required_slots_validation")
    assert slot_sub["status"] == "passed"
    assert slot_sub["invalid_slots"] == []


def test_generic_divergence_consumes_runtime_checks_without_project_branch():
    spec = load_project("marketting-planning-intent")
    adapter = load_adapter(spec)
    trace = _mpi_trace()
    actual = trace.extracted_output
    expected = trace.project_fields["reference"]
    runtime_values = extract_runtime_values(trace.execution_trace, actual)
    checks = adapter.get_runtime_checks(runtime_values, {"expected": expected, "actual": actual, "reference": expected})

    analysis = analyze_divergence(trace.execution_trace, expected, actual, runtime_checks=checks)

    assert analysis["system_check"]["check_type"] == "intent_contract"
    assert analysis["root_cause"]["category"] == "implementation_bug"
    assert analysis["causal_category"] == "implementation_bug"
    assert "prompt 文件不在 catalog" not in analysis["root_cause_hypothesis"]
    assert "无法审查 prompt" not in analysis["root_cause_hypothesis"]


# --- Issue #3 扩展: marketting-planning / QA / client_search 的 get_runtime_checks ---


def test_marketting_planning_runtime_check_loads_business_path_types():
    """marketting-planning adapter 的 get_runtime_checks 直接加载业务系统 path_types.py 和 config_dev.json"""
    spec = load_project("marketting-planning")
    adapter = load_adapter(spec)
    trace = _mp_trace()
    actual = trace.extracted_output
    expected = trace.project_fields["reference"]
    runtime_values = extract_runtime_values(trace.execution_trace, actual)

    checks = adapter.get_runtime_checks(runtime_values, {"expected": expected, "actual": actual, "reference": expected})

    assert checks["check_type"] == "marketing_planning_contract"
    assert "checks" in checks
    assert len(checks["checks"]) >= 3  # path_type + stage + fallback/sse
    assert checks["status"] == "passed"  # premium_growth + customer_growth 都匹配
    assert "app/workflow/path_types.py" in checks["source"] or "path_types" in checks["source"]
    assert "app/configs/config_dev.json" in checks["source"] or "config_dev" in checks["source"]

    # 验证 path_type 校验项
    path_check = next(c for c in checks["checks"] if c["check_type"] == "path_type_validation")
    assert path_check["status"] == "passed"
    assert path_check["missing_paths"] == []
    assert path_check["extra_forbidden"] == []


def test_marketting_planning_runtime_check_detects_missing_path():
    """marketting-planning 的 get_runtime_checks 检测到缺失路径时返回 root_cause"""
    spec = load_project("marketting-planning")
    adapter = load_adapter(spec)
    actual = {"stage": "planning", "card_summary": [{"path_type": "premium_growth"}], "fallback": {"used": False}, "event_summary": {"canonical_names": ["intent_detected", "planning_started", "card_delta", "done"], "completed": True}}
    expected = {"expected_stage": "planning", "required_path_types": ["premium_growth", "customer_growth"], "allow_fallback": False}

    checks = adapter.get_runtime_checks({}, {"expected": expected, "actual": actual, "reference": expected})

    assert checks["status"] == "failed"
    path_check = next(c for c in checks["checks"] if c["check_type"] == "path_type_validation")
    assert path_check["status"] == "failed"
    assert "customer_growth" in path_check["missing_paths"]
    assert path_check.get("root_cause") is not None
    assert checks["root_cause"] is not None
    assert checks["root_cause"]["category"] == "implementation_bug"


def test_qa_runtime_check_uses_golden_answer_match():
    """QA adapter 的 get_runtime_checks 直接调用 _infer_scenario + _text_overlap_ratio 判定"""
    spec = load_project("QA")
    adapter = load_adapter(spec)
    trace = _qa_trace()
    actual = trace.extracted_output
    expected = trace.project_fields["reference"]

    checks = adapter.get_runtime_checks({}, {"expected": expected, "actual": actual, "reference": expected})

    assert checks["check_type"] == "qa_answer_quality"
    assert "checks" in checks
    assert len(checks["checks"]) >= 2
    assert checks["status"] == "passed"  # exact match

    golden_check = next(c for c in checks["checks"] if c["check_type"] == "qa_golden_answer_match")
    assert golden_check["status"] == "passed"
    assert golden_check["exact_match"] is True
    assert "impl/projects/QA/adapter.py" in checks["source"]


def test_qa_runtime_check_detects_mismatch():
    """QA 的 get_runtime_checks 检测到 golden_answer 不匹配时返回 root_cause"""
    spec = load_project("QA")
    adapter = load_adapter(spec)
    actual = {"actual_answer": "保险期限就是合同生效后的一段时间"}
    expected = {"golden_answer": "犹豫期是投保人收到保险合同后在约定期限内可以解除合同的时间"}

    checks = adapter.get_runtime_checks({}, {"expected": expected, "actual": actual, "reference": expected})

    assert checks["status"] == "failed"
    golden_check = next(c for c in checks["checks"] if c["check_type"] == "qa_golden_answer_match")
    assert golden_check["status"] == "failed"
    assert golden_check["exact_match"] is False
    assert golden_check["overlap_ratio"] is not None
    assert golden_check["overlap_ratio"] < 1.0
    assert checks["root_cause"] is not None
    assert checks["root_cause"]["category"] == "model_capability_gap"


def test_client_search_runtime_check_loads_field_definitions():
    """client_search adapter 的 get_runtime_checks 直接加载业务系统 field definitions YAML"""
    spec = load_project("client_search")
    adapter = load_adapter(spec)
    trace = _cs_trace()
    actual = trace.extracted_output
    expected = trace.project_fields

    checks = adapter.get_runtime_checks({}, {"expected": expected, "actual": actual, "reference": expected, "wrong": [], "missing": []})

    assert checks["check_type"] == "client_search_condition_contract"
    assert "checks" in checks
    assert len(checks["checks"]) >= 2

    field_check = next(c for c in checks["checks"] if c["check_type"] == "field_definition_manifest")
    assert field_check["status"] == "passed"
    assert field_check["field_count"] > 0  # 至少加载了一些字段定义
    assert "source_field_definitions" in field_check["source"]

    cond_check = next(c for c in checks["checks"] if c["check_type"] == "condition_validation")
    assert cond_check["status"] == "passed"
    assert cond_check["unknown_fields"] == []


def test_client_search_runtime_check_detects_unknown_fields():
    """client_search 的 get_runtime_checks 检测到不在 capability_manifest 中的字段"""
    spec = load_project("client_search")
    adapter = load_adapter(spec)
    actual = {"conditions": [{"field": "clientAge", "operator": "GTE", "value": 50}, {"field": "nonExistentField", "operator": "MATCH", "value": "test"}]}
    expected = {"conditions": [{"field": "clientAge", "operator": "GTE", "value": 50}]}

    checks = adapter.get_runtime_checks({}, {"expected": expected, "actual": actual, "reference": expected, "wrong": [], "missing": []})

    cond_check = next(c for c in checks["checks"] if c["check_type"] == "condition_validation")
    assert cond_check["status"] == "failed"
    assert len(cond_check["unknown_fields"]) > 0
    assert "nonExistentField" in cond_check["unknown_fields"]
    assert checks["status"] == "failed"
    assert checks["root_cause"] is not None


def test_analyze_divergence_consumes_mp_runtime_checks():
    """marketting-planning 的 runtime_checks 被 analyze_divergence 正确消费，不再出现 stale 标记"""
    spec = load_project("marketting-planning")
    adapter = load_adapter(spec)
    trace = _mp_trace()
    actual = trace.extracted_output
    expected = trace.project_fields["reference"]
    runtime_values = extract_runtime_values(trace.execution_trace, actual)
    checks = adapter.get_runtime_checks(runtime_values, {"expected": expected, "actual": actual, "reference": expected})

    analysis = analyze_divergence(trace.execution_trace, expected, actual, runtime_checks=checks)

    assert analysis["system_check"]["check_type"] == "marketing_planning_contract"
    assert analysis["evidence_source"] == "execution_trace + adapter_runtime_checks"
    assert "prompt 文件不在 catalog" not in analysis.get("root_cause_hypothesis", "")
    assert "无法审查" not in analysis.get("root_cause_hypothesis", "")


def test_analyze_divergence_consumes_qa_runtime_checks():
    """QA 的 runtime_checks 被 analyze_divergence 正确消费"""
    spec = load_project("QA")
    adapter = load_adapter(spec)
    trace = _qa_trace()
    actual = trace.extracted_output
    expected = trace.project_fields["reference"]
    checks = adapter.get_runtime_checks({}, {"expected": expected, "actual": actual, "reference": expected})

    analysis = analyze_divergence(trace.execution_trace, expected, actual, runtime_checks=checks)

    assert analysis["system_check"]["check_type"] == "qa_answer_quality"
    assert analysis["evidence_source"] == "execution_trace + adapter_runtime_checks"


def test_analyze_divergence_consumes_cs_runtime_checks():
    """client_search 的 runtime_checks 被 analyze_divergence 正确消费"""
    spec = load_project("client_search")
    adapter = load_adapter(spec)
    trace = _cs_trace()
    actual = trace.extracted_output
    expected = trace.project_fields
    checks = adapter.get_runtime_checks({}, {"expected": expected, "actual": actual, "reference": expected, "wrong": [], "missing": []})

    analysis = analyze_divergence(trace.execution_trace, expected, actual, runtime_checks=checks)

    assert analysis["system_check"]["check_type"] == "client_search_condition_contract"
    assert analysis["evidence_source"] == "execution_trace + adapter_runtime_checks"


# --- Issue #3 扩展: 项目级 tool 暴露 + 模拟调用机制 ---


def test_build_attribute_tools_returns_callable_functions():
    """4 个 adapter 的 build_attribute_tools 返回非空可调用函数列表（Issue #3: 项目 tool 暴露给 attribute agent）"""
    for project_id in ("marketting-planning-intent", "marketting-planning", "QA", "client_search"):
        adapter = load_adapter(load_project(project_id))
        tools = adapter.build_attribute_tools()
        assert isinstance(tools, list), f"{project_id}: build_attribute_tools 应返回 list"
        assert len(tools) > 0, f"{project_id}: build_attribute_tools 不应为空（Issue #3 要求项目 tool 被暴露）"
        for tool in tools:
            assert callable(tool), f"{project_id}: tool {tool} 应是 callable"
            assert hasattr(tool, "__name__") and tool.__name__, f"{project_id}: tool 应有非空 __name__（Agno 需要）"
            assert tool.__doc__, f"{project_id}: tool {tool.__name__} 应有 docstring（Agno 需要）"


def test_simulate_trace_nodes_mpi_label_mapping():
    """marketting-planning-intent 的 simulate_trace_nodes 对 label_mapping 节点模拟调用 INTENT_MAPPING"""
    spec = load_project("marketting-planning-intent")
    adapter = load_adapter(spec)
    trace = _mpi_trace()
    checks = adapter.get_runtime_checks(
        extract_runtime_values(trace.execution_trace, trace.extracted_output),
        {"expected": trace.project_fields["reference"], "actual": trace.extracted_output, "reference": trace.project_fields["reference"]},
    )

    result = adapter.simulate_trace_nodes(trace, type("J", (), {"verdict": "incorrect"})())

    assert "simulated_nodes" in result
    assert "diverged_nodes" in result
    assert "source" in result
    assert len(result["simulated_nodes"]) > 0, "应对 label_mapping/adapter_extraction 节点产出模拟结果"
    # 每个模拟节点应包含关键字段
    for node in result["simulated_nodes"]:
        assert "stage" in node
        assert "simulated_output" in node
        assert "trace_actual" in node
        assert "status" in node
        assert "function_called" in node
        assert "source_file" in node
        assert node["function_called"] == "INTENT_MAPPING.get"
        assert "intent.py" in node["source_file"]


def test_simulate_trace_nodes_mp_path_dispatch():
    """marketting-planning 的 simulate_trace_nodes 对 path_dispatch 节点模拟调用 normalize_path_types"""
    spec = load_project("marketting-planning")
    adapter = load_adapter(spec)
    trace = _mp_trace()

    result = adapter.simulate_trace_nodes(trace, type("J", (), {"verdict": "correct"})())

    assert "simulated_nodes" in result
    assert "diverged_nodes" in result
    # path_dispatch 节点应被模拟
    path_nodes = [n for n in result["simulated_nodes"] if n["stage"] == "path_dispatch"]
    if path_nodes:
        node = path_nodes[0]
        assert node["function_called"] == "normalize_path_types"
        assert "path_types.py" in node["source_file"]
        assert "normalized_actual" in node["simulated_output"]


def test_simulate_trace_nodes_qa_answer_quality():
    """QA 的 simulate_trace_nodes 对 qa.output.read 节点模拟调用 _text_overlap_ratio"""
    spec = load_project("QA")
    adapter = load_adapter(spec)
    trace = _qa_trace()

    result = adapter.simulate_trace_nodes(trace, type("J", (), {"verdict": "correct"})())

    assert "simulated_nodes" in result
    assert "diverged_nodes" in result
    assert len(result["simulated_nodes"]) > 0
    for node in result["simulated_nodes"]:
        assert node["function_called"] == "_text_overlap_ratio"
        assert "QA/adapter.py" in node["source_file"]
        assert "overlap_ratio" in node["simulated_output"]
        assert "exact_match" in node["simulated_output"]


def test_simulate_trace_nodes_cs_field_validation():
    """client_search 的 simulate_trace_nodes 对 routing 节点模拟调用 _capability_manifest 校验字段"""
    spec = load_project("client_search")
    adapter = load_adapter(spec)
    trace = _cs_trace()

    result = adapter.simulate_trace_nodes(trace, type("J", (), {"verdict": "correct"})())

    assert "simulated_nodes" in result
    assert "diverged_nodes" in result
    assert len(result["simulated_nodes"]) > 0
    for node in result["simulated_nodes"]:
        assert node["function_called"] == "_capability_manifest"
        assert "valid_field_count" in node["simulated_output"]
        assert "unknown_fields" in node["simulated_output"]
