"""Standalone orchestration with a real local child process; no business or model network."""
import json
import sys
from pathlib import Path

from common import CATEGORIES, RULE_KEYS, load_profile, read_json, write_json
import collect
import gate
import live


FAKE_REVIEWER = '''
import json,re,sys
from pathlib import Path
out=Path(sys.argv[1]); task=sys.argv[2]
sid=re.search(r'^spawn_id: (.+)$',task,re.M)[1]
case=re.search(r'^case_id: (.+)$',task,re.M)[1]
calls=[c for c in json.loads((out/'raw/calls.json').read_text())['calls'] if c['case_id']==case]
manifest=json.loads((out/'raw/calls/chunks-manifest.json').read_text())
for call in calls:
 for n,item in enumerate(manifest['calls'][call['call_id']]):
  path=out/item['path']; tid=call['call_id']+str(n)
  print(json.dumps({'type':'tool_execution_start','toolCallId':tid,'toolName':'read','args':{'path':str(path)}}))
  print(json.dumps({'type':'tool_execution_end','toolCallId':tid,'result':{'content':[{'type':'text','text':path.read_text()}]},'isError':False}))
rules=['role','output_structure','axis_identifiers','reference_format','coverage','evidence_authority','outcome_semantics']
value={'spawn_id':sid,'case_id':case,
 'coverage':[{'call_id':c['call_id'],'depth':'full','note':''} for c in calls],
 'relations':[{'call_id':c['call_id'],'category':cat,'result':'ok','finding_ids':[],'note':'synthetic check'} for c in calls for cat in range(1,8)],
 'common_rules':[{'key':k,'scope':{'role':'judge','stage':'judge','version':'test-v1'},'status':'present','call_id':calls[0]['call_id'],'where':'system','quote':k,'note':''} for k in rules],
 'findings':[], 'carry_over':[], 'output_checks':[{'axis':'tool_execution','items':['synthetic check']}], 'summary':'Local process fixture only.'}
print(json.dumps({'type':'message_end','message':{'role':'assistant','model':'local-fixture','provider':'local','content':[{'type':'text','text':json.dumps(value)}]}}))
'''


def test_independent_command_end_to_end_without_main_flow(tmp_path, monkeypatch, capsys):
    out = tmp_path / 'result'
    fake = tmp_path / 'reviewer.py'
    fake.write_text(FAKE_REVIEWER)
    profile = load_profile()
    cases = [f'case-{i}' for i in range(4)]
    profile['live']['cases'] = cases
    profile['reviewer']['model'] = 'local/local-fixture'
    profile['reviewer']['commands']['pi'] = [sys.executable, str(fake), str(out), '{task}', '--no-skills',
        '--no-context-files', '--no-prompt-templates', '--no-extensions']
    monkeypatch.setattr(gate, 'load_profile', lambda: profile)
    monkeypatch.setattr(gate, 'CURRENT', tmp_path / 'current/progress.json')
    monkeypatch.setattr(gate, 'baseline', lambda: None)
    main_files = [gate.ROOT / p for p in ('run.sh', 'AGENTS.md', 'spec/verifier-ready-gate.md')]
    before = {str(p): p.read_bytes() for p in main_files if p.exists()}

    def local_capture(out, profile):
        records, identities, events = [], [], []
        for i, case in enumerate(cases):
            cid, eid = f'call-{i}', f'opaque-{i}'
            records.append(dict(call_id=cid, execution_id=eid, case_id=case, role='judge', stage='judge',
                state='succeeded', gateway='verifier_primary', latency_ms=100, ts=f'2026-10-07T00:00:0{i}Z',
                usage={'prompt_tokens': 10, 'completion_tokens': 1}))
            identities.append(dict(execution_id=eid, request_case_id=case))
            events.append({'run': {'case_id': case, 'execution_id': eid, 'status': 'completed', 'judge': {'verdict': 'pass'},
                'eval_axes': {'axes': [{'type': 'tool_execution', 'enabled': True}],
                              'results': [{'axis_id': 'tool_execution', 'status': 'succeeded', 'output': {}}]},
                'stage_timings': {'eval_axes_ms': 1000, 'judge_ms': 1000, 'live_ms': 10}}})
            path = out / 'raw/calls' / f'{cid}.txt'
            path.parent.mkdir(parents=True, exist_ok=True)
            # Long UTF-8 line exercises the actual chunk/reading path.
            path.write_text('system: test\n' + '材料🙂' * 14000 + '\nassistant: test\n')
        write_json(out / 'raw/calls.json', {'schema': 'llmtrace.calls/v1', 'status': 'complete',
                   'counts': {'total': 4}, 'pending_call_ids': [], 'conflicts': [], 'calls': records})
        write_json(out / 'raw/requests.json', identities)
        write_json(out / 'raw/batch-status.json', {'status': 'completed', 'identities': identities, 'events': events})
        collect.prepare_chunks(out)
        return dict(job_id='local-fixture', instance='not-a-live-instance', port=0, execution_ids=[i['execution_id'] for i in identities], cases=cases, elapsed_s=3)

    monkeypatch.setattr(live, 'run', local_capture)
    assert gate.main(['--all', '--out', str(out)]) == 0
    first = read_json(out / 'verdict.json')
    assert first['gate'] == 'PASS'
    assert first['consistency']['full'] == 4
    assert first['consistency']['pass']
    assert len(first['review']['shards']) == 4
    assert read_json(out / 'review/snapshot.json')['scope_valid']
    assert all(p.read_bytes() == before[str(p)] for p in main_files if str(p) in before)
    assert gate.main(['--status', '--out', str(out), '--json']) == 0
    capsys.readouterr()
    # Evidence mutation must be detected by the standalone read-only status command.
    (out / 'raw/calls/call-0.txt').write_text('changed evidence')
    assert gate.main(['--status', '--out', str(out), '--json']) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'stale'


def test_default_command_is_help_only(monkeypatch, capsys):
    monkeypatch.setattr(live, 'run', lambda *_: (_ for _ in ()).throw(AssertionError('must not launch')))
    assert gate.main([]) == 0
    assert '--all' in capsys.readouterr().out


def test_carry_over_does_not_require_user_remembering_previous(tmp_path, monkeypatch):
    prior = tmp_path / 'prior'
    write_json(prior / 'run.json', {'phase': 'completed'})
    write_json(prior / 'review-summary.json', {'findings': []})
    monkeypatch.setattr(gate, 'CURRENT', tmp_path / 'current/progress.json')
    write_json(gate.CURRENT, {'report': str(prior)})
    assert gate.previous_report() == prior


def test_archived_subset_does_not_include_other_executions(tmp_path, monkeypatch):
    profile = load_profile()
    monkeypatch.setattr(gate, 'baseline', lambda: None)
    out = gate.new_report(tmp_path / 'subset', profile)
    selected = {'execution_id': 'selected', 'request_case_id': 'case-one'}
    batch = {'identities': [selected, {'execution_id': 'other', 'request_case_id': 'case-two'},
                            {'execution_id': 'old', 'request_case_id': 'case-one'}],
             'events': [
                 {'run': {'execution_id': 'selected', 'case_id': 'case-one', 'judge': {'verdict': 'pass'},
                          'eval_axes': {'axes': [{'type': 'tool_execution', 'enabled': True}],
                                        'results': [{'axis_id': 'tool_execution', 'status': 'succeeded', 'output': {}}]},
                          'stage_timings': {'eval_axes_ms': 1000, 'judge_ms': 1000}}},
                 {'run': {'execution_id': 'other', 'case_id': 'case-two', 'error': 'unreachable'}},
                 {'run': {'execution_id': 'old', 'case_id': 'case-one', 'error': 'unreachable'}}]}
    write_json(out / 'raw/batch-status.json', batch)
    original = (out / 'raw/batch-status.json').read_bytes()
    write_json(out / 'raw/requests.json', [selected])
    write_json(out / 'raw/calls.json', {'calls': [{'call_id': 'call-one', 'execution_id': 'selected',
               'case_id': 'case-one', 'role': 'judge', 'stage': 'judge', 'state': 'succeeded',
               'gateway': 'verifier_primary', 'latency_ms': 100,
               'usage': {'prompt_tokens': 10, 'completion_tokens': 1}}]})
    path = out / 'raw/calls/call-one.txt'
    path.parent.mkdir(parents=True)
    path.write_text('selected context')
    gate.finish_collection(out, profile, 3)
    metrics = read_json(out / 'metrics.json')
    assert not metrics['failures']
    assert {row['case'] for row in metrics['reference']} == {'case-one'}
    assert not read_json(out / 'ledger/case-one.json')['business_unreachable']
    assert read_json(out / 'ledger/case-one.deref.json')['axes'][0]['axis_id'] == 'tool_execution'
    assert not (out / 'ledger/case-two.json').exists()
    assert (out / 'raw/batch-status.json').read_bytes() == original
