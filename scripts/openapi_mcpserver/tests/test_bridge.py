import asyncio
import copy
import json
import os
from pathlib import Path

import httpx2 as httpx
import pytest
from fastmcp import Client

from curl_mcp.config import Settings, load
from curl_mcp.runtime import Runtime

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "projects/insurance-tools"
EXAMPLES = json.loads((ROOT / "tests/fixtures/tool_arguments.json").read_text())


@pytest.mark.parametrize('name,field', [
    ('customer_query', 'queryLogic'), ('policy_query', 'filter'),
])
async def test_noauth_draft_rejects_missing_upstream_required_fields(name, field):
    settings, spec = load(PROJECT / 'draft-noauth/config.draft.yaml')
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'code': 0})

    runtime = Runtime(settings, spec, httpx.MockTransport(handler),
                      env={'MCP_AGENT_NUMBER': 'test-agent', 'MCP_AUTH_SUBJECT': 'test-subject'})
    try:
        async with Client(runtime.server) as client:
            arguments = {key: value for key, value in EXAMPLES[name].items() if key != field}
            result = await client.call_tool(name, arguments, raise_on_error=False)
            assert result.is_error
            assert calls == []
            result = await client.call_tool(name, EXAMPLES[name])
            assert result.data['code'] == 0
            assert len(calls) == 1
            assert json.loads(calls[0].content)[field] == EXAMPLES[name][field]
            assert 'token' not in calls[0].headers
    finally:
        await runtime.aclose()


@pytest.mark.parametrize('deployment', ['config.local.yaml', 'draft/config.draft.yaml', 'draft-noauth/config.draft.yaml'])
@pytest.mark.parametrize('name,source', [
    ('faq_search', 'askbob'), ('product_retrieve', 'product_wiki'), ('benefit_search', 'quanyi_wiki'),
])
async def test_source_is_injected_and_cannot_be_supplied_by_model(deployment, name, source):
    settings, spec = load(PROJECT / deployment)
    # Auth is tested separately; this exercises the actual schema and body rules of each deployment.
    for operation in settings.operations.values():
        operation.auth = None
        operation.headers = {}
    calls = []

    def handler(request):
        calls.append(request)
        assert json.loads(request.content)['source'] == source
        return httpx.Response(200, json={'code': 0})

    runtime = Runtime(settings, spec, httpx.MockTransport(handler),
                      env={'MCP_AGENT_NUMBER': 'test-agent', 'MCP_AUTH_SUBJECT': 'test-subject'})
    try:
        async with Client(runtime.server) as client:
            tool = next(t for t in await client.list_tools() if t.name == name)
            assert 'source' not in tool.input_schema['properties']
            assert 'source' not in tool.input_schema.get('required', [])
            assert 'source' not in EXAMPLES[name]
            result = await client.call_tool(name, EXAMPLES[name])
            assert result.data['code'] == 0
            result = await client.call_tool(name, {**EXAMPLES[name], 'source': 'wrong'}, raise_on_error=False)
            assert result.is_error
            assert len(calls) == 1
    finally:
        await runtime.aclose()


async def test_noauth_policy_parse_injects_fresh_trace_and_args():
    from uuid import UUID
    settings, spec = load(PROJECT / 'draft-noauth/config.draft.yaml')
    traces = []

    def handler(request):
        body = json.loads(request.content)
        UUID(body['trace_id'])
        assert body['extra_input_params']['args'] == {'contexts': []}
        assert 'token' not in request.headers
        traces.append(body['trace_id'])
        return httpx.Response(200, json={'code': 0})

    runtime = Runtime(settings, spec, httpx.MockTransport(handler),
                      env={'MCP_AGENT_NUMBER': 'test-agent', 'MCP_AUTH_SUBJECT': 'test-subject'})
    try:
        async with Client(runtime.server) as client:
            for _ in range(2):
                result = await client.call_tool('policy_parse', EXAMPLES['policy_parse'])
                assert result.data['code'] == 0
        assert len(set(traces)) == 2
    finally:
        await runtime.aclose()


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_AGENT_NUMBER", "test-agent")
    monkeypatch.setenv("MCP_AUTH_SUBJECT", "test-subject")
    settings, spec = load(PROJECT / "config.local.yaml")
    paths = {item["post"]["operationId"]: path for path, item in spec["paths"].items()}
    for name, operation in settings.operations.items():
        operation.url = "https://api.test.invalid" + paths[name]
    monkeypatch.setenv("ARK_TOKEN_URL", "https://auth.test.invalid/token")
    auth_dir = tmp_path / "auth_curls"
    auth_dir.mkdir()
    for name in settings.operations:
        text = (PROJECT / "auth_curls" / f"{name}.txt").read_text()
        text = text.replace("grant_type=待填写", "grant_type=test-grant").replace("invokeInterface=待填写", "invokeInterface=" + name)
        (auth_dir / f"{name}.txt").write_text(text)
    settings._project_dir = tmp_path
    for variable in ("ARK_CLIENT_ID", "ARK_CLIENT_SECRET"):
        monkeypatch.setenv(variable, "test-value")
    return settings, spec


def runtime_with_mock(settings, spec, transport):
    return Runtime(settings, spec, transport, env=dict(os.environ))


async def test_all_ten_tools_match_source_wire_contract(config):
    settings, spec = config
    captured = []

    def handler(req):
        captured.append(req)
        if req.url.path == "/token":
            return httpx.Response(200, json={"code": "0", "access_token": "secret-test-token", "expires_in": 60})
        return httpx.Response(200, json={"code": 0, "data": {"原始字段": [1, "2", None]}})

    runtime = runtime_with_mock(settings, spec, httpx.MockTransport(handler))
    fixtures = json.loads((ROOT / "tests/fixtures/source_requests.json").read_text())
    try:
        async with Client(runtime.server) as client:
            tools = await client.list_tools()
            assert {t.name for t in tools} == set(EXAMPLES)
            for name, args in EXAMPLES.items():
                result = await client.call_tool(name, args)
                assert result.data == {"code": 0, "data": {"原始字段": [1, "2", None]}}
                request = captured[-1]
                assert request.method == "POST"
                assert request.url.path == fixtures[name]["path"]
                assert request.headers["token"] == "secret-test-token"
                assert "authorization" not in request.headers
                actual = json.loads(request.content)
                expected = copy.deepcopy(fixtures[name]["body"])
                # Only policy_parse requires tracing in the current upstream contract.
                for field in ("trace_id", "traceId"):
                    if name == "policy_parse" and field == "trace_id":
                        from uuid import UUID
                        UUID(actual[field])
                        assert actual[field] != actual["session_id"]
                        expected[field] = actual[field]
                        continue
                    expected.pop(field, None)
                    assert field not in actual
                # Normalize only fields still generated by the runtime.
                for field in ["session_id"]:
                    if field in expected:
                        assert isinstance(actual[field], str) and actual[field]
                        expected[field] = actual[field]
                if name == "policy_parse":
                    stamp = actual["extra_input_params"]["policySearchParseArgs"]["currentTime"]
                    assert len(stamp) == 19
                    expected["extra_input_params"]["policySearchParseArgs"]["currentTime"] = stamp
                assert actual == expected, name
        assert sum(r.url.path == "/token" for r in captured) == 10
    finally:
        await runtime.aclose()


async def test_defaults_and_identity_override_rejected(config):
    settings, spec = config
    requests = []
    settings.operations["policy_query"].auth = None
    settings.operations["policy_query"].headers = {}

    def handler(req):
        requests.append(req)
        return httpx.Response(200, json={"code": 0})

    runtime = runtime_with_mock(settings, spec, httpx.MockTransport(handler))
    try:
        async with Client(runtime.server) as client:
            result = await client.call_tool("policy_query", {"filter": EXAMPLES["policy_query"]["filter"]})
            assert not result.is_error
            body = json.loads(requests[-1].content)
            assert (body["pageNo"], body["pageSize"], body["empno"]) == (1, 5, "test-agent")
            result = await client.call_tool("policy_query", {**EXAMPLES["policy_query"], "empno": "other"}, raise_on_error=False)
            assert result.is_error
            assert len(requests) == 1
    finally:
        await runtime.aclose()


async def test_ark_query_parameters_are_encoded_and_fetched_each_time(config, monkeypatch):
    monkeypatch.setenv("ARK_CLIENT_SECRET", "s&?=密钥")
    settings, spec = config
    calls = []

    async def handler(req):
        calls.append(req)
        token = "t" + str(len(calls))
        await asyncio.sleep(0.01)
        return httpx.Response(200, json={"access_token": token})

    runtime = runtime_with_mock(settings, spec, httpx.MockTransport(handler))
    try:
        provider = runtime.bridge.providers["policy_query"]
        values = await asyncio.gather(*(provider.token(runtime.upstream) for _ in range(8)))
        assert set(values) == {"t" + str(i) for i in range(1, 9)}
        assert len(calls) == 8
        assert calls[0].method == "POST"
        assert calls[0].url.params["client_secret"] == "s&?=密钥"
        assert calls[0].url.params["invokeInterface"] == "policy_query"
        assert not calls[0].content
        assert await provider.token(runtime.upstream) == "t9"
    finally:
        await runtime.aclose()


@pytest.mark.parametrize("body", [
    {"code": "failure"},
    {"access_token": "bad\ntoken"},
    {"access_token": None},
    {"access_token": ""},
    {"access_token": {"secret": "secret"}},
])
async def test_invalid_auth_fails_without_business_request(config, body):
    settings, spec = config
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json=body)

    runtime = runtime_with_mock(settings, spec, httpx.MockTransport(handler))
    try:
        async with Client(runtime.server) as client:
            result = await client.call_tool("policy_query", EXAMPLES["policy_query"], raise_on_error=False)
            assert result.is_error
            assert "secret" not in str(result)
        assert len(calls) == 1 and calls[0].url.path == "/token"
    finally:
        await runtime.aclose()


async def test_http_failure_not_replayed_or_leaked(config):
    settings, spec = config
    calls = []

    def handler(req):
        calls.append(req)
        if req.url.path == "/token":
            return httpx.Response(200, json={"code": "0", "access_token": "secret", "expires_in": 60})
        return httpx.Response(401, json={"token": "secret"})

    runtime = runtime_with_mock(settings, spec, httpx.MockTransport(handler))
    try:
        async with Client(runtime.server) as client:
            result = await client.call_tool("policy_query", EXAMPLES["policy_query"], raise_on_error=False)
            assert result.is_error and "secret" not in str(result)
        assert len(calls) == 2
    finally:
        await runtime.aclose()


@pytest.mark.parametrize("body", [
    {"code": 9, "message": "business rejected", "data": None},
    {"code": "0", "data": {"items": []}},
    {"items": [1, 2]},
])
async def test_business_json_returned_unchanged(config, body):
    settings, spec = config
    settings.operations["policy_query"].auth = None
    settings.operations["policy_query"].headers = {}
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=body)

    runtime = runtime_with_mock(settings, spec, httpx.MockTransport(handler))
    try:
        async with Client(runtime.server) as client:
            result = await client.call_tool("policy_query", EXAMPLES["policy_query"])
            assert not result.is_error
            assert result.data == body
        assert len(calls) == 1
    finally:
        await runtime.aclose()


async def test_auth_time_counts_toward_total_timeout(config):
    settings, spec = config
    settings.operations["policy_query"].timeout_seconds = 0.02
    calls = []

    async def handler(req):
        calls.append(req)
        await asyncio.sleep(0.1)
        return httpx.Response(200, json={"code": "0", "access_token": "t", "expires_in": 60})

    runtime = runtime_with_mock(settings, spec, httpx.MockTransport(handler))
    try:
        async with Client(runtime.server) as client:
            result = await client.call_tool("policy_query", EXAMPLES["policy_query"], raise_on_error=False)
            assert result.is_error
        assert len(calls) == 1
    finally:
        await runtime.aclose()


def test_auth_reference_requires_explicit_configuration(config):
    settings, _ = config
    raw = settings.model_dump()
    raw["operations"]["policy_query"]["auth"] = "misspelled"
    with pytest.raises(ValueError):
        Settings.model_validate(raw)
    del raw["operations"]["policy_query"]["auth"]
    with pytest.raises(ValueError):
        Settings.model_validate(raw)
