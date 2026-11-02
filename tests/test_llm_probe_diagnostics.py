"""供应商错误经过真实 SDK → 路由 → ToolLoop → 持久化 API，不发外网请求。"""
import json
import time
import uuid
from urllib.parse import quote

import httpx
import pytest
from fastapi.testclient import TestClient

from impl.core import context_store, llm_client
from impl.core.llm_router import LlmEndpoint, LlmRouter
from impl.tool_loop_lab import service, store
from impl.tool_loop_lab.connection import Connection
from impl.tool_loop_lab.store import LabStore
from impl.tool_loop_lab.__main__ import create_app


@pytest.mark.parametrize('status,message', [
    (400, 'unsupported parameter: temperature'),
    (401, 'invalid API key'),
    (404, 'model_not_found'),
    (429, 'rate_limit_exceeded'),
    (503, 'upstream unavailable'),
    (200, 'missing choices'),
    ('connect', 'DNS lookup failed'),
    ('timeout', 'read timed out'),
])
def test_probe_failure_reaches_lab_and_cooldown_keeps_reason(tmp_path, monkeypatch, status, message):
    requests, contexts = [], []
    key = 'sk-local-diagnostic-secret'
    connection = Connection(base_url='https://local-test.invalid/v1', model='test-' + uuid.uuid4().hex, api_key=key)
    sdk = llm_client.OpenAI

    def respond(request):
        requests.append(json.loads(request.content))
        if status == 'connect': raise httpx.ConnectError(message, request=request)
        if status == 'timeout': raise httpx.ReadTimeout(message, request=request)
        if status == 200: return httpx.Response(200, json={'choices': []})
        return httpx.Response(status, json={'error': {'message': message + ': ' + key, 'type': 'test_error'}})

    monkeypatch.setattr(llm_client, 'OpenAI', lambda **kw: sdk(http_client=httpx.Client(transport=httpx.MockTransport(respond)), **kw))
    monkeypatch.setattr(context_store, 'save_context', lambda record: contexts.append(record) or '')
    monkeypatch.setattr(service, 'load_connection', lambda: connection)
    monkeypatch.setattr(store, 'STORE', LabStore(tmp_path / 'lab.sqlite3'))
    with TestClient(create_app()) as api:
        errors = []
        for _ in range(2):
            response = api.post('/api/tool_loop_lab/start', json={'example_id': 'basic', 'mode': 'model', 'input': 'test'})
            assert response.status_code == 200
            for _ in range(200):
                state = api.get('/api/tool_loop_lab/state').json()
                if state['run']['status'] != 'running': break
                time.sleep(.01)
            assert state['run']['status'] == 'failed'
            error = state['run']['error'];errors.append(error)
            assert '健康检查失败' in error and '连接冷却中' in error
            if status == 200:
                assert '缺少 choices' in error
            else:
                assert message in error
                if isinstance(status, int): assert str(status) in error and '[REDACTED]' in error
            assert key not in json.dumps(state)
            assert not any(e['kind'] == 'tool_start' for e in state['events'])
            before = len(requests)
            assert api.get('/api/tool_loop_lab/state').json()['run']['error'] == error
            assert len(requests) == before  # 查询状态不探活、不重试。
        assert len(requests) == 1  # 同配置第二次启动仍在冷却，保留原原因，不重复请求。
        assert requests[0]['max_tokens'] == 4 and 'Health probe' in requests[0]['messages'][0]['content']
        assert store.LabStore(store.STORE.path).state()['run']['error'] == errors[-1]
    assert key not in json.dumps(contexts, default=str)
    assert key.encode() not in store.STORE.path.read_bytes()


def test_temperature_applies_to_probe_and_tool_turns_without_inheriting_old_cooldown(monkeypatch):
    from impl.core.tool_loop import LoopContext
    from tests.support.fake_openai import FakeOpenAI
    monkeypatch.setattr(context_store, 'save_context', lambda record: '')
    with FakeOpenAI({'': ['OK', [('read_material', {'id': 'note'})], 'finished']}) as fake:
        old = Connection(base_url=fake.base_url, model='temperature-test', api_key='local-test', temperature=0).client()
        endpoint = old.llm_router.endpoints[0]
        old.llm_router.record_failure(endpoint)
        old.llm_router.record_failure(endpoint)
        assert old.llm_router.active_endpoint_names() == []
        new = Connection(base_url=fake.base_url, model='temperature-test', api_key='local-test', temperature=1).client()
        assert new.llm_router is not old.llm_router
        assert new.temperature == new.llm_router.endpoints[0].temperature == 1
        loop = service.load_examples()['EXAMPLES']['basic']['build'](new)
        result = loop.run('read note', LoopContext('temperature-test'))
        assert result.status == 'complete' and result.value == 'finished'
        assert len(fake.requests) == 3
        assert all(request['temperature'] == 1 for request in fake.requests)
        assert fake.requests[0]['max_tokens'] == 4
        assert all(request.get('stream') for request in fake.requests[1:])
        same = Connection(base_url=fake.base_url, model='temperature-test', api_key='local-test', temperature=1).client()
        assert same.llm_router is new.llm_router


def test_router_redacts_encoded_keys_before_storing_and_recovery_clears_diagnostic():
    key = 'secret/"quoted\\key'
    encoded = json.dumps(key)[1:-1]
    endpoint = LlmEndpoint('primary', 'https://local-test.invalid/v1', 'm', key)
    def probe(ep):
        raise RuntimeError(f'rejected {key} {encoded} {quote(key, safe="")}')
    router = LlmRouter([endpoint], probe_fn=probe)
    router.refresh_health_if_stale()
    error = router.unavailable_reason()
    assert 'rejected' in error and '[REDACTED]' in error
    for forbidden in (key, encoded, quote(key, safe='')):
        assert forbidden not in error and forbidden not in router._health['primary'].last_probe_error
    router.record_success(endpoint)
    assert router._health['primary'].last_probe_error == ''
    assert 'rejected' not in router.unavailable_reason()


def test_probe_deadline_has_explicit_reason_and_does_not_accept_late_response():
    import threading
    release = threading.Event()
    router = LlmRouter([LlmEndpoint('primary', 'https://local-test.invalid', 'm', 'local-key')],
                       probe_fn=lambda ep: release.wait(2), probe_wait_seconds=.02)
    try:
        router.refresh_health_if_stale()
        assert '健康检查超时' in router.unavailable_reason()
        assert '不是聚类请求超时' in router.unavailable_reason()
    finally:
        release.set()
    assert router.active_endpoint_names() == []


@pytest.mark.parametrize('policy', ['any', 'same_model'])
@pytest.mark.parametrize('mode', ['step', 'json'])
def test_axis_cooling_failure_preserves_diagnostic_in_real_client(monkeypatch, policy, mode):
    from dataclasses import replace
    from impl.core.config import get_llm_config
    from impl.core.structured_output import FREE_TEXT_OUTPUT
    from impl.projects.llm_probe.eval_axes.llm import AxisLlm
    key = 'sk-local-axis-diagnostic-secret'
    client = llm_client.LlmClient(role='judge', config=replace(
        get_llm_config(), api_key=key, base_url='https://local-test.invalid/v1', fallbacks=()))
    primary = LlmEndpoint('primary', 'https://local-test.invalid/v1', client.model, key)
    alternate = LlmEndpoint('fallback', 'https://local-test.invalid/v1', 'different-model', key)
    router = LlmRouter([primary, alternate], cooldown_seconds=3600)
    client.llm_router = router
    router._record_probe_result(primary, False, 'HTTP 503: upstream unavailable ' + key)
    if policy == 'any':
        router._record_probe_result(alternate, False, 'HTTP 429: rate limited ' + key)
    shell = AxisLlm(client, policy=policy)
    waits, contexts = [], []
    monkeypatch.setattr(llm_client.time, 'sleep', waits.append)
    monkeypatch.setattr(context_store, 'save_context', lambda record: contexts.append(record) or '')
    monkeypatch.setattr(client, 'build_model', lambda **kwargs: pytest.fail('must not send to a cooling or excluded endpoint'))
    if mode == 'step':
        with pytest.raises(RuntimeError) as caught:
            shell.complete_step([{'role':'user', 'content':'organize evidence'}], [], trace_id='axis-cooling', stage='organize')
        message = str(caught.value)
    else:
        result = shell.complete_json('organize evidence', 'input', trace_id='axis-cooling', output_spec=FREE_TEXT_OUTPUT)
        assert result['error'] == 'llm_request_failed'
        message = result['raw_text']
    assert 'AttributeError' not in message and 'unavailable_reason' not in message
    assert 'HTTP 503' in message and '连接冷却中' in message and '[REDACTED]' in message
    assert waits == [30.0, 60.0, 120.0]
    assert contexts and key not in str(contexts)
    assert key not in message
    assert shell.attempts == []
    if policy == 'same_model':
        assert 'same_model' in message and client.model in message
        assert 'fallback' not in message and 'different-model' not in message
        assert router.active_endpoint_names() == ['fallback']
    else:
        assert 'HTTP 429' in message
