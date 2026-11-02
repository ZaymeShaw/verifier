from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest
from impl.core.llm_tracing import current_identity, trace_scope, trace_headers, submit_with_context, traced_entry, traced_model_call


def test_parallel_cases_and_roles_keep_identity_and_clean_workers():
    barrier = Barrier(2)
    def case(cid):
        with trace_scope(case_id=cid, new_attempt=True):
            barrier.wait(timeout=5)
            with ThreadPoolExecutor(2) as roles:
                return [f.result() for f in [submit_with_context(roles, trace_headers, role=r) for r in ('judge', 'attribute')]]
    with ThreadPoolExecutor(2) as cases:
        with trace_scope(run_id='batch-one', case_id='__batch__'):
            futures = [submit_with_context(cases, case, cid) for cid in ('A', 'B')]
            groups = [f.result() for f in futures]
        assert cases.submit(current_identity).result() == {}
    assert {h['X-Eval-Run-Id'] for group in groups for h in group} == {'batch-one'}
    assert [{h['X-Eval-Case-Id'] for h in group} for group in groups] == [{'A'}, {'B'}]
    assert len({h['X-Eval-Execution-Id'] for h in groups[0]}) == 1
    assert groups[0][0]['X-Eval-Execution-Id'] != groups[1][0]['X-Eval-Execution-Id']
    assert current_identity() == {}


def test_attempts_and_independent_health_probe():
    with trace_scope(run_id='batch', case_id='A') as first:
        assert trace_headers()['X-Eval-Execution-Id'] == first['execution_id']
        with trace_scope(new_attempt=True) as second:
            assert second['run_id'] == first['run_id']
            assert second['execution_id'] != first['execution_id']
        with trace_scope(case_id='__health_probe__', independent=True) as probe:
            assert probe['run_id'] != first['run_id']
            assert probe['execution_id'] != first['execution_id']
        assert current_identity() == first
    with pytest.raises(RuntimeError):
        trace_headers()


def test_unicode_collision_safe_ids_and_exception_reset():
    with trace_scope(case_id='题一\n') as a:
        a['case_id'].encode('ascii')
    with trace_scope(case_id='题二\n') as b:
        assert a['case_id'] != b['case_id']
    with pytest.raises(ValueError), trace_scope(case_id='error'):
        raise ValueError('expected')
    assert current_identity() == {}


def test_entry_uses_runtime_case_id_and_respects_nested_scope():
    @traced_entry()
    def run(project_id, case):
        return {'identity': current_identity()}
    result = run('test', SimpleNamespace(id='A01'))
    assert result['identity']['case_id'] == 'A01'
    assert result['llmtracing']['project_id'] == 'test'
    with trace_scope(run_id='batch', case_id='B', new_attempt=True) as identity:
        assert run('test', SimpleNamespace(id='A01'))['identity'] == identity


def test_wire_headers_for_shared_client_across_threads_and_fallbacks():
    from impl.core.llm_client import LlmClient
    from impl.core.llm_router import LlmEndpoint
    from impl.core.config import get_llm_config
    from dataclasses import replace
    config = replace(get_llm_config(), api_key='test', base_url='http://127.0.0.1:9/v1', fallbacks=())
    client = LlmClient(role='judge', config=config)
    barrier = Barrier(2)
    def run(cid):
        with trace_scope(run_id='batch', case_id=cid):
            barrier.wait(timeout=5)
            headers = trace_headers(role=client.role, stage='assessment')
            endpoints = [LlmEndpoint(name=name, base_url='http://127.0.0.1:9/v1', model='m', api_key='test') for name in ('primary', 'fallback1')]
            return [client.build_model(endpoint=ep, trace_identity_headers=headers).extra_headers for ep in endpoints]
    with ThreadPoolExecutor(2) as pool:
        a, b = list(pool.map(run, ('A', 'B')))
    assert [h['X-Eval-Case-Id'] for h in a] == ['A', 'A']
    assert [h['X-Eval-Case-Id'] for h in b] == ['B', 'B']
    assert a[0]['X-Eval-Execution-Id'] == a[1]['X-Eval-Execution-Id']
    assert a[0]['X-Eval-Execution-Id'] != b[0]['X-Eval-Execution-Id']
    assert a[0]['X-Eval-Harness'] == 'verifier'


def test_actual_complete_step_injects_headers_in_run_turn(monkeypatch):
    # Exercise the production call boundary; stop immediately after model creation.
    from impl.core.llm_client import LlmClient
    from impl.core.config import get_llm_config
    from impl.core.llm_router import LlmEndpoint
    from dataclasses import replace
    client = LlmClient(role='judge', config=replace(get_llm_config(), api_key='test', fallbacks=()))
    ep = LlmEndpoint(name='primary', base_url='http://127.0.0.1:9/v1', model='m', api_key='test')
    monkeypatch.setattr(client.llm_router, 'select', lambda **kw: ep)
    captured=[]
    class Stop(Exception): pass
    def build(**kw):
        captured.append(kw['trace_identity_headers'])
        raise Stop()
    monkeypatch.setattr(client, 'build_model', build)
    with trace_scope(run_id='real-boundary', case_id='A') as identity:
        with pytest.raises(Stop):
            client.complete_step([{'role':'user','content':'test'}], [], trace_id='t', stage='judge')
    assert captured[0]['X-Eval-Execution-Id'] == identity['execution_id']
    assert captured[0]['X-Eval-Stage'] == 'judge'
    assert current_identity() == {}


def test_pipeline_retry_keeps_submitted_execution_without_repeating_business(monkeypatch):
    from impl.core import pipeline, mock, config
    calls=[]; business=[]
    case=SimpleNamespace(id='A', input={})
    from impl.core.schema import RunTrace, to_dict
    trace=RunTrace(trace_id='t', project_id='p', case_id='A', execution_mode='live')
    monkeypatch.setattr(mock, 'parse_mock_case', lambda *a, **k: case)
    monkeypatch.setattr(mock, 'mock_case_to_single_turn', lambda *a, **k: case)
    monkeypatch.setattr(pipeline, 'normalize_case_interaction', lambda *a: SimpleNamespace(mode='single_turn',case_id='A',execution_input={}))
    monkeypatch.setattr(config, 'get_runtime_config', lambda: SimpleNamespace(execution=SimpleNamespace(case_retry_attempts=2)))
    def live(*a):
        business.append(current_identity());return trace
    monkeypatch.setattr(pipeline, 'live_run', live)
    def chain(*a):
        calls.append(current_identity())
        if len(calls)==1:raise RuntimeError('force judge retry')
        return {'trace':trace,'table_row':{'ok':True}}
    monkeypatch.setattr(pipeline, '_chain_from_trace', chain)
    monkeypatch.setattr(pipeline, '_failed_evaluation_run', lambda project, trace, error: {'error': error})
    monkeypatch.setattr(pipeline, 'trace_output_source', lambda _: 'live')
    with trace_scope(run_id='batch-retry',case_id='__batch__'):
        result=pipeline._batch_case(0,{'id':'A'},'p')
    assert 'error' not in result, result.get('error')
    assert len(business)==1
    assert {i['run_id'] for i in calls}=={'batch-retry'}
    assert {i['case_id'] for i in calls}=={'A'}
    assert {i['execution_id'] for i in calls} == {'batch-retry:0'}
    assert result['llmtracing']['execution_id']==calls[-1]['execution_id']
    assert result['trace'] is trace
    assert 'metadata' not in to_dict(trace)
    assert to_dict(result)['llmtracing']['run_id']=='batch-retry'
    assert current_identity()=={}


def test_single_real_trace_is_not_mutated_by_tracing():
    from impl.core.schema import RunTrace, to_dict
    captured=[]
    @traced_entry()
    def evaluate(project_id, trace):
        captured.append(trace_headers(role='judge'))
        return trace
    trace = RunTrace(trace_id='t', project_id='p', case_id='A')
    before = to_dict(trace)
    assert evaluate('p', trace) is trace
    assert to_dict(trace) == before
    assert captured[0]['X-Eval-Case-Id'] == 'A'
    assert captured[0]['X-Eval-Harness'] == 'verifier'


@pytest.mark.parametrize('outcome', ['interactive', 'failed', 'exception'])
def test_batch_row_scope_survives_every_result_path(monkeypatch, outcome):
    from impl.core import pipeline
    from impl.server.service import compact_run
    seen = []
    def execute(*args):
        seen.append(trace_headers(role='judge'))
        if outcome == 'exception':
            raise RuntimeError('worker failed')
        return {'case_id': 'duplicate', 'error': 'failed' if outcome == 'failed' else None}
    monkeypatch.setattr(pipeline, '_batch_case_traced', execute)
    monkeypatch.setattr(pipeline, '_batch_error_run', lambda i,c,p,e: {'case_id': c['id'], 'error': str(e)})
    with trace_scope(run_id='job', case_id='__batch__'):
        with ThreadPoolExecutor(2) as workers:
            runs = [f.result() for f in [submit_with_context(workers, pipeline._batch_case, i, {'id':'duplicate'}, 'p') for i in range(2)]]
    assert {h['X-Eval-Execution-Id'] for h in seen} == {'job:0', 'job:1'}
    assert [compact_run(run)['llmtracing']['execution_id'] for run in runs] == ['job:0', 'job:1']
    assert current_identity() == {}
