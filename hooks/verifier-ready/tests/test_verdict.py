import copy
import io

import pytest

from common import write_json, read_json, digest, fingerprint, load_profile
import verdict


@pytest.fixture
def captured(tmp_path):
    root = tmp_path / 'repo'
    (root / 'impl').mkdir(parents=True)
    (root / 'impl/file.py').write_text('original')
    out = root / 'report/run'
    profile = load_profile()
    write_json(out / 'raw/calls.json', {'calls': [{'call_id': 'call-1', 'case_id': 'case-1'}]})
    write_json(out / 'raw/requests.json', [{'execution_id': 'exec-1'}])
    write_json(out / 'metrics.json', {'hard_checks': [{'id': 'U1', 'pass': True}], 'reference': [], 'failures': []})
    review = {'spawn_id': 'spawn-1', 'case_id': 'case-1', 'findings': []}
    write_json(out / 'review/case-1.json', review)
    write_json(out / 'spawn/case-1/meta.json', {'spawn_id': 'spawn-1', 'has_result': True,
                'exit_code': 0, 'scope_valid': True, 'review_sha256': digest(out / 'review/case-1.json')})
    write_json(out / 'review/snapshot.json', {'scope_valid': True})
    summary = {'valid': True, 'shards': {'case-1': {'path': 'review/case-1.json', 'meta': 'spawn/case-1/meta.json', 'valid': True}},
               'findings': [], 'carry_over': [], 'consistency': {
                   'calls_total': 1, 'full': 1, 'partial': 0, 'unverifiable': 0, 'missing_relation': 0,
                   'missing_common_rules': 0, 'invalid_ref': 0, 'confirmed': dict(blocking=0, high=0, diagnostic=0),
                   'explained': 0, 'open_key': 0, 'open_other': 0, 'pass': True}}
    write_json(out / 'review-summary.json', summary)
    write_json(out / 'run.json', {'phase': 'completed', 'fingerprint': fingerprint(root, profile),
        'input_hashes': verdict.input_hashes(out), 'review_summary_sha256': digest(out / 'review-summary.json'),
        'metrics_sha256': digest(out / 'metrics.json')})
    return root, out, profile


def update_summary(out, transform):
    data = read_json(out / 'review-summary.json')
    transform(data)
    write_json(out / 'review-summary.json', data)
    run = read_json(out / 'run.json')
    run['review_summary_sha256'] = digest(out / 'review-summary.json')
    write_json(out / 'run.json', run)


def problem(out, severity='high'):
    finding = dict(key='case-1::F-01', shard='case-1', id='F-01', verdict='confirmed', severity=severity)
    update_summary(out, lambda data: data['findings'].append(finding))
    return finding['key']


def test_clean_unchanged_report_passes(captured):
    root, out, profile = captured
    result = verdict.compute(out, profile, root=root)
    assert result['gate'] == 'PASS'
    assert result['consistency']['pass']


def test_waiver_releases_without_lying_about_consistency(captured):
    root, out, profile = captured
    key = problem(out)
    write_json(out / 'adjudication.json', {'entries': [dict(finding=key, rule='waived-by-human', note='Accepted by owner')]})
    result = verdict.publish(out, profile, root=root)
    assert result['gate'] == 'PASS_WITH_EXCEPTION'
    assert result['release_allowed']
    assert not result['consistency']['pass']
    assert result['consistency']['confirmed']['high'] == 1
    assert 'Human release with exceptions' in (out / 'summary.md').read_text()


def test_fixed_response_does_not_close_a_problem(captured):
    root, out, profile = captured
    key = problem(out)
    write_json(out / 'response.json', {'responses': [dict(finding=key, status='fixed', note='Changed prompt')]})
    result = verdict.compute(out, profile, root=root)
    assert result['gate'] == 'FAIL'
    assert result['response']['unanswered'] == []


def test_human_withdrawal_corrects_the_review(captured):
    root, out, profile = captured
    key = problem(out)
    write_json(out / 'adjudication.json', {'entries': [dict(finding=key, rule='withdrawn', note='Original input contains rule')]})
    result = verdict.compute(out, profile, root=root)
    assert result['gate'] == 'PASS'
    assert result['consistency']['pass']


def test_refutation_waits_for_human(captured):
    root, out, profile = captured
    key = problem(out)
    write_json(out / 'response.json', {'responses': [dict(finding=key, status='refuted', note='Counterexample',
                counter_evidence=[dict(call_id='call-1', quote='actual rule')])]})
    assert verdict.compute(out, profile, root=root)['gate'] == 'NEEDS_HUMAN'


def test_agent_cannot_self_waive(captured):
    root, out, profile = captured
    key = problem(out)
    write_json(out / 'response.json', {'responses': [dict(finding=key, status='waived', note='Skip')]})
    with pytest.raises(ValueError):
        verdict.compute(out, profile, root=root)


def test_reused_local_id_does_not_answer_another_case(captured):
    root, out, profile = captured
    key = problem(out)
    update_summary(out, lambda data: data['findings'].append(dict(key='case-2::F-01', shard='case-2', id='F-01', verdict='confirmed', severity='high')))
    write_json(out / 'response.json', {'responses': [dict(finding=key, status='fixed', note='Only case 1')]})
    assert verdict.compute(out, profile, root=root)['response']['unanswered'] == ['case-2::F-01']


@pytest.mark.parametrize('change', ['code', 'profile', 'input', 'metrics'])
def test_changed_inputs_and_rules_invalidate_report(captured, change):
    root, out, profile = captured
    if change == 'code':
        (root / 'impl/file.py').write_text('changed')
    elif change == 'profile':
        profile['reviewer']['model'] = 'changed-model'
    elif change == 'input':
        write_json(out / 'raw/requests.json', [{'execution_id': 'changed'}])
    else:
        write_json(out / 'metrics.json', {'hard_checks': [{'id': 'U1', 'pass': False}], 'reference': [], 'failures': []})
    result = verdict.compute(out, profile, root=root)
    assert not result['release_allowed']
    assert result['status'] == 'stale'


@pytest.mark.parametrize('which', ['review', 'summary', 'snapshot'])
def test_modified_review_cannot_silently_pass(captured, which):
    root, out, profile = captured
    if which == 'review':
        write_json(out / 'review/case-1.json', {'spawn_id': 'changed'})
    elif which == 'summary':
        data = read_json(out / 'review-summary.json')
        data['consistency']['calls_total'] = 0
        write_json(out / 'review-summary.json', data)
    else:
        write_json(out / 'review/snapshot.json', {'scope_valid': False})
    assert not verdict.compute(out, profile, root=root)['review']['valid']


def test_high_issue_cannot_disappear_on_next_run(captured):
    root, out, profile = captured
    update_summary(out, lambda data: data['carry_over'].append(dict(key='case-1::CARRY-01', severity='high', ruling='unverifiable')))
    result = verdict.compute(out, profile, root=root)
    assert not result['release_allowed']
    assert not result['consistency']['pass']


def test_partial_coverage_cannot_claim_consistency(captured):
    root, out, profile = captured
    def partial(data):
        data['consistency'].update(full=0, partial=1)
    update_summary(out, partial)
    result = verdict.compute(out, profile, root=root)
    assert not result['release_allowed']
    assert result['status'] == 'coverage_incomplete'


def test_adjudication_requires_human_terminal(captured, monkeypatch):
    _, out, _ = captured
    key = problem(out)
    monkeypatch.setattr(verdict.sys, 'stdin', io.StringIO())
    with pytest.raises(ValueError, match='interactive terminal'):
        verdict.adjudicate(out, key, 'withdrawn', 'a reason')
    assert not (out / 'adjudication.json').exists()


def test_override_never_promotes_stale_report(captured):
    root, out, profile = captured
    (root / 'impl/file.py').write_text('changed')
    write_json(out / 'adjudication.json', {'entries': [dict(finding=None, rule='override-release', note='Force release')]})
    assert not verdict.compute(out, profile, root=root)['release_allowed']


def test_unknown_common_rule_cannot_pass(captured):
    root, out, profile = captured
    update_summary(out, lambda data: data['consistency'].update(unknown_common_rules=1, **{'pass': False}))
    result = verdict.compute(out, profile, root=root)
    assert not result['release_allowed']
    assert not result['consistency']['pass']


@pytest.mark.parametrize('phase', ['created', 'collected', 'reviewing', 'failed'])
def test_unfinished_rerun_cannot_reuse_old_pass(captured, phase):
    root, out, profile = captured
    run = read_json(out / 'run.json')
    run['phase'] = phase
    write_json(out / 'run.json', run)
    result = verdict.compute(out, profile, root=root)
    assert not result['release_allowed']
    assert not result['consistency']['pass']


def test_human_confirmation_applies_to_observed_counts(captured):
    root, out, profile = captured
    key = problem(out, severity='diagnostic')
    def make_open(data):
        data['findings'][0]['verdict'] = 'open'
    update_summary(out, make_open)
    write_json(out / 'adjudication.json', {'entries': [dict(finding=key, rule='confirmed', note='Verified conflict')]})
    result = verdict.compute(out, profile, root=root)
    assert not result['release_allowed']
    assert result['consistency']['confirmed']['diagnostic'] == 1
