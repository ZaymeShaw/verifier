"""轴类型 carryability：主轴的系统能力部分（承载性归位，spec/alg/capability_carrier.md）。

继承 ``TextCarrier``：门控、逐 blocking NF 期望循环、归位映射、重试复用 ``place()``（协议锁定，不可覆盖）。
边界输入分两路（§6.1 文本形态）：
- 依据：业务方登记的责任范围（框里 ``{boundary://项目/资料id}``）、知识源查询回执——可作自认、可引用，程序回读核验；
- 背景：框里其余文字（系统自己的能力描述等）——只帮助理解期望，不能作依据，引用它会被打回。

输入是 fulfillment 输出的几个字段，加本样本的请求体：请求体只交给 MCP 工具按信息源登记取身份去查，
不进模型上下文；承载性不看这次交付了什么（capability_carrier.md §5 第 6 条）。
"""
from __future__ import annotations

from typing import Any, Mapping
from dataclasses import replace
import json
import hashlib

from impl.core.judge import BUSINESS_CALL_FAILED
from impl.core.capability_carrier import (
    CARRY_NO,
    CARRY_UNDECIDABLE,
    PLACEMENT_CANNOT,
    PLACEMENT_UNCLEAR,
    PLACEMENT_WRONG,
    RECOG_RESPONSIBILITY,
    RECOG_SOURCE_ABSENT,
    carrier_text,
    format_carrier_errors,
)
from ..sources import expand_boundary, expand_sources, build_tools
from impl.projects.llm_probe.text_carrier import (
    _CARRIER_TOOLS_GUIDE,
    TextCarrier,
    _TOOL_CALL_LIMIT,
    _catalog_prompt,
    _verdict_output_spec,
    _parse_verdict,
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
_INPUT_FIELDS = ("overall_fulfillment", "business_expectations", "fulfillment_assessments", "evidence")

_SYSTEM = """你是承载性判定器。给你一条用户要的、这次没给到的期望。只判断：被测系统各部分（智能体、工具、数据、下游服务）都正常工作时，这条期望要的结果给得出还是给不出。

依据只有两种，都可以引用：
- 责任范围登记：业务方登记的事实（没有哪类数据、不接哪类系统、哪些要求不由本系统负责）。引用时 source 填它的 boundary:// uri，ref 填 boundary，note 逐字摘自登记原文。
- 信息源查询回执：用工具查到的被测系统数据、知识库原文（格式见下）。
背景是场景里对系统的描述（系统自己说能做什么、该怎么做），只帮助理解期望说的是什么，不能作依据，不能引用。

carry 只能是 yes / no / undecidable：
- no：依据表明给不出——责任范围登记写明这条落在系统之外，或信息源按该对象查过、读全了确实没有。self_recognition 逐字摘那段原文，并放进 citations。
- yes：依据表明给得出——如信息源里查到了这条期望要的数据。citations 引用它。
- undecidable：依据不足以判定；gap_kind 取「口径分歧」或「空间未受治理」，missing_material 写缺什么资料才能判。
查询报错、查回别的对象、没读全都不算查实没有；数据在，就是给得出。不看这次交付，不看被测系统说了什么。
"""


class BoxBoundaryCarrier(TextCarrier):
    """边界来自场景轴的描述：责任范围登记与知识源回执是依据，其余文字是背景。"""

    def __init__(self, spec: Any, description: str, runtime: AxisRuntime, request_body: Any = None) -> None:
        super().__init__(spec=spec)
        # 只交给 MCP 工具按信息源登记的 {request.<字段>} 取身份，不进模型上下文（承载性不看交付，见 capability_carrier.md §1）。
        self._request_body = request_body
        background, self._registrations = expand_boundary(description)
        text, catalog = expand_sources(background)
        self._box_text = str(text or "").strip()
        self._box_catalog = [dict(item) for item in catalog]
        self._runtime = runtime
        self._trace_id = runtime.trace_id
        self.tool_calls = 0
        self.timed_out = False
        # 逐条期望、逐次重试的模型调用记账合并在这里（llm_calls / llm_model / llm_endpoint …）。
        self.llm_usage: dict[str, Any] = {}

    def _current_boundary(self) -> dict[str, Any]:
        return {"text": self._box_text, "catalog": [dict(item) for item in self._box_catalog],
                "registrations": [dict(item) for item in self._registrations]}

    def snapshot_revision(self) -> str:
        es_snapshots = [item['snapshot_id'] for item in self._box_catalog if item.get('source') == 'es']
        registered = [hashlib.sha256(item['content'].encode()).hexdigest() for item in self._registrations]
        revision = super().snapshot_revision()
        extra = es_snapshots + registered
        return hashlib.sha256((revision + '|'.join(extra)).encode()).hexdigest()[:16] if extra else revision

    def _judge_with_retry(self, expectation_text, boundary):
        from ..sources.es_tools import EsTools
        from impl.projects.llm_probe.material_tools import quote_in_text
        es_catalog = [item for item in boundary['catalog'] if item.get('source') == 'es']
        registered = {item['uri']: item['content'] for item in boundary.get('registrations') or []}
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
                failures = []
                if verdict.carry != CARRY_UNDECIDABLE and not verdict.citations:
                    failures.append("carry=yes/no 必须引用责任范围登记或信息源查询回执")
                es_citations = []
                for citation in verdict.citations:
                    source, note = citation['source'], citation['note']
                    if source.startswith('boundary://'):
                        if source not in registered or not quote_in_text(note, registered[source]):
                            failures.append(f"责任范围登记引用回读核验失败：{source}")
                    elif source.startswith('mcp://'):
                        # 信息源查询回执：引句须逐字出自这次实际返回的原文（ref = 工具给的翻页句柄）。
                        # 报错的返回不算：查询失败不能当"查实没有"的证据。
                        returned = next((r.get('response_text') for r in receipts
                                         if r.get('page_id') == citation['ref'] and not r.get('error')), None)
                        if returned is None or not quote_in_text(note, returned):
                            failures.append(f"MCP 引用回读核验失败：{citation['ref']}")
                    elif source.startswith('es://'):
                        es_citations.append(citation)
                    else:
                        failures.append(f"{source} 不是依据：只能引用责任范围登记（boundary://）或信息源查询回执；"
                                        "场景描述里系统自己的说明是背景，不能作依据")
                if es_citations:
                    verifier = EsTools(es_catalog, receipts)
                    for citation in es_citations:
                        if not verifier.verify_quote(citation['source'][5:], citation['ref'], citation['note']):
                            failures.append("ES 引用回读核验失败")
                if failures:
                    raise ValueError("；".join(failures))
                if verdict.carry == CARRY_NO:
                    by_registration = any(c['source'].startswith('boundary://') for c in verdict.citations)
                    verdict = replace(verdict, recognition=RECOG_RESPONSIBILITY if by_registration else RECOG_SOURCE_ABSENT)
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
        catalog = list(boundary.get("catalog") or [])
        tools = build_tools(catalog, receipts, self._request_body)
        client = axis_llm(
            self._spec,
            role="capability_carrier_mapper",
            tools=tools,
            tool_call_limit=_TOOL_CALL_LIMIT if tools else None,
        )
        system = _SYSTEM + (_CARRIER_TOOLS_GUIDE if tools else "")
        es_catalog = [item for item in catalog if item.get('source') == 'es']
        mcp_catalog = [item for item in catalog if item.get('source') == 'mcp']
        if es_catalog:
            system += "\nES 回执引用格式：source=es://<知识源名>/<索引>，ref=文档ID#字段，note 逐字引用回读字段。使用 es_outline/es_search/es_read。"
        if mcp_catalog:
            system += "\nMCP 回执引用格式：source=mcp://<知识源名>，ref=工具返回的翻页句柄（mcp://<知识源名>#序号，原样复制），note 逐字摘自该次返回原文。"
        registrations = boundary.get("registrations") or []
        user = (
            f"未达成的期望：\n{expectation_text}\n\n"
            "## 依据：责任范围登记\n"
            + ("\n\n".join(f"### {item['uri']}（{item['title']}）\n{item['content']}" for item in registrations)
               if registrations else "（本场景没有登记责任范围）")
            + f"\n\n## 背景（不能作依据）\n{boundary['text']}"
            + _catalog_prompt([item for item in catalog if item.get('source') not in ('es', 'mcp')])
            + ("\nES 目录：\n" + json.dumps(es_catalog, ensure_ascii=False) if es_catalog else "")
            + ("\nMCP 信息源：\n" + json.dumps(mcp_catalog, ensure_ascii=False) if mcp_catalog else "")
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
    if BUSINESS_CALL_FAILED in (payload.get("evidence") or []):
        return RunOutcome(output={}, not_applicable="被测系统调用失败，没有答复，不判承载")
    carrier = BoxBoundaryCarrier(runtime.spec, axis.description, runtime, inputs.get("request_body"))
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
    summary="对没给到的 blocking 期望逐条判：依据（责任范围登记、信息源回执）表明给得出（做错了）还是给不出（做不了）",
    verdict_scope=VERDICT_SCOPE_ITEM,
    verdict_enum=(
        Verdict(PLACEMENT_CANNOT, "依据表明系统正常工作时也给不出：责任范围登记在系统之外，或信息源查实本来没有"),
        Verdict(PLACEMENT_WRONG, "依据表明给得出，但这次没给到"),
        Verdict(PLACEMENT_UNCLEAR, "承载性判不了；必带差在哪儿（口径分歧 / 空间未受治理）和缺料"),
    ),
    item_path="placements[].placement",
    depend_on=("fulfillment",),
    trigger_when=When(axis="fulfillment", verdict_in=("not_fulfilled",)),
    inputs=(Input("fulfillment", source="axis.fulfillment.output", fields=_INPUT_FIELDS),
            Input("request_body", source="sample.request_body", required=False)),
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
