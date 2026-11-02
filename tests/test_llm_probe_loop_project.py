"""llm_probe_loop 项目接入：轴定义存储、场景框校验、错误码、对外入口（实施 P6、R5、R6）。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from impl.core.axis_loop.validate import check_definitions
from impl.core.capability_store import validate_entry
from impl.projects.llm_probe_loop.eval_axes import business_failure, main_axis_upstream
from impl.projects.llm_probe_loop.eval_axes.materials import registry
from impl.projects.llm_probe_loop.eval_axes.registry import AXIS_TYPES, definitions, describe_axis_types
from impl.projects.llm_probe_loop.eval_axes.validate import validate_scenario_entry


def test_definitions_load_clean():
    defs = definitions()
    process = ("intent_understanding", "planning_routing", "tool_execution", "context_memory", "knowledge_data", "model_capability")
    assert list(defs.axes) == ["expectations", "blocking", "claims", "truthfulness", "fulfillment", "carryability", "main_verdict", "trace_analysis",
                               *(k for a in process for k in (f"{a}_expected", a))]
    assert list(defs.shared_tools) == ["search_knowledge"]
    assert check_definitions(defs, registry()) == []
    loops = {k: a.loop for k, a in defs.axes.items()}
    assert {k: loops[k] for k in ("expectations", "blocking", "claims", "truthfulness", "fulfillment", "carryability", "main_verdict", "trace_analysis")} == {
        "expectations": "expectations", "blocking": "blocking", "claims": "main", "truthfulness": "truthfulness",
        "fulfillment": "main", "carryability": "carryability", "main_verdict": "main", "trace_analysis": "trace_analysis"}
    assert all(loops[f"{a}_expected"] == "process_expected" and loops[a] == "process" for a in process)
    assert AXIS_TYPES["expectations"].role == "analysis" and AXIS_TYPES["fulfillment"].role == "evaluation"
    assert [k for k, info in AXIS_TYPES.items() if info.requires_business_trace] == ["trace_analysis"]
    assert {d["type_id"] for d in describe_axis_types()} == set(defs.axes)
    assert main_axis_upstream() == {"expectations", "blocking", "claims", "truthfulness", "trace_analysis",
                                    *process, *(f"{a}_expected" for a in process)}


def test_visibility_is_built_into_the_definitions():
    defs = definitions()
    delivery = ("case.deliveries",)
    # 交付第一次进 case loop 是说法抽取出现时，此时期望已定；需求、blocking 各自一个 loop、材料里没有交付
    assert ("expectations", True) in [(d.axis, d.hard) for d in defs.axes["claims"].depends]
    for key in ("expectations", "blocking"):
        assert not any(m.startswith(delivery) for m in defs.axes[key].materials)
    assert defs.loops["expectations"].dispatch is not None


def test_dispatch_splits_requirements_by_turn():
    view = SimpleNamespace(materials={"case.requirements": {"sources": [
        {"id": "t1.user", "turn": "t1", "side": "want", "component": "user"},
        {"id": "t2.history.0", "turn": "t2", "side": "history", "component": "history"},
        {"id": "t2.user", "turn": "t2", "side": "want", "component": "user"}], "missing": []}})
    parts = definitions().loops["expectations"].dispatch(view)
    assert parts == [{"id": "t1", "materials": ["case.requirements.sources[id=t1.user]"]},
                     {"id": "t2", "materials": ["case.requirements.sources[id=t2.history.0,t2.user]"]}]


def test_requirements_do_not_read_the_expectations_box():
    """场景对需求轴的描述走本轴描述槽位（spec/alg/axis_loop.md §2.5），需求侧材料里只有原话与历史。"""
    from impl.projects.llm_probe_loop.eval_axes.materials import Case
    trace = SimpleNamespace(turn_records=None, project_fields={},
                            normalized_request={"body": {"messages": [{"role": "user", "content": "查保单"}]}})
    sources = Case(trace, "s", {}, {"expectations": "交付物是保单金额"}).requirements()["sources"]
    assert [s["component"] for s in sources] == ["user"]


def test_process_obligations_live_in_the_expected_axis_box():
    with pytest.raises(ValueError, match="本应轴的描述框"):
        validate_scenario_entry({"axes": [], "process_obligations": []}, owner="x")


def test_every_model_axis_has_a_description_box():
    boxes = {d["type_id"]: bool(d["scenario_fields"]) for d in describe_axis_types()}
    assert boxes.pop("main_verdict") is False
    assert all(boxes.values())


def test_scenario_entry_needs_hard_dependencies():
    with pytest.raises(ValueError, match="硬依赖 expectations"):
        validate_scenario_entry({"axes": [{"type": "fulfillment", "enabled": True, "description": ""}]}, owner="x")
    axes = validate_scenario_entry({"axes": [{"type": k, "enabled": True, "description": ""}
                                             for k in ("expectations", "blocking", "claims", "fulfillment", "main_verdict")]}, owner="x")
    assert axes.enabled == ["expectations", "blocking", "claims", "fulfillment", "main_verdict"]


def _trace(output_text="", fallback_reason=""):
    fallbacks = [SimpleNamespace(quality_flags=["live_http_error"], reason=fallback_reason)] if fallback_reason else []
    return SimpleNamespace(fallbacks=fallbacks, extracted_output={"output_text": output_text})


def test_only_registered_error_codes_count_as_business_failure():
    entry = validate_entry("s", {"capability": "x", "business_failure": {"http_status": [503], "body": {"pointer": "/code", "values": ["E1"]}}})
    assert business_failure.matched(_trace(fallback_reason='HTTP 503: {"msg": "busy"}'), entry).startswith("被测系统返回 HTTP 503")
    assert business_failure.matched(_trace(fallback_reason='HTTP 500: {"msg": "x"}'), entry) == ""   # 没登记的非 2xx 照常评测
    assert "错误码 /code=E1" in business_failure.matched(_trace('{"code": "E1", "data": null}'), entry)
    assert business_failure.matched(_trace('{"code": "OK"}'), entry) == ""
    assert business_failure.matched(_trace(fallback_reason="HTTP 503: x"), {}) == ""                   # 没配就不判失败
    with pytest.raises(ValueError):
        validate_entry("s", {"capability": "x", "business_failure": {"http_status": ["503"]}})


def test_mcp_check_tool_is_registered_apart_from_model_tools():
    from impl.projects.llm_probe_loop.eval_axes.sources.registry import validate_source_entry
    base = {"type": "mcp", "command": "python", "args": [], "tools": ["policy_search"]}
    assert validate_source_entry("x", {**base, "check_tool": "check_case"})
    with pytest.raises(ValueError, match="check_tool"):
        validate_source_entry("x", {**base, "check_tool": "policy_search"})


def test_scenario_trace_selection_shape():
    entry = validate_entry("s", {"capability": "x", "business_trace": {"source": "agno-insurance", "bindings": {"session_id": {}}}})
    assert entry["business_trace"] == {"source": "agno-insurance", "bindings": {"session_id": {}}}
    with pytest.raises(ValueError, match="source"):
        validate_entry("s", {"capability": "x", "business_trace": {"source": "a", "bindings": {}, "config": {}}})


def test_case_trace_is_unavailable_when_a_turn_was_not_collected():
    from impl.core.axis_loop.materials import MaterialUnavailable
    from impl.projects.llm_probe_loop.eval_axes.materials import Case, _trace
    failed = {"status": "failed", "provider": "agno", "errors": ["Agno GET /sessions 失败"]}
    trace = SimpleNamespace(turn_records=[{"project_fields": {"business_trace": failed}, "request": {}, "extracted_output": {}}],
                            project_fields={}, normalized_request={}, extracted_output={})
    with pytest.raises(MaterialUnavailable, match="trace 采集失败"):
        _trace(Case(trace, "s", {}, {}), {})


def test_trace_is_collected_only_when_an_enabled_axis_reads_case_trace(monkeypatch):
    from impl.projects.llm_probe_loop import capability
    selection = {"source": "agno-insurance", "bindings": {}}
    scenarios = {"s": {"business_trace": selection, "axes": [{"type": "claims", "enabled": True}]}}
    monkeypatch.setattr(capability, "load_capability_map", lambda *a: scenarios)
    assert capability.capability_business_trace("s") is None
    defs = definitions()
    claims = defs.axes["claims"]
    reading = type(defs)(axes={**defs.axes, "claims": type(claims)(**{**claims.__dict__, "materials": ("case.trace.catalog",)})},
                         loops=defs.loops)
    monkeypatch.setattr("impl.projects.llm_probe_loop.eval_axes.registry.definitions", lambda: reading)
    assert capability.capability_business_trace("s") == selection


def test_axis_display_defaults_by_role_and_can_be_overridden():
    axes = definitions().axes
    # 需求、blocking、说法是分析轴但明细里展开；其余分析轴收起；评测轴展开
    assert {k for k, a in axes.items() if a.role == "analysis" and a.display == "expanded"} == {"expectations", "blocking", "claims"}
    assert axes["trace_analysis"].display == "collapsed"
    assert axes["planning_routing_expected"].display == "collapsed"
    assert all(a.display == "expanded" for a in axes.values() if a.role == "evaluation")
