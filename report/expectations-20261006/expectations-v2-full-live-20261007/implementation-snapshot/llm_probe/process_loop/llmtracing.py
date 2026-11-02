"""llmtracing 六轴实例：共享 ToolLoop，自主取证、逐轴提交、拒绝反馈；不使用 Agno 环节表。"""
from __future__ import annotations

import json
import time
from typing import Any, Mapping

from impl.core.tool_loop import (
    BudgetStop, Call, Continue, DependsOn, History, Hook, LoopContext, RequireDone, ToolLoop,
    is_accepted, until_accepted)
from impl.projects.llm_probe.business_trace.providers.llmtracing_evidence import TranscriptEvidence
from impl.projects.llm_probe.business_trace.design_rules import transcript_blocks
from impl.projects.llm_probe.eval_axes.adapters.process_common import (
    AxisSpec, _outcome, annotate, project_obligations)
from impl.projects.llm_probe.eval_axes.adapters.process_output import (
    OUTPUT, UNIT_SYSTEM, UNIT_CONSUMER, build_units, validate_submission)
from impl.projects.llm_probe.eval_axes.adapters.process_protocol import issues_for, validate_issue_references
from impl.projects.llm_probe.eval_axes.adapters.transcript_axes import _EVIDENCE_BOUNDARY
from impl.projects.llm_probe.eval_axes.llm import axis_llm
from impl.projects.llm_probe.eval_axes.types import FAILURE_AXIS, FAILURE_ENVIRONMENT, RunOutcome
from impl.tools.protocol import VerifiableTool
from .expectation_projection import prepare, required_units, criteria_for
from .evaluation import validate_read_endpoints

TOOL_CALLS = 40
SECONDS = 1200
PREFIX = 'eval_'
SYSTEM = UNIT_SYSTEM + UNIT_CONSUMER + '\n' + _EVIDENCE_BOUNDARY + """
【本次 llmtracing ToolLoop 执行方式】
每轴 briefing 给程序枚举的 units、criteria、original_blocks、links 与 obligations；每次 response 的每条模型义务必须检查。
original_blocks 是已交付完整原文，evidence/reference_catalog 只是目录；运行端点须用 evidence_read 读取，长条目按 next_offset 补齐。
原文块不能冒充其所在运行记录的完整正文。同一批 read 与 submit 不算先读后引，下一批才有回执。
每轴用 eval_<axis> 提交 reason/scope_note/units/problems。不得自造位置、端点或判准，不存在 transcript 占位替换规则。
pass/fail 必须读齐单位必要输入输出；缺端点要明确缺证，不能过滤未读端后凭另一端判通过。
model_capability 只比较该次实际输入与自己的 response；用 call_inputs 核对真实输入成员，不能按先后关系猜继承。
工具调用参数不是工具原始返回。实收 tool 消息仅证明模型收到了数据，不能证明工具执行成功或传递无损。
input_invalid 必须先获得已定位上游问题的 accepted 回执；同批提交互不可见，不得猜 problem_id。
expectation_sources 是需求出处；source_to_evidence 只给候选目录位置，不是读取回执。
各轴独立取证可并列；所有启用轴 accepted 才结束。被拒后修复具体错误，不删除真实问题。
"""

PARAMETERS = OUTPUT.json_schema()
for key, description in {'reason': '本轴结论理由', 'scope_note': '已检查范围与不可见边界',
                         'units': '逐单位判准核对与原文块标注', 'problems': '独立问题及判准引用'}.items():
    PARAMETERS['properties'][key]['description'] = description


class StepMeter:
    """实例级计数与时间检查，不改公共 AxisLlm / complete_step。每个 loop 独立持有。"""
    def __init__(self, client: Any, seconds: float):
        self.client = client
        self.deadline = time.monotonic() + seconds
        self.calls = 0

    def complete_step(self, *args, **kwargs):
        if time.monotonic() >= self.deadline:
            raise TimeoutError('llmtracing loop deadline')
        self.calls += 1
        result = self.client.complete_step(*args, **kwargs)
        if time.monotonic() >= self.deadline:
            raise TimeoutError('llmtracing loop deadline')
        return result

    def usage(self):
        get_usage = getattr(self.client, 'usage', None)
        return {**(get_usage() if get_usage else {}), 'llm_calls': self.calls}


class EvidenceReceipts(Hook):
    """辅助 post_batch hook：批尾记录回执，供下一批提交使用。"""
    def __init__(self, evidence: TranscriptEvidence):
        self.evidence = evidence
        self.readable: set[str] = set()
        self.calls: list[Call] = []
        self.issues: list[dict] = []

    def post_batch(self, history: History, calls):
        self.readable = self.evidence.read_ids
        self.calls = list(history.calls)
        self.issues = [p for c in history.calls if c.ok and is_accepted(c) and isinstance(c.result, Mapping)
                       for p in c.result.get('issues', [])]
        return ()


class SixAxesCompleted(RequireDone):
    """本实例的核心完成 hook；复用框架完成谓词，只丰富未完成反馈与审计。"""
    def __init__(self, axes):
        super().__init__([PREFIX + axis for axis in axes])
        self.checks: list[dict[str, Any]] = []

    def ready_to_finish(self, history: History):
        return all(any(c.ok and is_accepted(c) for c in history.of(tool)) for tool in self.tools)

    def stop(self, history: History, blocked: int):
        decision = super().stop(history, blocked)
        accepted = [tool for tool in self.tools if any(c.ok and is_accepted(c) for c in history.of(tool))]
        if isinstance(decision, Continue):
            notes = [decision.reason]
            if accepted:
                notes.append('已接受的提交：' + ', '.join(accepted))
            for tool in self.tools:
                if tool in accepted:
                    continue
                attempts = history.of(tool)
                if attempts:
                    last = attempts[-1]
                    result = last.result if isinstance(last.result, Mapping) else {}
                    reason = last.error or last.denied or result.get('error') or '提交未被接受'
                    notes.append(f'{tool} 最近未接受原因：{str(reason)[:1200]}')
            decision = Continue('\n'.join(notes))
        self.checks.append({'decision': type(decision).__name__.lower(), 'blocked': blocked,
                            'reason': decision.reason if isinstance(decision, Continue) else '',
                            'accepted_tools': accepted})
        return decision


class TranscriptEvaluation:
    def __init__(self, transcript: Mapping[str, Any], specs: Mapping[str, AxisSpec],
                 entry: Mapping[str, Any] | None, client: Any, *, expectations: Mapping[str, Any], projection: Mapping[str, Any], trace_id: str,
                 tool_calls: int = TOOL_CALLS, seconds: float = SECONDS):
        self.transcript, self.specs = transcript, specs
        self.expectations, self.projection = expectations, projection
        self.required = {axis: required_units(axis, expectations, projection) for axis in specs}
        self.obligations = {axis: {ob.obligation_id: ob for ob in spec.obligations + project_obligations(entry, axis)}
                            for axis, spec in specs.items()}
        self.evidence = TranscriptEvidence(transcript)
        self.links = {axis: {link['link_id']: link for link in
                      [*self.evidence.runtime_links(axis, self.obligations[axis]), *self.required[axis]]} for axis in specs}
        self.units, self.criteria, self.blocks = {}, {}, {}
        for axis in specs:
            pairs = [(ob, link_id) for link_id, link in self.links[axis].items()
                     for ob in self.obligations[axis] if ob in link['obligation_ids']]
            criteria = criteria_for(pairs, self.links[axis], self.obligations[axis])
            self.units[axis], self.criteria[axis], self.blocks[axis] = build_units(
                pairs, criteria, self.links[axis], transcript_blocks(transcript, list(self.links[axis].values()), axis))
        self.meter = StepMeter(client, seconds)
        self.trace_id = trace_id
        names = [PREFIX + axis for axis in specs]
        # 核心完成条件独立传入框架；辅助 hook 仅绑定声明的事件。
        self.completion_hook = SixAxesCompleted(specs)
        self.pre_tool_hook = DependsOn({name: until_accepted() for name in names})
        self.post_batch_hook = EvidenceReceipts(self.evidence)
        self.submitted: dict[str, list[dict]] = {}
        tools = self.evidence.tools() + [VerifiableTool(
            tool_id=PREFIX + axis, description=f'提交 {axis}；只传 reason/scope_note/units/problems，逐单位核对判准与原文块。',
            parameters=PARAMETERS, execute_fn=self._submitter(axis)) for axis in specs]
        self.loop = ToolLoop('llmtracing_evaluation', SYSTEM, tools, self.meter,
                             completion_hook=self.completion_hook,
                             hooks={'pre_tool': [self.pre_tool_hook], 'post_batch': [self.post_batch_hook]},
                             end=self._finish, budget=BudgetStop(tool_calls=tool_calls, seconds=seconds))

    def _submitter(self, axis):
        def submit(**payload):
            if axis in self.submitted:
                return {'accepted': False, 'error': '该轴已经被接受，不能覆盖已接受提交'}
            try:
                readable = self.post_batch_hook.readable
                results = validate_submission(payload, self.units[axis], self.criteria[axis], self.links[axis], readable,
                    axis_id=axis, obligations=self.obligations[axis], expectations=self.expectations,
                    required=self.required[axis], blocks=self.blocks[axis], recorded_issues=self.post_batch_hook.issues)
                validate_read_endpoints(results, self.links[axis], readable)
                design_refs = frozenset(c['criterion_ref'] for r in results for c in r['criterion_checks'] if c.get('quotes'))
                errors = self.evidence.validate(results, self.obligations[axis], readable,
                                                expectations=self.expectations, design_refs=design_refs)
                if errors:
                    return {'accepted': False, 'error': '\n'.join(errors[:12])}
            except (ValueError, KeyError, TypeError) as exc:
                return {'accepted': False, 'error': str(exc)[:2000]}
            self.submitted[axis] = results
            return {'accepted': True, 'issues': issues_for(axis, results)}
        return submit

    def _finish(self, history: History) -> dict[str, RunOutcome]:
        """仅由框架在完成检查通过后调用；提取被接受提交，不采用最后一句自然语言作结果。"""
        outcomes = {}
        for axis in self.specs:
            accepted = next(c for c in history.of(PREFIX + axis) if c.ok and is_accepted(c))
            results = self.submitted[axis]
            annotate(results, self.obligations[axis], self.links[axis], self.evidence.read_ids,
                     accepted.args['scope_note'], program_evidence=True)
            outcome = _outcome(results, self.obligations[axis], accepted.args['reason'], accepted.args['scope_note'],
                               self.transcript['coverage'], {}, axis_id=axis)
            outcome.output['selection'] = {'refs': [], 'why': []}
            outcome.output['view'] = {'kind': 'transcript', 'execution': 'tool_loop',
                                      'evidence_audit': {'reads': self.evidence.receipts},
                                      'unverified_refs': [], 'excluded': []}
            outcomes[axis] = outcome
        validate_issue_references({axis: outcome.output for axis, outcome in outcomes.items()})
        return outcomes

    def run(self) -> dict[str, RunOutcome]:
        started = time.monotonic()
        briefings = [{'axis': axis, 'question': spec.question, 'excludes': spec.excludes,
                      'units': self.units[axis], 'criteria': self.criteria[axis],
                      'original_blocks': self.blocks[axis], 'links': list(self.links[axis].values()),
                      'expectation_units': self.required[axis],
                      'obligations': [{'obligation_id': ob.obligation_id, 'link_type': ob.link_type,
                                       'situation': ob.situation, 'duty': ob.duty, 'source': ob.source}
                                      for ob in self.obligations[axis].values()]}
                     for axis, spec in self.specs.items()]
        catalog_ids = set(self.evidence.records)
        cited = {ref.removeprefix('expectation:') for table in self.criteria.values()
                 for ref in table.values() if ref.startswith('expectation:')}
        expectations = [e for e in self.expectations['expectations'] if e['expectation_id'] in cited]
        source_ids = {r for e in expectations for r in e['source_refs']}
        sources = [s for s in self.expectations['sources'] if s['id'] in source_ids]
        source_to_evidence = {source['id']: [ref for ref in source.get('trace_refs', []) if ref in catalog_ids]
                              for source in sources}
        prompt = json.dumps({'expectations': expectations, 'expectation_sources': sources,
                             'source_to_evidence': source_to_evidence,
                             'axes': briefings, 'evidence': self.evidence.catalog(),
                             'coverage': self.transcript['coverage']}, ensure_ascii=False)
        failure, calls, segments = '', [], 0
        outcomes = {}
        try:
            result = self.loop.run(prompt, LoopContext(trace_id=self.trace_id))
            calls, segments = result.calls, result.segments
            if result.status != 'complete':
                failure = f'{FAILURE_AXIS} {result.reason}'
            else:
                outcomes = result.value
        except ValueError as exc:
            calls = self.post_batch_hook.calls
            failure = f'{FAILURE_AXIS} {exc}'
        except Exception as exc:
            calls = self.post_batch_hook.calls
            failure = f'{FAILURE_ENVIRONMENT} {type(exc).__name__}: {exc}'
        audit = [{'tool': c.tool, 'batch': c.batch, 'denied': c.denied, 'error': c.error,
                  'result': c.result if c.tool.startswith(PREFIX) else None} for c in calls]
        usage = {**self.meter.usage(), 'tool_calls': len(calls), 'segments': segments,
                 'limits': {'tool_calls': self.loop.budget.tool_calls, 'seconds': self.loop.budget.seconds,
                            'max_blocked': self.loop.max_blocked},
                 'elapsed_ms': round((time.monotonic() - started) * 1000)}
        checks = list(self.completion_hook.checks)
        for i, axis in enumerate(self.specs):
            # 框架已完成结果提取；这里只附运行记账，不驱动重试或重新作业务判定。
            axis_usage = usage if i == 0 else {'llm_calls': 0, 'shared_usage_axis': next(iter(self.specs))}
            if failure:
                outcomes[axis] = RunOutcome(output={}, failed=True, failure_reason=failure,
                    usage={**axis_usage, 'loop_calls': audit, 'completion_checks': checks})
            else:
                outcomes[axis].usage = axis_usage
                outcomes[axis].output['view'].update(loop_calls=audit, completion_checks=checks)
        return outcomes


def run_evaluation(transcript, specs, entry, project_spec, *, expectations, trace_id):
    client = axis_llm(project_spec, role='judge')
    evidence = TranscriptEvidence(transcript)
    first_calls = {}
    for row in evidence.records.values():
        if row['kind'] == 'call':
            first_calls.setdefault(row['id'].split('.')[0], row['id'])
    links = [{'link_id': ref, 'input': [{'ref': ref, 'field': ''}], 'output': []}
             for ref in first_calls.values()]
    projection = prepare(expectations, client, trace_id,
                         tools=[b for b in transcript_blocks(transcript, links, 'planning_routing') if b['component'] == 'tools'])
    projection_usage = client.usage()
    result = TranscriptEvaluation(transcript, specs, entry, client, expectations=expectations,
                                  projection=projection, trace_id=trace_id).run()
    if result:
        usage = next(iter(result.values())).usage
        usage['projection_llm_calls'] = projection_usage.get('llm_calls', 0)
        usage['llm_calls'] += projection_usage.get('llm_calls', 0)
    return result
