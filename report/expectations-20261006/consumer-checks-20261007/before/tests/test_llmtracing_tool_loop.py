"""llmtracing adapter + 真实 ToolLoop 的离线回归；脚本模型不调用外部服务。"""
import copy
import json
from types import SimpleNamespace

from tests.support.expectations import E, PROJECTION

import pytest

from impl.core.tool_loop import Step
from impl.core.schema import RunTrace
from impl.projects.llm_probe.business_trace.providers.llmtracing_transcript import build_transcript
from impl.projects.llm_probe.business_trace.providers.llmtracing_evidence import TranscriptEvidence, READ_CHARS
from impl.projects.llm_probe.eval_axes import registry, build_report
from impl.projects.llm_probe.eval_axes.adapters import process_common as common
from impl.projects.llm_probe.eval_axes.types import ScenarioAxis
from impl.projects.llm_probe.process_loop import llmtracing as loop_module
from impl.projects.llm_probe.process_loop.llmtracing import TranscriptEvaluation


def make_trace(provider='llmtracing'):
    system = {'role': 'system', 'content': 'Only report known device state.'}
    user = {'role': 'user', 'content': 'Check device A.'}
    response = {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': 'tool-1', 'type': 'function', 'function': {'name': 'lookup', 'arguments': '{}'}}]}
    result = {'role': 'tool', 'tool_call_id': 'tool-1', 'content': 'state unknown'}
    calls = [{'call_id': 'a', 'pre': {'protocol': 'chat_completions', 'messages': [system, user]},
              'outcome': {'event': 'success', 'response': {'choices': [{'message': response}]}}},
             {'call_id': 'b', 'pre': {'protocol': 'chat_completions', 'messages': [system, user, response, result]},
              'outcome': {'event': 'success', 'response': {'choices': [{'message': {
                  'role': 'assistant', 'content': 'state unknown'}}]}}}]
    snapshot = {'provider': provider, 'status': 'succeeded', 'records': {'calls': calls}}
    return RunTrace(trace_id='local-case', project_id='llm_probe', case_id='case',
                    normalized_request={'capability_ref': 'insurance-llmtracing'},
                    raw_response={'answer': 'state unknown'}, extracted_output={'output_text': 'state unknown'},
                    project_fields={'business_trace': snapshot})


def material():
    t = make_trace()
    return build_transcript(t, t.project_fields['business_trace'])


class ScriptClient:
    def __init__(self, script):
        self.script = iter(script)
        self.requests = []

    def complete_step(self, messages, functions, **kwargs):
        self.requests.append(copy.deepcopy(messages))
        item = next(self.script)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, str):
            return Step({'role': 'assistant', 'content': item})
        return Step({'role': 'assistant', 'tool_calls': [
            {'id': f'c{len(self.requests)}-{i}', 'type': 'function',
             'function': {'name': name, 'arguments': json.dumps(args)}} for i, (name, args) in enumerate(item)]})

    def usage(self):
        return {'llm_calls': 0}  # 实例必须自行计 complete_step，不能把这个0当真


def payload(axis, outcome='insufficient_evidence', refs=('t1.request',)):
    return {'reason': 'Evidence is incomplete', 'scope_note': 'visible request only', 'results': [
        {'obligation_id': ob.obligation_id, 'link_ids': ['t1.c1.response', 't1.c2.response'] if axis == 'model_capability' else ['t1.c2.response'], 'outcome': outcome,
         'expectation_ids': [], 'matched_link_id': '', 'expectation_checks': [], 'observed': 'No independent upstream result',
         'source_refs': ['case'] if ob.source in {'trace', 'case'} else [],
         'input_refs': list(refs), 'output_refs': [], 'missing': ['original result']}
        for ob in common.PROCESS_SPECS[axis].obligations]}


def evaluation(client, axes=('context_memory',), **kwargs):
    return TranscriptEvaluation(material(), {a: common.PROCESS_SPECS[a] for a in axes},
                                {a: 'device-service contract' for a in axes}, None, client,
                                trace_id='test-loop', expectations=E, projection=PROJECTION, **kwargs)


def test_wrong_transfer_proof_rejected_then_model_can_submit_honest_gap():
    bad = payload('context_memory')
    bad['results'][0].update(link_ids=['t1.c2.m4'], outcome='pass', input_refs=['t1.c1.response'],
                             output_refs=['t1.c2.m4'], missing=[])
    good = copy.deepcopy(bad)
    good['results'][0].update(outcome='insufficient_evidence', missing=['tool-side original output'])
    ids = ['t1.request', 't1.c1.response', 't1.c2.m4']
    client = ScriptClient([[('evidence_read', {'ids': ids})], [('eval_context_memory', bad)],
                           'done early', [('eval_context_memory', good)], 'done'])
    result = evaluation(client).run()['context_memory']
    assert not result.failed
    assert result.output['assessment']['verdict'] == 'not_evaluable'
    audit = result.output['view']['loop_calls']
    assert audit[1]['result']['accepted'] is False
    assert '工具调用参数不是传递前的产出' in audit[1]['result']['error']
    assert '以下调用尚未被接受' in client.requests[3][-1]['content']
    assert result.usage['llm_calls'] == 4
    assert result.output['results'][0]['missing'] == ['tool-side original output']


def test_read_and_submit_in_same_batch_does_not_prove_model_has_read_result():
    p = payload('intent_understanding')
    client = ScriptClient([[('evidence_read', {'ids': ['t1.request']}), ('eval_intent_understanding', p)],
                           [('eval_intent_understanding', p)], 'done'])
    out = evaluation(client, ('intent_understanding',)).run()['intent_understanding']
    calls = out.output['view']['loop_calls']
    assert calls[1]['result']['accepted'] is False
    assert '此前批次' in calls[1]['result']['error']
    assert calls[2]['result']['accepted'] is True


def test_shared_six_axes_loop_counts_calls_once_and_requires_all_submissions():
    axes = tuple(common.PROCESS_SPECS)
    p = [(f'eval_{a}', payload(a)) for a in axes]
    client = ScriptClient([[('evidence_read', {'ids': ['t1.request']})], p, 'done'])
    result = evaluation(client, axes).run()
    assert set(result) == set(axes)
    assert all(not o.failed for o in result.values())
    assert sum(o.usage['llm_calls'] for o in result.values()) == 2
    assert len(client.requests) == 2
    assert all(set(o.output) == set(registry.AXIS_TYPES[a].output_fields) for a, o in result.items())


def test_budget_failure_does_not_salvage_or_keep_partial_axes():
    p = payload('intent_understanding')
    client = ScriptClient([[('evidence_read', {'ids': ['t1.request']})], [('eval_intent_understanding', p)],
                           [('eval_context_memory', {'reason': 'invalid'})]])
    result = evaluation(client, ('intent_understanding', 'context_memory'), tool_calls=2).run()
    assert all(o.failed and o.output == {} for o in result.values())
    assert all('budget' in o.failure_reason for o in result.values())


def test_loop_instances_do_not_share_receipts_or_submissions():
    p = payload('intent_understanding')
    a = evaluation(ScriptClient([[('evidence_read', {'ids': ['t1.request']})],
                                  [('eval_intent_understanding', p)], 'done']), ('intent_understanding',))
    assert not a.run()['intent_understanding'].failed
    b = evaluation(ScriptClient([[('eval_intent_understanding', p)],
                                  [('eval_intent_understanding', p)]]), ('intent_understanding',), tool_calls=1)
    result = b.run()['intent_understanding']
    assert result.failed and b.evidence.read_ids == set() and not b.submitted


def test_input_membership_tracks_prefix_drop_system_change_and_replayed_response():
    t = make_trace()
    tr = build_transcript(t, t.project_fields['business_trace'])
    rows = {r['id']: r for r in tr['records']}
    assert 't1.c1.m2' in rows['t1.c2']['input_refs']
    assert 't1.c1.system' in rows['t1.c2']['input_refs']
    assert 't1.c1.response' in rows['t1.c2']['input_refs']
    t.project_fields['business_trace']['records']['calls'][1]['pre']['messages'] = [
        {'role': 'system', 'content': 'New rules'}, {'role': 'user', 'content': 'Fresh question'}]
    tr = build_transcript(t, t.project_fields['business_trace'])
    index = TranscriptEvidence(tr)
    own = index.call_inputs('t1.c2')['input_refs']
    assert 't1.c1.system' not in own and 't1.c1.m2' not in own and 't1.c1.response' not in own


def test_mu_cannot_cite_removed_rule_even_if_earlier_and_read():
    t = make_trace()
    t.project_fields['business_trace']['records']['calls'][1]['pre']['messages'][0] = {'role': 'system', 'content': 'new'}
    tr = build_transcript(t, t.project_fields['business_trace'])
    index = TranscriptEvidence(tr)
    ob = next(ob for ob in common.PROCESS_SPECS['model_capability'].obligations if ob.source == 'trace')
    r = {'obligation_id': ob.obligation_id, 'link_id': 't1.c2.response', 'outcome': 'pass',
         'source_refs': ['t1.c1.system'], 'evidence': {'input': ['t1.c2.system'], 'output': ['t1.c2.response']}}
    errors = index.validate([r], {ob.obligation_id: ob}, set(index.records), expectations=E)
    assert any('不属于该次已记录输入' in e for e in errors)


def test_read_pagination_never_claims_full_body_until_complete():
    tr = material()
    tr['records'][0]['text'] = 'x' * (READ_CHARS + 100)
    index = TranscriptEvidence(tr)
    first = index.read(['t1.request'])
    assert first['items'][0]['next_offset'] == READ_CHARS and 't1.request' not in index.read_ids
    index.read(['t1.request'], offset=READ_CHARS)
    assert 't1.request' in index.read_ids


def test_final_provenance_does_not_trust_replay_extracted_output():
    t = make_trace()
    t.raw_response = None
    tr = build_transcript(t, t.project_fields['business_trace'])
    final = next(r for r in tr['records'] if r['kind'] == 'final')
    assert final['origin'] == 'unverified_extracted_output'
    index = TranscriptEvidence(tr)
    ob = next(ob for ob in common.PROCESS_SPECS['context_memory'].obligations if ob.obligation_id == 'delivered_intact')
    r = {'obligation_id': ob.obligation_id, 'link_id': 't1.final', 'outcome': 'pass', 'source_refs': [],
         'evidence': {'input': ['t1.c2.response'], 'output': ['t1.final']}}
    assert any('重建输出不能冒充实收' in e for e in index.validate([r], {ob.obligation_id: ob}, set(index.records), expectations=E))


def test_real_project_report_dispatches_llmtracing_once(monkeypatch):
    from impl.projects.llm_probe.eval_axes import runner
    from impl.projects.llm_probe.eval_axes.adapters import expectations
    from impl.projects.llm_probe.eval_axes.types import RunOutcome, AxisSummary
    monkeypatch.setattr(expectations, 'run', lambda *a: RunOutcome(E, AxisSummary('test'), usage={'llm_calls': 0}))
    monkeypatch.setattr(loop_module, 'prepare', lambda *a: PROJECTION)
    client = ScriptClient([[('evidence_read', {'ids': ['t1.request']})],
                           [(f'eval_{a}', payload(a)) for a in common.PROCESS_SPECS], 'done'])
    monkeypatch.setattr(loop_module, 'axis_llm', lambda *a, **kw: client)
    monkeypatch.setattr(runner, 'run_axes', lambda *a, **kw: pytest.fail('legacy runner entered'))
    # 真实场景保留公共义务，独立测试项目义务由其自己的场景用例覆盖。
    monkeypatch.setattr(loop_module, 'project_obligations', lambda *a: ())
    report = build_report(SimpleNamespace(project_id='llm_probe'), make_trace(), run_id='local-test')
    assert len(report['results']) == 8
    assert all(r['status'] == 'succeeded' for r in report['results'])
    assert len(client.requests) == 2
    assert report['results'][0]['usage']['llm_calls'] == 0


@pytest.mark.parametrize('provider', ['agno', None])
def test_other_provider_and_no_trace_never_enter_llmtracing_loop(monkeypatch, provider):
    from impl.projects.llm_probe import capability
    from impl.projects.llm_probe.eval_axes import runner
    from impl.projects.llm_probe.process_loop import llmtracing_report
    monkeypatch.setattr(capability, 'capability_business_trace', lambda _: {'provider': provider} if provider else None)
    monkeypatch.setattr(llmtracing_report, 'build_loop_results', lambda *a, **kw: pytest.fail('llmtracing loop entered'))
    seen = []
    monkeypatch.setattr(runner, 'run_axes', lambda *a, **kw: seen.append(kw) or [])
    t = make_trace(provider)
    t.normalized_request = {'capability_ref': 'insurance-agno-e2e'}
    assert build_report(SimpleNamespace(project_id='llm_probe'), t)['results'] == []
    assert len(seen) == 1


def test_failed_collection_blocks_all_axes_before_client_creation(monkeypatch):
    monkeypatch.setattr(loop_module, 'axis_llm', lambda *a, **kw: pytest.fail('model created'))
    t = make_trace()
    t.project_fields['business_trace']['status'] = 'failed'
    report = build_report(SimpleNamespace(project_id='llm_probe'), t)
    assert report['results'][0]['status'] == 'failed'
    assert all(r['status'] == 'blocked' for r in report['results'][1:])


def test_alias_only_is_not_a_read_receipt_for_rule_body():
    index = TranscriptEvidence(material())
    index.read(['t1.c2.system'])
    assert 't1.c2.system' not in index.read_ids
    index.read(['t1.c1.system'])
    assert {'t1.c1.system', 't1.c2.system'} <= index.read_ids


def test_valid_visible_intent_pass_is_accepted_without_extra_investigation():
    p = payload('intent_understanding', outcome='pass')
    for group in p['results']:
        group.update(link_ids=['t1.c1.response'], input_refs=['t1.request'],
                     output_refs=['t1.c1.response'], missing=[])
    client = ScriptClient([[('evidence_read', {'ids': ['t1.request', 't1.c1.response']})],
                           [('eval_intent_understanding', p)], 'done'])
    result = evaluation(client, ('intent_understanding',)).run()['intent_understanding']
    assert not result.failed and result.output['assessment']['verdict'] == 'sound'
    assert result.usage['llm_calls'] == 2


def test_model_exception_keeps_failed_attempt_audit_without_partial_results():
    client = ScriptClient([[('evidence_read', {'ids': ['t1.request']})], RuntimeError('transport failed')])
    result = evaluation(client).run()['context_memory']
    assert result.failed and result.output == {}
    assert result.usage['llm_calls'] == 2
    assert result.usage['loop_calls'][0]['tool'] == 'evidence_read'


def test_true_llm_client_and_tool_protocol_work_with_local_fake_server(monkeypatch):
    from dataclasses import replace
    from impl.core import context_store
    from impl.core.config import get_llm_config
    from impl.core.llm_client import LlmClient
    from tests.support.fake_openai import FakeOpenAI

    monkeypatch.setattr(context_store, 'save_context', lambda record: '')
    monkeypatch.setattr(LlmClient, '_endpoint_probe', staticmethod(lambda endpoint: True))
    script = ['finished early', [('evidence_read', {'ids': ['t1.request']})],
              [('eval_context_memory', payload('context_memory'))], 'done']
    with FakeOpenAI({'过程评测员': script}) as fake:
        config = replace(get_llm_config(), api_key='fake-key', base_url=fake.base_url, model='fake-m',
                         fallbacks=(), stream=True, role_policies={})
        result = evaluation(LlmClient(config=config)).run()['context_memory']
    assert not result.failed, result.failure_reason
    assert result.usage['llm_calls'] == 3
    assert [c['decision'] for c in result.output['view']['completion_checks']] == ['continue', 'done']


def test_project_contract_is_in_prompt_and_cannot_be_omitted_from_submission():
    entry = {'process_obligations': [{'id': 'visible_gap_policy', 'link_type': 'context_memory',
              'situation': '交付缺口', 'duty': '按设备服务披露规则呈现', 'confirmed': 'owner'}]}
    missing = payload('context_memory')
    complete = copy.deepcopy(missing)
    complete['results'].append({**complete['results'][0], 'obligation_id': 'project:visible_gap_policy'})
    client = ScriptClient([[('evidence_read', {'ids': ['t1.request']})], [('eval_context_memory', missing)],
                           [('eval_context_memory', complete)], 'done'])
    loop = TranscriptEvaluation(material(), {'context_memory': common.PROCESS_SPECS['context_memory']},
                                {'context_memory': '允许隐藏内部失败原因'}, entry, client, expectations=E, projection=PROJECTION, trace_id='policy-test')
    out = loop.run()['context_memory']
    assert not out.failed
    assert '允许隐藏内部失败原因' in client.requests[0][1]['content']
    assert '按设备服务披露规则呈现' in client.requests[0][1]['content']
    assert 'project:visible_gap_policy' in out.output['view']['loop_calls'][1]['result']['error']
    assert any(r['obligation_id'] == 'project:visible_gap_policy' for r in out.output['results'])


def test_completion_hook_is_explicit_and_end_extracts_accepted_results():
    from impl.core.tool_loop import DependsOn

    client = ScriptClient([[('evidence_read', {'ids': ['t1.request']})],
                           [('eval_context_memory', payload('context_memory'))], 'arbitrary final prose'])
    instance = evaluation(client)
    assert instance.loop.completion_hook is instance.completion_hook
    assert isinstance(instance.pre_tool_hook, DependsOn)
    assert instance.pre_tool_hook in instance.loop.hooks['pre_tool']
    assert instance.post_batch_hook in instance.loop.hooks['post_batch']
    assert instance.loop.end == instance._finish
    result = instance.run()['context_memory']
    assert not result.failed
    assert result.output['assessment']['reason'] == 'Evidence is incomplete'
    assert result.output['view']['completion_checks'] == [
        {'decision': 'done', 'blocked': 0, 'reason': '', 'accepted_tools': ['eval_context_memory']}]


def test_five_axes_do_not_finish_case_and_stop_feedback_names_missing_sixth():
    axes = tuple(common.PROCESS_SPECS)
    first_five, last = axes[:-1], axes[-1]
    client = ScriptClient([[('evidence_read', {'ids': ['t1.request']})],
                           [(f'eval_{a}', payload(a)) for a in first_five], 'finished',
                           [(f'eval_{last}', payload(last))], 'now finished'])
    instance = evaluation(client, axes)
    result = instance.run()
    assert all(not outcome.failed for outcome in result.values())
    checks = instance.completion_hook.checks
    assert [c['decision'] for c in checks] == ['continue', 'done']
    assert f'eval_{last}' in checks[0]['reason']
    assert set(checks[0]['accepted_tools']) == {f'eval_{a}' for a in first_five}
    assert checks[0]['reason'] in client.requests[3][-1]['content']
    assert sum(outcome.usage['llm_calls'] for outcome in result.values()) == 4


def test_stop_feedback_carries_last_rejection_instead_of_generic_retry():
    bad = payload('context_memory')
    bad['results'][0].update(outcome='pass', input_refs=['t1.c1.response'],
                             output_refs=['t1.c2.m4'], missing=[])
    good = copy.deepcopy(bad)
    good['results'][0].update(outcome='insufficient_evidence', missing=['original tool output'])
    client = ScriptClient([[('evidence_read', {'ids': ['t1.request', 't1.c1.response', 't1.c2.m4']})],
                           [('eval_context_memory', bad)], 'done', [('eval_context_memory', good)], 'done'])
    result = evaluation(client).run()['context_memory']
    assert not result.failed
    feedback = client.requests[3][-1]['content']
    assert 'eval_context_memory' in feedback
    assert '工具调用参数不是传递前的产出' in feedback
    assert result.output['view']['completion_checks'][0]['decision'] == 'continue'


@pytest.mark.parametrize('outcome', ['pass', 'fail', 'not_applicable', 'insufficient_evidence', 'contract_missing'])
def test_completion_accepts_every_legal_business_outcome(outcome):
    p = payload('intent_understanding', outcome=outcome)
    for group in p['results']:
        group.update(input_refs=['t1.request'], output_refs=['t1.c1.response'])
        if outcome == 'fail':
            group['problems'] = [dict(problem_id=group['obligation_id'], phenomenon='表达遗漏目标', expectation_ids=[],
                observed='目标未进入表达', source_refs=['case'], input_refs=['t1.request'], output_refs=['t1.c1.response'],
                attribution_axes=['intent_understanding'], impact='yes')]
    client = ScriptClient([[('evidence_read', {'ids': ['t1.request', 't1.c1.response']})],
                           [('eval_intent_understanding', p)], 'done'])
    instance = evaluation(client, ('intent_understanding',))
    result = instance.run()['intent_understanding']
    assert not result.failed
    assert {r['outcome'] for r in result.output['results']} == {outcome}
    assert instance.completion_hook.checks[-1]['decision'] == 'done'


def test_all_accepted_submissions_stop_before_further_model_calls():
    client = ScriptClient([[('evidence_read', {'ids': ['t1.request']})],
                           [('eval_context_memory', payload('context_memory'))],
                           [('call_inputs', {'call_id': 't1.c2'})], 'done'])
    instance = evaluation(client)
    result = instance.run()['context_memory']
    assert not result.failed and len(client.requests) == 2
    assert len(instance.completion_hook.checks) == 1
    assert result.output['view']['loop_calls'][-1]['tool'] == 'eval_context_memory'


def test_end_never_runs_when_stop_keeps_finding_unfinished_axes():
    instance = evaluation(ScriptClient(['done'] * 9))
    instance.loop.end = lambda history: pytest.fail('failed loop must not run end')
    result = instance.run()['context_memory']
    assert result.failed and result.output == {}
    assert 'max_blocked' in result.failure_reason
    assert len(result.usage['completion_checks']) == 9
    assert all(c['decision'] == 'continue' for c in result.usage['completion_checks'])


def test_completion_hook_exception_is_failure_not_business_verdict():
    instance = evaluation(ScriptClient(['done']))

    def broken(*args):
        raise RuntimeError('completion check failed')

    instance.completion_hook.stop = broken
    result = instance.run()['context_memory']
    assert result.failed and result.output == {}
    assert 'completion check failed' in result.failure_reason


def test_parallel_instances_keep_completion_and_receipt_state_separate():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(2)

    class PausedClient(ScriptClient):
        def complete_step(self, *args, **kwargs):
            if not self.requests:
                barrier.wait(timeout=10)
            return super().complete_step(*args, **kwargs)

    def run_one(axis):
        client = PausedClient(['done early', [('evidence_read', {'ids': ['t1.request']})],
                               [(f'eval_{axis}', payload(axis))], 'done'])
        instance = evaluation(client, (axis,))
        result = instance.run()[axis]
        assert not result.failed
        return instance.completion_hook.checks

    axes = ['intent_understanding', 'context_memory']
    with ThreadPoolExecutor(max_workers=2) as pool:
        checks = list(pool.map(run_one, axes))
    for axis, history in zip(axes, checks):
        assert [c['decision'] for c in history] == ['continue', 'done']
        assert history[0]['accepted_tools'] == []
        assert history[1]['accepted_tools'] == [f'eval_{axis}']


def test_recorded_upstream_issue_is_returned_and_resolves_dependent_axis():
    upstream = payload('planning_routing')
    row = next(r for r in upstream['results'] if r['obligation_id'] == 'work_coverage')
    row.update(outcome='fail', missing=[], source_refs=['case'], output_refs=['t1.c2.response'], problems=[{
        'problem_id': 'missing-query', 'phenomenon': 'Required query was omitted',
        'expectation_ids': [], 'observed': 'No query for the required device',
        'source_refs': ['case'], 'input_refs': ['t1.request'], 'output_refs': ['t1.c2.response'],
        'attribution_axes': ['planning_routing'], 'impact': 'yes'}])
    downstream = payload('knowledge_data')
    for row in downstream['results']:
        row.update(outcome='input_invalid', missing=[], upstream_issue_ids=['missing-query'])
    client = ScriptClient([[('evidence_read', {'ids': ['t1.request', 't1.c2.response']})],
                           [('eval_planning_routing', upstream)],
                           [('eval_knowledge_data', downstream)], 'done'])
    outcomes = evaluation(client, ('planning_routing', 'knowledge_data')).run()
    assert all(not o.failed for o in outcomes.values())
    assert outcomes['planning_routing'].output['assessment']['verdict'] == 'problematic'
    output = outcomes['knowledge_data'].output
    assert output['assessment']['verdict'] == 'untested' and output['issues'] == []
    assert all(u['upstream_issue_ids'] == ['missing-query'] for u in output['results'])
    accepted = json.loads(client.requests[2][-1]['content'])
    assert accepted['issues'][0]['problem_id'] == 'missing-query'


def test_transfer_cannot_reverse_received_tool_message_into_original_output():
    index = TranscriptEvidence(material())
    ob = next(o for o in common.PROCESS_SPECS['context_memory'].obligations if o.obligation_id == 'arrives_intact')
    r = {'obligation_id': ob.obligation_id, 'link_id': 't1.c2.m4', 'outcome': 'pass', 'source_refs': [],
         'evidence': {'input': ['t1.c2.m4'], 'output': ['t1.c2']}}
    assert any('快照没有独立工具原始产出' in e for e in index.validate([r], {ob.obligation_id: ob}, set(index.records), expectations=E))
    r['evidence'] = {'input': ['t1.c1.response'], 'output': ['t1.c2']}
    assert any('调用元数据' in e for e in index.validate([r], {ob.obligation_id: ob}, set(index.records), expectations=E))
    r['evidence']['output'] = ['t1.c2.m3']
    assert not index.validate([r], {ob.obligation_id: ob}, set(index.records), expectations=E)


def test_same_comparison_cannot_inflate_exercise_counts_with_multiple_locations():
    index = TranscriptEvidence(material())
    ob = common.PROCESS_SPECS['context_memory'].obligations[0]
    row = {'obligation_id': ob.obligation_id, 'link_id': 't1.c2.m3', 'outcome': 'pass', 'source_refs': [],
           'evidence': {'input': ['t1.c1.response'], 'output': ['t1.c2.m3']}}
    other = copy.deepcopy(row);other['link_id'] = 't1.c1.response'
    assert any('重复计为行使' in e for e in index.validate([row, other], {ob.obligation_id: ob}, set(index.records), expectations=E))


def test_distinct_expected_subquestions_can_share_the_same_evidence_body():
    index = TranscriptEvidence(material())
    ob = common.PROCESS_SPECS['knowledge_data'].obligations[0]
    row = {'obligation_id': ob.obligation_id, 'link_id': 'expected:sex', 'outcome': 'pass',
           'source_refs': ['case'], 'origin': 'expectation_deduction',
           'evidence': {'input': ['t1.request'], 'output': ['t1.c2.m4']}}
    other = copy.deepcopy(row);other['link_id'] = 'expected:birthdate'
    assert not index.validate([row, other], {ob.obligation_id: ob}, set(index.records), expectations=E)
