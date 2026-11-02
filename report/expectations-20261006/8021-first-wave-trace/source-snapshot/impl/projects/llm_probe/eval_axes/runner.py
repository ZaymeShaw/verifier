"""运行器：对一个样本按 depend_on 拓扑序执行场景轴，固定五步（axe-v4 §5），不做通用 DAG。

1. enabled?                         否 → disabled
2. depend_on 全部 succeeded?        否 → blocked（trigger_decision 记上游实际状态）
3. trigger_when 命中?               否 → not_applicable
4. 按 inputs 声明逐项取数           必填缺失 → failed
5. run()                            → succeeded | failed；output 键集必须等于 output_fields，
                                       axis 级 verdict / item 级逐项值必须落在 verdict_enum 内
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import replace
from typing import Any, Mapping, Sequence

from impl.core.config import ROOT
from impl.core.schema import RunTrace
from impl.core.schema.base import now_iso

from .registry import get_axis_type
from .types import (
    FAILURE_AXIS,
    FAILURE_ENVIRONMENT,
    FAILURE_KINDS,
    FAILURE_MATERIAL,
    SOURCE_SAMPLE,
    STATUS_BLOCKED,
    STATUS_DISABLED,
    STATUS_FAILED,
    STATUS_NOT_APPLICABLE,
    STATUS_SUCCEEDED,
    VERDICT_SCOPE_AXIS,
    AxisResult,
    AxisRuntime,
    AxisRequestFailed,
    AxisTimeout,
    AxisType,
    ScenarioAxis,
)

_IMPLEMENTATION_FINGERPRINTS: dict[str, str] = {}


def new_run_id() -> str:
    return f"axes-{uuid.uuid4().hex[:12]}"


def topo_order(axes: Sequence[ScenarioAxis]) -> list[ScenarioAxis]:
    """按 depend_on 排序；同层保持传入顺序。不在本场景的上游不参与排序（运行时落 blocked）。"""
    present = {axis.type_id: axis for axis in axes}
    pending = list(axes)
    ordered: list[ScenarioAxis] = []
    done: set[str] = set()
    while pending:
        progressed = False
        for axis in list(pending):
            deps = [d.type_id for d in get_axis_type(axis.type_id).depend_on if d.type_id in present]
            if all(d in done for d in deps):
                ordered.append(axis)
                done.add(axis.type_id)
                pending.remove(axis)
                progressed = True
        if not progressed:
            # 注册表已保证类型层无环；走到这里只可能是场景配置引用了自身之外的环，直接报出。
            raise ValueError("场景轴依赖成环: " + ", ".join(axis.type_id for axis in pending))
    return ordered


def config_fingerprint(axis: ScenarioAxis) -> str:
    raw = json.dumps(axis.as_dict(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def implementation_fingerprint(axis_type: AxisType) -> str:
    cached = _IMPLEMENTATION_FINGERPRINTS.get(axis_type.type_id)
    if cached:
        return cached
    digest = hashlib.sha256()
    for relative in axis_type.implementation_files:
        path = ROOT / relative
        digest.update(relative.encode("utf-8"))
        if path.is_file():
            digest.update(path.read_bytes())
        else:
            digest.update(b"<missing>")
    value = digest.hexdigest()
    _IMPLEMENTATION_FINGERPRINTS[axis_type.type_id] = value
    return value


def _get_path(payload: Mapping[str, Any], dotted: str) -> Any:
    current: Any = payload
    for part in dotted.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _item_values(payload: Mapping[str, Any], item_path: str) -> list[Any]:
    list_field, value_field = item_path.split("[].", 1)
    items = payload.get(list_field)
    if not isinstance(items, list):
        return []
    return [item.get(value_field) if isinstance(item, Mapping) else None for item in items]


def _base_result(
    axis: ScenarioAxis,
    axis_type: AxisType,
    runtime: AxisRuntime,
    status: str,
    *,
    summary_text: str = "",
) -> AxisResult:
    return AxisResult(
        run_id=runtime.run_id,
        case_id=runtime.case_id,
        scenario_id=runtime.scenario_id,
        axis_id=axis.type_id,
        type_id=axis.type_id,
        verdict_scope=axis_type.verdict_scope,
        status=status,
        title=axis_type.title,
        summary={"text": summary_text, "items": []} if summary_text else {},
        config_fingerprint=config_fingerprint(axis),
        implementation_fingerprint=implementation_fingerprint(axis_type),
        execution_trace_ref=runtime.trace_id,
    )


_REQUEST_ERROR_CODES = ("llm_call_failed", "llm_request_failed", "llm_empty_response")


def _fail(result: AxisResult, error: str, *, items: list[dict[str, Any]] | None = None) -> AxisResult:
    if not error.startswith(FAILURE_KINDS):
        # 共用 judge 链路的失败标记里带 llm_client 的请求层错误码时，属于运行环境而不是轴实现。
        kind = FAILURE_ENVIRONMENT if any(code in error for code in _REQUEST_ERROR_CODES) else FAILURE_AXIS
        error = f"{kind} {error}"
    result.status = STATUS_FAILED
    result.error = error
    result.verdict = None
    result.verdict_description = ""
    result.summary = {"text": error, "items": list(items or [])}
    return result


def _run_one(
    axis: ScenarioAxis,
    trace: RunTrace,
    runtime: AxisRuntime,
    results: Mapping[str, AxisResult],
) -> AxisResult:
    axis_type = get_axis_type(axis.type_id)

    # 1. enabled
    if not axis.enabled:
        return _base_result(axis, axis_type, runtime, STATUS_DISABLED, summary_text="未启用")

    # 2. depend_on
    upstream_status = {}
    required_ids = {d.type_id for d in axis_type.depend_on if not d.optional}
    for dependency in axis_type.depend_on:
        upstream_id = dependency.type_id
        upstream = results.get(upstream_id)
        upstream_status[upstream_id] = upstream.status if upstream is not None else "missing"
    if any(upstream_status[key] != STATUS_SUCCEEDED for key in required_ids):
        # 阻断原因要一眼看到上游为什么没成：直接带上游的失败分类与原文。
        blocked_by = "，".join(
            f"{k}={v}" + (f"（{results[k].error}）" if k in results and results[k].error else "")
            for k, v in upstream_status.items() if k in required_ids and v != STATUS_SUCCEEDED)
        result = _base_result(axis, axis_type, runtime, STATUS_BLOCKED, summary_text=f"上游未成功：{blocked_by}")
        result.trigger_decision = {"depend_on_satisfied": False, "upstream": upstream_status}
        return result
    trigger_decision: dict[str, Any] = {"depend_on_satisfied": True, "trigger_when_matched": None, "upstream": upstream_status}

    # 3. trigger_when
    when = axis_type.trigger_when
    if when is not None:
        observed = results[when.axis].verdict
        matched = observed in when.verdict_in
        trigger_decision["trigger_when_matched"] = {
            "axis": when.axis,
            "verdict": observed,
            "verdict_in": list(when.verdict_in),
            "matched": matched,
        }
        if not matched:
            result = _base_result(
                axis, axis_type, runtime, STATUS_NOT_APPLICABLE,
                summary_text=f"{when.axis}={observed}，不在筛选范围 [{'/'.join(when.verdict_in)}]，不判",
            )
            result.trigger_decision = trigger_decision
            return result

    # 4. inputs
    inputs: dict[str, Any] = {}
    inputs_used: dict[str, Any] = {}
    missing: list[str] = []
    for slot in axis_type.inputs:
        if slot.kind == SOURCE_SAMPLE:
            if slot.sample_field == "trace":
                value = trace
            elif slot.sample_field == "requirements":
                from ..business_trace.expectation_material import project_requirements
                from .adapters.process_common import _scenario_entry
                value = project_requirements(trace, _scenario_entry(runtime))
            elif slot.sample_field == "business_trace":
                fields = trace.project_fields if isinstance(trace.project_fields, Mapping) else {}
                value = fields.get("business_trace")
            else:
                value = None
            ref = f"{slot.source}@{trace.trace_id}"
        else:
            upstream = results.get(slot.axis_ref)
            output = upstream.output if upstream is not None and upstream.status == STATUS_SUCCEEDED else None
            value = None
            if isinstance(output, Mapping):
                value = {name: output.get(name) for name in slot.fields}
            ref = f"{slot.source}[{','.join(slot.fields)}]@{runtime.run_id}"
        if value is None:
            if slot.required:
                missing.append(slot.name)
            continue
        inputs[slot.name] = value
        inputs_used[slot.name] = ref
    if missing:
        result = _base_result(axis, axis_type, runtime, STATUS_FAILED)
        result.trigger_decision = trigger_decision
        result.inputs_used = inputs_used
        return _fail(result, f"{FAILURE_MATERIAL} 必填输入缺失: " + ", ".join(missing))

    # 5. run
    started_at = now_iso()
    started = time.monotonic()
    seconds = axis_type.limits.seconds
    runtime = replace(runtime, deadline=(started + float(seconds)) if seconds else None)
    try:
        outcome = axis_type.run(inputs, axis, runtime)
    except AxisTimeout as exc:
        result = _base_result(axis, axis_type, runtime, STATUS_FAILED)
        result.trigger_decision = trigger_decision
        result.inputs_used = inputs_used
        result.started_at = started_at
        result.finished_at = now_iso()
        result.usage = {"elapsed_ms": int((time.monotonic() - started) * 1000), "timed_out": True}
        return _fail(result, f"{FAILURE_ENVIRONMENT} 超时（上限 {seconds:g}s）：{exc}")
    except AxisRequestFailed as exc:  # 请求层失败：与模型格式错误分流，usage 留原始错误文本
        result = _base_result(axis, axis_type, runtime, STATUS_FAILED)
        result.trigger_decision = trigger_decision
        result.inputs_used = inputs_used
        result.started_at = started_at
        result.finished_at = now_iso()
        result.usage = {
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "llm_error": exc.error,
            "llm_error_text": exc.raw_text,
        }
        return _fail(result, f"{FAILURE_ENVIRONMENT} 模型请求失败 {exc.error}：{str(exc.raw_text or '')[:300]}")
    except Exception as exc:  # 单轴失败隔离：不让一个 adapter 的异常拖垮同批其他轴
        result = _base_result(axis, axis_type, runtime, STATUS_FAILED)
        result.trigger_decision = trigger_decision
        result.inputs_used = inputs_used
        result.started_at = started_at
        result.finished_at = now_iso()
        result.usage = {"elapsed_ms": int((time.monotonic() - started) * 1000)}
        return _fail(result, f"{type(exc).__name__}: {exc}")
    finished_at = now_iso()
    usage = dict(outcome.usage)
    usage["elapsed_ms"] = int((time.monotonic() - started) * 1000)

    result = _base_result(axis, axis_type, runtime, STATUS_SUCCEEDED)
    result.trigger_decision = trigger_decision
    result.inputs_used = inputs_used
    result.started_at = started_at
    result.finished_at = finished_at
    result.usage = usage
    result.output = dict(outcome.output) if isinstance(outcome.output, Mapping) else None
    partial_items = list(outcome.summary.items) if outcome.summary is not None else []

    if outcome.failed:
        # 没跑成：解释就是失败原因；adapter 若交了已完成部分的逐格结果（如轴2部分归位）保留作诊断。
        return _fail(result, outcome.failure_reason or "adapter reported failure", items=partial_items)
    if result.output is None or set(result.output) != set(axis_type.output_fields):
        got = sorted(result.output) if result.output is not None else None
        return _fail(result, f"output 键集与类型声明不一致: 声明 {sorted(axis_type.output_fields)}，得到 {got}")
    if axis_type.verdict_scope == VERDICT_SCOPE_AXIS:
        verdict = _get_path(result.output, axis_type.verdict_path)
        if verdict not in axis_type.verdict_values:
            return _fail(result, f"verdict {verdict!r} 不在枚举 {list(axis_type.verdict_values)} 内")
        result.verdict = str(verdict)
        result.verdict_description = axis_type.verdict_description(verdict)
    else:
        bad = [value for value in _item_values(result.output, axis_type.item_path) if value not in axis_type.verdict_values]
        if bad:
            return _fail(result, f"逐项值 {bad} 不在枚举 {list(axis_type.verdict_values)} 内")
    # 判了就必须能解释：与 reason 必填、枚举必须落在词表内是同一标准。
    if outcome.summary is None or not str(outcome.summary.text or "").strip():
        return _fail(result, "adapter 未提供 summary（判定必须带解释）", items=partial_items)
    bad_items = [item for item in outcome.summary.items if not isinstance(item, Mapping) or "value" not in item]
    if bad_items:
        return _fail(result, "summary.items 每格必须含 value（枚举值）")
    result.summary = outcome.summary.as_dict()
    return result


def run_axes(
    spec: Any,
    trace: RunTrace,
    axes: Sequence[ScenarioAxis],
    *,
    scenario_id: str,
    run_id: str = "",
) -> list[AxisResult]:
    """对一个样本跑完场景里的全部框，返回拓扑序的 AxisResult 列表（每框一条，含未发动的）。"""
    run_id = run_id or new_run_id()
    case_id = str(trace.case_id or "")
    runtime = AxisRuntime(
        spec=spec,
        run_id=run_id,
        trace_id=f"{run_id}:{trace.trace_id or case_id or 'sample'}",
        scenario_id=scenario_id,
        case_id=case_id,
        enabled_axes=tuple(axis.type_id for axis in axes if axis.enabled),
    )
    results: dict[str, AxisResult] = {}
    ordered = topo_order(axes)
    for axis in ordered:
        result = _run_one(axis, trace, runtime, results)
        for dependency in get_axis_type(axis.type_id).depend_on:
            upstream = results.get(dependency.type_id)
            if axis.enabled and dependency.optional and upstream is not None and upstream.status not in (STATUS_DISABLED, STATUS_SUCCEEDED):
                result.summary["text"] += f"（{dependency.type_id}未完成，未纳入）"
        results[axis.type_id] = result
        if result.status == STATUS_SUCCEEDED:
            for issue in (result.output or {}).get('issues', []):
                runtime.process_issues[issue['problem_id']] = issue
    from .adapters.process_protocol import AXES, validate_issue_references
    process = {key: value for key, value in results.items() if key in AXES and value.status == STATUS_SUCCEEDED}
    try:
        validate_issue_references({key: value.output for key, value in process.items()})
    except ValueError as exc:
        for result in process.values():
            _fail(result, str(exc))
            result.output = None
    return [results[axis.type_id] for axis in ordered]
