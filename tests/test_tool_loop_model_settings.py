import json
import stat

import pytest
from fastapi.testclient import TestClient

from impl.tool_loop_lab import connection, service, store
from impl.tool_loop_lab.__main__ import create_app
from impl.tool_loop_lab.store import LabStore


@pytest.fixture
def settings(tmp_path, monkeypatch):
    path = tmp_path / '.env.tool_loop'
    monkeypatch.setattr(connection, 'ENV_PATH', path)
    for key in connection.NAMES: monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(store, 'STORE', LabStore(tmp_path / 'lab.sqlite3'))
    return path


def save(path, revision, **updates):
    values = dict(base_url='https://supplier.example/v1', model='strong-model', api_key='sk-private-key',
                  reasoning_effort='', timeout=300, expected_revision=revision, path=path, environ={})
    values.update(updates)
    return connection.save_connection(**values)


def test_save_is_atomic_private_and_does_not_touch_public_config(settings):
    public_env = settings.parent / '.env';public_env.write_text('PUBLIC_CONFIG=unchanged\n')
    state = connection.connection_state(settings, {})
    saved = save(settings, state['revision'])
    assert saved['config']['ready'] and saved['config']['key_configured']
    assert 'sk-private-key' not in json.dumps(saved)
    assert connection.load_connection(settings, {}).api_key == 'sk-private-key'
    assert stat.S_IMODE(settings.stat().st_mode) == 0o600
    assert public_env.read_text() == 'PUBLIC_CONFIG=unchanged\n'
    kept = save(settings, saved['revision'], model='another-model', api_key='')
    assert connection.load_connection(settings, {}).api_key == 'sk-private-key'
    assert kept['config']['model'] == 'another-model'


def test_revision_and_address_change_cannot_silently_reuse_or_overwrite_key(settings):
    first = connection.connection_state(settings, {})
    saved = save(settings, first['revision'])
    before = settings.read_bytes()
    with pytest.raises(ValueError, match='其他页面'):
        save(settings, first['revision'], api_key='old-tab-key')
    with pytest.raises(ValueError, match='更换供应商'):
        save(settings, saved['revision'], api_key='', base_url='https://different.example/v1')
    assert settings.read_bytes() == before
    moved = save(settings, saved['revision'], api_key='new-provider-key', base_url='https://different.example/v1')
    assert moved['config']['base_url'] == 'https://different.example/v1'
    assert connection.load_connection(settings, {}).api_key == 'new-provider-key'


def test_process_environment_override_is_explicit_read_only(settings):
    env = {'TOOL_LOOP_MODEL': 'managed'}
    state = connection.connection_state(settings, env)
    assert not state['editable'] and state['managed_by_environment'] == ['TOOL_LOOP_MODEL']
    with pytest.raises(ValueError, match='进程环境变量'):
        save(settings, state['revision'], environ=env)
    assert not settings.exists()


def test_bad_dotenv_or_url_does_not_replace_original(settings):
    saved = save(settings, connection.connection_state(settings, {})['revision'])
    before = settings.read_bytes()
    for overrides in [dict(api_key='key\nmalicious'), dict(api_key='key${VAR}'),
                      dict(base_url='https://user:password@host/v1'), dict(base_url='https://host:bad/v1')]:
        with pytest.raises(ValueError): save(settings, saved['revision'], **overrides)
        assert settings.read_bytes() == before


def test_model_api_never_echoes_secret_and_does_not_make_model_calls(settings, monkeypatch):
    monkeypatch.setattr(connection.Connection, 'client', lambda self: pytest.fail('saving must not call model'))
    with TestClient(create_app()) as api:
        state = api.get('/api/tool_loop_lab/model').json()
        payload = {'base_url': 'https://supplier.example/v1', 'model': 'strong', 'api_key': 'sk-very-secret',
                   'expected_revision': state['revision'], 'temperature': 1}
        saved = api.post('/api/tool_loop_lab/model', json=payload)
        assert saved.status_code == 200, saved.text
        assert 'sk-very-secret' not in saved.text
        assert saved.json()['config']['temperature'] == 1
        assert connection.load_connection(settings, {}).temperature == 1
        assert 'sk-very-secret' not in api.get('/api/tool_loop_lab/catalog').text
        assert api.get('/api/tool_loop_lab/state').json()['run'] is None
        invalid = api.post('/api/tool_loop_lab/model', json={'api_key': 'sk-do-not-echo'})
        assert invalid.status_code == 422 and 'sk-do-not-echo' not in invalid.text
        assert api.post('/api/tool_loop_lab/model', json=payload).status_code == 409
        assert api.post('/api/tool_loop_lab/model', json=payload, headers={'Origin': 'https://evil.example'}).status_code == 403
        assert connection.load_connection(settings, {}).api_key == 'sk-very-secret'
