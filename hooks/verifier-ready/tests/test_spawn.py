from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import spawn_reviewer as spawn


def result(sid='sid', case='case-a'):
    return {'spawn_id': sid, 'case_id': case, 'coverage': [], 'relations': [], 'common_rules': [],
            'findings': [], 'carry_over': [], 'output_checks': [], 'summary': 'Evidence reviewed.'}


def assistant(text, **extra):
    return {'type': 'message_end', 'message': {'role': 'assistant', 'model': 'model', 'provider': 'fake',
                                             'content': [{'type': 'text', 'text': text}],
                                             'usage': {'input': 20, 'output': 10}, **extra}}


def profile(model='fake/model'):
    return {'reviewer': {'spawn': 'pi', 'model': model, 'parallel': 4, 'timeout_s': 7200,
                         'commands': {'pi': ['pi', '-p', '--mode', 'json', '--no-session',
                                             '--model', '{model}', '--tools', 'read,bash,grep,find,ls',
                                             '--append-system-prompt', '{system_prompt_file}', '{task}']}}}


def test_result_is_exact_json_only():
    value = json.dumps(result())
    assert spawn.parse_result(value) == result()
    assert spawn.parse_result('explanation ' + value) is None
    assert spawn.parse_result('```json\n' + value + '\n```') is None
    assert spawn.parse_result(value + ' extra') is None
    assert spawn.parse_result(value[:-1]) is None
    assert spawn.parse_result(json.dumps({'spawn_id': 'sid', 'findings': []})) is None


def test_pi_captures_actual_tool_result_and_last_complete_message():
    events = [
        {'type': 'tool_execution_start', 'toolCallId': 'read-1', 'toolName': 'read', 'args': {'path': '/chunk'}},
        {'type': 'tool_execution_end', 'toolCallId': 'read-1', 'toolName': 'read',
         'isError': False, 'result': {'content': [{'type': 'text', 'text': 'entire chunk'}],
                                     'details': {'truncation': {'truncated': False}}}},
        assistant(json.dumps(result('old'))), assistant('non-result'), assistant(json.dumps(result()))]
    review, tools, messages, errors = spawn.extract_pi('\n'.join(json.dumps(e) for e in events))
    assert review['spawn_id'] == 'sid'
    assert tools[0]['completed']
    assert tools[0]['result']['content'][0]['text'] == 'entire chunk'
    assert len(messages) == 3
    assert not errors


def test_tool_start_is_not_completed_evidence():
    _, tools, _, _ = spawn.extract_pi(json.dumps({'type': 'tool_execution_start', 'toolCallId': 'id',
                                                  'toolName': 'read', 'args': {'path': '/chunk'}}))
    assert not tools[0]['completed']
    assert tools[0]['result'] is None


def test_cli_extraction_without_claiming_tool_reads():
    value = json.dumps(result())
    claude = spawn.extract_claude(json.dumps({'result': value, 'usage': {'input_tokens': 5}}))
    codex = spawn.extract_codex(value)
    assert claude[0] == result() and not claude[1]
    assert codex[0] == result() and not codex[1]
    assert spawn.extract_claude('{bad')[0] is None
    assert spawn.extract_codex('noise' + value)[0] is None
    assert spawn.extract_claude(json.dumps({'result': value, 'is_error': True}))[3]


def test_model_error_even_with_valid_json_is_preserved():
    _, _, _, errors = spawn.extract_pi(json.dumps(assistant(json.dumps(result()), stopReason='error',
                                                           errorMessage='unsupported model')))
    assert errors == ['unsupported model']


class Process:
    pid = 987654
    def __init__(self, argv, **kwargs):
        kwargs['stdout'].write(json.dumps(assistant(json.dumps(result()))) + '\n')
        self.kwargs = kwargs
    def wait(self, timeout=None):
        assert timeout == 7200
        return 0


def test_spawn_pinned_clean_pi_and_usage(tmp_path):
    with patch.object(spawn.subprocess, 'Popen', Process):
        output = spawn.run(tmp_path, 'case-a', profile(), 'read the chunks', spawn_id='sid')
    meta = output['meta']
    assert meta['has_result'] and meta['exit_code'] == 0
    assert meta['usage'] == {'input': 20, 'output': 10}
    assert meta['model_requests'] == 1
    for flag in ('--no-skills', '--no-context-files', '--no-prompt-templates', '--no-extensions'):
        assert flag in meta['command']
    assert '--model' in meta['command']
    assert not meta['errors']
    assert not meta['scope_valid']  # Global audit is performed by review.run, not per shard.


def test_exit_zero_without_json_is_failure(tmp_path):
    class Empty(Process):
        def __init__(self, argv, **kwargs):
            pass
    with patch.object(spawn.subprocess, 'Popen', Empty):
        output = spawn.run(tmp_path, 'case-a', profile(), 'read chunks', spawn_id='sid')
    assert output['meta']['exit_code'] == 0
    assert not output['meta']['has_result']
    assert not (tmp_path / 'spawn/case-a/result.json').exists()


def test_timeout_kills_process_group(tmp_path):
    class Timeout(Process):
        def __init__(self, argv, **kwargs):
            self.waits = 0
        def wait(self, timeout=None):
            self.waits += 1
            if self.waits <= 2:
                raise subprocess.TimeoutExpired('pi', timeout)
            return -9
    with patch.object(spawn.subprocess, 'Popen', Timeout), patch.object(spawn.os, 'killpg') as kill:
        output = spawn.run(tmp_path, 'case-a', profile(), 'read chunks', spawn_id='sid')
    assert output['meta']['exit_code'] == -1
    assert output['meta']['errors'] == ['timeout']
    assert kill.call_count == 2
    assert all(call.args[0] == Timeout.pid for call in kill.call_args_list)


def test_pinned_model_mismatch_invalidates_result(tmp_path):
    with patch.object(spawn.subprocess, 'Popen', Process):
        output = spawn.run(tmp_path, 'case-a', profile('fake/other'), 'read chunks', spawn_id='sid')
    assert output['meta']['has_result']
    assert 'reviewer_model_mismatch' in output['meta']['errors']


def test_private_flash_registration_preserves_endpoint_and_cleans_up(tmp_path):
    home = tmp_path / 'home'
    agent = home / '.pi/agent'
    agent.mkdir(parents=True)
    provider = {'baseUrl': 'https://same-endpoint.example/v1', 'api': 'openai-completions',
                'apiKey': 'secret-test-key', 'models': [{'id': 'qwen3.8-max'}]}
    models = agent / 'models.json'
    models.write_text(json.dumps({'providers': {'dashscope': provider, 'other': {'apiKey': 'other-secret'}}}))
    auth = agent / 'auth.json'
    auth.write_text(json.dumps({'dashscope': {'type': 'api_key', 'key': 'auth-secret'}, 'other': {}}))
    config = profile('dashscope/qwen3.8-flash')['reviewer']
    with patch.object(spawn.Path, 'home', return_value=home), spawn.pi_agent_dir(config) as (directory, error):
        assert not error
        assert directory != agent
        value = json.loads((directory / 'models.json').read_text())
        assert set(value['providers']) == {'dashscope'}
        assert value['providers']['dashscope']['baseUrl'] == provider['baseUrl']
        assert value['providers']['dashscope']['apiKey'] == provider['apiKey']
        assert value['providers']['dashscope']['models'][0]['id'] == 'qwen3.8-flash'
        assert (directory / 'models.json').stat().st_mode & 0o777 == 0o600
        assert (directory / 'auth.json').stat().st_mode & 0o777 == 0o600
        assert set(json.loads((directory / 'auth.json').read_text())) == {'dashscope'}
    assert not directory.exists()
    assert json.loads(models.read_text())['providers']['dashscope'] == provider


def test_explicit_agent_dir_must_register_pinned_model(tmp_path):
    (tmp_path / 'models.json').write_text(json.dumps({'providers': {'dashscope': {'models': [{'id': 'qwen3.8-max'}]}}}))
    config = profile('dashscope/qwen3.8-flash')['reviewer']
    config['agent_dir'] = str(tmp_path)
    with spawn.pi_agent_dir(config) as (directory, error):
        assert directory is None
        assert error.startswith('unsupported_model:')
    assert not (tmp_path / 'auth.json').exists()


def test_jsonc_uses_installed_dependency_no_credentials_in_command(tmp_path):
    source = tmp_path / '.pi/agent'
    source.mkdir(parents=True)
    (source / 'models.json').write_text('{ // comments\n "providers": {} }')
    dependency = source / 'npm/node_modules/strip-json-comments/index.js'
    dependency.parent.mkdir(parents=True)
    dependency.write_text('// stub')
    completed = subprocess.CompletedProcess([], 0, stdout=json.dumps({'providers': {'dashscope': {'apiKey': 'secret-not-in-command'}}}), stderr='')
    with patch.object(spawn.Path, 'home', return_value=tmp_path), patch.object(spawn.subprocess, 'run', return_value=completed) as run:
        value = spawn.read_pi_config(source)
    assert value['providers']['dashscope']['apiKey'] == 'secret-not-in-command'
    command = run.call_args.args[0]
    assert 'secret-not-in-command' not in repr(command)
    assert 'trailingCommas:true' in repr(command)
    assert run.call_args.kwargs['capture_output']
