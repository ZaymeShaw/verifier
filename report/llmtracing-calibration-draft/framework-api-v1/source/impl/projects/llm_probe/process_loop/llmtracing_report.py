"""llmtracing ToolLoop 的项目报告 adapter；保持现有 AxisResult，不替换公共 runner。"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Sequence

from impl.core.schema.base import now_iso
from impl.projects.llm_probe.eval_axes.adapters.process_common import PROCESS_SPECS, _scenario_entry
from impl.projects.llm_probe.eval_axes.adapters.transcript_axes import run_analysis
from impl.projects.llm_probe.eval_axes.registry import get_axis_type
from impl.projects.llm_probe.eval_axes.runner import config_fingerprint
from impl.projects.llm_probe.eval_axes.types import (
    AxisResult, AxisRuntime, FAILURE_ENVIRONMENT, FAILURE_MATERIAL, RunOutcome, ScenarioAxis)
from impl.core.materials_store import expand_material_uris
from .llmtracing import run_evaluation

ROOT = Path(__file__).resolve().parents[4]
FILES = (
    'impl/core/tool_loop.py',
    'impl/projects/llm_probe/process_loop/llmtracing.py',
    'impl/projects/llm_probe/process_loop/llmtracing_report.py',
    'impl/projects/llm_probe/business_trace/providers/llmtracing_transcript.py',
    'impl/projects/llm_probe/business_trace/providers/llmtracing_evidence.py',
    'impl/projects/llm_probe/business_trace/providers/llmtracing.py',
    'impl/projects/llm_probe/eval_axes/adapters/transcript_axes.py',
    'impl/projects/llm_probe/eval_axes/adapters/process_common.py',
)


def _fingerprint(axis_id):
    files = (*FILES, f'impl/projects/llm_probe/eval_axes/adapters/{axis_id}.py')
    digest = hashlib.sha256()
    for name in dict.fromkeys(files):
        digest.update(name.encode())
        digest.update((ROOT / name).read_bytes())
    return digest.hexdigest()


def _result(axis, runtime, outcome, started, *, blocked=False):
    kind = get_axis_type(axis.type_id)
    failed = outcome.failed
    if not failed and (set(outcome.output) != set(kind.output_fields) or outcome.summary is None):
        raise ValueError(f'{axis.type_id}: ToolLoop 输出不符合现有轴协议')
    verdict = None if failed else (outcome.output.get('verdict') if axis.type_id == 'trace_analysis'
                                   else outcome.output['assessment']['verdict'])
    if not failed and verdict not in kind.verdict_values:
        raise ValueError(f'{axis.type_id}: 非法 verdict {verdict!r}')
    return AxisResult(
        run_id=runtime.run_id, case_id=runtime.case_id, scenario_id=runtime.scenario_id,
        axis_id=axis.type_id, type_id=axis.type_id, verdict_scope=kind.verdict_scope, title=kind.title,
        status='blocked' if blocked else ('failed' if failed else 'succeeded'),
        verdict=verdict, verdict_description=kind.verdict_description(verdict),
        summary={'text': outcome.failure_reason, 'items': []} if failed else outcome.summary.as_dict(),
        output=None if failed else outcome.output, usage=outcome.usage,
        config_fingerprint=config_fingerprint(axis), implementation_fingerprint=_fingerprint(axis.type_id),
        execution_trace_ref=runtime.trace_id, started_at=started, finished_at=now_iso(),
        error=outcome.failure_reason if failed else '',
        trigger_decision={'depend_on_satisfied': not blocked, 'execution': 'llmtracing_tool_loop'},
        inputs_used={'trace': f'sample.trace@{runtime.trace_id}'},
    ).as_dict()


def build_loop_results(spec: Any, trace: Any, axes: Sequence[ScenarioAxis], *, scenario_id: str, run_id: str):
    """一个case只运行一次共享六轴loop；分析失败不启动loop；loop失败不返回部分轴结论。"""
    runtime = AxisRuntime(spec=spec, run_id=run_id, trace_id=f'{run_id}:{trace.trace_id}',
                          case_id=str(trace.case_id or ''), scenario_id=scenario_id,
                          enabled_axes=tuple(a.type_id for a in axes if a.enabled))
    started = now_iso()
    analysis_axis = next(a for a in axes if a.type_id == 'trace_analysis')
    analysis = run_analysis({'trace': trace, 'business_trace': (trace.project_fields or {}).get('business_trace')},
                            analysis_axis, runtime)
    transcript = analysis.output['dossier']
    if any(c.get('status') == 'failed' for c in transcript['coverage']):
        analysis.failed = True
        analysis.failure_reason = f'{FAILURE_MATERIAL} 业务 Trace 缺失或采集失败'
    results = [_result(analysis_axis, runtime, analysis, started)]
    process_axes = [a for a in axes if a.type_id != 'trace_analysis' and a.enabled]
    if analysis.failed:
        failed = RunOutcome({}, failed=True, failure_reason=analysis.failure_reason, usage={'llm_calls': 0})
        return results + [_result(a, runtime, failed, started, blocked=True) for a in process_axes]
    try:
        outcomes = run_evaluation(transcript, {a.type_id: PROCESS_SPECS[a.type_id] for a in process_axes},
            {a.type_id: expand_material_uris(a.description) for a in process_axes},
            _scenario_entry(runtime), spec, trace_id=runtime.trace_id)
    except Exception as exc:
        failure = RunOutcome({}, failed=True, failure_reason=f'{FAILURE_ENVIRONMENT} {type(exc).__name__}: {exc}')
        outcomes = {a.type_id: failure for a in process_axes}
    return results + [_result(a, runtime, outcomes[a.type_id], started) for a in process_axes]
