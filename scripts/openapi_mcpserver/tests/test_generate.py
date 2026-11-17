import json
import shlex
import subprocess
import sys
from pathlib import Path

import httpx2 as httpx
import pytest
import yaml
from fastmcp import Client
from jsonschema import Draft202012Validator

from curl_mcp.config import Settings, load
from curl_mcp.generate import generate, generate_project, parse_curl, write_drafts
from curl_mcp.runtime import Runtime

ROOT = Path(__file__).resolve().parents[1]


def curl(body, path="/query"):
    return "curl 'https://upstream.test.invalid" + path + "' --json " + shlex.quote(json.dumps(body, ensure_ascii=False))


def test_infers_structure_without_inventing_business_contract():
    body = {"name": "001", "active": True, "page": 1, "ratio": 0.5,
            "unknown": None, "empty": [], "options": {},
            "conditions": [{"field": "age", "value": 18}, {"field": "name", "value": "张"}]}
    operation = generate(curl(body), "query")["paths"]["/query"]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    Draft202012Validator(schema).validate(body)
    properties = schema["properties"]
    assert properties["name"]["type"] == "string"
    assert properties["active"]["type"] == "boolean"
    assert properties["page"]["type"] == "integer"
    assert properties["ratio"]["type"] == "number"
    assert "type" not in properties["unknown"]
    assert "type" not in properties["empty"]["items"]
    assert properties["options"]["additionalProperties"] is True
    assert set(properties["conditions"]["items"]["properties"]["value"]["type"]) == {"integer", "string"}
    assert "required" not in schema
    assert "default" not in properties["page"]
    assert operation["description"] == "待补充"
    assert all(child["description"] == "待补充" for child in properties.values())
    assert "001" not in json.dumps(schema)  # Values aren't embedded as defaults or enums.


@pytest.mark.parametrize("command", [
    "",
    "curl https://example.invalid/query",
    "curl https://example.invalid/query --json '[]'",
    "curl 'https://example.invalid/query?key=value' --json '{}'",
    "curl 'https://example.invalid/query/{id}' --json '{}'",
    "curl https://example.invalid/query -X GET --json '{}'",
    "curl https://example.invalid/query --json '{}' --json '{}'",
    "curl https://example.invalid/query --data-binary @body.json",
    "curl https://example.invalid/query --json '{}' | cat",
    "curl https://example.invalid/query --json '{}' ; curl https://second.invalid --json '{}'",
    """curl https://example.invalid/query --json '{"x": NaN}'""",
    "curl https://example.invalid/query -H 'Content-Type: text/plain' -d '{}'",
    """curl https://example.invalid/query --data '{"x":1,"x":2}'""",
    "curl https://example.invalid/query --unsupported sensitive-value --json '{}'",
    "curl --url https://one.invalid --url https://two.invalid --json '{}'",
])
def test_rejects_ambiguous_or_unsupported_commands(command):
    with pytest.raises(ValueError) as error:
        generate(command)
    assert "sensitive-value" not in str(error.value)


@pytest.mark.parametrize("flag", ["--data", "--data-raw", "--data-binary", "--json"])
def test_multiline_curl_preserves_body_and_omits_credentials(flag):
    body = {"text": "O'Reilly 的引号、空格 ; $(echo text)", "nested": {"enabled": False}}
    command = ("curl --location --request POST 'https://private.invalid/api/query' \\\n"
               " --header 'Content-Type: application/json' \\\n"
               " --header 'Authorization: Bearer header-secret' -b 'sid=cookie-secret' \\\n"
               " -u 'user:password-secret' " + flag + " " + shlex.quote(json.dumps(body, ensure_ascii=False)))
    url, parsed = parse_curl(command)
    assert url == "https://private.invalid/api/query"
    assert parsed == body
    spec = generate(command)
    encoded = json.dumps(spec)
    for secret in ("header-secret", "cookie-secret", "password-secret", "private.invalid"):
        assert secret not in encoded
    assert spec["paths"]["/api/query"]["post"]["operationId"] == "post_api_query"


def test_url_option_and_double_quoted_json():
    url, body = parse_curl(r'curl --url https://example.invalid/query -XPOST -d "{\"text\":\"hello\"}"')
    assert url == "https://example.invalid/query" and body == {"text": "hello"}


def test_does_not_rewrite_backslash_newline_inside_quoted_body():
    invalid_body = '{"text":"a' + "\\\n" + 'b"}'
    with pytest.raises(ValueError, match="valid JSON"):
        parse_curl("curl https://example.invalid --data-raw '" + invalid_body + "'")


def test_cli_generates_matching_drafts_without_overwriting_manual_work(tmp_path):
    sources = tmp_path / "curls"
    sources.mkdir()
    (sources / "customer_query.txt").write_text(curl({"query": "test"}, "/customers"))
    (sources / "policy_query.txt").write_text(curl({"page": 1}, "/policies") + " -H 'token: header-secret'")
    command = [sys.executable, str(ROOT / "generate_openapi.py")]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    spec_file = tmp_path / "openapi.draft.json"
    config_file = tmp_path / "config.draft.yaml"
    spec = json.loads(spec_file.read_text())
    config = yaml.safe_load(config_file.read_text())
    assert config["openapi"] == spec_file.name
    assert {item["post"]["operationId"] for item in spec["paths"].values()} == set(config["operations"])
    assert config["operations"] == {
        "customer_query": {"url": "https://upstream.test.invalid/customers", "auth": "待填写"},
        "policy_query": {"url": "https://upstream.test.invalid/policies", "auth": "待填写"},
    }
    assert "header-secret" not in spec_file.read_text() + config_file.read_text()
    with pytest.raises(ValueError, match="Python file:function"):
        load(config_file)  # Unreviewed auth cannot silently become anonymous.
    spec_file.write_text("manually edited")
    old_config = config_file.read_bytes()
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert spec_file.read_text() == "manually edited"
    assert config_file.read_bytes() == old_config


@pytest.mark.parametrize("existing", ["openapi.draft.json", "config.draft.yaml"])
def test_either_existing_draft_prevents_both_writes(tmp_path, existing):
    target = tmp_path / existing
    target.write_text("keep")
    with pytest.raises(ValueError, match="overwrite"):
        write_drafts(tmp_path, {}, {})
    assert list(tmp_path.iterdir()) == [target]
    assert target.read_text() == "keep"


def test_duplicate_routes_across_hosts_fail_without_outputs(tmp_path):
    sources = tmp_path / "curls"
    sources.mkdir()
    (sources / "first.txt").write_text(curl({"a": 1}))
    (sources / "second.txt").write_text(curl({"b": 1}).replace("upstream.test.invalid", "another.test.invalid"))
    result = subprocess.run([sys.executable, str(ROOT / "generate_openapi.py"), str(sources)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert "Duplicate POST path" in result.stderr
    assert not (tmp_path / "openapi.draft.json").exists()
    assert not (tmp_path / "config.draft.yaml").exists()


@pytest.mark.parametrize("filename", ["two__names.txt", "has-dash.txt", "UpperCase.txt", "a" * 57 + ".txt"])
def test_names_that_fastmcp_would_rewrite_are_rejected(tmp_path, filename):
    (tmp_path / filename).write_text(curl({"a": 1}))
    with pytest.raises(ValueError, match="snake_case"):
        generate_project(tmp_path)


def test_empty_directory_and_invalid_sample_fail_clearly(tmp_path):
    with pytest.raises(ValueError, match="No .txt"):
        generate_project(tmp_path)
    (tmp_path / "good.txt").write_text(curl({"a": 1}))
    (tmp_path / "bad.txt").write_text("curl --unsupported secret-value")
    with pytest.raises(ValueError, match="bad.txt") as error:
        generate_project(tmp_path)
    assert "secret-value" not in str(error.value)


async def test_generated_schema_can_register_and_call_through_fastmcp():
    bodies = json.loads((ROOT / "tests/fixtures/tool_arguments.json").read_text())
    fixtures = json.loads((ROOT / "tests/fixtures/source_requests.json").read_text())
    cases = {name: {"path": fixtures[name]["path"], "body": body} for name, body in bodies.items()}
    specs = [generate(curl(case["body"], case["path"]), name) for name, case in cases.items()]
    spec = {**specs[0], "paths": {path: value for item in specs for path, value in item["paths"].items()}}
    settings = Settings.model_validate({"operations": {
        name: {"url": "https://upstream.test.invalid" + case["path"], "auth": None}
        for name, case in cases.items()
    }})
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"code": 0, "data": "fixture"})

    runtime = Runtime(settings, spec, httpx.MockTransport(handler), env={})
    try:
        async with Client(runtime.server) as client:
            assert {tool.name for tool in await client.list_tools()} == set(cases)
            for name, case in cases.items():
                result = await client.call_tool(name, case["body"])
                assert result.data == {"code": 0, "data": "fixture"}
                assert json.loads(captured[-1].content) == case["body"]
                assert captured[-1].url.path == case["path"]
    finally:
        await runtime.aclose()


async def test_curls_are_authoritative_despite_stale_same_named_operation(tmp_path):
    sources = tmp_path / 'curls'
    sources.mkdir()
    auth_dir = tmp_path / 'auth_curls'
    auth_dir.mkdir()
    (auth_dir / 'query.txt').write_text("curl '${env.AUTH_URL}'")
    (sources / 'query.txt').write_text(curl({'query': 'hello', 'agentNo': '${env.AGENT}',
                                          'extra': {'query': 'keep', 'time': '${time_utc8}'}}, '/query')
                                      + " -H 'token: ${token}'")
    existing = {'name': 'reviewed', 'operations': {'query': {
        'url': 'https://old.invalid/query',
        'auth': {'curl': 'auth_curls/shared.txt', 'token_path': '/data/token'},
        'headers': {'Authorization': 'Bearer ${token}'},
        'inject_body': {'agentno': '${env.WRONG_AGENT}', 'extra': {'time': 'stale-time'}},
        'timeout_seconds': 75.0,
    }}}
    (tmp_path / 'config.local.yaml').write_text(yaml.safe_dump(existing))
    spec, config = generate_project(sources, token_path='/access_token')
    op = config['operations']['query']
    assert op['url'] == 'https://upstream.test.invalid/query'
    assert config['name'] == tmp_path.name
    assert op['auth'] == {'curl': 'auth_curls/query.txt', 'token_path': '/access_token'}
    assert 'timeout_seconds' not in op
    assert op['headers'] == {'token': '${token}'}
    assert op['inject_body'] == {'agentNo': '${env.AGENT}', 'extra': {'time': '${time_utc8}'}}
    # An old or malformed config is not an input, even if it has matching tool names.
    (tmp_path / 'config.local.yaml').write_text('not: [valid yaml')
    assert generate_project(sources, token_path='/access_token') == (spec, config)
    props = spec['paths']['/query']['post']['requestBody']['content']['application/json']['schema']['properties']
    assert set(props) == {'query', 'extra'}
    assert set(props['extra']['properties']) == {'query'}
    draft = tmp_path / 'draft'
    write_drafts(draft, spec, config, source_dir=tmp_path)
    assert not (draft / "auth_curls").exists()
    loaded, loaded_spec = load(draft / 'config.draft.yaml')
    assert loaded.operations['query'].auth.token_path == '/access_token'
    assert loaded.operations['query'].auth.curl == '../auth_curls/query.txt'
    assert not (draft / '.env').exists()
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == 'auth.invalid':
            return httpx.Response(200, json={'access_token': 'fresh-token'})
        assert request.url == 'https://upstream.test.invalid/query'
        assert request.headers['token'] == 'fresh-token'
        assert 'Authorization' not in request.headers
        body = json.loads(request.content)
        assert body.keys() == {'query', 'agentNo', 'extra'}
        assert body['agentNo'] == 'current-agent'
        assert body['extra']['query'] == 'keep'
        assert body['extra']['time'] != 'stale-time'
        return httpx.Response(200, json={'ok': True})

    runtime = Runtime(loaded, loaded_spec, httpx.MockTransport(handler),
                      env={'AUTH_URL': 'https://auth.invalid/token', 'AGENT': 'current-agent'})
    try:
        async with Client(runtime.server) as client:
            result = await client.call_tool('query', {'query': 'hello', 'extra': {'query': 'keep'}})
            assert result.data == {'ok': True}
        assert len(requests) == 2
    finally:
        await runtime.aclose()


def test_literal_samples_are_not_hidden_by_unrelated_deployment_config():
    project = ROOT / 'projects/insurance-tools'
    spec, config = generate_project(project / 'curls')
    operations = {item['post']['operationId']: item['post'] for item in spec['paths'].values()}
    for name, source in [('faq_search', 'askbob'), ('product_retrieve', 'product_wiki'),
                         ('benefit_search', 'quanyi_wiki')]:
        assert 'source' not in config['operations'][name].get('inject_body', {})
        schema = operations[name]['requestBody']['content']['application/json']['schema']
        assert schema['properties']['source']['type'] == 'string'
        assert 'source' not in schema.get('required', [])


def test_new_project_matches_auth_filename_but_requires_confirmed_token_path(tmp_path):
    sources = tmp_path / 'curls'
    sources.mkdir()
    (tmp_path / 'auth_curls').mkdir()
    (tmp_path / 'auth_curls/query.txt').write_text('curl https://auth.invalid/token')
    (sources / 'query.txt').write_text(curl({'query': 'hello'}))
    _, config = generate_project(sources)
    assert config['operations']['query']['auth'] == {'curl': 'auth_curls/query.txt', 'token_path': '待填写'}
    with pytest.raises(ValueError, match='JSON Pointer'):
        Settings.model_validate(config)
    _, confirmed = generate_project(sources, token_path='/data/access_token')
    assert Settings.model_validate(confirmed).operations['query'].auth.token_path == '/data/access_token'


def test_explicit_placeholder_needs_no_existing_config(tmp_path):
    sources = tmp_path / 'curls'
    sources.mkdir()
    (sources / 'query.txt').write_text(curl({'query': 'hello', 'empno': '${env.OTHER}'}))
    config = {'operations': {'query': {'url': 'https://api.invalid/query', 'auth': None,
                                      'inject_body': {'empno': '${env.AGENT}'}}}}
    (tmp_path / 'config.local.yaml').write_text(yaml.safe_dump(config))
    with_existing = generate_project(sources)
    (tmp_path / 'config.local.yaml').unlink()
    assert generate_project(sources) == with_existing
    assert with_existing[1]['operations']['query']['inject_body'] == {'empno': '${env.OTHER}'}


def test_drafts_do_not_read_or_overwrite_unrelated_auth_assets(tmp_path):
    source = tmp_path / 'project'
    (source / 'auth_curls').mkdir(parents=True)
    (source / 'auth_curls/query.txt').write_text('shared source')
    draft = tmp_path / 'draft'
    (draft / 'auth_curls').mkdir(parents=True)
    asset = draft / 'auth_curls/query.txt'
    asset.write_text('unrelated hand edited file')
    config = {'operations': {'query': {'auth': {'curl': 'auth_curls/query.txt', 'token_path': '/token'}}}}
    write_drafts(draft, {}, config, source_dir=source)
    assert asset.read_text() == 'unrelated hand edited file'
    generated = yaml.safe_load((draft / 'config.draft.yaml').read_text())
    assert generated['operations']['query']['auth']['curl'] == '../project/auth_curls/query.txt'


def test_fully_injected_request_accepts_no_model_fields(tmp_path):
    (tmp_path / 'query.txt').write_text(curl({'token': '${token}'}))
    spec, _ = generate_project(tmp_path)
    schema = spec['paths']['/query']['post']['requestBody']['content']['application/json']['schema']
    Draft202012Validator(schema).validate({})
    from jsonschema import ValidationError
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate({'token': 'model-controlled'})
