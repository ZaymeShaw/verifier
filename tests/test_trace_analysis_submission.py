import json
from types import SimpleNamespace
import pytest
from impl.core.schema import RunTrace
from impl.projects.llm_probe.business_trace.dossier import build_dossier
from impl.projects.llm_probe.business_trace.links import AXIS_LINK_TYPES
from impl.projects.llm_probe.eval_axes.adapters import trace_analysis
from impl.projects.llm_probe.eval_axes.types import ScenarioAxis
from tests.test_trace_analysis import snapshot, _suspect, _new_suspect, _downstream, AXES


class ScriptClient:
    def __init__(self, script):
        self.script = iter(script)
        self.requests = []

    def complete_step(self, messages, functions, **kwargs):
        from impl.core.tool_loop import Step
        self.requests.append(json.loads(json.dumps(messages)))
        item = next(self.script)
        if isinstance(item, str):
            return Step({'role': 'assistant', 'content': item})
        calls = [{'id': f'call-{len(self.requests)}-{i}', 'type': 'function',
                  'function': {'name': name, 'arguments': json.dumps(args)}}
                 for i, (name, args) in enumerate(item)]
        return Step({'role': 'assistant', 'content': '', 'tool_calls': calls})

    def usage(self):
        return {'llm_calls': 0}


def _run_script(monkeypatch, script, snap=None, runtime=None):
    client = ScriptClient(script)
    monkeypatch.setattr(trace_analysis, 'axis_llm', lambda *a, **kw: client)
    trace = RunTrace(trace_id='x', project_id='llm_probe', case_id='x')
    runtime = runtime or SimpleNamespace(spec=None, trace_id='x', ensure_time_left=lambda _: None,
                                         enabled_axes=AXES)
    out = trace_analysis.run({'trace': trace, 'business_trace': snap or snapshot()},
                             ScenarioAxis('trace_analysis', True, '整理'), runtime)
    return client, out


def _structure(refs=(), existing=(), new=()):
    return {'route': [{'action': '读取消息', 'purpose': '检查调用参数', 'evidence_refs': list(refs),
                       'input_refs': [], 'output_refs': []}],
            'coverage_note': '只描述已读内容',
            'existing_link_suspects': list(existing), 'new_link_suspects': list(new)}


def _linked_message():
    from tests.test_business_trace_linking import snapshot as linked_snapshot
    snap = linked_snapshot()
    d = build_dossier(SimpleNamespace(turn_records=[]), snap)
    a = next(r for r in d['records'] if r.get('model_call_ref'))
    return snap, d, a['id'], a['model_call_ref']


@pytest.mark.parametrize('read_b', [False, True])
def test_associated_ref_is_repaired_in_same_conversation_without_rereading_a(monkeypatch, read_b):
    snap, d, a, b = _linked_message()
    bad = _structure([a, b], [_suspect(link_id='intent_understanding:turn1', source_refs=[a])])
    good = _structure([a, b] if read_b else [a], bad['existing_link_suspects'])
    script = [[('dossier_collect', {'ids': [a]})], [('submit_structure', bad)]]
    if read_b:
        script.append([('dossier_collect', {'ids': [b]})])
    script += [[('submit_structure', good)], '完成']
    client, out = _run_script(monkeypatch, script, snap)
    assert not out.failed
    structure = out.output['structure']
    assert structure['route'][0]['evidence_refs'] == good['route'][0]['evidence_refs']
    assert next(s for s in structure['suspects'] if s['link_id'] == 'intent_understanding:turn1')['source_refs'] == [a]
    audit = structure['evidence_audit']
    assert [r['accepted'] for r in audit['submissions']] == [False, True]
    assert b in audit['submissions'][0]['reason']
    assert '若已读证据足以支撑陈述' in audit['submissions'][0]['reason']
    assert {r['id'] for r in audit['reads']} == ({a, b} if read_b else {a})
    repair_history = client.requests[2]
    # 原始工具结果、被拒的候选以及拒绝原因都在后续请求里；目录只发送为一条初始消息。
    assert sum('## 案卷目录' in str(m.get('content')) for m in repair_history) == 1
    assert any(a in str(m.get('content')) and b in str(m.get('content'))
               for m in repair_history if m['role'] == 'tool')
    submitted = [m for m in repair_history if m.get('tool_calls')
                 and m['tool_calls'][0]['function']['name'] == 'submit_structure']
    assert json.loads(submitted[0]['tool_calls'][0]['function']['arguments']) == bad
    assert out.usage['llm_calls'] == len(script) - 1
    calls = [c for m in client.requests[-1] for c in m.get('tool_calls', [])]
    assert sum(c['function']['name'] == 'dossier_collect' and a in json.loads(c['function']['arguments']).get('ids', [])
               for c in calls) == 1
    # 不引用 B 也不丢失原始关联及下游的调用定位。
    assert next(r for r in out.output['dossier']['records'] if r['id'] == a)['model_call_ref'] == b
    from impl.projects.llm_probe.business_trace.links import build_links
    assert any(link['link_id'] == f'model_capability:{b}' for link in build_links(out.output['dossier'])['links'])


def test_structure_rejection_preserves_findings_until_model_fixes_them(monkeypatch):
    snap, d, a, b = _linked_message()
    bad = _structure([a], [{**_suspect(link_id='intent_understanding:turn1', source_refs=[a]), 'link_type': 'tool_execution'}])
    good = _structure([a], [_suspect(link_id='intent_understanding:turn1', source_refs=[a])])
    client, out = _run_script(monkeypatch, [
        [('dossier_collect', {'ids': [a]})], [('submit_structure', bad)],
        [('submit_structure', good)], '完成'], snap)
    assert not out.failed
    audit = out.output['structure']['evidence_audit']
    assert [r['accepted'] for r in audit['submissions']] == [False, True]
    assert '必须恰好含' in audit['submissions'][0]['reason']
    findings = [s for s in out.output['suspects'] if 'analysis' in s['origin']]
    assert len(findings) == 1
    assert findings[0]['why'] == [bad['existing_link_suspects'][0]['why']]
    assert 'repaired' not in out.output['structure']


@pytest.mark.parametrize('payload', [
    {'route': 1, 'coverage_note': '', 'existing_link_suspects': [], 'new_link_suspects': []},
    {'route': [], 'coverage_note': '', 'existing_link_suspects': 1, 'new_link_suspects': []},
    _structure(['not-in-dossier']),
    _structure([], [{**_suspect('intent_understanding:turn1'), 'link_type': 'tool_execution'}]),
    _structure(new=[_new_suspect('tool_execution', input_refs=['not-in-dossier'], source_refs=['not-in-dossier'])]),
])
def test_repeated_invalid_submissions_fail_without_silently_pruning(monkeypatch, payload):
    _, out = _run_script(monkeypatch, [[('submit_structure', payload)]] * trace_analysis.LLM_CALL_LIMIT)
    assert out.failed and out.output == {}
    assert '未通过验收' in out.failure_reason and 'budget' in out.failure_reason


def test_read_and_submit_in_same_batch_does_not_claim_model_saw_tool_result(monkeypatch):
    snap, d, a, b = _linked_message()
    _, out = _run_script(monkeypatch, [
        [('dossier_collect', {'ids': [a]}), ('submit_structure', _structure([a]))],
        [('submit_structure', _structure([a]))], '完成'], snap)
    assert not out.failed
    assert [x['accepted'] for x in out.output['structure']['evidence_audit']['submissions']] == [False, True]


def test_index_only_gaps_are_citable_without_reading(monkeypatch):
    d = build_dossier(SimpleNamespace(turn_records=[]), snapshot())
    gap = d['gaps'][0]['id']
    _, out = _run_script(monkeypatch, [[('submit_structure', _structure([gap]))], '完成'])
    assert not out.failed
    assert out.output['structure']['route'][0]['evidence_refs'] == [gap]
    assert out.usage['read_ids'] == 0


def test_every_axis_keeps_all_link_ends_without_analysis_suspects(monkeypatch):
    from impl.projects.llm_probe.business_trace.links import build_links, link_ends
    client, out = _run_script(monkeypatch, [[('submit_structure', _structure())], '完成'])
    assert not out.failed
    d = out.output['dossier']
    user = client.requests[0][1]['content']
    assert _downstream(user)['context_memory']['link_types'] == ['context_memory']
    for axis in AXES:
        ends = [ref for link in build_links(d)['links'] if link['link_type'] in AXIS_LINK_TYPES[axis]
                for ref in link_ends(link)]
        assert set(ends) <= set(out.output['selections'][axis]['refs'])


def test_program_suspects_survive_without_model_restatement(monkeypatch):
    from impl.projects.llm_probe.process_loop import analysis
    monkeypatch.setattr(analysis, 'program_suspects', lambda _: [
        {'link_id': 'intent_understanding:turn1', 'why': '程序命中', 'origin': 'program'}])
    _, out = _run_script(monkeypatch, [[('submit_structure', _structure())], '完成'])
    assert not out.failed and out.output['suspects'][0]['origin'] == ['program']


def test_axis_deadline_is_checked_between_model_requests():
    from impl.projects.llm_probe.eval_axes.types import AxisRuntime, AxisTimeout
    import time
    client = ScriptClient(['完成'])
    runtime = AxisRuntime(None, 'r', 't', 's', 'c', deadline=time.monotonic() - 1)
    steps = trace_analysis._AnalysisClient(client, runtime)
    with pytest.raises(AxisTimeout):
        steps.complete_step([], [])
    assert client.requests == []


def test_quoted_route_key_gets_specific_feedback_and_keeps_evidence(monkeypatch):
    snap, _, a, _ = _linked_message()
    good = _structure([a], [_suspect(link_id='intent_understanding:turn1', source_refs=[a])])
    bad = json.loads(json.dumps(good))
    bad['route'][0]['"action"'] = bad['route'][0].pop('action')
    client, out = _run_script(monkeypatch, [
        [('dossier_collect', {'ids': [a]})], [('submit_structure', bad)],
        [('submit_structure', good)], '完成'], snap)
    assert not out.failed
    audit = out.output['structure']['evidence_audit']
    assert [r['accepted'] for r in audit['submissions']] == [False, True]
    error = audit['submissions'][0]['reason']
    assert 'route[0]' in error and "缺少 ['action']" in error
    assert '字面引号' in error and '只修改错误的字段名' in error
    assert out.output['structure']['route'] == good['route']
    assert len([c for m in client.requests[-1] for c in m.get('tool_calls', [])
                if c['function']['name'] == 'dossier_collect']) == 1


def test_thirteen_tools_in_five_rounds_can_submit_without_a_farewell(monkeypatch):
    # 实测失败形态：12 次取证后，第 13 次工具才是提交；应按 5 轮算。
    script = [[('dossier_timeline', {})] * 3 for _ in range(4)]
    script.append([('submit_structure', _structure())])
    client, out = _run_script(monkeypatch, script)
    assert not out.failed
    assert len(client.requests) == out.usage['llm_calls'] == 5
    assert out.usage['tool_calls'] == 13
    assert out.usage['limits'] == {'llm_calls': 8, 'tool_calls': None, 'seconds': 7200}
    assert out.output['structure']['evidence_audit']['submissions'] == [{'accepted': True, 'reason': ''}]


def test_last_round_submission_is_validated_and_finishes_without_round_nine(monkeypatch):
    bad = {'route': 1, 'coverage_note': '', 'existing_link_suspects': [], 'new_link_suspects': []}
    script = [[('submit_structure', bad)]] * 7 + [[('submit_structure', _structure())]]
    client, out = _run_script(monkeypatch, script)
    assert not out.failed and len(client.requests) == out.usage['llm_calls'] == 8
    assert [s['accepted'] for s in out.output['structure']['evidence_audit']['submissions']] == [False] * 7 + [True]
    for used, request in enumerate(client.requests):
        assert f'已使用 {used}/8 轮，剩余 {8-used} 轮（含本轮）' in request[-1]['content']


def test_invalid_last_submission_fails_at_round_limit_without_partial_structure(monkeypatch):
    bad = _structure(['not-in-dossier'])
    client, out = _run_script(monkeypatch, [[('submit_structure', bad)]] * 8)
    assert out.failed and out.output == {} and len(client.requests) == 8
    assert out.usage['llm_calls'] == 8
    assert 'llm_calls 已达上限 8' in out.failure_reason
    assert '不在案卷清单' in out.failure_reason
