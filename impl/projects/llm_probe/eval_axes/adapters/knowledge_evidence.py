"""知识查证：收集各用知识的轴提的待查项，ToolLoop 到场景知识源取证，交出知识案卷；只取证，不判对错。

spec/alg/knowledge-evidence.md。待查项来源由各轴类型的 knowledge_items 声明，只收本次启用的轴。
"""
from __future__ import annotations

from typing import Any, Mapping

from impl.core.live_protocol import business_call_failure
from impl.core.tool_loop import LoopContext
from impl.projects.llm_probe.knowledge_loop.loop import FOUND, NOT_FOUND, SUBMIT, KnowledgeLoop, render_input
from ..llm import axis_llm
from ..sources import expand_sources
from ..sources.es_tools import EsTools
from ..types import (FAILURE_AXIS, AxisRequestFailed, AxisSummary, AxisType, ExecutionLimits, Field, Input, RunOutcome,
                     ScenarioAxis, Verdict)

SECONDS = 900


class _StepClient:
    """每次模型请求前后检查轴时间；端点失败归环境类失败。"""

    def __init__(self, client: Any, runtime: Any) -> None:
        self.client, self.runtime = client, runtime

    def complete_step(self, *args: Any, **kwargs: Any) -> Any:
        self.runtime.ensure_time_left('knowledge_evidence')
        try:
            result = self.client.complete_step(*args, **kwargs)
        except RuntimeError as exc:
            raise AxisRequestFailed('llm_request_failed', str(exc)) from exc
        self.runtime.ensure_time_left('knowledge_evidence')
        return result


def _outline(catalog):
    """ES 知识源的字段骨架随首条消息给模型。outline 出错直接抛：知识源不可用不该伪装成没找到。"""
    es_catalog = [c for c in catalog if c.get('source') == 'es']
    if not es_catalog:
        return []
    receipts: list[dict[str, Any]] = []
    tools = EsTools(es_catalog, receipts)
    outline = [tools.es_outline(c['uri'][len('es://'):]) for c in es_catalog]
    failed = [r['error'] for r in receipts if r.get('error')]
    if failed:
        raise ValueError('知识源 outline 失败：' + '；'.join(failed))
    return outline


def item_label(item: Mapping[str, Any]) -> str:
    """展示用：context 段已含在 text 里就不重复。"""
    extra = [c for c in item.get('context') or [] if c not in item['text']]
    return item['text'] if not extra else '·'.join(extra) + '：' + item['text']


def _producers(runtime):
    from ..registry import AXIS_TYPES
    enabled = set(getattr(runtime, 'enabled_axes', ()) or ())
    return [(t.type_id, t.knowledge_items) for t in AXIS_TYPES.values() if t.knowledge_items and t.type_id in enabled]


def _outcome(items, searches, catalog, usage):
    found = sum(i['status'] == FOUND for i in items)
    by_origin: dict[str, int] = {}
    for item in items:
        by_origin[item['origin']] = by_origin.get(item['origin'], 0) + 1
    coverage = {'items': len(items), FOUND: found, NOT_FOUND: len(items) - found, 'by_origin': by_origin}
    sources = [{'uri': c['uri'], 'snapshot_id': c.get('snapshot_id') or c.get('sha256', ''), 'notes': c.get('notes', '')} for c in catalog]
    output = {'items': items, 'searches': searches, 'sources': sources, 'coverage': coverage, 'errors': []}
    text = (f"待查 {len(items)} 条：找到相关原文 {found}，没找到 {len(items) - found}；知识源调用 {len(searches)} 次"
            if items else '没有待查项')
    rows = [{'key': item_label(i), 'value': i['status'], 'reason': i['note'], 'item_id': i['item_id']} for i in items]
    return RunOutcome(output=output, summary=AxisSummary(text, rows), usage=usage)


def run(inputs: Mapping[str, Any], axis: ScenarioAxis, runtime: Any) -> RunOutcome:
    trace = inputs['trace']
    failure = business_call_failure(trace)
    if failure:
        return RunOutcome(output={}, not_applicable='被测系统调用失败，没有答复可查证：' + failure[:300])
    description, catalog = expand_sources(axis.description, material_catalog=True)
    if not catalog:
        return RunOutcome(output={}, not_applicable='场景未声明知识源')
    producers = _producers(runtime)
    if not producers:
        return RunOutcome(output={}, not_applicable='没有启用需要知识依据的轴')
    usage: dict[str, Any] = {'llm_calls': 0, 'tool_calls': 0}
    items = []
    try:
        for origin, produce in producers:
            for item in produce(trace, runtime, usage):
                items.append({**item, 'item_id': f"{origin}:{item['item_id']}", 'origin': origin})
    except ValueError as exc:
        return RunOutcome(output={}, failed=True, usage=usage, failure_reason=f'{FAILURE_AXIS} 待查清单生成失败：{exc}')
    if not items:
        return _outcome([], [], catalog, usage)
    client = axis_llm(runtime.spec, role='truthfulness')
    client.reasoning_effort = 'low'
    question = (trace.normalized_request or {}).get('body') or {}
    try:
        knowledge = KnowledgeLoop(items, catalog, _StepClient(client, runtime), seconds=SECONDS, request=question)
    except ValueError as exc:
        # 缺身份字段、MCP 登记的工具不在服务里：查不了就明说，不换身份硬查。
        return RunOutcome(output={}, failed=True, usage=usage, failure_reason=f'{FAILURE_AXIS} 知识源不可用：{exc}')
    result = knowledge.loop.run(render_input(description, catalog, _outline(catalog), items, question), LoopContext(runtime.trace_id))
    extract_calls = usage['llm_calls']
    usage.update(client.usage())
    usage.update({'llm_calls': extract_calls + result.llm_calls, 'tool_calls': sum(c.tool != SUBMIT for c in result.calls),
                  'submissions': sum(c.tool == SUBMIT for c in result.calls), 'limits': knowledge.limits})
    if result.status != 'complete':
        # 不产出部分案卷：已接受的条数只作诊断，没交的条目不能变成"没找到"。
        denied = [c.denied for c in result.calls if c.tool == SUBMIT and c.denied and c.denied != result.reason]
        accepted = len(items) - len(knowledge.checklist.missing_from(result.calls))
        return RunOutcome(output={}, failed=True, usage=usage,
                          failure_reason=f'{FAILURE_AXIS} 查证未完成（已接受 {accepted}/{len(items)} 条）：{result.reason}'
                                         + (f'；最后一次被拒：{denied[-1][:300]}' if denied else ''))
    return _outcome(result.value['items'], result.value['searches'], catalog, usage)


AXIS_TYPE = AxisType(
    type_id='knowledge_evidence', title='知识查证', summary='针对各轴提的待查项到场景知识源取证，交出知识案卷，不判对错',
    verdict_scope='item', verdict_enum=(Verdict(FOUND, '知识源里有讲同一对象、同一事项的原文'), Verdict(NOT_FOUND, '查过了，知识源里没有相关原文')),
    item_path='items[].status', depend_on=(), trigger_when=None, inputs=(Input('trace', 'sample.trace'),),
    output_fields=('items', 'searches', 'sources', 'coverage', 'errors'),
    scenario_fields=(Field('description', required=True, expand='catalog'),),
    limits=ExecutionLimits(seconds=SECONDS), run=run,
)
