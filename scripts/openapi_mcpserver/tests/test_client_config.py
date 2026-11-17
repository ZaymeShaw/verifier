import json
from pathlib import Path

import pytest
from fastmcp.mcp_config import MCPConfig

from curl_mcp.client_config import export_client_config


@pytest.mark.parametrize('host,expected', [
    ('0.0.0.0', '127.0.0.1'), ('::', '[::1]'), ('::1', '[::1]'),
    ('localhost', 'localhost'), ('192.0.2.1', '192.0.2.1'),
])
def test_http_client_address_handles_bind_hosts(tmp_path, host, expected):
    target, config = export_client_config('sample', 'http', tmp_path / '.env', tmp_path / 'config.yaml',
                                         tmp_path / 'server.py', {'host': host, 'port': 8000, 'path': '/mcp'},
                                         tmp_path / 'exports')
    assert config == {'mcpServers': {'sample': {'url': f'http://{expected}:8000/mcp'}}}
    assert json.loads(target.read_text()) == config
    MCPConfig.model_validate(config)


def test_stdio_export_retains_virtualenv_executable_and_exact_arguments(tmp_path, monkeypatch):
    import sys
    python = tmp_path / 'space dir/.venv/bin/python'
    monkeypatch.setattr(sys, 'executable', str(python))
    (tmp_path / 'draft').mkdir()
    target, config = export_client_config('sample', 'stdio', tmp_path / 'my .env', tmp_path / 'draft/config.yaml',
                                         tmp_path / 'server.py', {}, tmp_path / 'exports')
    entry = config['mcpServers']['sample']
    assert entry['command'] == str(python)
    assert entry['args'] == [str(tmp_path / 'server.py'), '--env-file', str(tmp_path / 'my .env'),
                             '--config', str(tmp_path / 'draft/config.yaml'), '--transport', 'stdio']
    MCPConfig.model_validate(config)
    assert not list(target.parent.glob('.mcp-client-*'))


def test_export_replaces_only_current_transport_file(tmp_path):
    output = tmp_path / 'nested/client files'
    args = ('sample', 'http', tmp_path / '.env', tmp_path / 'config.yaml', tmp_path / 'server.py')
    options = {'host': '127.0.0.1', 'port': 8000, 'path': '/mcp'}
    http_file, _ = export_client_config(*args, options, output)
    stdio_file, _ = export_client_config('sample', 'stdio', args[2], args[3], args[4], {}, output)
    stdio_before = stdio_file.read_bytes()
    http_file.write_text('{"manual": "discarded on export"}')
    _, config = export_client_config(*args, {**options, 'port': 8123}, output)
    assert json.loads(http_file.read_text()) == config
    assert config['mcpServers']['sample']['url'] == 'http://127.0.0.1:8123/mcp'
    assert stdio_file.read_bytes() == stdio_before
    assert not (tmp_path / 'mcp.client.http.json').exists()
