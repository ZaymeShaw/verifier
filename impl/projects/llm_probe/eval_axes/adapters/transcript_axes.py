"""llmtracing 的轴 adapter：对话稿的确定性分析与主轴材料（过程六轴暂不支持对话稿，见 process_common.run_process_axis）。

不再保留一次性 complete_json / 格式重试 / salvage 评判路线。
"""
from __future__ import annotations

from typing import Any, Mapping

from impl.projects.llm_probe.business_trace.providers.llmtracing import PROVIDER
from impl.projects.llm_probe.business_trace.providers.llmtracing_transcript import (
    build_transcript, is_transcript, render)
from ..types import AxisSummary, RunOutcome, ScenarioAxis

_EVIDENCE_BOUNDARY = """【证据边界】
只核对有证据的实际边界。工具调用参数不是工具原始产出；模型输入里的 tool 消息只证明模型收到了该内容，
不能单凭这一端证明业务工具产出到模型输入之间无损。传递无损需要传递前后两端，合理压缩与按契约隐藏不等于改义。
request/final 的含义以采集来源和应用边界为准：真实 HTTP 实收可证明 API 交付，不能证明最终 UI 已展示；
重放构造的 final、末次模型输出不能冒充独立的业务实收。没有记录的落库或内部步骤不要虚构。
不可见不等于未发生；not_applicable 要有范围与未发生的依据，不能用 gap 证明整条业务链没有该步骤。
只在判断确实需要不可见证据时记缺证；可见调用的正常行为照常判断，不把整轴一律判缺证。
把观察事实、潜在影响和根因假设分开。API 内容混杂不证明 UI 已展示，也不证明哪个组件解析失败。
业务契约决定重试、信息披露与交付要求；不把某个业务的政策当通用规则。没有判准是 contract_missing，
有判准但缺事实才是 insufficient_evidence；局部偏差不自动等于整体业务失败。"""


def transcript_snapshot(trace: Any, snapshot: Any) -> bool:
    """按快照识别 provider；所有快照都缺失时才按场景声明识别，避免把采集失败当未启用。"""
    snaps = [((r.get('project_fields') or {}).get('business_trace')) for r in getattr(trace, 'turn_records', None) or []]
    snaps.append(snapshot)
    providers = {s.get('provider') for s in snaps if isinstance(s, Mapping) and s.get('provider')}
    if providers:
        return providers == {PROVIDER}
    from impl.projects.llm_probe.capability import capability_business_trace

    request = trace.normalized_request if isinstance(getattr(trace, 'normalized_request', None), Mapping) else {}
    envelope = capability_business_trace(str(request.get('capability_ref') or '')) or {}
    return envelope.get('provider') == PROVIDER


def run_analysis(inputs: Mapping[str, Any], axis: ScenarioAxis, runtime: Any) -> RunOutcome:
    transcript = build_transcript(inputs['trace'], inputs.get('business_trace'))
    text = render(transcript)
    verdict = 'partial' if any(c['status'] in {'failed', 'partial'} for c in transcript['coverage']) else 'complete'
    turns = len(transcript['coverage'])
    return RunOutcome(
        output={'verdict': verdict, 'dossier': transcript, 'coverage': transcript['coverage'],
                'structure': {'route': [], 'suspects': [], 'coverage_note': 'llmtracing 对话稿：程序重建，未做结构分析'},
                'suspects': [], 'selections': {}, 'catalog_chars': len(text)},
        summary=AxisSummary(f"对话稿 {verdict}：{turns} 轮、{transcript['model_calls']} 次模型调用、"
                            f"{len(transcript['records'])} 个位置、{len(text)} 字；证据限制见 gap 条目", []),
        usage={'llm_calls': 0, 'transcript_chars': len(text)},
    )


def main_judge_material(transcript: Mapping[str, Any], budget_chars: int) -> dict[str, Any]:
    return {'kind': 'transcript', 'text': render(transcript, budget_chars=budget_chars),
            'reading_guide': '这是经模型中转记录的对话稿，按位置编号；gap 是不可见范围，截断处标出原长。'
                             + '\n\n' + _EVIDENCE_BOUNDARY,
            'final_sources': [{'id': r['id'], 'origin': r.get('origin', 'unverified_extracted_output')}
                              for r in transcript['records'] if r['kind'] == 'final']}


__all__ = ['main_judge_material', 'run_analysis', 'run_axis', 'transcript_snapshot', 'is_transcript']
