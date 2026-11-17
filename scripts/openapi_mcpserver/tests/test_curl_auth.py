import asyncio
import json
from urllib.parse import parse_qs

import httpx2 as httpx
import pytest
import yaml
from fastmcp import Client

from curl_mcp.auth import load_handlers
from curl_mcp.config import Settings, load
from curl_mcp.curl_auth import load_curl, select_token
from curl_mcp.generate import generate, generate_project
from curl_mcp.runtime import Runtime


def project(tmp_path, command, token_path='/data/access_token'):
    (tmp_path / 'auth.txt').write_text(command)
    spec = generate('curl https://business.invalid/query --json \'{"query":"test"}\'', 'query')
    (tmp_path / 'openapi.json').write_text(json.dumps(spec))
    config = {'operations': {'query': {
        'url': 'https://business.invalid/query',
        'auth': {'curl': 'auth.txt', 'token_path': token_path},
        'headers': {'Authorization': 'Bearer ${token}'},
        'inject_body': {'credentials': {'access_token': '${token}'}},
    }}}
    (tmp_path / 'config.yaml').write_text(yaml.safe_dump(config))
    return load(tmp_path / 'config.yaml')


@pytest.mark.parametrize('command,kind', [
    ("curl -X POST 'https://auth.invalid/token?client_secret=${env.SECRET}'", 'query'),
    ("curl -X POST '${env.URL}' --url-query 'client_secret=${env.SECRET}'", 'query'),
    ("curl https://auth.invalid/token --json '{\"client_secret\":\"${env.SECRET}\"}'", 'json'),
    ("curl https://auth.invalid/token --data-urlencode 'client_secret=${env.SECRET}'", 'form'),
    ("curl https://auth.invalid/token -d 'client_secret=${env.SECRET}'", 'form'),
])
async def test_curl_request_encoding_and_token_in_header_and_body(tmp_path, command, kind):
    settings, spec = project(tmp_path, command)
    secret = 's&=+密钥'
    requests = []

    def handler(req):
        requests.append(req)
        if req.url.host == 'auth.invalid':
            if kind == 'query':
                assert req.url.params['client_secret'] == secret
                assert not req.content
            elif kind == 'form':
                assert parse_qs(req.content.decode())['client_secret'] == [secret]
                assert req.headers['content-type'] == 'application/x-www-form-urlencoded'
            else:
                assert json.loads(req.content) == {'client_secret': secret}
            return httpx.Response(200, json={'data': {'access_token': 'call-token'}})
        assert req.headers['Authorization'] == 'Bearer call-token'
        assert json.loads(req.content) == {'query': 'test', 'credentials': {'access_token': 'call-token'}}
        return httpx.Response(200, json={'result': 'ok'})

    env = {'SECRET': secret, 'URL': 'https://auth.invalid/token'}
    runtime = Runtime(settings, spec, httpx.MockTransport(handler), env=env)
    try:
        async with Client(runtime.server) as client:
            assert (await client.call_tool('query', {'query': 'test'})).data == {'result': 'ok'}
        assert len(requests) == 2
        assert 'token' not in env
    finally:
        await runtime.aclose()


async def test_concurrent_tools_keep_tokens_local_and_auth_failure_does_not_reuse(tmp_path, monkeypatch):
    settings, spec = project(tmp_path, 'curl https://auth.invalid/token')
    monkeypatch.setenv('token', 'untouched-process-value')
    issued = 0
    received = []

    async def handler(req):
        nonlocal issued
        if req.url.host == 'auth.invalid':
            issued += 1
            n = issued
            await asyncio.sleep(0.01 if n % 2 else 0)
            if n == 5:
                return httpx.Response(200, json={'data': {}})
            return httpx.Response(200, json={'data': {'access_token': f'token-{n}'}})
        token = json.loads(req.content)['credentials']['access_token']
        assert req.headers['Authorization'] == 'Bearer ' + token
        received.append(token)
        return httpx.Response(200, json={'ok': True})

    runtime = Runtime(settings, spec, httpx.MockTransport(handler), env={})
    try:
        async with Client(runtime.server) as client:
            await asyncio.gather(*(client.call_tool('query', {'query': str(i)}) for i in range(4)))
            assert set(received) == {f'token-{n}' for n in range(1, 5)}
            failed = await client.call_tool('query', {'query': 'fifth'}, raise_on_error=False)
            assert failed.is_error
            assert len(received) == 4
        import os
        assert os.environ['token'] == 'untouched-process-value'
    finally:
        await runtime.aclose()


@pytest.mark.parametrize('command', [
    "curl https://auth.invalid --header 'Authorization: ${token}'",
    "curl https://auth.invalid --header 'X-Key: ${env.MISSING}'",
    "curl https://auth.invalid --data-binary @credentials.json",
    "curl -k https://auth.invalid",
    "curl -L https://auth.invalid",
    "curl https://auth.invalid | echo secret",
])
def test_invalid_auth_curl_fails_before_serving_without_leaking_secrets(tmp_path, command):
    settings, _ = project(tmp_path, command)
    with pytest.raises(ValueError, match='Cannot load auth handler') as error:
        load_handlers(settings, {})
    assert 'secret' not in str(error.value)


async def test_auth_http_failure_blocks_business_call(tmp_path):
    settings, spec = project(tmp_path, 'curl https://auth.invalid/token')
    requests = []

    def handler(req):
        requests.append(req)
        return httpx.Response(401, json={'error': 'secret-credential'})

    runtime = Runtime(settings, spec, httpx.MockTransport(handler), env={})
    try:
        async with Client(runtime.server) as client:
            result = await client.call_tool('query', {'query': 'test'}, raise_on_error=False)
            assert result.is_error and 'secret-credential' not in str(result)
        assert len(requests) == 1
    finally:
        await runtime.aclose()


def test_pointer_handles_nested_keys_and_array_indices():
    assert select_token({'a/b': [{'~key': 'token'}]}, '/a~1b/0/~0key') == 'token'
    with pytest.raises(ValueError):
        select_token(['one', 'two'], '/-1')


def test_token_reference_requires_auth():
    with pytest.raises(ValueError, match='requires auth'):
        Settings.model_validate({'operations': {'query': {
            'url': 'https://example.invalid', 'auth': None, 'headers': {'token': '${token}'},
        }}})


def test_business_curl_import_preserves_explicit_token_and_env_bindings(tmp_path):
    (tmp_path / 'query.txt').write_text('''curl https://business.invalid/query \
      -H 'Authorization: Bearer ${token}' \
      --json '{"query":"example","credentials":{"token":"${token}"},"user_id":"${env.USER_ID}"}' ''')
    spec, config = generate_project(tmp_path)
    schema = spec['paths']['/query']['post']['requestBody']['content']['application/json']['schema']
    assert set(schema['properties']) == {'query'}
    op = config['operations']['query']
    assert op['headers'] == {'Authorization': 'Bearer ${token}'}
    assert op['inject_body'] == {'credentials': {'token': '${token}'}, 'user_id': '${env.USER_ID}'}


async def test_get_auth_with_basic_credentials_and_custom_header(tmp_path):
    command = "curl https://auth.invalid/token -u '${env.USER}:${env.PASS}' -H 'X-Key: prefix-${env.KEY}'"
    settings, spec = project(tmp_path, command)
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.host == 'auth.invalid':
            assert request.method == 'GET'
            assert request.headers['Authorization'] == 'Basic dXNlcjpwYXNz'
            assert request.headers['X-Key'] == 'prefix-key'
            return httpx.Response(200, json={'data': {'access_token': 'fresh'}})
        assert request.headers['Authorization'] == 'Bearer fresh'
        return httpx.Response(200, json={'ok': True})

    runtime = Runtime(settings, spec, httpx.MockTransport(handler), env={'USER': 'user', 'PASS': 'pass', 'KEY': 'key'})
    try:
        async with Client(runtime.server) as client:
            assert (await client.call_tool('query', {'query': 'test'})).data == {'ok': True}
        assert len(seen) == 2
    finally:
        await runtime.aclose()


async def test_script_auth_uses_same_token_placement_contract(tmp_path):
    settings, spec = project(tmp_path, 'curl https://unused.invalid')
    (tmp_path / 'custom.py').write_text('async def fetch(env): return env["API_KEY"]\n')
    settings.operations['query'].auth = 'custom.py:fetch'
    seen = []

    def handler(request):
        seen.append(request)
        assert request.headers['Authorization'] == 'Bearer script-token'
        assert json.loads(request.content)['credentials']['access_token'] == 'script-token'
        return httpx.Response(200, json={'ok': True})

    runtime = Runtime(settings, spec, httpx.MockTransport(handler), env={'API_KEY': 'script-token'})
    try:
        async with Client(runtime.server) as client:
            await client.call_tool('query', {'query': 'test'})
        assert len(seen) == 1
    finally:
        await runtime.aclose()
