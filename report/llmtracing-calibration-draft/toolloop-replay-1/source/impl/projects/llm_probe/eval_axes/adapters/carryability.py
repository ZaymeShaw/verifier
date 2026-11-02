"""轴类型 carryability：新版轴2（承载性归位）。

实现方式（axe-v4 D7）：继承 ``TextCarrier``，只换两处入口——
- ``_current_boundary``：边界文本来自框里的 description，走与 ``resolve_boundary`` 相同的
  ``expand_material_uris_with_catalog``（小资料内联、大资料转目录 + 检索工具）；
- ``_call_llm``：与父类同一套 prompt / 角色 / 工具 / 上限，只多传本次试验的 trace_id 并计数。
门控、逐 blocking NF 期望循环、归位映射、引用核验、重试全部复用 ``place()``（协议锁定，不可覆盖）。

输入只有 fulfillment 输出的三个字段，没有任何 sample 来源：轴2不看这次交付了什么
（spec/alg/capability_carrier.md §5 第 6 条）。
"""
from __future__ import annotations

from typing import Any, Mapping
from dataclasses import replace
import json
import hashlib

from impl.core.capability_carrier import (
    PLACEMENT_CANNOT,
    PLACEMENT_UNCLEAR,
    PLACEMENT_WRONG,
    carrier_text,
    format_carrier_errors,
)
from ..sources import expand_sources, build_tools
from impl.projects.llm_probe.text_carrier import (
    _CARRIER_SYSTEM,
    _CARRIER_TOOLS_GUIDE,
    TextCarrier,
    _TOOL_CALL_LIMIT,
    _catalog_prompt,
    _verdict_output_spec,
    _parse_verdict,
    _verify_citations,
    CarrierError,
)

from ..llm import axis_llm, merge_usage
from ..types import (
    VERDICT_SCOPE_ITEM,
    AxisRuntime,
    AxisSummary,
    AxisTimeout,
    AxisType,
    ExecutionLimits,
    Field,
    Input,
    RunOutcome,
    ScenarioAxis,
    Verdict,
    When,
)

_OUTPUT_FIELDS = ("applicable", "axis1_status", "placements", "errors", "snapshot_id")
_INPUT_FIELDS = ("overall_fulfillment", "business_expectations", "fulfillment_assessments")


class BoxBoundaryCarrier(TextCarrier):
    """边界来自场景轴的描述；其余行为与生产 TextCarrier 一致。"""

    def __init__(self, spec: Any, description: str, runtime: AxisRuntime) -> None:
        super().__init__(spec=spec)
        text, catalog = expand_sources(description)
        self._box_text = str(text or "").strip()
        self._box_catalog = [dict(item) for item in catalog]
        self._runtime = runtime
        self._trace_id = runtime.trace_id
        self.tool_calls = 0
        self.timed_out = False
        # 逐条期望、逐次重试的模型调用记账合并在这里（llm_calls / llm_model / llm_endpoint …）。
        self.llm_usage: dict[str, Any] = {}

    def _current_boundary(self) -> dict[str, Any]:
        return {"text": self._box_text, "catalog": [dict(item) for item in self._box_catalog]}

    def snapshot_revision(self) -> str:
        es_snapshots = [item['snapshot_id'] for item in self._box_catalog if item.get('source') == 'es']
        revision = super().snapshot_revision()
        return hashlib.sha256((revision + '|'.join(es_snapshots)).encode()).hexdigest()[:16] if es_snapshots else revision

    def _judge_with_retry(self, expectation_text, boundary):
        from ..sources.es_tools import EsTools
        es_catalog = [item for item in boundary['catalog'] if item.get('source') == 'es']
        feedback = ""
        last_error = "承载性判定无效"
        for attempt in range(self._retries):
            # 到点后余下的期望全部记"超时未判"，不再开新的模型调用；已归位的保留。
            try:
                self._runtime.ensure_time_left(f"期望 {expectation_text[:40]}")
            except AxisTimeout as exc:
                self.timed_out = True
                return CarrierError("text_carrier", "超出本轴时间上限", str(exc))
            receipts = []
            try:
                result = self._call_llm(expectation_text, boundary, receipts, feedback)
                verdict = _parse_verdict(result)
                if verdict is None:
                    raise ValueError("LLM 输出缺少必填字段或取值非法")
                es_citations = [c for c in verdict.citations if c['source'].startswith('es://')]
                ordinary = replace(verdict, citations=tuple(c for c in verdict.citations if not c['source'].startswith('es://')))
                # 保留生产文件资料核验；ES 引用独立回读，不能当 boundary 文本放行。
                failures = _verify_citations(ordinary, boundary['text']) if ordinary.citations or not es_citations else []
                if es_citations:
                    verifier = EsTools(es_catalog, receipts)
                    for citation in es_citations:
                        if not verifier.verify_quote(citation['source'][5:], citation['ref'], citation['note']):
                            failures.append("ES 引用回读核验失败")
                if failures:
                    raise ValueError("；".join(failures))
                return replace(verdict, tool_trail=tuple(receipts))
            except Exception as exc:
                last_error = str(exc)
                feedback = "上次输出未通过机械核验：" + last_error + "。请回读原文，引用必须逐字。"
                self._wait(attempt)
            finally:
                self.tool_calls += len(receipts)
        return CarrierError("text_carrier", "承载性判定重试耗尽", last_error)

    def _call_llm(
        self,
        expectation_text: str,
        boundary: Mapping[str, Any],
        receipts: list[dict[str, Any]],
        feedback: str = "",
    ) -> Mapping[str, Any]:
        # 与 TextCarrier._call_llm 逐行同构；差别只有 trace_id、记账与模型策略外壳（axe-v4 D9 / D12）。
        catalog = list(boundary.get("catalog") or [])
        tools = build_tools(catalog, receipts)
        client = axis_llm(
            self._spec,
            role="capability_carrier_mapper",
            tools=tools,
            tool_call_limit=_TOOL_CALL_LIMIT if tools else None,
        )
        system = _CARRIER_SYSTEM + (_CARRIER_TOOLS_GUIDE if tools else "")
        es_catalog = [item for item in catalog if item.get('source') == 'es']
        if es_catalog:
            system += "\nES 资料同样可作原文证据：source=es://索引，ref=文档ID#字段。使用 es_outline/es_search/es_read，note 逐字引用回读字段。"
        user = (
            f"未达成的期望：\n{expectation_text}\n\n"
            f"能力边界描述：\n{boundary['text']}"
            f"{_catalog_prompt([item for item in catalog if item.get('source') != 'es'])}"
            + ("\nES 目录：\n" + json.dumps(es_catalog, ensure_ascii=False) if es_catalog else "")
        )
        if feedback:
            user += f"\n\n{feedback}"
        try:
            return client.complete_json(
                system,
                user,
                trace_id=self._trace_id,
                reasoning_effort="low",
                output_spec=_verdict_output_spec(),
                stage="llm_probe_text_carrier",
            )
        finally:
            merge_usage(self.llm_usage, client.usage())


def _summary(report: Mapping[str, Any]) -> AxisSummary:
    """复制旧轴2的解释：一句话 = 报表"裁决"列的原文 carrier_text(report)；逐格 = 每条归位 + 理由。"""
    text = carrier_text(report)
    if not text:
        text = "轴1不是 not_fulfilled，无需归位" if report.get("applicable") is False else "无未达成期望需要归位"
    items: list[dict[str, Any]] = []
    for item in report.get("placements") or []:
        if not isinstance(item, Mapping):
            continue
        reason = str(item.get("reason") or "").strip()
        if item.get("gap_kind"):
            reason = f"{reason}；差在哪儿：{item['gap_kind']}".strip("；")
        if item.get("missing_material"):
            reason = f"{reason}；缺料：{item['missing_material']}".strip("；")
        items.append({
            "key": str(item.get("expectation_id") or ""),
            "value": str(item.get("placement") or ""),
            "reason": reason,
            "carry": str(item.get("carry") or ""),
        })
    for item in report.get("errors") or []:
        if not isinstance(item, Mapping):
            continue
        detail = str(item.get("last_error") or "").strip()
        reason = str(item.get("reason") or "归位失败").strip()
        items.append({
            "key": str(item.get("expectation_id") or ""),
            "value": "归位失败",
            "reason": f"{reason}：{detail}" if detail else reason,
        })
    return AxisSummary(text=text, items=items)


def run_carryability(inputs: Mapping[str, Any], axis: ScenarioAxis, runtime: AxisRuntime) -> RunOutcome:
    payload = dict(inputs["fulfillment"])
    carrier = BoxBoundaryCarrier(runtime.spec, axis.description, runtime)
    report = carrier.place(payload)
    usage = {"llm_calls": 0, **carrier.llm_usage, "tool_calls": carrier.tool_calls}
    if carrier.timed_out:
        usage["timed_out"] = True
    errors = list(report.get("errors") or [])
    summary = _summary(report)
    if errors:
        # 旧规则：任一条期望归位失败，整 run 标 error。这里落 status=failed，output 与已完成的逐格归位保留供诊断。
        return RunOutcome(output=report, summary=summary, failed=True, failure_reason=format_carrier_errors(errors), usage=usage)
    return RunOutcome(output=report, summary=summary, usage=usage)


AXIS_TYPE = AxisType(
    type_id="carryability",
    title="承载性",
    summary="对轴1未达成的 blocking 期望逐条判：受治理能力空间承载得了（做错了）还是承载不了（做不了）",
    verdict_scope=VERDICT_SCOPE_ITEM,
    verdict_enum=(
        Verdict(PLACEMENT_CANNOT, "能力边界资料自认承载不了；≠ 职责外"),
        Verdict(PLACEMENT_WRONG, "能力边界证实承载得了，但这次没做对"),
        Verdict(PLACEMENT_UNCLEAR, "承载性判不了；必带差在哪儿（口径分歧 / 空间未受治理）和缺料"),
    ),
    item_path="placements[].placement",
    depend_on=("fulfillment",),
    trigger_when=When(axis="fulfillment", verdict_in=("not_fulfilled",)),
    inputs=(Input("fulfillment", source="axis.fulfillment.output", fields=_INPUT_FIELDS),),
    output_fields=_OUTPUT_FIELDS,
    scenario_fields=(Field("description", required=True, expand="catalog"),),
    # 每条期望 ≤3 次重试（TextCarrier 默认）；每次调用工具上限与生产 TextCarrier 相同；seconds 先放宽只兜失控。
    limits=ExecutionLimits(llm_calls=None, tool_calls=_TOOL_CALL_LIMIT, seconds=600),
    run=run_carryability,
    implementation_files=(
        "impl/projects/llm_probe/eval_axes/adapters/carryability.py",
        "impl/projects/llm_probe/text_carrier.py",
        "impl/projects/llm_probe/material_tools.py",
        "impl/projects/llm_probe/eval_axes/sources/__init__.py",
        "impl/projects/llm_probe/eval_axes/sources/es_client.py",
        "impl/projects/llm_probe/eval_axes/sources/es_tools.py",
        "impl/core/capability_carrier.py",
    ),
)
