import json
import sys

import httpx2 as httpx
import pytest
import yaml
from fastmcp import Client

from curl_mcp.auth import load_handlers
from curl_mcp.config import load
from curl_mcp.generate import generate
from curl_mcp.runtime import Runtime


def project(tmp_path, script, handler="auth.py:main"):
    (tmp_path / "auth.py").write_text(script)
    (tmp_path / "openapi.json").write_text(json.dumps(generate(
        "curl https://example.invalid/query --json '{\"query\":\"test\"}'", "query")))
    (tmp_path / "config.local.yaml").write_text(yaml.safe_dump({
        "operations": {"query": {"url": "https://example.invalid/query", "auth": handler}},
    }))
    return load(tmp_path / "config.local.yaml")


async def test_env_script_loads_once_with_runtime_isolation(tmp_path):
    settings, _ = project(tmp_path, 'count = 0\nasync def main(env):\n    global count\n    count += 1\n    return str(count)\n')
    providers = load_handlers(settings, {})
    assert await providers["query"].token() == "1"
    assert await providers["query"].token() == "2"
    other = load_handlers(settings, {})
    assert await other["query"].token() == "1"
    providers.close()
    other.close()


async def test_named_functions_share_module_but_return_separate_tokens(tmp_path):
    settings, _ = project(tmp_path,
        'async def policy_token(env): return env["TOKEN"]\n'
        'async def customer_token(env): return "customer-token"\n',
        handler="auth.py:policy_token")
    settings.operations["query"].headers = {"Authorization": "Bearer ${token}"}
    settings.operations["customer"] = settings.operations["query"].model_copy(deep=True)
    settings.operations["customer"].auth = "auth.py:customer_token"
    providers = load_handlers(settings, {"TOKEN": "policy-token"})
    try:
        assert await providers["query"].token() == "policy-token"
        assert await providers["customer"].token() == "customer-token"
        assert providers["query"].function.__globals__ is providers["customer"].function.__globals__
    finally:
        providers.close()


async def test_relative_helper_shared_within_runtime_and_removed_on_close(tmp_path):
    settings, _ = project(tmp_path,
        'from . import helper\nasync def main(env):\n    helper.count += 1\n    return str(helper.count)\n')
    (tmp_path / "helper.py").write_text("count = 0\n")
    (tmp_path / "second.py").write_text(
        'from . import helper\nasync def main(env):\n    helper.count += 1\n    return str(helper.count)\n')
    settings.operations["second"] = settings.operations["query"].model_copy(deep=True)
    settings.operations["second"].auth = "second.py:main"
    providers = load_handlers(settings, {})
    namespace = providers.namespace
    try:
        assert await providers["query"].token() == "1"
        assert await providers["second"].token() == "2"
        assert namespace + ".helper" in sys.modules
    finally:
        providers.close()
    assert not any(name == namespace or name.startswith(namespace + ".") for name in sys.modules)


@pytest.mark.parametrize("script", [
    'def main(): return "token"',
    'async def main(): return "token"',
    'async def main(interface): return "token"',
    'raise ValueError("secret-credential")',
    'async def wrong_name(): return "token"',
])
def test_bad_script_fails_before_serving_without_exception_leak(tmp_path, script):
    settings, _ = project(tmp_path, script)
    with pytest.raises(ValueError, match="Cannot load auth handler") as error:
        load_handlers(settings, {})
    assert "secret-credential" not in str(error.value)


async def test_env_is_explicit_snapshot_and_script_cannot_mutate_shared_values(tmp_path, monkeypatch):
    monkeypatch.setenv("API_KEY", "wrong-process-value")
    settings, _ = project(tmp_path,
        'async def main(env):\n    return env.pop("API_KEY")\n')
    env = {"API_KEY": "provided-token"}
    providers = load_handlers(settings, env)
    env["API_KEY"] = "changed-after-load"
    assert await providers["query"].token() == "provided-token"
    assert await providers["query"].token() == "provided-token"
    providers.close()


@pytest.mark.parametrize("script", [
    'async def main(env): return ""',
    'async def main(env): return {"token": "secret"}',
    'async def main(env): return "secret\\r\\ninjected"',
    'async def main(env): raise ValueError("secret-credential")',
])
async def test_auth_failure_never_reaches_business_api(tmp_path, script):
    settings, spec = project(tmp_path, script)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"code": 0})

    runtime = Runtime(settings, spec, httpx.MockTransport(handler), env={})
    try:
        async with Client(runtime.server) as client:
            result = await client.call_tool("query", {"query": "test"}, raise_on_error=False)
            assert result.is_error
            assert "secret" not in str(result)
            assert calls == []
    finally:
        await runtime.aclose()
