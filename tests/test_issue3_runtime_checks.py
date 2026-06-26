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

    assert checks["check_type"] == "intent_mapping"
    assert checks["source"] == "projects/marketting-planning-intent/intent.py:INTENT_MAPPING"
    assert checks["raw_intent"] == "4001"
    assert checks["actual_mapping"] == "other"
    assert checks["expected_intent"] == "nbev_planning"
    assert checks["status"] == "failed"
    assert checks["root_cause"]


def test_generic_divergence_consumes_runtime_checks_without_project_branch():
    spec = load_project("marketting-planning-intent")
    adapter = load_adapter(spec)
    trace = _mpi_trace()
    actual = trace.extracted_output
    expected = trace.project_fields["reference"]
    runtime_values = extract_runtime_values(trace.execution_trace, actual)
    checks = adapter.get_runtime_checks(runtime_values, {"expected": expected, "actual": actual, "reference": expected})

    analysis = analyze_divergence(trace.execution_trace, expected, actual, runtime_checks=checks)

    assert analysis["system_check"]["check_type"] == "intent_mapping"
    assert analysis["root_cause"]["category"] == "implementation_bug"
    assert analysis["causal_category"] == "implementation_bug"
    assert "prompt 文件不在 catalog" not in analysis["root_cause_hypothesis"]
    assert "无法审查 prompt" not in analysis["root_cause_hypothesis"]
