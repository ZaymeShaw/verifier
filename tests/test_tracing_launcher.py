from types import SimpleNamespace
from pathlib import Path
import importlib.util
import yaml
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('tracing_launcher', ROOT / 'scripts/tracing.py')
tracing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tracing)


def config():
    return SimpleNamespace(base_url='https://primary.test/v1', api_key='primary-secret', model='main',
        role_policies={'live_stub': SimpleNamespace(base_url=None, model='stub')},
        fallbacks=[SimpleNamespace(base_url=f'https://fallback{i}.test/v1', api_key=f'key-{i}', model='same-model')
                   for i in [1, 2]])


def test_route_generation_preserves_models_keys_and_distinct_upstreams(tmp_path, monkeypatch):
    from impl.core.config_bootstrap import parse_dotenv
    monkeypatch.setattr(tracing, 'RUNTIME', tmp_path / '.runtime/tracing')
    env = tmp_path / '.env'
    env.write_text('DEEPSEEK_API_KEY=original-secret\n')
    before = env.read_bytes()
    llm = config()
    cfg = yaml.safe_load((ROOT / 'tracing/config.yaml').read_text())
    ports = [4005, 4006, 4007]
    routes = tracing.upstream_routes(llm, ports)
    dependency = tmp_path / 'dependency'
    dependency.mkdir()
    (dependency / 'custom_callbacks.py').write_text('# callback entry point\n')
    ctl = SimpleNamespace(parse_env=parse_dotenv, GATEWAY_DIR=dependency)
    overlay = tracing.prepare(routes, cfg, ctl)
    assert (tracing.RUNTIME / 'custom_callbacks.py').is_symlink()
    assert (tracing.RUNTIME / 'custom_callbacks.py').resolve() == dependency / 'custom_callbacks.py'
    assert env.read_bytes() == before
    assert overlay['LLM_BASE_URL'] == 'http://127.0.0.1:4005/v1'
    assert overlay['LLM_FALLBACK_2_BASE_URL'] == 'http://127.0.0.1:4007/v1'
    assert 'LLM_MODEL' not in overlay
    assert overlay['DEEPSEEK_API_KEY'] != llm.api_key
    for route in routes:
        profile = tracing.RUNTIME / ('.env.' + route['name'])
        values = parse_dotenv(profile)
        assert profile.stat().st_mode & 0o777 == 0o600
        assert values['UPSTREAM_API_BASE'] == route['upstream_url']
        assert values['UPSTREAM_API_KEY'] == route['upstream_key']
        assert values['LLM_GATEWAY_THINKING_POLICY'] == 'passthrough'
        generated = yaml.safe_load(Path(values['LITELLM_CONFIG']).read_text())
        assert [m['model_name'] for m in generated['model_list']] == route['models']
        assert all(m['litellm_params']['allowed_openai_params'] == ['reasoning_effort'] for m in generated['model_list'])
    assert routes[0]['models'] == ['main', 'stub']
    assert routes[1]['upstream_url'] != routes[2]['upstream_url']
    # Restarting retains client credentials; changing the source regenerates routes.
    llm.api_key = 'rotated-key'
    assert tracing.prepare(tracing.upstream_routes(llm, ports), cfg, ctl) == overlay
    assert parse_dotenv(tracing.RUNTIME / '.env.verifier_primary')['UPSTREAM_API_KEY'] == 'rotated-key'


def test_refuses_nested_launchers_and_explicit_role_endpoint():
    llm = config()
    llm.base_url = 'http://127.0.0.1:4005/v1/'
    with pytest.raises(ValueError, match='already points'):
        tracing.upstream_routes(llm, [4005, 4006, 4007])
    llm = config()
    llm.role_policies['live_stub'].base_url = llm.base_url
    with pytest.raises(ValueError, match='bypass'):
        tracing.upstream_routes(llm, [4005, 4006, 4007])
