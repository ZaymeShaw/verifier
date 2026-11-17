"""UTF-8 project files must work even when the OS defaults to GBK."""
import json
from pathlib import Path

import pytest

from curl_mcp.config import load
from curl_mcp.curl_auth import load_curl
from curl_mcp.generate import generate_project, write_drafts


def test_generation_and_runtime_files_ignore_gbk_default(tmp_path, monkeypatch):
    original_open = Path.open

    def gbk_open(self, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
        if 'b' not in mode and encoding in (None, 'locale'):
            encoding = 'gbk'
        return original_open(self, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, 'open', gbk_open)
    project = tmp_path / '服务😀'
    curls = project / 'curls'
    curls.mkdir(parents=True)
    sample = curls / 'query.txt'
    sample.write_bytes('curl https://api.example/query -H \'token: ${token}\' --json \'{"query":"问题😀","source":"${env.SOURCE}"}\''.encode('utf-8'))
    # Prove that an implicit read fails under the simulated Windows locale.
    with pytest.raises(UnicodeDecodeError):
        sample.read_text()
    auth = project / 'auth_curls'
    auth.mkdir()
    (auth / 'query.txt').write_bytes('curl https://auth.example/token --json \'{"client_id":"客户😀"}\''.encode('utf-8'))
    spec, generated = generate_project(curls, token_path='/access_token')
    spec['paths']['/query']['post']['summary'] = '查询😀'
    output = tmp_path / 'draft'
    write_drafts(output, spec, generated, source_dir=project)
    assert json.loads((output / 'openapi.draft.json').read_bytes().decode('utf-8')) == spec
    settings, loaded = load(output / 'config.draft.yaml')
    assert settings.name == '服务😀'
    assert settings.operations['query'].inject_body == {'source': '${env.SOURCE}'}
    assert loaded == spec
    provider = load_curl(output, settings.operations['query'].auth.curl, '/access_token', {})
    assert provider.kwargs['json'] == {'client_id': '客户😀'}
