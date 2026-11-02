import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import review
from common import CATEGORIES, RULE_KEYS, write_json


@pytest.fixture
def evidence(tmp_path):
    out = tmp_path / 'report'
    calls = [{'call_id': 'call-a', 'case_id': 'case-a', 'role': 'judge', 'stage': 'judge'},
             {'call_id': 'call-b', 'case_id': 'case-b', 'role': 'judge', 'stage': 'judge'}]
    manifest = {'calls': {}}
    for call in calls:
        chunk = out / 'raw/calls' / f"{call['call_id']}.chunks/chunk-0001.txt"
        chunk.parent.mkdir(parents=True)
        chunk.write_text('header\nfirst line\nsecond line\n')
        manifest['calls'][call['call_id']] = [{'path': str(chunk.relative_to(out)),
                                             'start_byte': 0, 'end_byte': 23, 'sha256': 'test'}]
    write_json(out / 'raw/calls.json', {'schema': 'llmtrace.calls/v1', 'status': 'complete', 'calls': calls})
    write_json(out / 'raw/calls/chunks-manifest.json', manifest)
    for call in calls:
        write_json(out / 'ledger' / (call['case_id'] + '.json'), {'case_id': call['case_id'], 'business_unreachable': False})
        write_json(out / 'ledger' / (call['case_id'] + '.deref.json'), {'axes': [{'axis_id': 'judge'}]})
    return out, calls, manifest


def result(case='case-a', call='call-a', sid='spawn-a'):
    return {'spawn_id': sid, 'case_id': case, 'coverage': [{'call_id': call, 'depth': 'full', 'note': ''}],
            'relations': [{'call_id': call, 'category': cat, 'result': 'ok', 'finding_ids': [], 'note': 'checked'}
                          for cat in CATEGORIES],
            'common_rules': [{'key': key, 'scope': {'role': 'judge', 'stage': 'judge', 'version': 'v1'},
                              'status': 'present', 'call_id': call, 'where': 'request.system',
                              'quote': key, 'note': ''} for key in RULE_KEYS],
            'findings': [], 'carry_over': [], 'output_checks': [{'axis': 'judge', 'items': ['checked']}],
            'diff_rulings': [], 'summary': 'Checked without reported conflicts.'}


def finding(fid='F-01', verdict='confirmed', call='call-a'):
    return {'id': fid, 'verdict': verdict, 'severity': 'high', 'category': 2,
            'ends': [{'call_id': call, 'side': 'request', 'where': 'system', 'quote': 'one'},
                     {'call_id': call, 'side': 'request', 'where': 'task', 'quote': 'two'}],
            'scope': 'same task', 'exclusive': 'cannot both hold', 'counter_evidence': 'checked nearby',
            'impact': 'fails task', 'remediation': 'remove conflict'}


def tool_for(out, manifest, call_id):
    chunk = out / manifest['calls'][call_id][0]['path']
    return {'tool': 'read', 'args': {'path': str(chunk)}, 'completed': True, 'is_error': False,
            'result': {'content': [{'type': 'text', 'text': chunk.read_text()}]}}


def meta(out, manifest, case='case-a', call='call-a', sid='spawn-a', tools=None):
    dest = out / 'spawn' / case
    dest.mkdir(parents=True, exist_ok=True)
    tools = [tool_for(out, manifest, call)] if tools is None else tools
    path = dest / 'tool_calls.jsonl'
    path.write_text(''.join(json.dumps(tool) + '\n' for tool in tools))
    return {'spawn_id': sid, 'case_id': case, 'tool_calls': str(path), 'has_result': True,
            'exit_code': 0, 'errors': [], 'scope_valid': False}


def test_exact_chunk_required(evidence):
    out, calls, manifest = evidence
    tools = [tool_for(out, manifest, 'call-a')]
    assert review.full_chunks(out, 'call-a', manifest, tools) == (True, '')
    tools[0]['result']['content'][0]['text'] = 'header\n'
    assert review.full_chunks(out, 'call-a', manifest, tools) == (False, 'chunk_missing')


@pytest.mark.parametrize('change', ['truncated', 'firstLineExceedsLimit', 'error', 'unfinished', 'offset', 'limit', 'bash'])
def test_false_full_read_rejected(evidence, change):
    out, calls, manifest = evidence
    tool = tool_for(out, manifest, 'call-a')
    if change in {'truncated', 'firstLineExceedsLimit'}:
        tool['result']['details'] = {'truncation': {change: True}}
    elif change == 'error':
        tool['is_error'] = True
    elif change == 'unfinished':
        tool['completed'] = False
    elif change == 'offset':
        tool['args']['offset'] = 2
    elif change == 'limit':
        tool['args']['limit'] = 1
    else:
        tool['tool'] = 'bash'
    checked = review.validate(result(), meta(out, manifest, tools=[tool]), calls[:1], out, manifest)
    assert checked['coverage'][0]['depth'] == 'partial'


def test_tool_limit_presence_alone_is_not_partial(evidence):
    out, _, manifest = evidence
    tool = tool_for(out, manifest, 'call-a')
    tool['args'].update(offset=1, limit=1000)
    assert review.full_chunks(out, 'call-a', manifest, [tool])[0]


def test_missing_relation_and_common_rule_keys(evidence):
    out, calls, manifest = evidence
    value = result()
    value['relations'].pop()
    value['common_rules'].pop()
    checked = review.validate(value, meta(out, manifest), calls[:1], out, manifest)
    assert checked['validation']['missing_relation'] == 1
    assert checked['validation']['missing_common_rules'] == 1


def test_unknown_common_rules_are_explicit(evidence):
    out, calls, manifest = evidence
    value = result()
    value['common_rules'][0].update(status='unknown', call_id=None, quote='', where='', note='not captured')
    checked = review.validate(value, meta(out, manifest), calls[:1], out, manifest)
    assert checked['validation']['valid']
    assert checked['validation']['unknown_common_rules'] == 1
    assert checked['validation']['missing_common_rules'] == 0


def test_invalid_call_id_is_open_high(evidence):
    out, calls, manifest = evidence
    value = result()
    value['findings'] = [finding(call='call-a.txt')]
    checked = review.validate(value, meta(out, manifest), calls[:1], out, manifest)
    assert not checked['validation']['valid']
    assert checked['validation']['invalid_ref'] == 1
    assert checked['findings'][0]['verdict'] == 'open'
    assert checked['findings'][0]['severity'] == 'high'


@pytest.mark.parametrize('field', ['coverage', 'relations', 'findings'])
def test_duplicates_never_valid(evidence, field):
    out, calls, manifest = evidence
    value = result()
    if field == 'findings':
        value[field] = [finding(), finding()]
    else:
        value[field].append(value[field][0].copy())
    checked = review.validate(value, meta(out, manifest), calls[:1], out, manifest)
    assert not checked['validation']['valid']
    if field == 'findings':
        assert len({f['id'] for f in checked['findings']}) == 2


def old_carry():
    return {'reference': 'old::case-a::F-01', 'previous_report': '/old', 'key': 'case-a::F-01',
            'shard': 'case-a', 'severity': 'high'}


def test_unreported_old_high_cannot_disappear(evidence):
    out, calls, manifest = evidence
    checked = review.validate(result(), meta(out, manifest), calls[:1], out, manifest, [old_carry()])
    carry = checked['carry_over'][0]
    assert carry['ruling'] == 'unverifiable'
    assert carry['key'] == 'case-a::F-carry-1'
    assert checked['findings'][0]['verdict'] == 'open'
    assert checked['findings'][0]['severity'] == 'high'


def test_resolved_requires_new_evidence(evidence):
    out, calls, manifest = evidence
    value = result()
    value['carry_over'] = [{'finding': old_carry()['reference'], 'ruling': 'resolved',
                            'ends': [], 'finding_ids': [], 'note': 'gone from new run'}]
    checked = review.validate(value, meta(out, manifest), calls[:1], out, manifest, [old_carry()])
    assert checked['carry_over'][0]['ruling'] == 'unverifiable'
    assert checked['findings'][0]['severity'] == 'high'


def test_aggregate_references_union_and_requires_all_diffs(evidence):
    out, calls, manifest = evidence
    value = result('_aggregate', 'call-a')
    value.update(coverage=[], relations=[], common_rules=[], findings=[finding()])
    value['findings'][0]['ends'][1]['call_id'] = 'call-b'
    value['diff_rulings'] = [{'diff_id': 'D-001', 'verdict': 'confirmed', 'finding_ids': ['F-01'], 'note': 'same scope'}]
    checked = review.validate(value, meta(out, manifest, case='_aggregate'), calls, out, manifest,
                              diffs=[{'id': 'D-001'}])
    assert checked['validation']['valid']
    checked = review.validate(value, meta(out, manifest, case='_aggregate'), calls, out, manifest,
                              diffs=[{'id': 'D-001'}, {'id': 'D-002'}])
    assert 'missing_diff_ruling' in checked['validation']['errors']


def test_rule_difference_is_not_automatic_conflict():
    a, b = result(), result('case-b', 'call-b')
    b['common_rules'][0]['quote'] = 'other words'
    diffs = review.common_rule_diffs({'case-a': a, 'case-b': b})
    assert len(diffs) == 1
    assert diffs[0]['entries'][0]['key'] == 'role'
    assert not a['findings'] and not b['findings']


def test_last_human_ruling_controls_previous_carry(tmp_path):
    previous = tmp_path / 'old'
    value = {**finding(), 'key': 'case-a::F-01', 'shard': 'case-a'}
    write_json(previous / 'review-summary.json', {'findings': [value]})
    write_json(previous / 'adjudication.json', {'entries': [
        {'finding': value['key'], 'rule': 'waived-by-human'}, {'finding': value['key'], 'rule': 'confirmed'}]})
    assert review.previous_findings(previous)[0]['reference'] == 'old::case-a::F-01'
    write_json(previous / 'adjudication.json', {'entries': [{'finding': value['key'], 'rule': 'withdrawn'}]})
    assert not review.previous_findings(previous)


def run_stub(out, manifest):
    def spawn(report, case, profile, task):
        call = 'call-a' if case == 'case-a' else 'call-b'
        value = result(case, call, sid='sid-' + case)
        info = meta(out, manifest, case, call, sid=value['spawn_id'])
        task_path = out / 'spawn' / case / 'task.md'
        task_path.write_text(task)
        write_json(out / 'spawn' / case / 'result.json', value)
        return {'result': value, 'meta': info, 'task': str(task_path)}
    return spawn


def test_global_snapshot_buffers_excluded(evidence, tmp_path):
    out, calls, manifest = evidence
    root = tmp_path / 'repo'
    (root / 'impl').mkdir(parents=True)
    (root / 'impl/file.py').write_text('old')
    profile = {'live': {'cases': ['case-a', 'case-b']}, 'reviewer': {'parallel': 2}}
    with patch.object(review, 'ROOT', root), patch.object(review.spawn_reviewer, 'run', run_stub(out, manifest)):
        summary = review.run(out, profile)
    assert summary['valid']
    assert summary['consistency']['pass']
    assert summary['consistency']['full'] == 2
    assert (out / 'review/case-a.json').exists()


def test_workspace_change_invalidates_entire_review(evidence, tmp_path):
    out, calls, manifest = evidence
    root = tmp_path / 'repo'
    (root / 'impl').mkdir(parents=True)
    source = root / 'impl/file.py'
    source.write_text('old')
    original = run_stub(out, manifest)
    def mutation(*args):
        value = original(*args)
        source.write_text('modified again')
        return value
    profile = {'live': {'cases': ['case-a', 'case-b']}, 'reviewer': {'parallel': 1}}
    with patch.object(review, 'ROOT', root), patch.object(review.spawn_reviewer, 'run', mutation):
        summary = review.run(out, profile)
    assert not summary['valid']
    assert not summary['consistency']['pass']
    assert not (out / 'review/case-a.json').exists()
    assert not (out / 'review-task/case-a.md').exists()
    assert not any(review.read_json(out / shard['meta'])['scope_valid'] for shard in summary['shards'].values())
