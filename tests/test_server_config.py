from __future__ import annotations

import sys
import types

from impl.server.__main__ import main


def test_server_uses_config_defaults(monkeypatch):
    calls = []
    fake_uvicorn = types.SimpleNamespace(run=lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.delenv("VERIFIER_HOST", raising=False)
    monkeypatch.delenv("VERIFIER_PORT", raising=False)

    main([])

    assert calls[0][1]["host"] == "127.0.0.1"
    assert calls[0][1]["port"] == 8020


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
