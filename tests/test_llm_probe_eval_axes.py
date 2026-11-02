"""llm_probe 扩展评估轴（试验体系）：一个 trace → 两个 AxisResult，依赖 / 筛选 / 隔离 / 校验。

LLM 用确定性假客户端：monkeypatch impl.core.llm_client.project_llm_client，
按 role 分发——judge 给轴1，capability_carrier_mapper 给轴2。
"""
from __future__ import annotations

import json
from typing import Any, Callable

import pytest

from impl.core.capability_carrier import PLACEMENT_CANNOT, PLACEMENT_WRONG
from impl.core.capability_store import validate_entry
from impl.core.project_loader import load_project
from impl.core.schema import RunTrace
from impl.projects.llm_probe.eval_axes import runner as runner_module
from impl.projects.llm_probe.eval_axes.registry import AXIS_TYPES, describe_axis_types, get_axis_type
from impl.projects.llm_probe.eval_axes.runner import run_axes, topo_order
from impl.projects.llm_probe.eval_axes.types import (
    STATUS_BLOCKED,
    STATUS_DISABLED,
    STATUS_FAILED,
    STATUS_NOT_APPLICABLE,
    STATUS_SUCCEEDED,
    AxisRequestFailed,
    AxisRuntime,
    AxisType,
    ExecutionLimits,
    Field,
    Input,
    RunOutcome,
    ScenarioAxis,
    Verdict,
    When,
    raise_for_error_payload,
)
from impl.projects.llm_probe.eval_axes.validate import parse_axes, validate_scenario_axes

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

CAPABILITY = "用户拿它办的事：从客户库检回符合描述的客户。交付物是查询条件。"
BOUNDARY = "本接口仅支持按客户姓名检索，不支持年龄。"
EXPECTATION = "按年龄筛选客户"


FAKE_MODEL = "fake-judge-model"


def _fake_router(*endpoints):
    from impl.core.llm_router import LlmEndpoint, LlmRouter

    endpoints = endpoints or (("primary", FAKE_MODEL),)
    return LlmRouter([LlmEndpoint(name=name, base_url="http://fake", model=model, api_key="x") for name, model in endpoints])


class FakeLlm:
    """模拟 LlmClient 与路由交互的最小面：select → 调用 → record_success；select 抛错则像真客户端一样返回 error 字典。"""

    def __init__(self, role: str, script: Callable[[str, str, str], dict], router=None) -> None:
        self.role = role
        self.model = FAKE_MODEL
        self.llm_router = router or _fake_router()
        self._script = script
        self.calls: list[dict[str, Any]] = []

    def complete_json(self, system: str, user: str, trace_id: str | None = None, output_spec: Any = None, **kwargs: Any) -> dict:
        self.calls.append({"system": system, "user": user, "trace_id": trace_id, **kwargs})
        try:
            endpoint = self.llm_router.select()
        except RuntimeError as exc:
            return {"error": "llm_request_failed", "raw_text": str(exc)}
        self.llm_router.record_success(endpoint)
        return self._script(self.role, system, user)


E_ID = "t1." + EXPECTATION  # 需求轴给期望编号加轮次前缀
SCOPE_URI = "boundary://llm_probe/scope"  # 业务方登记的责任范围（测试里由 expand_boundary 假装登记）


def _judge_payload(system: str, status: str, output_text: str) -> dict:
    """judge 角色的三种调用：需求轴写 E、兑现轴投影 blocking、兑现轴判给到没有。按 system 区分。"""
    from impl.projects.llm_probe.eval_axes.adapters import expectations as expectations_axis, fulfillment as fulfillment_axis
    if system.startswith(expectations_axis.SYSTEM):  # 需求轴，或兑现轴自推（同一套写法加排除规则）
        return {"expectations": [{"expectation_id": EXPECTATION, "source_refs": ["t1.user"], "about": "客户",
                                  "statement": "输出带年龄条件", "condition": "总是", "ambiguity_group": ""}]}
    if system == fulfillment_axis.BLOCKING_SYSTEM:
        return {"items": [{"expectation_id": E_ID, "blocking": True}]}
    assert system == fulfillment_axis.DELIVERY_SYSTEM
    return {"items": [{"expectation_id": E_ID, "reason": "输出缺少年龄条件", "status": status,
                       "evidence": [output_text] if status == "fulfilled" and output_text else [], "claim_refs": []}],
            "reasoning_summary": "输出缺少年龄条件"}


def _carrier_payload(carry: str) -> dict:
    if carry == "no":
        return {
            "carry": "no",
            "reason": "责任范围登记写明不支持年龄",
            "self_recognition": "不支持年龄",
            "citations": [{"source": SCOPE_URI, "ref": "boundary", "note": "不支持年龄"}],
        }
    return {
        "carry": "yes",
        "reason": "登记覆盖姓名检索",
        "citations": [{"source": SCOPE_URI, "ref": "boundary", "note": "支持按客户姓名检索"}],
    }


def _install_fake_llm(monkeypatch, *, judge_status: str = "not_fulfilled", carry: str = "no", judge_error: bool = False,
                      router_factory=None, output_text: str = '{"conditions": []}') -> list[FakeLlm]:
    created: list[FakeLlm] = []
    from impl.projects.llm_probe.eval_axes.adapters import expectations as expectations_axis

    def script(role: str, system: str, _user: str) -> dict:
        if role == "judge":
            if judge_error and not system.startswith(expectations_axis.SYSTEM):
                return {"error": "llm down"}
            return _judge_payload(system, judge_status, output_text)
        if role == "capability_carrier_mapper":
            return _carrier_payload(carry)
        raise AssertionError(f"unexpected role {role}")

    def factory(_spec: Any, role: str, **_kwargs: Any) -> FakeLlm:
        client = FakeLlm(role, script, router=router_factory() if router_factory else None)
        created.append(client)
        return client

    monkeypatch.setattr("impl.core.llm_client.project_llm_client", factory)
    monkeypatch.setattr("impl.projects.llm_probe.eval_axes.adapters.carryability.expand_boundary",
                        lambda description: (description, [{"uri": SCOPE_URI, "title": "责任范围", "content": BOUNDARY}]))
    return created


def _judge_clients(clients: list[FakeLlm]) -> list[FakeLlm]:
    """兑现轴自己的 judge 客户端（需求轴也用 judge 角色，按第一次调用的 system 区分）。"""
    from impl.projects.llm_probe.eval_axes.adapters import fulfillment as fulfillment_axis
    return [c for c in clients if c.role == "judge" and c.calls and c.calls[0]["system"] == fulfillment_axis.BLOCKING_SYSTEM]


def _trace(output_text: str = '{"conditions": []}') -> RunTrace:
    return RunTrace(
        trace_id="probe-trace-1",
        project_id="llm_probe",
        case_id="case-1",
        normalized_request={
            "body": {"query": "找 30 岁以下客户"},
            "url": "http://127.0.0.1:9/llm-probe",
            "capability_ref": "client_search",
        },
        extracted_output={"output_text": output_text},
    )


def _axes(*, fulfillment_enabled: bool = True, carryability_enabled: bool = True) -> list[ScenarioAxis]:
    return [
        ScenarioAxis("expectations", True, ""),
        ScenarioAxis("fulfillment", fulfillment_enabled, ""),
        ScenarioAxis("carryability", carryability_enabled, BOUNDARY),
    ]


def _by_id(results) -> dict[str, Any]:
    return {item.axis_id: item for item in results}


# ---------------------------------------------------------------- 类型可见


def test_registry_exposes_types_with_frozen_enums() -> None:
    described = {item["type_id"]: item for item in describe_axis_types()}
    assert set(described) == {
        "fulfillment", "carryability", "knowledge_evidence", "truthfulness", "trace_analysis", "expectations", "intent_understanding",
        "planning_routing", "tool_execution", "context_memory", "knowledge_data",
        "model_capability",
    }
    assert [v["value"] for v in described["trace_analysis"]["verdict_enum"]] == ["complete", "partial"]
    assert described["trace_analysis"]["verdict_scope"] == "axis"
    assert described["trace_analysis"]["requires_business_trace"] is True
    assert [v["value"] for v in described["fulfillment"]["verdict_enum"]] == ["fulfilled", "not_fulfilled", "not_evaluable"]
    assert [v["value"] for v in described["carryability"]["verdict_enum"]] == ["做不了", "做错了", "说不清"]
    assert described["fulfillment"]["verdict_scope"] == "axis"
    assert described["carryability"]["verdict_scope"] == "item"
    assert described["carryability"]["depend_on"] == [{"type_id": "fulfillment", "optional": False}]
    assert described["carryability"]["trigger_when"] == {"axis": "fulfillment", "verdict_in": ["not_fulfilled"]}
    # 轴2不看这次交付了什么：除上游轴字段外只有请求体（只交给 MCP 取身份），没有整份 trace
    assert all(item["source"].startswith("axis.") or item["source"] == "sample.request_body" for item in described["carryability"]["inputs"])


# ---------------------------------------------------------------- 端到端


def test_one_trace_yields_two_results_with_isolation(monkeypatch) -> None:
    monkeypatch.setattr("impl.projects.llm_probe.eval_axes.llm.model_policy", lambda: "any")
    clients = _install_fake_llm(monkeypatch, judge_status="not_fulfilled", carry="no")
    spec = load_project("llm_probe")
    results = _by_id(run_axes(spec, _trace(), _axes(), scenario_id="client_search", run_id="axes-test"))

    fulfillment = results["fulfillment"]
    assert fulfillment.status == STATUS_SUCCEEDED
    assert fulfillment.title == "能力兑现"
    assert fulfillment.verdict == "not_fulfilled"
    assert fulfillment.verdict_description
    assert fulfillment.summary["text"] == "输出缺少年龄条件"
    assert fulfillment.summary["items"] == [{
        "key": E_ID, "value": "not_fulfilled", "reason": "输出缺少年龄条件", "blocking": True, "claim_refs": [],
    }]
    assert set(fulfillment.output) == set(AXIS_TYPES["fulfillment"].output_fields)
    assert fulfillment.output["overall_fulfillment"]["status"] == "not_fulfilled"
    assert fulfillment.output["claims_checked"] is False
    # 期望来自需求轴，不由兑现轴派生（spec/alg/fulfilled.md §1）
    assert set(fulfillment.inputs_used) == {"trace", "expectations"}
    assert fulfillment.output["business_expectations"][0]["expected_outcome"] == "输出带年龄条件"
    assert fulfillment.usage["llm_calls"] == 2  # blocking 投影 + 交付判定
    # 实际命中的模型/端点进 usage（axe-v4 D12）
    assert fulfillment.usage["llm_model"] == FAKE_MODEL
    assert fulfillment.usage["llm_endpoint"] == "primary"
    assert fulfillment.usage["model_policy"] == "any"
    assert fulfillment.execution_trace_ref == "axes-test:probe-trace-1"

    carryability = results["carryability"]
    assert carryability.status == STATUS_SUCCEEDED
    assert carryability.verdict is None  # item 级没有轴级单值
    assert carryability.trigger_decision["trigger_when_matched"]["matched"] is True
    assert list(carryability.inputs_used) == ["fulfillment", "request_body"]
    assert "sample.trace" not in json.dumps(carryability.inputs_used)
    placements = carryability.output["placements"]
    assert [item["placement"] for item in placements] == [PLACEMENT_CANNOT]
    assert placements[0]["expectation_id"] == E_ID
    assert placements[0]["recognition"] == "responsibility_registration"
    assert carryability.output["errors"] == []
    assert carryability.usage["llm_calls"] == 1
    assert carryability.usage["llm_model"] == FAKE_MODEL
    assert carryability.usage["tool_calls"] == 0
    from impl.core.capability_carrier import carrier_text
    assert carryability.summary["text"] == carrier_text(carryability.output)
    assert carryability.summary["text"].startswith("$做不了\n")
    assert carryability.summary["items"] == [{
        "key": E_ID, "value": PLACEMENT_CANNOT, "reason": "责任范围登记写明不支持年龄", "carry": "no",
    }]

    judge_calls = [c for client in _judge_clients(clients) for c in client.calls]
    carrier_calls = [c for client in clients if client.role == "capability_carrier_mapper" for c in client.calls]
    assert len(judge_calls) == 2 and len(carrier_calls) == 1
    # blocking 只看 E，不看交付；兑现轴不读场景能力描述
    assert "conditions" not in judge_calls[0]["user"]
    assert "conditions" in judge_calls[1]["user"]
    assert all(CAPABILITY not in call["user"] for call in judge_calls)
    # 信息隔离：承载性 prompt 只有期望 + 依据 / 背景，没有这次的回答
    assert BOUNDARY in carrier_calls[0]["user"]
    assert "输出带年龄条件" in carrier_calls[0]["user"]
    assert "conditions" not in carrier_calls[0]["user"]
    # 试验的 LLM 调用统一挂在 axes- 前缀的 trace_id 下
    assert judge_calls[0]["trace_id"] == "axes-test:probe-trace-1"
    assert carrier_calls[0]["trace_id"] == "axes-test:probe-trace-1"


def test_fulfillment_derives_expectations_without_seeing_delivery_when_no_expectations_axis(monkeypatch) -> None:
    """只开兑现轴：自推期望（demand/expectations.md §3）——推期望那次只看用户原话和场景描述，看不到交付；
    场景描述当判准读，但要排除行为规范和能力声明。"""
    from impl.projects.llm_probe.eval_axes.adapters import fulfillment as fulfillment_axis
    clients = _install_fake_llm(monkeypatch, judge_status="not_fulfilled")
    axes = [ScenarioAxis("fulfillment", True, CAPABILITY), ScenarioAxis("carryability", False, BOUNDARY)]
    results = _by_id(run_axes(load_project("llm_probe"), _trace('{"conditions": []}'), axes, scenario_id="client_search"))
    fulfillment = results["fulfillment"]
    assert fulfillment.status == STATUS_SUCCEEDED and fulfillment.verdict == "not_fulfilled"
    assert fulfillment.output["expectations_source"] == "self"
    assert "expectations" not in results
    calls = [c for client in clients if client.role == "judge" for c in client.calls]
    derive = calls[0]
    assert derive["system"] == fulfillment_axis.DERIVE_SYSTEM
    assert "行为规范" in derive["system"]
    assert CAPABILITY in derive["user"] and "找 30 岁以下客户" in derive["user"]
    assert "conditions" not in derive["user"]  # 定期望时看不到交付
    assert "conditions" in calls[-1]["user"]


def test_fulfillment_reads_expectations_axis_when_present_and_fails_if_it_failed(monkeypatch) -> None:
    """需求轴跑了就用它的 E，不另推；开了却失败，兑现轴记运行失败，不自推顶上。"""
    _install_fake_llm(monkeypatch)
    results = _by_id(run_axes(load_project("llm_probe"), _trace(), _axes(carryability_enabled=False), scenario_id="client_search"))
    assert results["fulfillment"].output["expectations_source"] == "expectations"
    assert set(results["fulfillment"].inputs_used) == {"trace", "expectations"}

    from impl.projects.llm_probe.eval_axes.adapters import expectations as expectations_axis
    def boom(*_args, **_kwargs):
        raise ValueError("需求材料坏了")
    monkeypatch.setattr(expectations_axis, "write_expectations", boom)
    results = _by_id(run_axes(load_project("llm_probe"), _trace(), _axes(carryability_enabled=False), scenario_id="client_search"))
    assert results["expectations"].status == STATUS_FAILED
    assert results["fulfillment"].status == STATUS_FAILED
    assert "需求轴已启用但没有成功" in results["fulfillment"].error


def test_carry_yes_places_wrong(monkeypatch) -> None:
    _install_fake_llm(monkeypatch, judge_status="not_fulfilled", carry="yes")
    results = _by_id(run_axes(load_project("llm_probe"), _trace(), _axes(), scenario_id="client_search"))
    assert results["carryability"].status == STATUS_SUCCEEDED
    assert [p["placement"] for p in results["carryability"].output["placements"]] == [PLACEMENT_WRONG]


def test_fulfilled_makes_carryability_not_applicable_without_llm_call(monkeypatch) -> None:
    clients = _install_fake_llm(monkeypatch, judge_status="fulfilled")
    results = _by_id(run_axes(load_project("llm_probe"), _trace(), _axes(), scenario_id="client_search"))
    assert results["fulfillment"].verdict == "fulfilled"
    carryability = results["carryability"]
    assert carryability.status == STATUS_NOT_APPLICABLE
    assert carryability.output is None
    assert carryability.trigger_decision["depend_on_satisfied"] is True
    assert carryability.trigger_decision["trigger_when_matched"]["verdict"] == "fulfilled"
    assert carryability.summary == {"text": "fulfillment=fulfilled，不在筛选范围 [not_fulfilled]，不判", "items": []}
    assert not [c for c in clients if c.role == "capability_carrier_mapper"]


def test_not_evaluable_also_skips_carryability(monkeypatch) -> None:
    _install_fake_llm(monkeypatch, judge_status="not_evaluable")
    results = _by_id(run_axes(load_project("llm_probe"), _trace(), _axes(), scenario_id="client_search"))
    assert results["fulfillment"].status == STATUS_SUCCEEDED
    assert results["fulfillment"].verdict == "not_evaluable"
    assert results["carryability"].status == STATUS_NOT_APPLICABLE


def test_judge_failure_is_failed_status_and_blocks_downstream(monkeypatch) -> None:
    clients = _install_fake_llm(monkeypatch, judge_error=True)
    results = _by_id(run_axes(load_project("llm_probe"), _trace(), _axes(), scenario_id="client_search"))
    fulfillment = results["fulfillment"]
    assert fulfillment.status == STATUS_FAILED
    assert fulfillment.verdict is None          # 没跑成进 status，不伪装成 not_evaluable
    assert "llm down" in fulfillment.error
    assert fulfillment.summary["text"] == fulfillment.error
    carryability = results["carryability"]
    assert carryability.status == STATUS_BLOCKED
    assert carryability.trigger_decision == {"depend_on_satisfied": False, "upstream": {"fulfillment": STATUS_FAILED}}
    assert carryability.summary["text"].startswith("上游未成功：fulfillment=failed（[运行环境] ")
    assert "llm down" in carryability.summary["text"]
    assert not [c for c in clients if c.role == "capability_carrier_mapper"]


def test_disabled_axis_is_recorded_not_run(monkeypatch) -> None:
    clients = _install_fake_llm(monkeypatch)
    results = _by_id(run_axes(load_project("llm_probe"), _trace(), _axes(carryability_enabled=False), scenario_id="client_search"))
    assert results["carryability"].status == STATUS_DISABLED
    assert not [c for c in clients if c.role == "capability_carrier_mapper"]


def test_topo_order_puts_upstream_first(monkeypatch) -> None:
    _install_fake_llm(monkeypatch)
    reversed_axes = list(reversed(_axes()))
    assert [a.type_id for a in topo_order(reversed_axes)] == ["expectations", "fulfillment", "carryability"]
    results = run_axes(load_project("llm_probe"), _trace(), reversed_axes, scenario_id="client_search")
    assert [r.axis_id for r in results] == ["expectations", "fulfillment", "carryability"]
    assert results[2].status == STATUS_SUCCEEDED


def test_fingerprints_are_stable_and_config_sensitive(monkeypatch) -> None:
    _install_fake_llm(monkeypatch)
    spec = load_project("llm_probe")
    first = _by_id(run_axes(spec, _trace(), _axes(), scenario_id="client_search"))
    second = _by_id(run_axes(spec, _trace(), _axes(), scenario_id="client_search"))
    assert first["carryability"].config_fingerprint == second["carryability"].config_fingerprint
    assert first["carryability"].implementation_fingerprint == second["carryability"].implementation_fingerprint
    changed = _by_id(run_axes(spec, _trace(), [*_axes()[:2], ScenarioAxis("carryability", True, BOUNDARY + "多一句")], scenario_id="client_search"))
    assert changed["carryability"].config_fingerprint != first["carryability"].config_fingerprint


# ---------------------------------------------------------------- 运行器对 adapter 输出的校验


def test_runner_rejects_output_not_matching_declared_fields(monkeypatch) -> None:
    def bad_run(_inputs, _axis, _runtime) -> RunOutcome:
        return RunOutcome(output={"verdict": "ok", "extra": 1})

    custom = AxisType(
        type_id="custom",
        title="c",
        summary="c",
        verdict_scope="axis",
        verdict_enum=(Verdict("ok", "ok"),),
        depend_on=(),
        trigger_when=None,
        inputs=(Input("trace", source="sample.trace"),),
        output_fields=("verdict",),
        verdict_path="verdict",
        scenario_fields=(Field("description"),),
        limits=ExecutionLimits(),
        run=bad_run,
    )
    monkeypatch.setattr(runner_module, "get_axis_type", lambda type_id: custom if type_id == "custom" else get_axis_type(type_id))
    results = run_axes(load_project("llm_probe"), _trace(), [ScenarioAxis("custom", True, "x")], scenario_id="client_search")
    assert results[0].status == STATUS_FAILED
    assert "output 键集" in results[0].error


def test_runner_rejects_verdict_outside_enum(monkeypatch) -> None:
    custom = AxisType(
        type_id="custom",
        title="c",
        summary="c",
        verdict_scope="axis",
        verdict_enum=(Verdict("ok", "ok"),),
        depend_on=(),
        trigger_when=None,
        inputs=(Input("trace", source="sample.trace"),),
        output_fields=("verdict",),
        verdict_path="verdict",
        scenario_fields=(Field("description"),),
        limits=ExecutionLimits(),
        run=lambda _i, _a, _r: RunOutcome(output={"verdict": "maybe"}),
    )
    monkeypatch.setattr(runner_module, "get_axis_type", lambda type_id: custom if type_id == "custom" else get_axis_type(type_id))
    results = run_axes(load_project("llm_probe"), _trace(), [ScenarioAxis("custom", True, "x")], scenario_id="client_search")
    assert results[0].status == STATUS_FAILED
    assert "不在枚举" in results[0].error


def test_adapter_exception_is_isolated_to_that_axis(monkeypatch) -> None:
    def boom(_inputs, _axis, _runtime) -> RunOutcome:
        raise RuntimeError("adapter exploded")

    custom = AxisType(
        type_id="custom",
        title="c",
        summary="c",
        verdict_scope="axis",
        verdict_enum=(Verdict("ok", "ok"),),
        depend_on=(),
        trigger_when=None,
        inputs=(Input("trace", source="sample.trace"),),
        output_fields=("verdict",),
        verdict_path="verdict",
        scenario_fields=(Field("description"),),
        limits=ExecutionLimits(),
        run=boom,
    )
    _install_fake_llm(monkeypatch, judge_status="fulfilled")
    monkeypatch.setattr(runner_module, "get_axis_type", lambda type_id: custom if type_id == "custom" else get_axis_type(type_id))
    results = _by_id(run_axes(
        load_project("llm_probe"),
        _trace(),
        [ScenarioAxis("custom", True, "x"), *_axes(carryability_enabled=False)],
        scenario_id="client_search",
    ))
    assert results["custom"].status == STATUS_FAILED
    assert "adapter exploded" in results["custom"].error
    assert results["fulfillment"].status == STATUS_SUCCEEDED


def test_runner_hands_adapter_a_deadline_from_limits_seconds(monkeypatch) -> None:
    """seconds 是协作式上限：运行器算好截止时刻交给 run()，adapter 在开下一次调用前查；到点报 failed 且写明超时。"""
    seen: dict[str, Any] = {}

    def slow(_inputs, _axis, runtime) -> RunOutcome:
        seen["deadline"] = runtime.deadline
        monkeypatch.setattr(runner_module.time, "monotonic", lambda: runtime.deadline + 1)
        runtime.ensure_time_left("第二次调用")
        raise AssertionError("到点后不该继续")

    custom = AxisType(
        type_id="custom", title="c", summary="c", verdict_scope="axis", verdict_enum=(Verdict("ok", "ok"),),
        depend_on=(), trigger_when=None, inputs=(Input("trace", source="sample.trace"),), output_fields=("verdict",),
        verdict_path="verdict", scenario_fields=(Field("description"),), limits=ExecutionLimits(seconds=5), run=slow,
    )
    monkeypatch.setattr(runner_module, "get_axis_type", lambda type_id: custom if type_id == "custom" else get_axis_type(type_id))
    result = run_axes(load_project("llm_probe"), _trace(), [ScenarioAxis("custom", True, "x")], scenario_id="s")[0]
    assert seen["deadline"] is not None
    assert result.status == STATUS_FAILED
    assert "超时（上限 5s）" in result.error and "第二次调用" in result.error
    assert result.usage["timed_out"] is True


def test_runner_requires_summary_for_succeeded_axis(monkeypatch) -> None:
    custom = AxisType(
        type_id="custom",
        title="c",
        summary="c",
        verdict_scope="axis",
        verdict_enum=(Verdict("ok", "ok"),),
        depend_on=(),
        trigger_when=None,
        inputs=(Input("trace", source="sample.trace"),),
        output_fields=("verdict",),
        verdict_path="verdict",
        scenario_fields=(Field("description"),),
        limits=ExecutionLimits(),
        run=lambda _i, _a, _r: RunOutcome(output={"verdict": "ok"}),   # 只交枚举，不交解释
    )
    monkeypatch.setattr(runner_module, "get_axis_type", lambda type_id: custom if type_id == "custom" else get_axis_type(type_id))
    results = run_axes(load_project("llm_probe"), _trace(), [ScenarioAxis("custom", True, "x")], scenario_id="client_search")
    assert results[0].status == STATUS_FAILED
    assert "summary" in results[0].error
    assert results[0].summary["text"] == results[0].error


# ---------------------------------------------------------------- 模型策略（axe-v4 D12）：any 按路由回退；same_model 只允许同名模型端点


def _cool_down(router, endpoint_name: str) -> None:
    endpoint = next(ep for ep in router.endpoints if ep.name == endpoint_name)
    for _ in range(router.failure_threshold):
        router.record_failure(endpoint)


def test_router_view_any_falls_back_across_models_and_records_selection() -> None:
    from impl.projects.llm_probe.eval_axes.llm import AxisLlm

    router = _fake_router(("primary", "gpt-x"), ("fallback1", "gpt-x"), ("fallback2", "deepseek-y"))
    client = FakeLlm("judge", lambda *_: {"ok": True}, router=router)
    shell = AxisLlm(client, policy="any")
    _cool_down(router, "primary")
    _cool_down(router, "fallback1")
    assert shell.complete_json("s", "u") == {"ok": True}
    usage = shell.usage()
    assert usage["llm_model"] == "deepseek-y" and usage["llm_endpoint"] == "fallback2"
    assert usage["llm_calls"] == 1 and usage["model_policy"] == "any"
    # 记账不改变共享路由的健康状态：fallback2 成功被记到公共路由上
    assert router.active_endpoint_names() == ["fallback2"]


def test_router_view_same_model_never_switches_model() -> None:
    from impl.projects.llm_probe.eval_axes.llm import AxisLlm

    router = _fake_router(("primary", "gpt-x"), ("fallback1", "gpt-x"), ("fallback2", "deepseek-y"))
    client = FakeLlm("judge", lambda *_: {"ok": True}, router=router)
    client.model = "gpt-x"   # 真客户端的 model 就是角色策略模型 = primary 端点的模型
    shell = AxisLlm(client, policy="same_model")
    # 视图只暴露同名模型的端点；中转站不同没关系
    assert [ep.name for ep in client.llm_router.endpoints] == ["primary", "fallback1"]
    _cool_down(router, "primary")
    assert shell.complete_json("s", "u") == {"ok": True}
    assert shell.usage()["llm_endpoint"] == "fallback1" and shell.usage()["llm_model"] == "gpt-x"
    # 同模型端点全部冷却：即便 deepseek-y 健康也不用，直接失败
    _cool_down(router, "fallback1")
    result = shell.complete_json("s", "u")
    assert result["error"] == "llm_request_failed"
    assert "same_model" in result["raw_text"] and "gpt-x" in result["raw_text"]
    assert shell.usage()["llm_model"] == "gpt-x"   # 没有出现过 deepseek-y


def test_router_view_retry_candidate_respects_model_and_request_constraints() -> None:
    from impl.core.llm_router import LlmEndpoint, LlmRouter
    from impl.projects.llm_probe.eval_axes.llm import AxisLlm

    router = LlmRouter([
        LlmEndpoint("primary", "http://fake", "gpt-x", "x", max_prompt_chars=100),
        LlmEndpoint("fallback2", "http://fake", "deepseek-y", "x"),
    ])
    client = FakeLlm("judge", lambda *_: {"ok": True}, router=router)
    client.model = "gpt-x"
    AxisLlm(client, policy="same_model")
    assert client.llm_router.retry_candidate({"primary", "fallback2"}).name == "primary"
    assert client.llm_router.retry_candidate({"primary"}, prompt_chars=10_000_000) is None
    _cool_down(router, "primary")
    assert client.llm_router.retry_candidate({"primary", "fallback2"}) is None


def test_same_model_attempts_eligible_endpoint_without_health_probe(monkeypatch) -> None:
    from impl.projects.llm_probe.eval_axes.llm import AxisLlm

    router = _fake_router(("primary", "gpt-x"), ("fallback2", "deepseek-y"))
    client = FakeLlm("judge", lambda *_: {"ok": True}, router=router)
    client.model = "gpt-x"
    shell = AxisLlm(client, policy="same_model")
    monkeypatch.setattr(router, "refresh_health_if_stale", lambda: pytest.fail("unexpected probe"))
    client.llm_router.refresh_health_if_stale()
    assert shell.complete_json("s", "u") == {"ok": True}
    assert shell.usage()["llm_endpoint"] == "primary"


def test_same_model_policy_makes_fulfillment_fail_closed(monkeypatch) -> None:
    def router_factory():
        router = _fake_router(("primary", FAKE_MODEL), ("fallback2", "other-model"))
        _cool_down(router, "primary")
        return router

    clients = _install_fake_llm(monkeypatch, judge_status="not_fulfilled", router_factory=router_factory)
    monkeypatch.setattr("impl.projects.llm_probe.eval_axes.llm.model_policy", lambda: "same_model")
    results = _by_id(run_axes(load_project("llm_probe"), _trace(), _axes(), scenario_id="client_search"))
    # 第一个用 judge 角色的是需求轴：它 fail closed；兑现轴不自推顶上，记运行失败；承载性被挡
    expectations = results["expectations"]
    assert expectations.status == STATUS_FAILED
    assert "llm_request_failed" in expectations.error
    assert not expectations.usage.get("llm_model")      # 没有任何一次落到别的模型
    assert results["fulfillment"].status == STATUS_FAILED
    assert "需求轴已启用但没有成功" in results["fulfillment"].error
    assert results["carryability"].status == STATUS_BLOCKED
    # any 策略下同一情形会用 other-model 顶上
    monkeypatch.setattr("impl.projects.llm_probe.eval_axes.llm.model_policy", lambda: "any")
    results = _by_id(run_axes(load_project("llm_probe"), _trace(), _axes(), scenario_id="client_search"))
    assert results["fulfillment"].status == STATUS_SUCCEEDED
    assert results["fulfillment"].usage["llm_model"] == "other-model"
    assert results["fulfillment"].usage["llm_endpoint"] == "fallback2"


def test_model_policy_is_registered_config_with_env_override(tmp_path) -> None:
    from impl.core.config import ConfigError, resolve_runtime_config

    config_path = ROOT_DIR / "impl/config.yaml"
    base_env = (ROOT_DIR / ".env").read_text() if (ROOT_DIR / ".env").exists() else ""
    base_env = "\n".join(line for line in base_env.splitlines() if not line.startswith("EVAL_AXES_MODEL_POLICY="))
    plain = tmp_path / "plain.env"; plain.write_text(base_env)
    assert resolve_runtime_config(config_path=config_path, dotenv_path=plain, environ={}).eval_axes.model_policy == "any"
    strict = tmp_path / "strict.env"; strict.write_text(base_env + "\nEVAL_AXES_MODEL_POLICY=same_model\n")
    resolved = resolve_runtime_config(config_path=config_path, dotenv_path=strict, environ={})
    assert resolved.eval_axes.model_policy == "same_model"
    assert resolved.source_for("eval_axes.model_policy").name == "EVAL_AXES_MODEL_POLICY"
    bad = tmp_path / "bad.env"; bad.write_text(base_env + "\nEVAL_AXES_MODEL_POLICY=whatever\n")
    with pytest.raises(ConfigError, match="eval_axes.model_policy"):
        resolve_runtime_config(config_path=config_path, dotenv_path=bad, environ={})


# ---------------------------------------------------------------- 判后 pass：钩子、core 装载、_run_payload、表格


def _preset_with_axes(*, enabled: bool = True) -> dict:
    return {"client_search": {
        "capability": CAPABILITY,
        "axes": [
            {"type": "fulfillment", "enabled": enabled, "description": CAPABILITY},
            {"type": "carryability", "enabled": enabled, "description": BOUNDARY},
        ],
    }}


def test_run_for_trace_is_noop_without_enabled_boxes(monkeypatch) -> None:
    from impl.projects.llm_probe.eval_axes import run_for_trace

    spec = load_project("llm_probe")
    clients = _install_fake_llm(monkeypatch)
    monkeypatch.setattr("impl.projects.llm_probe.eval_axes.load_capability_map", lambda _p: {"client_search": {"capability": CAPABILITY}})
    assert run_for_trace(spec, _trace()) is None
    monkeypatch.setattr("impl.projects.llm_probe.eval_axes.load_capability_map", lambda _p: _preset_with_axes(enabled=False))
    assert run_for_trace(spec, _trace()) is None
    monkeypatch.setattr("impl.projects.llm_probe.eval_axes.load_capability_map", lambda _p: {})
    assert run_for_trace(spec, _trace()) is None
    assert clients == []   # 一次模型调用都没有


def test_run_for_trace_runs_enabled_boxes(monkeypatch) -> None:
    from impl.projects.llm_probe.eval_axes import run_for_trace

    _install_fake_llm(monkeypatch, judge_status="not_fulfilled", carry="no")
    monkeypatch.setattr("impl.projects.llm_probe.eval_axes.load_capability_map", lambda _p: _preset_with_axes())
    monkeypatch.setattr("impl.projects.llm_probe.eval_axes.validate.load_capability_map", lambda _p: _preset_with_axes())
    report = run_for_trace(load_project("llm_probe"), _trace())
    assert report["scenario_id"] == "client_search"
    # 只开兑现轴：需求轴不被补上，兑现轴自推期望
    assert [r["axis_id"] for r in report["results"]] == ["fulfillment", "carryability"]
    assert report["results"][0]["output"]["expectations_source"] == "self"
    assert report["results"][0]["summary"]["text"] == "输出缺少年龄条件"
    assert report["results"][1]["summary"]["items"][0]["value"] == PLACEMENT_CANNOT
    assert report["main_verdict"]["verdict"] == "做不了"


def test_core_loader_is_declarative_and_isolated(monkeypatch) -> None:
    from impl.core.eval_axes import eval_axes_report

    trace = _trace()
    judge = object()
    # 没有 eval_axes 模块的项目：什么都不发生
    assert eval_axes_report(load_project("client_search"), trace, judge) is None
    # 没有 judge 的 run 不做判后 pass
    assert eval_axes_report(load_project("llm_probe"), trace, None) is None
    # 钩子抛异常 → 只记 error，不外抛
    def boom(_spec, _trace):
        raise RuntimeError("axes exploded")
    monkeypatch.setattr("impl.projects.llm_probe.eval_axes.run_for_trace", boom)
    assert eval_axes_report(load_project("llm_probe"), trace, judge) == {"error": "RuntimeError: axes exploded"}
    # 无效配置（carryability 启用但 fulfillment 未启用）同样只落 error
    monkeypatch.undo()
    monkeypatch.setattr("impl.projects.llm_probe.eval_axes.load_capability_map", lambda _p: {"client_search": {
        "capability": CAPABILITY,
        "axes": [{"type": "carryability", "enabled": True, "description": BOUNDARY}],
    }})
    monkeypatch.setattr("impl.projects.llm_probe.eval_axes.validate.load_capability_map", lambda _p: {"client_search": {
        "capability": CAPABILITY,
        "axes": [{"type": "carryability", "enabled": True, "description": BOUNDARY}],
    }})
    report = eval_axes_report(load_project("llm_probe"), trace, judge)
    assert "依赖 fulfillment" in report["error"]


def test_run_payload_attaches_eval_axes_without_touching_run_status(monkeypatch) -> None:
    from impl.core import pipeline
    from impl.core.schema import JudgeResult

    monkeypatch.setattr(pipeline, "live_carrier_report", lambda *_a, **_k: None)   # 旧轴2不在本测试范围
    fake_report = {"run_id": "axes-x", "scenario_id": "client_search", "results": [{
        "axis_id": "fulfillment", "type_id": "fulfillment", "title": "能力兑现", "status": "succeeded",
        "verdict": "not_fulfilled", "summary": {"text": "not_fulfilled · blocking=[x]", "items": [{"key": "x", "value": "not_fulfilled", "reason": "r"}]},
    }]}
    monkeypatch.setattr(pipeline, "eval_axes_report", lambda *_a, **_k: fake_report)
    judge = JudgeResult(trace_id="probe-trace-1", project_id="llm_probe", overall_fulfillment={"status": "not_fulfilled"})
    run = pipeline._run_payload(_trace(), judge, None, case_id="case-1")
    assert run["eval_axes"] is fake_report
    assert "run_status" not in run and "error" not in run

    monkeypatch.setattr(pipeline, "eval_axes_report", lambda *_a, **_k: {"error": "RuntimeError: axes exploded"})
    run = pipeline._run_payload(_trace(), judge, None, case_id="case-1")
    assert run["eval_axes"] == {"error": "RuntimeError: axes exploded"}
    assert "run_status" not in run and "error" not in run

    monkeypatch.setattr(pipeline, "eval_axes_report", lambda *_a, **_k: None)
    run = pipeline._run_payload(_trace(), judge, None, case_id="case-1")
    assert "eval_axes" not in run   # 没启用框：run 的键集与改动前一致


def test_table_row_carries_eval_axes_summary_through_compact_run() -> None:
    from impl.core.schema import JudgeResult, normalize_trace_table_row, to_dict
    from impl.core.table_view import build_trace_table_row_from_run
    from impl.server.service import compact_run

    judge = JudgeResult(trace_id="probe-trace-1", project_id="llm_probe", overall_fulfillment={"status": "not_fulfilled"})
    run = {
        "trace": _trace(), "judge": judge, "attribute": None, "case_id": "case-1",
        "stage_timings": {"live_ms": 6200, "judge_ms": 40100, "eval_axes_ms": 105000},
        "eval_axes": {"run_id": "axes-x", "scenario_id": "client_search", "results": [
            {"axis_id": "fulfillment", "type_id": "fulfillment", "title": "能力兑现", "status": "succeeded", "verdict": "not_fulfilled",
             "usage": {"llm_calls": 1, "tool_calls": 0, "elapsed_ms": 45000, "llm_model": "m"},
             "summary": {"text": "not_fulfilled · blocking=[x]", "items": [{"key": "x", "value": "not_fulfilled", "reason": "r", "blocking": True}]}},
            {"axis_id": "carryability", "type_id": "carryability", "title": "承载性", "status": "not_applicable", "verdict": None,
             "summary": {"text": "fulfillment=fulfilled，不在筛选范围 [not_fulfilled]，不判", "items": []}},
            {"axis_id": "truthfulness", "type_id": "truthfulness", "title": "真实性", "status": "succeeded", "verdict": None,
             "usage": {"llm_calls": 3, "tool_calls": 11, "elapsed_ms": 60400},
             "summary": {"text": "$refuted…", "items": [{"key": "c1", "value": "refuted", "reason": "r1"}, {"key": "c2", "value": "verified", "reason": "r2"}, {"key": "c3", "value": "refuted", "reason": "r3"}]}},
        ]},
    }
    compact = compact_run(run)
    assert compact["eval_axes"] is run["eval_axes"]
    rows = compact["table_row"]["eval_axes_summary"]
    assert [(r["axis_id"], r["status"], r["verdict"]) for r in rows] == [("fulfillment", "succeeded", "not_fulfilled"), ("carryability", "not_applicable", None), ("truthfulness", "succeeded", None)]
    assert rows[0]["title"] == "能力兑现"
    assert rows[0]["text"] == "not_fulfilled · blocking=[x]"
    assert rows[0]["items"][0]["value"] == "not_fulfilled"
    # 结论令牌 `轴id:值`：轴级一个；item 级按值计数；没跑成用状态；Excel 里「包含 truthfulness:refuted」就能筛。
    assert rows[0]["tokens"] == ["fulfillment:not_fulfilled"]
    assert rows[1]["tokens"] == ["carryability:not_applicable"]
    assert rows[2]["tokens"] == ["truthfulness:refuted×2", "truthfulness:verified×1"]
    # 耗时与调用数一起搬到表格层，主表/导出不用再翻 usage。
    assert (rows[0]["elapsed_ms"], rows[0]["llm_calls"], rows[0]["tool_calls"], rows[0]["llm_model"]) == (45000, 1, 0, "m")
    assert (rows[2]["elapsed_ms"], rows[2]["tool_calls"]) == (60400, 11)
    assert compact["table_row"]["stage_timings"] == {"live_ms": 6200, "judge_ms": 40100, "eval_axes_ms": 105000}
    # 整体失败折成一条伪轴
    failed = build_trace_table_row_from_run({"trace": _trace(), "judge": judge, "eval_axes": {"error": "RuntimeError: boom"}})
    assert failed.eval_axes_summary == [{"axis_id": "", "title": "扩展评估轴", "display": "", "status": "failed", "verdict": None, "text": "RuntimeError: boom", "items": []}]
    # 没有 eval_axes 的 run：字段为空列表，其他字段不受影响
    plain = build_trace_table_row_from_run({"trace": _trace(), "judge": judge})
    assert plain.eval_axes_summary == [] and plain.stage_timings == {}
    from impl.core.table_view import eval_axis_tokens
    assert eval_axis_tokens("truthfulness", "disabled", None, []) == []
    assert eval_axis_tokens("truthfulness", "succeeded", None, []) == ["truthfulness:empty"]
    assert eval_axis_tokens("truthfulness", "failed", None, [{"value": "verified"}]) == ["truthfulness:failed"]
    # 反序列化保留
    restored = normalize_trace_table_row(to_dict(compact["table_row"]))
    assert restored.eval_axes_summary == rows


# ---------------------------------------------------------------- 类型层约束


def test_axis_type_requires_references_inside_depend_on() -> None:
    with pytest.raises(ValueError, match="depend_on"):
        AxisType(
            type_id="bad",
            title="b",
            summary="b",
            verdict_scope="axis",
            verdict_enum=(Verdict("ok", "ok"),),
            depend_on=(),
            trigger_when=When(axis="fulfillment", verdict_in=("not_fulfilled",)),
            inputs=(),
            output_fields=("verdict",),
            verdict_path="verdict",
            scenario_fields=(),
            limits=ExecutionLimits(),
            run=lambda *_: RunOutcome(output={}),
        )


def test_axis_input_from_upstream_must_project_named_fields() -> None:
    with pytest.raises(ValueError, match="fields"):
        Input("fulfillment", source="axis.fulfillment.output")
    with pytest.raises(ValueError, match="source"):
        Input("answer", source="sample.answer")


# ---------------------------------------------------------------- 加载期校验


def test_validate_rejects_enabled_downstream_without_enabled_upstream() -> None:
    report = validate_scenario_axes([ScenarioAxis("carryability", True, BOUNDARY)])
    assert any("依赖 fulfillment" in item for item in report.errors)
    report = validate_scenario_axes(_axes(fulfillment_enabled=False))
    assert any("未启用" in item for item in report.errors)
    assert validate_scenario_axes(_axes()).ok


def test_validate_rejects_unknown_type_and_bad_material_ref() -> None:
    report = validate_scenario_axes([ScenarioAxis("fluency", True, "流畅度")])
    assert any("未注册" in item for item in report.errors)
    report = validate_scenario_axes([ScenarioAxis("truthfulness", True, "见 {material://llm_probe/no-such-material}")])
    assert any("资料引用无效" in item for item in report.errors)


def test_parse_axes_shape_rules() -> None:
    assert parse_axes(None) == []
    axes = parse_axes([{"type": "fulfillment", "enabled": True, "description": CAPABILITY}])
    assert axes == [ScenarioAxis("fulfillment", True, CAPABILITY)]
    with pytest.raises(ValueError, match="只允许一个"):
        parse_axes([
            {"type": "fulfillment", "description": "a"},
            {"type": "fulfillment", "description": "b"},
        ])
    # 形状层只要求字符串；是否必填由轴类型声明决定（validate_scenario_axes）。
    with pytest.raises(ValueError, match="description"):
        parse_axes([{"type": "fulfillment", "description": 3}])
    blank = parse_axes([{"type": "carryability", "description": "   "}, {"type": "context_memory", "description": "旧口径"},
                        {"type": "fulfillment", "description": "   "}])
    errors = validate_scenario_axes(blank).errors
    assert any("carryability.description 不能为空" in e for e in errors)
    assert any("context_memory 不读取场景 description" in e for e in errors)
    # 兑现轴的场景描述选填：只在自推期望时读（spec/alg/fulfilled.md §1.1）
    assert not any("fulfillment" in e for e in errors)
    assert validate_scenario_axes(parse_axes([{"type": "context_memory"}])).errors == []
    with pytest.raises(ValueError, match="enabled"):
        parse_axes([{"type": "fulfillment", "enabled": "yes", "description": "a"}])


# ---------------------------------------------------------------- 试验入口（API）


def _post(path: str, payload: dict):
    import asyncio

    import httpx

    from impl.server.app import create_app

    async def request():
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(path, json=payload)

    return asyncio.run(request())


def test_types_endpoint_lists_registered_types() -> None:
    response = _post("/api/eval_axes/types", {"project": "llm_probe"})
    assert response.status_code == 200
    body = response.json()
    assert [item["type_id"] for item in body["types"]] == [
        "fulfillment", "carryability", "knowledge_evidence", "truthfulness", "trace_analysis", "expectations", "intent_understanding",
        "planning_routing", "tool_execution", "context_memory", "knowledge_data",
        "model_capability",
    ]
    other = _post("/api/eval_axes/types", {"project": "client_search"})
    assert other.status_code == 500
    assert "llm_probe" in other.json()["error"]


def test_run_endpoint_reads_axes_from_capability_preset(monkeypatch) -> None:
    _install_fake_llm(monkeypatch, judge_status="not_fulfilled", carry="no")
    monkeypatch.setattr(
        "impl.projects.llm_probe.eval_axes.validate.load_capability_map",
        lambda _project: {"client_search": {
            "capability": CAPABILITY,
            "axes": [
                {"type": "fulfillment", "enabled": True, "description": CAPABILITY},
                {"type": "carryability", "enabled": True, "description": BOUNDARY},
            ],
        }},
    )
    from impl.core.schema import to_dict

    response = _post("/api/eval_axes/run", {"project": "llm_probe", "trace": to_dict(_trace()), "run_id": "axes-api"})
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["run_id"] == "axes-api"
    assert body["scenario_id"] == "client_search"
    assert [item["type"] for item in body["axes"]] == ["fulfillment", "carryability"]
    statuses = {item["axis_id"]: item["status"] for item in body["results"]}
    assert statuses == {"fulfillment": STATUS_SUCCEEDED, "carryability": STATUS_SUCCEEDED}
    by_type = {item["axis_id"]: item for item in body["results"]}
    assert by_type["fulfillment"]["verdict"] == "not_fulfilled"
    assert by_type["carryability"]["output"]["placements"][0]["placement"] == PLACEMENT_CANNOT
    assert body["main_verdict"]["verdict"] == "做不了"


def test_run_endpoint_rejects_missing_trace_and_unknown_preset(monkeypatch) -> None:
    assert "trace" in _post("/api/eval_axes/run", {"project": "llm_probe"}).json()["error"]
    monkeypatch.setattr("impl.projects.llm_probe.eval_axes.validate.load_capability_map", lambda _project: {})
    from impl.core.schema import to_dict

    response = _post("/api/eval_axes/run", {"project": "llm_probe", "trace": to_dict(_trace())})
    assert response.status_code == 500
    assert "client_search" in response.json()["error"]


def test_capability_entry_keeps_axes_and_rejects_bad_shape() -> None:
    clean = validate_entry("policy_search", {
        "capability": CAPABILITY,
        "axes": [
            {"type": "fulfillment", "enabled": True, "description": CAPABILITY},
            {"type": "carryability", "enabled": False, "description": BOUNDARY},
        ],
    })
    assert clean["axes"] == [
        {"type": "fulfillment", "enabled": True, "description": CAPABILITY},
        {"type": "carryability", "enabled": False, "description": BOUNDARY},
    ]
    assert "axes" not in validate_entry("policy_search", {"capability": CAPABILITY})
    with pytest.raises(ValueError, match="axes"):
        validate_entry("policy_search", {"capability": CAPABILITY, "axes": {"type": "fulfillment"}})
    with pytest.raises(ValueError, match="description"):
        validate_entry("policy_search", {"capability": CAPABILITY, "axes": [{"type": "fulfillment", "description": 3}]})


@pytest.mark.parametrize('upstream_state', ['missing', 'disabled', 'succeeded', 'failed'])
def test_optional_dependency_orders_projects_and_omits_failed_output(monkeypatch, upstream_state):
    from dataclasses import replace
    from impl.projects.llm_probe.eval_axes.types import Dependency, AxisSummary
    seen = []
    def upstream_run(inputs, axis, runtime):
        seen.append('upstream')
        return RunOutcome({'value': 'fulfilled'}, AxisSummary('上游'), failed=upstream_state == 'failed')
    def downstream_run(inputs, axis, runtime):
        seen.append(inputs)
        return RunOutcome({'value': 'fulfilled'}, AxisSummary('下游'))
    template = get_axis_type('fulfillment')
    upstream = replace(template, type_id='upstream', depend_on=(), inputs=(), output_fields=('value',), verdict_path='value', run=upstream_run)
    downstream = replace(upstream, type_id='downstream', depend_on=(Dependency('upstream', optional=True),), inputs=(Input('evidence', 'axis.upstream.output', fields=('value',), required=False),), run=downstream_run)
    registry = {'upstream': upstream, 'downstream': downstream}
    monkeypatch.setattr(runner_module, 'get_axis_type', registry.__getitem__)
    monkeypatch.setattr('impl.projects.llm_probe.eval_axes.validate.AXIS_TYPES', registry)
    axes = [ScenarioAxis('downstream', True, '')]
    if upstream_state != 'missing':
        axes.append(ScenarioAxis('upstream', upstream_state != 'disabled', ''))
    assert validate_scenario_axes(axes).ok
    results = _by_id(run_axes(None, _trace(), axes, scenario_id='test'))
    result = results['downstream']
    assert result.status == 'succeeded'
    assert seen[-1] == ({'evidence': {'value': 'fulfilled'}} if upstream_state == 'succeeded' else {})
    if upstream_state in ('failed', 'succeeded'):
        assert seen[0] == 'upstream'
    assert result.trigger_decision['upstream']['upstream'] == upstream_state
    assert ('（upstream未完成，未纳入）' in result.summary['text']) == (upstream_state == 'failed')


def test_optional_dependency_rejects_required_input_and_trigger():
    from dataclasses import replace
    from impl.projects.llm_probe.eval_axes.types import Dependency
    template = get_axis_type('carryability')
    with pytest.raises(ValueError, match='required=False'):
        replace(template, depend_on=(Dependency('fulfillment', True),), trigger_when=None)
    with pytest.raises(ValueError, match='trigger_when.*可选'):
        replace(template, depend_on=(Dependency('fulfillment', True),), inputs=())


@pytest.fixture
def fake_es(monkeypatch, tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    requests = []
    documents = {'doc1': {'clause': '犹豫期二十日', 'nested': {'title': '保障条款'}, 'tags': ['保障', '保险']}}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            self.respond()
        def do_POST(self):
            self.respond()
        def respond(self):
            from urllib.parse import unquote
            body = json.loads(self.rfile.read(int(self.headers['Content-Length']))) if self.headers.get('Content-Length') else None
            requests.append((self.command, self.path, body, self.headers.get('Authorization')))
            status = 200
            if self.path == '/kb_policy/_mapping':
                result = {'kb_policy': {'mappings': {'properties': {'clause': {'type': 'text', 'fields': {'raw': {'type': 'keyword'}}}, 'nested': {'properties': {'title': {'type': 'text'}}}, 'tags': {'type': 'keyword'}}}}}
            elif self.path == '/kb_policy/_count':
                result = {'count': len(documents)}
            elif self.path == '/kb_policy/_settings/index.uuid':
                result = {'kb_policy': {'settings': {'index': {'uuid': 'uuid-test'}}}}
            elif self.path == '/kb_policy/_search':
                asked = json.dumps(body, ensure_ascii=False)
                hits = [] if '不存在' in asked else [{'_id': 'doc1', '_score': 2.0, '_source': documents.get('doc1', {}), 'highlight': {'clause': ['犹豫期二十日']}}]
                result = {'hits': {'hits': hits}}
            elif self.path.startswith('/kb_policy/_doc/') and unquote(self.path.split('/_doc/')[1]) in documents:
                result = {'found': True, '_source': documents[unquote(self.path.split('/_doc/')[1])]}
            else:
                status, result = 404, {'error': 'missing'}
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode())
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    from impl.projects.llm_probe.eval_axes.sources import registry
    path = tmp_path / 'knowledge_sources.json'
    path.write_text(json.dumps({'test': {'type': 'es', 'url': f'http://127.0.0.1:{server.server_port}', 'api_key': '${TEST_ES_API_KEY}'}}))
    monkeypatch.setattr(registry, 'registry_path', lambda: path)
    monkeypatch.setenv('TEST_ES_API_KEY', 'test-key')
    try:
        yield requests, documents
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_es_tools_catalog_receipts_scope_and_quote_readback(fake_es):
    from impl.projects.llm_probe.eval_axes.sources import expand_sources, build_tools
    from impl.projects.llm_probe.eval_axes.sources.es_tools import EsTools
    requests, documents = fake_es
    text, catalog = expand_sources('核对 {es://test/kb_policy} 条款。')
    assert '{es://' not in text
    assert catalog[0]['snapshot_id'].startswith('uuid-test@')
    assert catalog[0]['doc_count'] == 1
    receipts = []
    tools = {t.name: t.entrypoint for t in build_tools(catalog, receipts)}
    outline = tools['es_outline'](index='test/kb_policy')
    assert [f['name'] for f in outline['fields'] if f['full_text']] == ['clause', 'nested.title']
    search = tools['es_search'](index='test/kb_policy', query='犹豫期 康宁')
    assert search['hits'][0]['locator'] == 'doc1#clause'
    assert search['hits'][0]['matched'] == ['犹豫期']
    sent = next(r for r in requests if r[0] == 'POST')
    # 与 material search 同语义：每词 phrase（子串）OR keyword 通配，词间 OR；不能把整串交给 ES 按单字 OR。
    should = sent[2]['query']['bool']['should']
    assert sent[2]['query']['bool']['minimum_should_match'] == 1
    assert [c['multi_match'] for c in should if 'multi_match' in c] == [
        {'query': '犹豫期', 'fields': ['clause', 'nested.title'], 'type': 'phrase'},
        {'query': '康宁', 'fields': ['clause', 'nested.title'], 'type': 'phrase'},
    ]
    assert [c['wildcard'] for c in should if 'wildcard' in c] == [
        {'tags': {'value': '*犹豫期*', 'case_insensitive': True}},
        {'tags': {'value': '*康宁*', 'case_insensitive': True}},
    ]
    assert sent[3] == 'ApiKey test-key'
    empty = tools['es_search'](index='test/kb_policy', query='不存在的词')
    assert empty['hits'] == [] and '零命中' in empty['note']
    assert tools['es_read'](index='test/kb_policy', locator='doc1#nested.title')['text'] == '保障条款'
    assert 'clause' in tools['es_read'](index='test/kb_policy', locator='doc1')['text']
    before = len(requests)
    assert 'error' in tools['es_read'](index='../secret', locator='x')
    assert len(requests) == before
    assert receipts[-1]['returned_locators'] == [] and receipts[-1]['error']
    verifier = EsTools(catalog, receipts)
    assert verifier.verify_quote('test/kb_policy', 'doc1#clause', '犹豫期二十日')
    assert not verifier.verify_quote('test/kb_policy', 'doc1#clause', '十五日')
    assert not verifier.verify_quote('test/kb_policy', 'doc1#absent', '二十日')
    documents.clear()
    assert not verifier.verify_quote('test/kb_policy', 'doc1#clause', '二十日')
    assert all('tool' in r and 'returned_locators' in r for r in receipts)


def test_es_save_only_validates_format_and_load_rejects_unregistered_source(monkeypatch, tmp_path):
    from impl.projects.llm_probe.eval_axes.sources import registry
    monkeypatch.setattr(registry, 'registry_path', lambda: tmp_path / 'knowledge_sources.json')
    for marker in ('{es://}', '{es://kb_policy}', '{es://UPPER/kb}', '{es://src/UPPER}', '{es://src/x*}', '{es://src/x'):
        with pytest.raises(ValueError, match='ES 引用'):
            validate_entry('test', {'capability': 'test', 'axes': [{'type': 'carryability', 'enabled': True, 'description': marker}]})
    entry = validate_entry('test', {'capability': 'test', 'axes': [{'type': 'knowledge_evidence', 'enabled': True, 'description': '{es://test/kb_policy}'}]})
    report = validate_scenario_axes(parse_axes(entry['axes']))
    assert any('知识源 test 未登记' in e for e in report.errors)
    # 未启用的框引用了未登记的知识源：不拦同预设里已启用的其他轴。
    entry = validate_entry('test', {'capability': 'test', 'axes': [
        {'type': 'knowledge_evidence', 'enabled': False, 'description': '{es://test/kb_policy}'},
        {'type': 'expectations', 'enabled': True},
    ]})
    assert validate_scenario_axes(parse_axes(entry['axes'])).ok


def test_es_sources_are_registered_per_business_system_with_env_secrets(monkeypatch, tmp_path):
    from impl.projects.llm_probe.eval_axes.sources import registry
    path = tmp_path / 'knowledge_sources.json'
    monkeypatch.setattr(registry, 'registry_path', lambda: path)
    path.write_text(json.dumps({
        'biz-a': {'type': 'es', 'url': 'http://a:9200', 'api_key': '${BIZ_A_ES_KEY}', 'max_hits': 3},
        'biz-b': {'type': 'es', 'url': 'https://b:9200', 'basic_auth': 'u:p'},
        'bad-url': {'type': 'es', 'url': 'http://user@b:9200'},
        'bad-type': {'type': 'mysql', 'url': 'http://c'},
        'bad-key': {'type': 'es', 'url': 'http://c', 'index': 'x'},
    }))
    monkeypatch.setenv('BIZ_A_ES_KEY', 'secret-a')
    a, b = registry.load_es_source('biz-a'), registry.load_es_source('biz-b')
    assert (a.base_url, a.api_key, a.max_hits, a.max_field_chars) == ('http://a:9200', 'secret-a', 3, 6000)
    assert (b.base_url, b.basic_auth, b.api_key) == ('https://b:9200', 'u:p', '')
    monkeypatch.delenv('BIZ_A_ES_KEY')
    with pytest.raises(ValueError, match='BIZ_A_ES_KEY 未设置'):
        registry.load_es_source('biz-a')
    for name, message in (('bad-url', '无凭据'), ('bad-type', 'type=es'), ('bad-key', '未知字段'), ('missing', '未登记')):
        with pytest.raises(ValueError, match=message):
            registry.load_es_source(name)


def test_es_read_truncation_and_explicit_fields(fake_es):
    from impl.projects.llm_probe.eval_axes.sources.es_tools import EsTools
    requests, documents = fake_es
    documents['doc1']['long'] = '甲' * 6001
    tools = EsTools([{'source': 'es', 'uri': 'es://test/kb_policy'}], [])
    result = tools.es_read('test/kb_policy', 'doc1#long')
    assert result['truncated'] and len(result['text']) == 6000
    assert 'error' in tools.es_search('test/kb_policy', 'x', ['not_in_mapping'])
    assert 'error' in tools.es_search('test/kb_policy', 'x', [])
    keyword_only = tools.es_search('test/kb_policy', 'x', ['clause.raw'])
    # 显式 keyword 字段同样是子串语义：走通配，不走 phrase（phrase 只能整值命中）；命中仍带可回读的全文字段 locator。
    assert keyword_only['hits'][0]['locator'] == 'doc1#clause'
    sent = requests[-1][2]
    assert sent['query']['bool']['should'] == [{'wildcard': {'clause.raw': {'value': '*x*', 'case_insensitive': True}}}]
    assert 'highlight' not in sent
    tools.es_search('test/kb_policy', 'x', ['clause', 'tags'])
    # 显式混合字段：text 走 phrase，keyword 走通配，不附带其他字段。
    assert requests[-1][2]['query']['bool']['should'] == [
        {'multi_match': {'query': 'x', 'fields': ['clause'], 'type': 'phrase'}},
        {'wildcard': {'tags': {'value': '*x*', 'case_insensitive': True}}},
    ]


def test_source_dispatch_preserves_material_entries(monkeypatch):
    from impl.projects.llm_probe.eval_axes.sources import build_tools
    material = {'uri': 'material://p/m', 'project_id': 'p', 'id': 'm'}
    received = []
    monkeypatch.setattr('impl.projects.llm_probe.eval_axes.sources.build_material_tools', lambda catalog, recorder: received.extend(catalog) or ['material'])
    assert build_tools([material], []) == ['material']
    assert received[0] is material


def test_carryability_es_quotes_are_read_back(fake_es, monkeypatch):
    from impl.projects.llm_probe.eval_axes.adapters.carryability import BoxBoundaryCarrier
    from impl.projects.llm_probe.eval_axes.types import AxisRuntime
    runtime = AxisRuntime(spec=load_project('llm_probe'), run_id='axes-test', trace_id='axes-test', scenario_id='s', case_id='c')
    carrier = BoxBoundaryCarrier(load_project('llm_probe'), '范围 {es://test/kb_policy}', runtime)
    monkeypatch.setattr(carrier, '_call_llm', lambda *args: {'carry': 'yes', 'reason': '条款覆盖', 'citations': [{'source': 'es://test/kb_policy', 'ref': 'doc1#clause', 'note': '犹豫期二十日'}]})
    verdict = carrier.verdict_for({'expectation_id': '查犹豫期'})
    assert verdict.carry == 'yes'
    assert verdict.tool_trail[-1]['tool'] == 'es_read'


class FakeStepLlm(FakeLlm):
    """知识查证 loop 用 complete_step：按 steps 逐条回放模型回复，[(工具名, 参数)]，空列表 = 不再调工具。"""

    def __init__(self, role, script, steps):
        super().__init__(role, script)
        self.steps, self.step_messages = steps, []

    def complete_step(self, messages, functions, *, trace_id, stage):
        from impl.core.tool_loop import Step
        from impl.tools.protocol import runtime_tool_name
        self.step_messages.append(list(messages))
        self.step_functions = [fn.name for fn in functions]
        calls = self.steps.pop(0) if self.steps else []
        return Step({'role': 'assistant', 'content': '' if calls else '完成', 'tool_calls': [
            {'id': f's{len(self.step_messages)}-{i}', 'type': 'function',
             'function': {'name': runtime_tool_name(name), 'arguments': json.dumps(args, ensure_ascii=False)}}
            for i, (name, args) in enumerate(calls)]})


def _knowledge_llm(monkeypatch, extracted, steps=(), judges=(), other=None):
    """truthfulness 角色：含 output_text 的是抽取，其余 complete_json 是逐条判定；complete_step 是查证 loop。"""
    clients, steps, judges = [], [list(step) for step in steps], iter(judges)

    def script(role, system, user):
        if role != 'truthfulness':
            return other(role, system, user)
        if user.startswith('{"output_text"'):
            return extracted(user) if callable(extracted) else extracted
        return next(judges)

    def factory(spec, role, **kwargs):
        client = FakeStepLlm(role, script, steps)
        clients.append(client)
        return client
    monkeypatch.setattr('impl.core.llm_client.project_llm_client', factory)
    return clients


def _search(query):
    return ('es_search', {'index': 'test/kb_policy', 'query': query})


def _submit(item_id, status, citations=(), searches=('c0',), note='检索了 犹豫期', gap=None):
    gap = ('item_absent' if status == 'not_found' else '') if gap is None else gap
    return ('submit_item', {'item_id': item_id, 'status': status, 'citations': list(citations),
                            'search_calls': list(searches), 'note': note, 'gap': gap})


def _truth_verdict(verdict='refuted', note='犹豫期二十日'):
    return {'verdict': verdict, 'reason': '资料中是二十日', 'citations': [{'source': 'es://test/kb_policy', 'ref': 'c0', 'note': note}]}


def _knowledge_axes(description='核对事实 {es://test/kb_policy}', truth=''):
    return [ScenarioAxis('knowledge_evidence', True, description), ScenarioAxis('truthfulness', True, truth)]


def test_knowledge_evidence_gathers_then_truthfulness_judges(fake_es, monkeypatch):
    # 说法 = 主张 + 片段 + context：上下文片段单独带着，查证时才知道该找哪个产品、哪个条件下的条款；不需要的填 []。
    extracted = {'claims': [{'claim_id': '天数', 'claim': '犹豫期十五日', 'span': '犹豫期十五日', 'context': ['康宁险']}, {'claim_id': '条款', 'claim': '保障条款', 'span': '保障条款'}]}
    clients = _knowledge_llm(monkeypatch, extracted, steps=[
        [_search('犹豫期')],
        [_submit('truthfulness:天数', 'found', [{'call_id': 'c0', 'quote': '犹豫期二十日'}]),
         _submit('truthfulness:条款', 'not_found', note='检索 犹豫期 只命中犹豫期条款，没有保障条款原文')],
    ], judges=[{'reason': '原文是二十日，说法是十五日', 'verdict': 'refuted', 'basis': [0]}])
    results = _by_id(run_axes(load_project('llm_probe'), _trace('康宁险犹豫期十五日；保障条款'), _knowledge_axes(), scenario_id='s'))
    evidence, truth = results['knowledge_evidence'], results['truthfulness']
    assert evidence.status == 'succeeded' and evidence.verdict is None
    assert evidence.output['coverage'] == {'items': 2, 'found': 1, 'not_found': 1, 'by_origin': {'truthfulness': 2}}
    assert evidence.output['searches'][0]['source'] == 'es://test/kb_policy'
    assert evidence.output['sources'][0]['snapshot_id'].startswith('uuid-test@')
    assert truth.status == 'succeeded'
    assert truth.output['coverage'] == {'extracted': 2, 'verified': 0, 'refuted': 1, 'unverifiable': 1}
    assert truth.output['claims'][0]['citations'] == [{'source': 'es://test/kb_policy', 'ref': 'c0', 'note': '犹豫期二十日'}]
    assert truth.summary['text'].startswith('$refuted\n天数')
    assert [item['key'] for item in truth.summary['items']] == ['康宁险：犹豫期十五日', '保障条款']
    # 没找到的直接给 unverifiable，不调模型：真实性只调一次（判"天数"）。
    assert truth.usage['llm_calls'] == 1
    extraction = json.loads(clients[0].calls[0]['user'])
    assert set(extraction) == {'output_text', 'question'}
    loop_input = clients[1].step_messages[0][1]['content']
    # 查证只拿清单、目录和骨架，不拿整份回答。
    assert '待查清单' in loop_input and 'truthfulness:天数' in loop_input and 'ES 字段骨架' in loop_input
    assert '康宁险犹豫期十五日；保障条款' not in loop_input
    judged = json.loads(clients[2].calls[0]['user'])
    assert judged['claim'] == {'text': '犹豫期十五日', 'context': ['康宁险'], 'span': '犹豫期十五日'}
    assert judged['citations'][0]['quote'] == '犹豫期二十日' and judged['citations'][0]['window']
    assert all(call.get('reasoning_effort') == 'low' for client in clients for call in client.calls)


def test_extraction_repairs_schema_block_once(fake_es, monkeypatch):
    """提取被结构校验阻断（如模型把 schema 里的 required 当字段输出）时，与生产 judge 一样只做一次带具体错误的格式修复。"""
    attempts = []

    def extracted(user):
        attempts.append(user)
        if len(attempts) == 1:
            raise ValueError('额外字段不允许：required')
        assert '上次输出不符合要求' in user and 'required' in user
        return {'claims': []}

    _knowledge_llm(monkeypatch, extracted)
    results = _by_id(run_axes(None, _trace('答复'), _knowledge_axes(), scenario_id='s'))
    assert results['knowledge_evidence'].status == 'succeeded' and len(attempts) == 2
    assert results['knowledge_evidence'].usage['llm_calls'] == 2
    assert results['truthfulness'].summary['text'] == '回答不含可核验的事实断言'


@pytest.mark.parametrize('claims', [[{'claim_id': 'fake', 'claim': '原文中不存在', 'span': '原文中不存在'}], [{'claim_id': 'x', 'claim': '答案', 'span': '答案'}],
                                    [{'claim_id': 'x', 'claim': '答复', 'span': '答复', 'context': ['原文中不存在']}]])
def test_fabricated_claims_fail_evidence_and_block_truthfulness(fake_es, monkeypatch, claims):
    clients = _knowledge_llm(monkeypatch, {'claims': claims})
    results = _by_id(run_axes(None, _trace('答复'), _knowledge_axes(), scenario_id='s'))
    assert results['knowledge_evidence'].status == 'failed' and '待查清单生成失败' in results['knowledge_evidence'].error
    assert results['knowledge_evidence'].usage['llm_calls'] == 2 and len(clients) == 1
    assert results['truthfulness'].status == 'blocked'


def test_context_must_not_leak_other_claims(fake_es, monkeypatch):
    """context 带了别条说法的片段 = 把整句塞回来，隔离失效，程序打回；给一次带具体错误的修复机会，仍偷懒则 failed。"""
    answer = '安心医疗险的等待期为三十日，免赔额为一万元。'
    attempts = []

    def lazy(user):
        attempts.append(user)
        return {'claims': [{'claim_id': '1', 'claim': '等待期为三十日', 'span': '等待期为三十日', 'context': [answer]},
                           {'claim_id': '2', 'claim': '免赔额为一万元', 'span': '免赔额为一万元', 'context': ['安心医疗险']}]}

    _knowledge_llm(monkeypatch, lazy)
    result = _by_id(run_axes(None, _trace(answer), _knowledge_axes(), scenario_id='s'))['knowledge_evidence']
    assert result.status == 'failed' and '含了说法 2 的片段' in result.error
    assert len(attempts) == 2 and '含了说法 2 的片段' in attempts[1]


def test_unfinished_checklist_fails_instead_of_becoming_not_found(fake_es, monkeypatch):
    """模型查了却交不齐：预算耗尽记执行失败，不产出部分案卷，没交的条目不会变成"没找到"。"""
    _knowledge_llm(monkeypatch, {'claims': [{'claim_id': 'x', 'claim': '十五日', 'span': '十五日'}]}, steps=[[_search('犹豫期')]] * 30)
    results = _by_id(run_axes(None, _trace('十五日'), _knowledge_axes(), scenario_id='s'))
    assert results['knowledge_evidence'].status == 'failed'
    assert '查证未完成（已接受 0/1 条）' in results['knowledge_evidence'].error and 'budget' in results['knowledge_evidence'].error
    assert results['truthfulness'].status == 'blocked'


@pytest.mark.parametrize('invalid', [{'reason': '支持', 'verdict': 'verified', 'basis': []},
                                     {'reason': '支持', 'verdict': 'verified', 'basis': [3]},
                                     {'error': 'llm down'}])
def test_judgement_repairs_once_then_records_error(fake_es, monkeypatch, invalid):
    steps = [[_search('犹豫期')], [_submit('truthfulness:days', 'found', [{'call_id': 'c0', 'quote': '犹豫期二十日'}])]]
    good = {'reason': '原文二十日', 'verdict': 'refuted', 'basis': [0]}
    _knowledge_llm(monkeypatch, {'claims': [{'claim_id': 'days', 'claim': '十五日', 'span': '十五日'}]}, steps=steps, judges=[invalid, good])
    truth = _by_id(run_axes(None, _trace('十五日'), _knowledge_axes(), scenario_id='s'))['truthfulness']
    assert truth.status == 'succeeded' and truth.output['coverage']['refuted'] == 1 and truth.usage['llm_calls'] == 2
    _knowledge_llm(monkeypatch, {'claims': [{'claim_id': 'days', 'claim': '十五日', 'span': '十五日'}]}, steps=[list(s) for s in steps], judges=[invalid, invalid])
    truth = _by_id(run_axes(None, _trace('十五日'), _knowledge_axes(), scenario_id='s'))['truthfulness']
    assert truth.status == 'failed' and truth.output['errors'][0]['claim_id'] == 'truthfulness:days'


def test_without_knowledge_source_both_axes_not_applicable(monkeypatch):
    clients = _knowledge_llm(monkeypatch, {'claims': []})
    results = _by_id(run_axes(None, _trace('答复'), _knowledge_axes(description='核对事实'), scenario_id='s'))
    assert results['knowledge_evidence'].status == 'not_applicable' and '场景未声明知识源' in results['knowledge_evidence'].summary['text']
    assert results['truthfulness'].status == 'not_applicable' and '上游不适用' in results['truthfulness'].summary['text']
    assert clients == []


def test_truthfulness_box_rejects_knowledge_source_refs():
    report = validate_scenario_axes([ScenarioAxis('knowledge_evidence', True, '核对 {es://test/kb_policy}'),
                                     ScenarioAxis('truthfulness', True, '核对 {es://test/kb_policy}')])
    assert any('truthfulness' in e and '知识查证框' in e for e in report.errors)
    report = validate_scenario_axes([ScenarioAxis('truthfulness', True, '')])
    assert any('依赖 knowledge_evidence' in e for e in report.errors)


def test_small_material_goes_to_catalog_with_tools_and_snapshot(monkeypatch):
    import impl.core.materials_store as ms
    from impl.projects.llm_probe.eval_axes.sources import expand_sources
    token = '{material://llm_probe/client-search-match-rule}'
    content = ms.read_content('llm_probe', 'client-search-match-rule')
    quote = next(line for line in content.splitlines() if line.strip())
    clients = _knowledge_llm(monkeypatch, {'claims': [{'claim_id': '规则', 'claim': quote, 'span': quote}]}, steps=[
        [('material_read', {'material_id': 'client-search-match-rule', 'locator': 'L1-L10'})],
        [_submit('truthfulness:规则', 'found', [{'call_id': 'c0', 'quote': quote}])],
    ], judges=[{'reason': '原文支持', 'verdict': 'verified', 'basis': [0]}])
    results = _by_id(run_axes(None, _trace(quote), _knowledge_axes(description=token), scenario_id='s'))
    assert results['truthfulness'].status == 'succeeded'
    assert results['truthfulness'].output['claims'][0]['citations'][0]['source'] == token[1:-1]
    assert results['knowledge_evidence'].output['sources'][0]['snapshot_id']
    assert {'material_outline', 'material_search', 'material_read', 'submit_item'} == set(clients[1].step_functions)
    assert expand_sources(token)[1] == []  # 承载性原有小资料内联行为不变


def test_fulfillment_deliveries_are_per_turn():
    """E 按轮标注，交付也按轮给：多轮时每轮一份答复（demand/expectations.md §1）。"""
    from dataclasses import replace
    from impl.projects.llm_probe.eval_axes.adapters.fulfillment import _deliveries
    trace = _trace('最后一轮答复')
    assert _deliveries(trace) == [{'turn': 't1', 'output_text': '最后一轮答复'}]
    multi = replace(trace, turn_records=[{'extracted_output': {'output_text': '查到伏云平'}},
                                         {'extracted_output': {'output_text': '余昕雅的保单是 P1'}}])
    assert _deliveries(multi) == [{'turn': 't1', 'output_text': '查到伏云平'}, {'turn': 't2', 'output_text': '余昕雅的保单是 P1'}]


def _assessment(status, evidence=(), refs=()):
    return {'expectation_id': 'e', 'reason': 'r', 'status': status, 'evidence': list(evidence), 'claim_refs': list(refs)}


@pytest.mark.parametrize('item, claims, problem', [
    # 没有核事实结果时 claim_refs 必须为空；有结果时只能引用存在的 claim
    (_assessment('not_fulfilled', refs=['x']), None, '没有核事实结果'),
    (_assessment('not_fulfilled', refs=['x']), [], '不在核事实结果里'),
    # 引用了被否定的事实只能是没给到 / 给错了
    (_assessment('not_evaluable', refs=['v']), [{'claim_id': 'v', 'verdict': 'refuted'}], 'refuted'),
    # 依赖的事实核实不了不能判 fulfilled
    (_assessment('fulfilled', ['保费1089.1元'], ['v']), [{'claim_id': 'v', 'verdict': 'unverifiable'}], '核实不了'),
    # 有核事实结果时，fulfilled 必须有 verified 的 claim 撑着（不凭模型自己的知识判对，M5）
    (_assessment('fulfilled', ['保费1089.1元']), [{'claim_id': 'v', 'verdict': 'verified'}], '至少一条 verified'),
])
def test_fulfillment_program_checks(item, claims, problem):
    from impl.projects.llm_probe.eval_axes.adapters.fulfillment import check_assessments
    problems = check_assessments([item], {'e'}, claims)
    assert any(problem in p for p in problems), problems


def test_fulfillment_unit_unverified_does_not_block_verified_value():
    """值核实了、修饰它的单位核实不了，不挡这条期望（demand/main_axis.md §2.6）。"""
    from impl.projects.llm_probe.eval_axes.adapters.fulfillment import check_assessments
    claims = [{'claim_id': 'value', 'verdict': 'verified', 'qualifies': ''},
              {'claim_id': 'unit', 'verdict': 'unverifiable', 'qualifies': 'value'}]
    item = _assessment('fulfilled', ['1089.1元'], ['value', 'unit'])
    assert check_assessments([item], {'e'}, claims) == []
    assert check_assessments([_assessment('fulfilled', ['1089.1元'])], {'e'}, None) == []  # 没开核事实：只判有没有


def test_truthfulness_flows_to_fulfillment_but_not_carryability(fake_es, monkeypatch):
    from impl.projects.llm_probe.eval_axes.adapters import expectations as expectations_axis, fulfillment as fulfillment_axis

    def other(role, system, user):
        if role == 'judge':
            if system == fulfillment_axis.DELIVERY_SYSTEM:
                assert '"claims"' in user and '十五日' in user
                payload = _judge_payload(system, 'not_fulfilled', '十五日')
                payload['items'][0]['claim_refs'] = ['days']
                return payload
            assert '十五日' not in user or system == expectations_axis.SYSTEM
            return _judge_payload(system, 'not_fulfilled', '十五日')
        assert 'truthfulness' not in user and '十五日' not in user
        return _carrier_payload('no')
    monkeypatch.setattr('impl.projects.llm_probe.eval_axes.adapters.carryability.expand_boundary',
                        lambda description: (description, [{'uri': SCOPE_URI, 'title': '责任范围', 'content': BOUNDARY}]))
    _knowledge_llm(monkeypatch, {'claims': [{'claim_id': 'days', 'claim': '十五日', 'span': '十五日'}]}, steps=[
        [_search('犹豫期')], [_submit('truthfulness:days', 'found', [{'call_id': 'c0', 'quote': '犹豫期二十日'}])],
    ], judges=[{'reason': '原文二十日', 'verdict': 'refuted', 'basis': [0]}], other=other)
    results = _by_id(run_axes(load_project('llm_probe'), _trace('十五日'), _axes() + _knowledge_axes(), scenario_id='s'))
    assert all(r.status == 'succeeded' for r in results.values())
    assert set(results['fulfillment'].inputs_used) == {'trace', 'expectations', 'truth'}
    assert results['fulfillment'].output['claims_checked'] is True
    assert results['fulfillment'].output['fulfillment_assessments'][0]['claim_refs'] == ['days']
    assert set(results['carryability'].inputs_used) == {'fulfillment', 'request_body'}  # 请求体只交给 MCP 取身份，没有真实性结果


def test_request_failed_payload_raises_instead_of_masquerading_as_format_error() -> None:
    """v2 §5.2：complete_json 请求层失败返回 error dict，不得被当模型输出进格式重试/salvage。"""
    payload = {"error": "llm_request_failed", "raw_text": "HTTP 401 invalid api-key"}
    with pytest.raises(AxisRequestFailed) as caught:
        raise_for_error_payload(payload)
    assert caught.value.error == "llm_request_failed"
    assert caught.value.raw_text == "HTTP 401 invalid api-key"
    raise_for_error_payload({"route": []})  # 正常模型输出：放行
    raise_for_error_payload(None)


def test_runner_marks_request_failure_failed_with_llm_error_usage(monkeypatch) -> None:
    """v2 §5.2：请求失败与模型格式错误分流——轴 failed，usage 带 llm_error / llm_error_text。"""

    def _run(_inputs: Any, _axis: Any, _runtime: Any) -> RunOutcome:
        raise AxisRequestFailed("llm_request_failed", "HTTP 401 invalid api-key")

    axis_type = AxisType(
        type_id="request_failed_probe",
        title="probe",
        summary="",
        verdict_scope="axis",
        verdict_enum=(Verdict("ok", ""),),
        depend_on=(),
        trigger_when=None,
        inputs=(),
        output_fields=("status",),
        scenario_fields=(),
        limits=ExecutionLimits(),
        run=_run,
        verdict_path="status",
    )
    monkeypatch.setattr(runner_module, "get_axis_type", lambda _type_id: axis_type)
    runtime = AxisRuntime(spec=None, run_id="axes-test", trace_id="t", scenario_id="s", case_id="c")

    result = runner_module._run_one(ScenarioAxis("request_failed_probe", True, ""), _trace(), runtime, {})

    assert result.status == STATUS_FAILED
    assert result.usage["llm_error"] == "llm_request_failed"
    assert "401" in result.usage["llm_error_text"]
    assert result.error.startswith("[运行环境] 模型请求失败 llm_request_failed")
    assert "HTTP 401" in result.error


# ---------------------------------------------------------------- 被测系统调用失败
def _http_failed_trace() -> RunTrace:
    from impl.core.live import fallback_decision
    from impl.core.live_protocol import LIVE_HTTP_ERROR
    trace = _trace()
    trace.extracted_output = {}
    trace.fallbacks = [fallback_decision(
        fallback_id="live-error-llm_probe", source_stage="live", fallback_type="live_error", status="error",
        reason='HTTP 400: {"code":"Arrearage"}', missing_evidence=["valid_live_response"], recoverable=False,
        needs_human_review=True, quality_flags=[LIVE_HTTP_ERROR], metadata={"failure_type": LIVE_HTTP_ERROR})]
    return trace


def test_business_http_failure_is_not_fulfilled_without_llm_and_others_not_applicable(monkeypatch) -> None:
    created = _install_fake_llm(monkeypatch)
    axes = [*_knowledge_axes("核验条款。知识源：{es://local-es/clause_kb} 条款原文。"), *_axes()]
    results = _by_id(run_axes(load_project("llm_probe"), _http_failed_trace(), axes, scenario_id="client_search"))
    # 只有需求轴调了模型（E 与这次答复无关）；兑现由程序直接判没给到
    from impl.projects.llm_probe.eval_axes.adapters import expectations as expectations_axis
    assert [c.calls[0]["system"] for c in created] == [expectations_axis.SYSTEM]
    assert results["fulfillment"].status == "succeeded"
    assert results["fulfillment"].verdict == "not_fulfilled"
    assert "Arrearage" in json.dumps(results["fulfillment"].summary, ensure_ascii=False)
    assert results["fulfillment"].output["evidence"] == ["business_call_failed"]
    assert results["knowledge_evidence"].status == "not_applicable"
    assert results["truthfulness"].status == "not_applicable"
    assert "被测系统调用失败" in results["truthfulness"].summary["text"]
    assert results["carryability"].status == "not_applicable"


def test_pipeline_judge_and_attribute_short_circuit_on_business_http_failure(monkeypatch) -> None:
    from impl.core import pipeline
    monkeypatch.setattr(pipeline, "load_project", lambda _pid: (_ for _ in ()).throw(AssertionError("不应进入项目判定")))
    trace = _http_failed_trace()
    result = pipeline.judge("llm_probe", trace)
    assert result.overall_fulfillment["status"] == "not_fulfilled"
    assert result.evidence == ["business_call_failed"]
    assert "HTTP 400" in result.reasoning_summary and "Arrearage" in result.summary["reason"]
    # 展示状态单列 fail：一眼区别于"答得不好"的 not_fulfilled；结果表规范化后仍是 fail。
    assert result.summary["fulfillment_status"] == "fail" and result.summary["reason"].startswith("fail · 被测系统报错：HTTP 400")
    from impl.core.schema import normalize_trace_table_row
    assert normalize_trace_table_row({"trace_id": "t", "fulfillment_status": "fail"}).fulfillment_status == "fail"
    assert normalize_trace_table_row({"trace_id": "t", "fulfillment_status": "weird"}).fulfillment_status == "not_evaluable"
    monkeypatch.undo()
    attribution = pipeline.attribute("llm_probe", trace, result)
    assert attribution.summary["attribution_status"] == "skipped"
    assert "被测系统调用失败" in attribution.unresolved_reason


# ---------------------------------------------------------------- 知识源登记的增删与 MCP 回读
def test_knowledge_source_save_delete_share_data_root_with_presets(monkeypatch, tmp_path):
    from impl.core import capability_store
    from impl.projects.llm_probe.eval_axes import sources
    from impl.projects.llm_probe.eval_axes.sources import registry
    monkeypatch.setattr(capability_store, 'store_path', lambda project: tmp_path / project / 'capability_map.json')
    assert registry.registry_path() == tmp_path / 'llm_probe' / 'knowledge_sources.json'
    with pytest.raises(ValueError, match='无凭据'):
        sources.save_source('biz-a', {'type': 'es', 'url': 'http://u@x'})
    with pytest.raises(ValueError, match='type 必须是'):
        sources.save_source('biz-a', {'type': 'mysql'})
    # 凭据变量可以晚于登记设置：保存只校写法。
    sources.save_source('biz-a', {'type': 'es', 'url': 'http://x:9200', 'api_key': '${BIZ_A_UNSET_KEY}'})
    sources.save_source('biz-m', {'type': 'mcp', 'command': '/bin/python', 'args': ['-m', 'x'], 'env': {'K': 'v'}, 'tools': ['qa']})
    presets = tmp_path / 'llm_probe' / 'capability_map.json'
    presets.write_text(json.dumps({'preset-a': capability_store.validate_entry('preset-a', {
        'capability': '回答问题', 'axes': [{'type': 'truthfulness', 'enabled': True, 'description': '核验 {es://biz-a/kb} 与 {mcp://biz-m}'}]})}, ensure_ascii=False))
    for name in ('biz-a', 'biz-m'):
        with pytest.raises(ValueError, match='preset-a'):
            sources.delete_source(name)
    presets.write_text('{}')
    assert sources.delete_source('biz-a')['sources'] == {'biz-m': {'type': 'mcp', 'command': '/bin/python', 'args': ['-m', 'x'], 'env': {'K': 'v'}, 'tools': ['qa']}}


def test_mcp_refs_format():
    from impl.core.capability_store import validate_mcp_refs
    assert validate_mcp_refs('看 {mcp://insurance-tools} 和 {mcp://insurance-tools}') == ['insurance-tools']
    for bad in ('{mcp://}', '{mcp://A}', '{mcp://a/b}', '{mcp://a'):
        with pytest.raises(ValueError, match='MCP 引用'):
            validate_mcp_refs(bad)


def test_mcp_source_exposes_only_allowlisted_read_tools(monkeypatch):
    from impl.projects.llm_probe.eval_axes.sources import mcp_tools
    from impl.projects.llm_probe.eval_axes.sources.registry import parse_mcp

    with pytest.raises(ValueError, match='tools'):
        parse_mcp('biz', {'type': 'mcp', 'command': '/bin/python'})
    source = parse_mcp('biz', {'type': 'mcp', 'command': '/bin/python', 'tools': ['general_qa']})
    # 入参没写说明的 MCP 也要能接：评测侧补占位，不要求业务方改 schema。
    offered = [{'name': name, 'description': name, 'schema': {'type': 'object', 'properties': {'query': {'type': 'string'}}}}
               for name in ('general_qa', 'customer_detail')]
    monkeypatch.setattr(mcp_tools, 'load_mcp_source', lambda name: source)
    monkeypatch.setattr(mcp_tools, 'list_tools', lambda src: offered)
    names = [fn.name for fn in mcp_tools.build_mcp_tools([{'source': 'mcp', 'uri': 'mcp://biz'}], [])]
    assert names == ['biz__general_qa', 'mcp_read', 'mcp_find']
    missing = parse_mcp('biz', {'type': 'mcp', 'command': '/bin/python', 'tools': ['nope']})
    monkeypatch.setattr(mcp_tools, 'load_mcp_source', lambda name: missing)
    with pytest.raises(ValueError, match='不在服务提供的工具里'):
        mcp_tools.build_mcp_tools([{'source': 'mcp', 'uri': 'mcp://biz'}], [])


def test_extraction_verbatim_ignores_markdown_emphasis_and_spacing():
    """回答常带 **加粗**、数字两侧空格：格式符不是内容，摘片段去掉它们仍算逐字；改了字就不算。"""
    from impl.projects.llm_probe.knowledge_loop.extract import parse_claims
    answer = '收到资料后，应在**5个工作日内**作出回复；中止后 **2 年内**可申请复效。'
    got = parse_claims({'claims': [{'claim_id': 'a', 'claim': '回复时限是5个工作日内', 'span': '应在5个工作日内'},
                                   {'claim_id': 'b', 'claim': '可申请复效的期限是2年内', 'span': '2年内', 'context': ['中止后']}]}, answer)
    assert [c['span'] for c in got] == ['应在5个工作日内', '2年内']
    with pytest.raises(ValueError, match='逐字连续原文'):
        parse_claims({'claims': [{'claim_id': 'a', 'claim': '回复时限是7个工作日内', 'span': '应在7个工作日内'}]}, answer)


def test_extraction_value_and_unit_are_two_claims_sharing_one_span():
    """demand/claims.md §2.2：「1089.1 元」是两条主张（值、单位），共用同一段片段；共用片段不算隔离泄漏。"""
    from impl.projects.llm_probe.knowledge_loop.extract import parse_claims
    answer = '保单 P1 累计已交保费为**1089.1元**。'
    span = '累计已交保费为1089.1元'
    got = parse_claims({'claims': [{'claim_id': 'v', 'claim': '累计已交保费的数值是1089.1', 'span': span, 'context': ['P1']},
                                   {'claim_id': 'u', 'claim': '累计已交保费的单位是元', 'span': span, 'context': ['P1']}]}, answer)
    assert [(c['claim'], c['span']) for c in got] == [('累计已交保费的数值是1089.1', span), ('累计已交保费的单位是元', span)]
    with pytest.raises(ValueError, match='只放定位所需'):
        parse_claims({'claims': [{'claim_id': 'a', 'claim': '保单号是P1', 'span': '保单 P1'},
                                 {'claim_id': 'b', 'claim': '累计已交保费是1089.1元', 'span': '1089.1元', 'context': ['保单 P1 累计已交保费为']}]}, answer)


def test_extraction_span_matches_decoded_json_answer_and_shared_identifier_is_not_a_leak():
    """回答是 JSON 字符串时引号被转义成 \\"，模型摘的是解码后的字，仍算逐字；context 段恰好等于别条说法的片段（产品名）是对象标识，不算塞整句。"""
    import json as _json
    from impl.projects.llm_probe.knowledge_loop.extract import parse_claims
    answer = _json.dumps({'answer': '主险：甲产品\n该医保条款中的"2.1 责任免除"正文未返回。'}, ensure_ascii=False)
    got = parse_claims({'claims': [{'claim_id': 'a', 'claim': '主险是甲产品', 'span': '甲产品'},
                                   {'claim_id': 'b', 'claim': '甲产品没有2.1责任免除正文', 'span': '"2.1 责任免除"正文未返回', 'context': ['甲产品']}]}, answer)
    assert [c['claim_id'] for c in got] == ['a', 'b']


def test_extraction_context_may_come_from_question_but_span_must_not():
    """短答"5天"的对象"年休假"只在问题里（demand/claims.md §2.1、C8）：context 可摘自问题，span 仍须出自回答。"""
    from types import SimpleNamespace
    from impl.projects.llm_probe.knowledge_loop.extract import parse_claims, user_turns
    question = '\n'.join(user_turns(SimpleNamespace(conversation_transcript=[], normalized_request={
        'body': {'input': {'messages': [{'role': 'user', 'content': '我累计工龄3年，年休假有几天？只回答天数。'}]}}})))
    got = parse_claims({'claims': [{'claim_id': 'a', 'claim': '年休假是5天', 'span': '5天', 'context': ['累计工龄3年', '年休假']}]}, '5天', question)
    assert got[0]['context'] == ['累计工龄3年', '年休假']
    with pytest.raises(ValueError, match='逐字连续原文'):
        parse_claims({'claims': [{'claim_id': 'a', 'claim': '年休假是5天', 'span': '年休假5天'}]}, '5天', question)
    with pytest.raises(ValueError, match='用户问题'):
        parse_claims({'claims': [{'claim_id': 'a', 'claim': '年休假是5天', 'span': '5天', 'context': ['入职满3年']}]}, '5天', question)
    # 多轮：以对话记录为准，后面的更正也是问题的一部分（demand/main_axis.md §4.5）。
    multi = SimpleNamespace(normalized_request={'body': {'messages': [{'role': 'user', 'content': '查伏云平名下保单'}]}},
                            conversation_transcript=[{'role': 'user', 'query': '查伏云平名下保单'}, {'role': 'assistant', 'content': 'ok'},
                                                     {'role': 'user', 'query': '名字说错了，是余昕雅，问题不变。'}])
    assert user_turns(multi) == ['查伏云平名下保单', '名字说错了，是余昕雅，问题不变。']


def test_carryability_mcp_citation_must_come_from_a_successful_query_receipt():
    """信息源里本来没有也是做不了（capability_carrier.md §2.1）：引句须逐字出自这次成功查询的返回；
    报错的返回不算查实。请求体只交给工具，不进模型上下文。"""
    from types import SimpleNamespace
    from impl.projects.llm_probe.eval_axes.adapters.carryability import BoxBoundaryCarrier
    runtime = SimpleNamespace(trace_id='t', ensure_time_left=lambda label: None)
    carrier = BoxBoundaryCarrier(load_project('llm_probe'), '保单查询能力', runtime, {'empno': '1'})
    carrier._wait = lambda attempt: None
    verdict = {'carry': 'no', 'reason': '按保单号查过，没有这张保单', 'self_recognition': '未查询到该保单',
               'citations': [{'source': 'mcp://ins', 'ref': 'mcp://ins#1', 'note': '未查询到该保单'}]}
    seen = []

    def call(error):
        def _call_llm(expectation_text, boundary, receipts, feedback=''):
            seen.append(expectation_text + json.dumps(boundary, ensure_ascii=False))
            receipts.append({'tool': 'mcp_call', 'page_id': 'mcp://ins#1', 'response_text': '{"status":"EMPTY","hint":"未查询到该保单"}',
                             **({'error': 'MCP 调用失败'} if error else {})})
            return verdict
        return _call_llm

    carrier._call_llm = call(error=False)
    assert carrier._judge_with_retry('告知保单P1的被保人', {'text': '保单查询能力', 'catalog': []}).carry == 'no'
    carrier._call_llm = call(error=True)
    failed = carrier._judge_with_retry('告知保单P1的被保人', {'text': '保单查询能力', 'catalog': []})
    assert 'MCP 引用回读核验失败' in failed.last_error
    assert all('empno' not in text for text in seen)
    # 查实没有 → 做不了的依据种类是信息源回执
    carrier._call_llm = call(error=False)
    assert carrier._judge_with_retry('告知保单P1的被保人', {'text': '保单查询能力', 'catalog': []}).recognition == 'source_absent'


def test_carryability_cites_only_registration_or_receipts_not_background():
    """依据只有责任范围登记和信息源回执；场景描述里系统自己的说明是背景，引用它被打回（capability_carrier.md §6.1）。"""
    from types import SimpleNamespace
    from impl.projects.llm_probe.eval_axes.adapters.carryability import BoxBoundaryCarrier
    runtime = SimpleNamespace(trace_id='t', ensure_time_left=lambda label: None)
    carrier = BoxBoundaryCarrier(load_project('llm_probe'), BOUNDARY, runtime)
    carrier._wait = lambda attempt: None
    boundary = {'text': BOUNDARY, 'catalog': [], 'registrations': [{'uri': SCOPE_URI, 'title': '责任范围', 'content': '本系统不接年龄数据。'}]}
    from_background = {'carry': 'no', 'reason': '描述说不支持年龄', 'self_recognition': '不支持年龄',
                       'citations': [{'source': 'boundary', 'ref': 'boundary', 'note': '不支持年龄'}]}
    carrier._call_llm = lambda *args, **kwargs: from_background
    failed = carrier._judge_with_retry(EXPECTATION, boundary)
    assert '不是依据' in failed.last_error
    from_registration = {'carry': 'no', 'reason': '登记写明不接年龄数据', 'self_recognition': '不接年龄数据',
                         'citations': [{'source': SCOPE_URI, 'ref': 'boundary', 'note': '不接年龄数据'}]}
    carrier._call_llm = lambda *args, **kwargs: from_registration
    assert carrier._judge_with_retry(EXPECTATION, boundary).recognition == 'responsibility_registration'
    # carry=yes 同样要有依据，不能空口
    carrier._call_llm = lambda *args, **kwargs: {'carry': 'yes', 'reason': '应该能做', 'citations': []}
    assert '依据' in carrier._judge_with_retry(EXPECTATION, boundary).last_error


def _fulfillment_result(*statuses, blocking=True):
    return {'type_id': 'fulfillment', 'status': 'succeeded', 'output': {
        'business_expectations': [{'expectation_id': f'e{i}', 'blocking': blocking} for i, _ in enumerate(statuses)],
        'fulfillment_assessments': [{'expectation_id': f'e{i}', 'status': st, 'claim_refs': []} for i, st in enumerate(statuses)]}}


def _carry_result(*placements):
    return {'type_id': 'carryability', 'status': 'succeeded',
            'output': {'placements': [{'expectation_id': f'e{i}', 'placement': p} for i, p in enumerate(placements)]}}


def _truth_result(*verdicts):
    return {'type_id': 'truthfulness', 'status': 'succeeded',
            'output': {'claims': [{'claim_id': f'c{i}', 'verdict': v, 'qualifies': q} for i, (v, q) in enumerate(verdicts)]}}


@pytest.mark.parametrize('results, expected, flags', [
    ([_fulfillment_result('fulfilled')], '做成了', {'claims_checked': False}),
    ([_fulfillment_result('not_evaluable')], '不确定', {}),
    # 没开承载性：区分不出，不改成不确定
    ([_fulfillment_result('not_fulfilled')], '没做成', {'capability_undetermined': True}),
    ([_fulfillment_result('not_fulfilled', 'not_fulfilled'), _carry_result('做不了', '做不了')], '做不了', {}),
    ([_fulfillment_result('not_fulfilled', 'not_fulfilled'), _carry_result('做不了', '做错了')], '没做成', {'capability_undetermined': False}),
    ([_fulfillment_result('not_fulfilled', 'not_fulfilled'), _carry_result('做不了', '说不清')], '没做成', {'capability_undetermined': True}),
    # 非 blocking 的没给到不影响结论
    ([_fulfillment_result('not_fulfilled', blocking=False)], '做成了', {}),
    # 交付里说错的事实：用户要的给到了也挡（main_axis §2.5），组成里看得出是被它挡的
    ([_fulfillment_result('fulfilled'), _truth_result(('verified', ''), ('refuted', ''))], '没做成', {'blocked_by_claims': ['c1']}),
    ([_fulfillment_result('fulfilled'), _truth_result(('verified', ''), ('unverifiable', ''))], '不确定', {'blocked_by_claims': ['c1']}),
    # 单位核实不了、值已核实：不挡（main_axis §2.6）
    ([_fulfillment_result('fulfilled'), _truth_result(('verified', ''), ('unverifiable', 'c0'))], '做成了', {'claims_checked': True}),
])
def test_main_verdict_composes_fulfillment_carryability_and_claims(results, expected, flags):
    """demand/main_axis.md §2–§4、spec/math-abstract/judge.md §3.1：确定性合成，不调模型，组成随结论给出。"""
    from impl.projects.llm_probe.eval_axes.main_verdict import main_verdict
    verdict = main_verdict(results)
    assert verdict['verdict'] == expected
    for key, value in flags.items():
        assert verdict['composition'][key] == value
    assert len(verdict['composition']['items']) == len(results[0]['output']['fulfillment_assessments'])


def test_main_verdict_has_no_conclusion_when_an_enabled_part_failed():
    from impl.projects.llm_probe.eval_axes.main_verdict import main_verdict
    assert main_verdict([{'type_id': 'fulfillment', 'status': 'failed'}]) is None
    # 开了核事实却没跑成：不能当成没开放过
    assert main_verdict([_fulfillment_result('fulfilled'), {'type_id': 'truthfulness', 'status': 'failed'}]) is None


def test_ambiguity_group_is_fulfilled_by_any_adopted_reading(monkeypatch):
    """同一句话的互斥读法不替用户选：交付按任一读法给到，这一组就算给到（spec/alg/fulfilled.md §1）。"""
    from types import SimpleNamespace
    from impl.projects.llm_probe.eval_axes.adapters import fulfillment as fulfillment_axis
    from impl.projects.llm_probe.eval_axes.main_verdict import main_verdict
    frozen = {'sha256': 'x', 'verdict': 'complete', 'expectations': [
        {'expectation_id': 't1.ge', 'turn': 't1', 'about': '年龄', 'statement': '年龄≥50', 'condition': '总是', 'ambiguity_group': 'g'},
        {'expectation_id': 't1.gt', 'turn': 't1', 'about': '年龄', 'statement': '年龄>50', 'condition': '总是', 'ambiguity_group': 'g'}]}
    replies = iter([{'items': [{'expectation_id': 't1.ge', 'blocking': True}, {'expectation_id': 't1.gt', 'blocking': True}]},
                    {'items': [_assessment('fulfilled', ['age GTE 50']) | {'expectation_id': 't1.ge'},
                               _assessment('not_fulfilled') | {'expectation_id': 't1.gt'}], 'reasoning_summary': '按≥读'}])
    monkeypatch.setattr(fulfillment_axis, '_ask', lambda *args, **kwargs: next(replies))
    monkeypatch.setattr(fulfillment_axis, 'axis_llm', lambda *args, **kwargs: SimpleNamespace(usage=lambda: {}))
    runtime = SimpleNamespace(spec=None, enabled_axes=('expectations', 'fulfillment'), trace_id='t', ensure_time_left=lambda label: None)
    outcome = fulfillment_axis.run_fulfillment({'trace': _trace('age GTE 50'), 'expectations': frozen}, ScenarioAxis('fulfillment', True, ''), runtime)
    assert outcome.output['overall_fulfillment']['status'] == 'fulfilled'
    gt = next(a for a in outcome.output['fulfillment_assessments'] if a['expectation_id'] == 't1.gt')
    assert gt['other_reading_fulfilled'] is True and gt['status'] == 'not_fulfilled'
    verdict = main_verdict([{'type_id': 'fulfillment', 'status': 'succeeded', 'output': outcome.output}])
    assert verdict['verdict'] == '做成了' and [i['expectation_id'] for i in verdict['composition']['items']] == ['t1.ge']
