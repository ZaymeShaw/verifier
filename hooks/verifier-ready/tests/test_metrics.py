import json
from pathlib import Path

from common import HERE
import metrics


def profile(cases=('c',)):
    return {'live': {'cases': list(cases), 'wall_clock_s': 5400},
            'hard_checks': {'case_eval_s': 900, 'latency_p95_s': 180, 'latency_max_s': 400, 'baseline_growth': 1.1}}


def run(case='c'):
    return {'case_id': case, 'judge': {'overall_fulfillment': {'status': 'not_fulfilled'}},
            'stage_timings': {'live_ms': 5000000, 'judge_ms': 1000, 'eval_axes_ms': 1000},
            'eval_axes': {'axes': [{'type': 'a', 'enabled': True}], 'results': [{'axis_id': 'a', 'status': 'succeeded'}]}}


def call(i=1, case='c', **extra):
    return {'call_id': f'call-{i}', 'case_id': case, 'stage': 'judge', 'latency_ms': 1000,
            'usage': {'prompt_tokens': 90000, 'completion_tokens': 100}, 'state': 'succeeded',
            'gateway': 'verifier_primary', **extra}


def test_volume_caps_are_reference_and_baseline_alone_makes_v5_hard():
    calls = {'calls': [call(i) for i in range(20)]}
    batch = {'events': [{'run': run()}]}
    result = metrics.evaluate(calls, batch, profile(), 10)
    assert result['failures'] == []
    assert not any(check['id'] == 'V5' for check in result['hard_checks'])
    refs = {r['id']: r for r in result['reference']}
    assert refs['V1']['value'] == 20 and refs['V1']['reference'] == 14
    assert refs['V3']['value'] == 90000
    assert refs['V4']['value'] == 1800000
    baseline = metrics.evaluate({'calls': [call()]}, batch, profile(), 10)
    compared = metrics.evaluate(calls, batch, profile(), 10, baseline)
    assert len([c for c in compared['hard_checks'] if c['id'] == 'V5' and not c['pass']]) == 2


def test_missing_axis_and_timings_fail_and_business_unreachable_is_separate():
    missing = run()
    missing['eval_axes']['results'] = []
    missing['stage_timings'].pop('judge_ms')
    result = metrics.evaluate({'calls': [call()]}, {'events': [{'run': missing}]}, profile(), 10)
    assert 'U1:c' in result['failures'] and 'L1:c' in result['failures']
    unreachable = {'case_id': 'c', 'error': 'live_service_unavailable', 'trace': {}}
    result = metrics.evaluate({'calls': []}, {'events': [{'run': unreachable}]}, profile(), 10)
    assert 'business_unreachable:c' in result['failures']
    assert not any(c['id'] in ('U1', 'L1') for c in result['hard_checks'])
    assert [r['value'] for r in result['reference'] if r['id'] == 'V1'] == [0]


def test_undeclared_axes_do_not_pass_and_archived_cases_come_from_raw_identity():
    missing = run('archived-case')
    missing['eval_axes'].pop('axes')
    result = metrics.evaluate({'calls': [call(case='archived-case')]}, {'events': [{'run': missing}]}, profile(), 10)
    assert 'U1:archived-case' in result['failures']
    assert not any(r.get('case') == 'c' for r in result['reference'])


def test_latency_nearest_rank_and_max_are_independent():
    records = [call(i, latency_ms=1000) for i in range(19)] + [call(20, latency_ms=401000)]
    result = metrics.evaluate({'calls': records}, {'events': [{'run': run()}]}, profile(), 10)
    assert 'L2_max' in result['failures'] and 'L2_p95' not in result['failures']
    assert next(c for c in result['hard_checks'] if c['id'] == 'L2_max')['call_id'] == 'call-20'


def test_archived_metadata_reconciles_111_calls_24_repeats_and_zero_execution():
    # Frozen mechanical metadata only; projected batch cannot prove semantic coverage.
    report = HERE / 'tests/fixtures/20261006-metadata'
    calls_path = report / 'calls.json'
    batch_path = report / 'batch-metadata.json'
    calls = json.loads(calls_path.read_text())
    batch = json.loads(batch_path.read_text())
    cases = [r['run']['case_id'] for r in batch['events']]
    result = metrics.evaluate(calls, batch, profile(cases), 10)
    assert len(calls['calls']) == 111
    assert sum(c['state'] == 'succeeded' for c in calls['calls']) == 110
    assert sum(r['value'] for r in result['reference'] if r['id'] == 'V2') == 24
    refs = {(r['case'], r['id']): r['value'] for r in result['reference']}
    assert refs[('llm-probe-insurance-real-smoke-policy-list-fuyunping', 'V3')] == 254035
    case_three = next(c['case_id'] for c in calls['calls'] if c['execution_id'].endswith(':3'))
    assert refs[(case_three, 'V2')] == 9
    assert refs[('llm-probe-insurance-real-smoke-agg-paid-prem-fuyunping', 'V1')] == 0
    assert any(c['id'] == 'U1' and not c['pass'] for c in result['hard_checks'])
    assert any(c['id'] == 'L1' and not c['pass'] for c in result['hard_checks'])
    assert 'L2_p95' in result['failures'] and 'L2_max' in result['failures']
