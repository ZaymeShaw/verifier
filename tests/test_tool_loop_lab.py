import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from impl.core import context_store, llm_client
from impl.core.tool_loop import Hook, LoopContext, Step, ToolLoop
from impl.tool_loop_lab import service, store
from impl.tool_loop_lab.connection import Connection, load_connection
from impl.tool_loop_lab.observation import BoundaryGuard, observe
from impl.tool_loop_lab.store import LabStore
from impl.tool_loop_lab.__main__ import create_app
from tests.support.fake_openai import FakeOpenAI


@pytest.mark.parametrize('submit', [True, False])
def test_observation_preserves_round_budget_feedback_and_immediate_completion(submit):
    from impl.core.tool_loop import BudgetStop
    from tests.test_tool_loop_round_budget import Client, Completed, tools

    batch = [('read', {'value': str(i)}) for i in range(13)]
    if submit:
        batch.append(('submit', {}))
    client, events = Client([batch]), []
    loop = ToolLoop('round-test', 'system', tools([]), client, completion_hook=Completed(),
                    budget=BudgetStop(llm_calls=1), end=lambda h: h.llm_calls)
    observed = observe(loop, lambda kind, data: events.append((kind, data)), BoundaryGuard(lambda: False))
    result = observed.run('go', LoopContext('test'))
    assert result.status == ('complete' if submit else 'failed')
    assert result.llm_calls == len(client.requests) == 1
    assert len(result.calls) == 13 + int(submit)
    assert '剩余 1 轮（含本轮）' in client.requests[0][-1]['content']
    if submit:
        assert result.value == 1
    else:
        assert result.reason == 'budget: llm_calls 已达上限 1'
    assert any(kind == 'hook' and data['event'] == 'before_step' for kind, data in events)


@pytest.fixture
def lab(tmp_path, monkeypatch):
    current = LabStore(tmp_path / 'lab.sqlite3')
    monkeypatch.setattr(store, 'STORE', current)
    monkeypatch.setattr(service, 'load_connection', lambda: Connection())
    with TestClient(create_app()) as api:
        yield api, current


def finished(api):
    for _ in range(100):
        state = api.get('/api/tool_loop_lab/state').json()
        if state['run'] and state['run']['status'] != 'running': return state
        time.sleep(.02)
    pytest.fail('scripted run did not finish')


def test_scripted_completion_runs_real_hooks_and_exposes_final_value(lab):
    api, current = lab
    result = api.post('/api/tool_loop_lab/start', json={'example_id': 'checked', 'input': 'demo', 'mode': 'scripted'})
    assert result.status_code == 200, result.text
    state = finished(api)
    assert state['run']['status'] == 'complete', state['run']
    output = state['run']['result']
    assert output['value']['evidence_ids'] == ['note']
    assert output['final_message'] != output['value']['answer']
    hooks = [e['data'] for e in state['events'] if e['kind'] == 'hook']
    assert any(h['core_completion'] and h['decision'] == 'Continue' for h in hooks)
    assert any(h['hook'] == 'DependsOn' and h['decision'] == 'Deny' for h in hooks)
    assert any(h['core_completion'] and h['decision'] == 'Done' for h in hooks)
    assert any(e['kind'] == 'tool_result' and e['data']['result'].get('accepted') is False for e in state['events'])
    assert output['model_requests'] == 6
    assert len([e for e in state['events'] if e['kind'] == 'model_request']) == 6
    restored = LabStore(current.path).state()
    assert restored['run']['result'] == output
    last = state['events'][-1]['seq']
    incremental = api.get('/api/tool_loop_lab/state', params={'run_id': state['run']['id'], 'after': last}).json()
    assert incremental['events'] == [] and not incremental['reset']


def test_latest_run_overwrites_not_accumulates(lab):
    api, current = lab
    for example in ['checked', 'basic']:
        api.post('/api/tool_loop_lab/start', json={'example_id': example, 'input': 'demo'})
        state = finished(api)
    assert state['run']['metadata']['example_id'] == 'basic'
    assert state['run']['result']['model_requests'] == 2
    assert sum(e['kind'] == 'run_start' for e in state['events']) == 1
    assert not any(e['kind'] == 'hook' and e['data']['hook'] == 'RequireDone' for e in state['events'])


def test_no_key_does_not_start_real_model_or_expose_key(lab):
    api, current = lab
    catalog = api.get('/api/tool_loop_lab/catalog').json()
    assert not catalog['model']['ready']
    assert 'api_key' not in catalog['model']
    error = api.post('/api/tool_loop_lab/start', json={'example_id': 'basic', 'input': 'demo', 'mode': 'model'})
    assert error.status_code == 409 and 'TOOL_LOOP_API_KEY' in error.text
    assert current.state()['run'] is None
    assert api.post('/api/tool_loop_lab/start', json={'example_id': 'basic', 'input': 'x', 'code': 'arbitrary'}).status_code == 422
    assert api.post('/api/tool_loop_lab/start', json={'example_id': '../outside.py', 'input': 'x'}).status_code == 409
    assert api.get('/api/tool_loop_lab/catalog', headers={'Origin': 'https://other.example'}).status_code == 403


def test_connection_is_independent_and_environment_is_explicit(tmp_path):
    path = tmp_path / '.env.tool_loop'
    path.write_text('TOOL_LOOP_BASE_URL=https://independent.example/v1\nTOOL_LOOP_MODEL=strong\nTOOL_LOOP_API_KEY=independent-key\n')
    c = load_connection(path, {'LLM_MODEL': 'public', 'DEEPSEEK_API_KEY': 'public-key'})
    assert c.model == 'strong' and c.api_key == 'independent-key'
    assert c.problems() == []
    assert 'independent-key' not in json.dumps(c.public()) and 'independent-key' not in repr(c)
    c2 = load_connection(path, {'TOOL_LOOP_MODEL': 'override'})
    assert c2.model == 'override'
    path.write_text('UNRELATED_CONFIG=x\n')
    with pytest.raises(ValueError, match='未识别'): load_connection(path, {})
    assert not Connection(timeout=float('nan')).problems() == []
    assert Connection(base_url='https://user:secret@host/v1').public()['base_url'] != 'https://user:secret@host/v1'


def test_real_client_uses_local_openai_compatible_endpoint_and_same_loop(monkeypatch):
    monkeypatch.setattr(context_store, 'save_context', lambda record: '')
    monkeypatch.setattr(llm_client.LlmClient, '_endpoint_probe', staticmethod(lambda endpoint: True))
    with FakeOpenAI({'材料问答助手': [[('read_material', {'id': 'note'})], 'local model answer']}) as fake:
        client = Connection(base_url=fake.base_url, model='independent-model', api_key='local-test-key').client()
        assert len(client.llm_router.endpoints) == 1
        assert client.llm_router.endpoints[0].base_url == fake.base_url
        example = service.load_examples()['EXAMPLES']['basic']
        events = []
        loop = observe(example['build'](client), lambda kind, data: events.append((kind, data)), BoundaryGuard(lambda: False))
        result = loop.run('read note', LoopContext('local-test'))
    assert result.status == 'complete' and result.value == 'local model answer'
    assert all(request['model'] == 'independent-model' for request in fake.requests)
    assert len(fake.requests) == 2
    assert any(kind == 'tool_result' for kind, _ in events)


def test_stop_is_cooperative_and_prevents_followup_steps(lab, monkeypatch):
    api, current = lab
    gate = threading.Event();entered = threading.Event()
    class HeldClient:
        def complete_step(self, *args, **kwargs):
            entered.set()
            assert gate.wait(10)
            return Step({'role': 'assistant', 'content': 'late answer'})
    module = service.load_examples()
    module['EXAMPLES']['basic']['script_client'] = lambda: HeldClient()
    monkeypatch.setattr(service, 'load_examples', lambda: module)
    try:
        start = api.post('/api/tool_loop_lab/start', json={'example_id': 'basic', 'input': 'demo'}).json()
        assert entered.wait(5)
        assert api.post('/api/tool_loop_lab/start', json={'example_id': 'basic', 'input': 'again'}).status_code == 409
        assert api.post('/api/tool_loop_lab/stop', json={'run_id': start['run_id']}).status_code == 200
        state = api.get('/api/tool_loop_lab/state').json()
        assert state['run']['status'] == 'running' and state['run']['cancel_requested']
    finally:
        gate.set()
    state = finished(api)
    assert state['run']['status'] == 'cancelled'
    assert state['run']['result'] is None


def test_failure_redacts_supplier_key(lab, monkeypatch):
    api, _ = lab
    class BadConnection(Connection):
        def client(self):
            key = self.api_key
            class BadClient:
                def complete_step(self, *args, **kwargs): raise ValueError('upstream failed: ' + key)
            return BadClient()
    monkeypatch.setattr(service, 'load_connection', lambda: BadConnection(base_url='https://example.com/v1', model='m', api_key='sk-private-test'))
    api.post('/api/tool_loop_lab/start', json={'example_id': 'basic', 'input': 'test', 'mode': 'model'})
    state = finished(api)
    assert state['run']['status'] == 'failed'
    assert 'sk-private-test' not in json.dumps(state)
    assert '[REDACTED]' in state['run']['error']


def test_python_example_edits_apply_next_run_and_previous_result_stays_frozen(lab, tmp_path, monkeypatch):
    api, _ = lab
    source = service.EXAMPLES_PATH.read_text()
    example_path = tmp_path / 'examples.py'
    example_path.write_text(source)
    (tmp_path / 'clustering_example.py').write_text(service.EXAMPLES_PATH.with_name('clustering_example.py').read_text())
    monkeypatch.setattr(service, 'EXAMPLES_PATH', example_path)
    api.post('/api/tool_loop_lab/start', json={'example_id': 'basic', 'input': 'demo'})
    first = finished(api)
    before = next(e for e in first['events'] if e['kind'] == 'tool_result')['data']['result']['text']
    example_path.write_text(source.replace('演示设备的维护窗口是周三 14:00–16:00，变更前需要通知值班人员。', '更新后的测试材料'))
    assert api.get('/api/tool_loop_lab/state').json()['run']['result'] == first['run']['result']
    api.post('/api/tool_loop_lab/start', json={'example_id': 'basic', 'input': 'demo'})
    second = finished(api)
    after = next(e for e in second['events'] if e['kind'] == 'tool_result')['data']['result']['text']
    assert before != after and after == '更新后的测试材料'
    assert second['run']['metadata']['source_sha256'] != first['run']['metadata']['source_sha256']


def test_clustering_loop_delivers_a_complete_visual_artifact(lab):
    api, _ = lab
    response = api.post('/api/tool_loop_lab/start', json={'example_id': 'clustering', 'input': 'show situations', 'mode': 'scripted'})
    assert response.status_code == 200, response.text
    state = finished(api)
    assert state['run']['status'] == 'complete', state['run']
    value = state['run']['result']['value']
    assert value['kind'] == 'axes_clustering' and value['data_source'] == 'synthetic-demo'
    assert len(value['cases']) == 8 and value['criteria'] == 'show situations'
    clusters = [cluster for axis in value['clustering']['axes'] for label in axis['labels'] for cluster in label['clusters']]
    assert len(clusters) == 5
    assert all(set(cluster['member_evidence']) == set(cluster['member_refs']) for cluster in clusters)
    assert set(ref for cluster in clusters for ref in cluster['member_refs']) == set(value['clustering']['refs'])
    assert any(e['kind'] == 'tool_result' and e['data']['tool'] == 'submit_clustering' and not e['data']['result']['accepted'] for e in state['events'])
    assert any(e['kind'] == 'hook' and e['data']['core_completion'] and e['data']['decision'] == 'Done' for e in state['events'])
    assert any(e['kind'] == 'tool_start' and e['data']['tool'] == 'read_case' for e in state['events'])
    assert api.get('/frontend/tool_loop_lab_artifact.html').status_code == 200


def test_clustering_real_client_path_delivers_same_artifact_contract(monkeypatch):
    monkeypatch.setattr(context_store, 'save_context', lambda record: '')
    monkeypatch.setattr(llm_client.LlmClient, '_endpoint_probe', staticmethod(lambda endpoint: True))
    example = service.load_examples()['EXAMPLES']['clustering']
    scripted = example['script_client']()
    replies = []
    while True:
        try: message = scripted.complete_step().message
        except StopIteration: break
        if message.get('tool_calls'):
            replies.append([(call['function']['name'], json.loads(call['function']['arguments'])) for call in message['tool_calls']])
        else: replies.append(message['content'])
    with FakeOpenAI({'评估结果的浏览目录': replies}) as fake:
        client = Connection(base_url=fake.base_url, model='independent-cluster-model', api_key='local-test-key').client()
        result = example['build'](client).run('cluster visible situations', LoopContext('local-cluster-test'))
    assert result.status == 'complete'
    assert result.value['kind'] == 'axes_clustering'
    assert len(result.value['cases']) == 8
    assert result.value['criteria'] == 'cluster visible situations'
    assert all(request['model'] == 'independent-cluster-model' for request in fake.requests)
    assert len(fake.requests) == 6


def test_clustering_submit_cannot_bypass_reading_or_coverage():
    example = service.load_examples()['EXAMPLES']['clustering']
    loop = example['build'](None)
    from impl.core.tool_loop import Call, History, Deny, Continue
    guard = loop.hooks['pre_tool'][0]
    assert isinstance(guard.pre_tool(History(), Call(0, 'submit_clustering', {}, 0)), Deny)
    submit = next(t for t in loop.tools if t.tool_id == 'submit_clustering')
    assert submit.execute_fn(axes=[])['accepted'] is False
    assert isinstance(loop.completion_hook.stop(History(), 0), Continue)
    assert '历史上下文未带入' not in loop.system_prompt  # 脚本的类名不是给真实模型的标准答案。


def test_observation_does_not_change_completion_semantics():
    class Core(Hook):
        def stop(self, history, blocked):
            from impl.core.tool_loop import Failed
            return Failed('core refused')
    class Client:
        def complete_step(self, *args, **kwargs): return Step({'role': 'assistant', 'content': 'done'})
    base = ToolLoop('test', 'test', [], Client(), completion_hook=Core(), hooks={'stop': [Hook()]})
    events = []
    result = observe(base, lambda k, d: events.append((k, d)), BoundaryGuard(lambda: False)).run('x', LoopContext('t'))
    assert result.status == 'failed' and result.reason == 'core refused'
    assert any(d.get('core_completion') and d.get('decision') == 'Failed' for k, d in events if k == 'hook')
