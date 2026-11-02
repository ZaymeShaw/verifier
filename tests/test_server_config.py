from __future__ import annotations

import sys
import types

import pytest

from impl.core import config as runtime_config
from impl.server.__main__ import main
from impl.core import instances


@pytest.fixture(autouse=True)
def reset_config_between_server_starts(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_config, "DOTENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(instances, 'ROOT', tmp_path)
    original_activate = instances.activate
    def scoped_activate(instance):
        for name in ('VERIFIER_INSTANCE_ID', 'VERIFIER_PORT', 'CONTEXT_DATA_ROOT', 'CONTEXT_STORE_ROOT'):
            monkeypatch.setenv(name, __import__('os').environ.get(name, ''))
        original_activate(instance)
    monkeypatch.setattr('impl.server.__main__.activate', scoped_activate)
    monkeypatch.delenv('VERIFIER_TRACING_ENABLED', raising=False)
    runtime_config.reset_runtime_config_for_tests()
    yield
    runtime_config.reset_runtime_config_for_tests()


def test_server_uses_config_defaults(monkeypatch):
    calls = []
    fake_uvicorn = types.SimpleNamespace(run=lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.delenv("VERIFIER_HOST", raising=False)
    monkeypatch.delenv("VERIFIER_PORT", raising=False)
    configured = runtime_config.get_runtime_config().server

    main([])

    assert calls[0][1]["host"] == configured.host
    assert calls[0][1]["port"] == configured.port


def test_server_uses_env_port(monkeypatch):
    calls = []
    fake_uvicorn = types.SimpleNamespace(run=lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.setenv("VERIFIER_PORT", "18020")

    main([])

    assert calls[0][1]["port"] == 18020


def test_server_cli_overrides_env(monkeypatch):
    calls = []
    fake_uvicorn = types.SimpleNamespace(run=lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.setenv("VERIFIER_PORT", "18020")

    main(["--port", "19020", "--host", "0.0.0.0"])

    assert calls[0][1]["host"] == "0.0.0.0"
    assert calls[0][1]["port"] == 19020
