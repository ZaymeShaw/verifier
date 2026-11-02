"""显式注册的轴类型。资料页下拉只列这里的类型；预设里的 type 不在这里 → 加载报错。"""
from __future__ import annotations

from typing import Any, Mapping

from .adapters import (
    carryability,
    expectations,
    context_memory,
    fulfillment,
    intent_understanding,
    knowledge_data,
    knowledge_evidence,
    model_capability,
    planning_routing,
    tool_execution,
    trace_analysis,
    truthfulness,
)
from .types import VERDICT_SCOPE_AXIS, AxisType

_REGISTERED: tuple[AxisType, ...] = (
    fulfillment.AXIS_TYPE,
    carryability.AXIS_TYPE,
    knowledge_evidence.AXIS_TYPE,
    truthfulness.AXIS_TYPE,
    trace_analysis.AXIS_TYPE,
    expectations.AXIS_TYPE,
    intent_understanding.AXIS_TYPE,
    planning_routing.AXIS_TYPE,
    tool_execution.AXIS_TYPE,
    context_memory.AXIS_TYPE,
    knowledge_data.AXIS_TYPE,
    model_capability.AXIS_TYPE,
)


def _check_registry(types: tuple[AxisType, ...]) -> Mapping[str, AxisType]:
    """类型层静态校验（axe-v4 §7 里不依赖场景的那几条），import 时 fail-fast。"""
    by_id: dict[str, AxisType] = {}
    for item in types:
        if item.type_id in by_id:
            raise ValueError(f"轴类型重复注册: {item.type_id}")
        by_id[item.type_id] = item
    for item in types:
        for dependency in item.depend_on:
            upstream_id = dependency.type_id
            if upstream_id not in by_id:
                raise ValueError(f"{item.type_id}: depend_on 引用了未注册的类型 {upstream_id}")
        if item.trigger_when is not None:
            upstream = by_id[item.trigger_when.axis]
            if upstream.verdict_scope != VERDICT_SCOPE_AXIS:
                raise ValueError(
                    f"{item.type_id}: trigger_when 引用的 {upstream.type_id} 是 item 级类型，没有轴级 verdict 可筛"
                )
            bad = sorted(set(item.trigger_when.verdict_in) - set(upstream.verdict_values))
            if bad:
                raise ValueError(
                    f"{item.type_id}: trigger_when.verdict_in 含 {bad}，不在 {upstream.type_id} 的枚举里"
                )
        for slot in item.inputs:
            if not slot.axis_ref:
                continue
            upstream = by_id[slot.axis_ref]
            bad = sorted(set(slot.fields) - set(upstream.output_fields))
            if bad:
                raise ValueError(
                    f"{item.type_id}: inputs.{slot.name} 引用了 {upstream.type_id} 没有的 output 字段 {bad}"
                )
    # depend_on 不得成环
    state: dict[str, int] = {}

    def visit(type_id: str, path: list[str]) -> None:
        mark = state.get(type_id, 0)
        if mark == 1:
            raise ValueError(f"轴类型 depend_on 成环: {' -> '.join(path + [type_id])}")
        if mark == 2:
            return
        state[type_id] = 1
        for dependency in by_id[type_id].depend_on:
            visit(dependency.type_id, path + [type_id])
        state[type_id] = 2

    for type_id in by_id:
        visit(type_id, [])
    return by_id


AXIS_TYPES: Mapping[str, AxisType] = _check_registry(_REGISTERED)


def get_axis_type(type_id: str) -> AxisType:
    try:
        return AXIS_TYPES[str(type_id)]
    except KeyError:
        raise ValueError(
            f"未注册的轴类型 {type_id!r}；可用类型: {', '.join(sorted(AXIS_TYPES))}"
        ) from None


def describe_axis_types() -> list[dict[str, Any]]:
    """给 /api/eval_axes/types：按注册顺序返回类型声明。"""
    return [item.describe() for item in _REGISTERED]
