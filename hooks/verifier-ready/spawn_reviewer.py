"""Spawn an isolated stdout-only reviewer and preserve actual tool result evidence."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import tempfile
import uuid

from common import HERE, ROOT, now, read_json, safe_id, write_json

RESULT_FIELDS = {'spawn_id', 'case_id', 'coverage', 'relations', 'common_rules',
                 'findings', 'carry_over', 'output_checks', 'summary'}


def parse_result(text):
    """Only a complete JSON message is a result; arbitrary embedded objects are not."""
    if not isinstance(text, str):
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    if not isinstance(value, dict) or not RESULT_FIELDS <= value.keys():
        return None
    if not all(isinstance(value[k], list) for k in
               ('coverage', 'relations', 'common_rules', 'findings', 'carry_over', 'output_checks')):
        return None
    if not all(isinstance(value[k], str) for k in ('spawn_id', 'case_id', 'summary')):
        return None
    return value


def content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(block.get('text', '') for block in content
                       if isinstance(block, dict) and block.get('type') == 'text'
                       and isinstance(block.get('text'), str))
    return ''


def extract_pi(stdout):
    texts, messages, tools, errors = [], [], [], []
    pending = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get('type')
        if kind == 'tool_execution_start':
            call = {'id': event.get('toolCallId'), 'tool': event.get('toolName'),
                    'args': event.get('args', {}), 'result': None, 'is_error': False,
                    'completed': False}
            tools.append(call)
            pending[event.get('toolCallId')] = call
        elif kind == 'tool_execution_end':
            call = pending.pop(event.get('toolCallId'), None)
            if call is not None:
                call.update(result=event.get('result'), is_error=event.get('isError', False),
                            completed=True)
        elif kind == 'message_end' and isinstance(event.get('message'), dict):
            msg = event['message']
            if msg.get('role') == 'assistant':
                texts.append(content_text(msg.get('content')))
                messages.append({key: msg.get(key) for key in
                                 ('model', 'provider', 'usage', 'stopReason', 'errorMessage')})
                if msg.get('errorMessage') or msg.get('stopReason') in {'error', 'aborted'}:
                    errors.append(msg.get('errorMessage') or msg['stopReason'])
        elif kind == 'error':
            errors.append(event.get('message') or 'harness_error')
    result = next((value for candidate in reversed(texts)
                   if (value := parse_result(candidate)) is not None), None)
    return result, tools, messages, errors


def extract_claude(stdout):
    try:
        envelope = json.loads(stdout)
    except ValueError:
        return None, [], [], ['malformed_cli_envelope']
    if not isinstance(envelope, dict):
        return None, [], [], ['malformed_cli_envelope']
    errors = ['harness_error'] if envelope.get('is_error') else []
    return parse_result(envelope.get('result')), [], [
        {key: envelope.get(key) for key in ('model', 'usage', 'stop_reason')}], errors


def extract_codex(final_text):
    # Codex -o writes the final message, without proof of chunk-read tool results.
    return parse_result(final_text), [], [], []


def system_prompt():
    return '\n\n'.join((HERE / path).read_text(encoding='utf-8') for path in
                       ('roles/gate-reviewer.md', 'checklists/consistency.md', 'checklists/output.md'))


def configuration_digest(profile):
    payload = {'reviewer': profile['reviewer'], 'system_prompt': system_prompt()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def read_pi_config(agent_dir):
    """Use pi's installed JSONC dependency, keeping credential data in process memory."""
    source = Path(agent_dir) / 'models.json'
    # Explicit user agent directories use the same strict JSON written by this launcher.
    try:
        return read_json(source)
    except ValueError:
        module = Path.home() / '.pi/agent/npm/node_modules/strip-json-comments/index.js'
        if not module.is_file():
            raise ValueError('JSONC parser unavailable; supply a valid JSON reviewer.agent_dir') from None
        script = """import fs from 'node:fs'; import {pathToFileURL} from 'node:url';
try { const {default:strip}=await import(pathToFileURL(process.argv[1]).href);
const value=JSON.parse(strip(fs.readFileSync(process.argv[2],'utf8'),{trailingCommas:true}));
process.stdout.write(JSON.stringify(value)); } catch { process.exit(2); }"""
        completed = subprocess.run(['node', '--input-type=module', '-e', script, str(module), str(source)],
                                   capture_output=True, text=True, timeout=10, check=False)
        if completed.returncode:
            raise ValueError('Cannot parse pi provider configuration')
        return json.loads(completed.stdout)


@contextmanager
def pi_agent_dir(config):
    """Register only the pinned Flash model in a private, short-lived configuration."""
    configured = config.get('agent_dir')
    agent_dir = Path(configured) if configured else Path.home() / '.pi/agent'
    if not config['model'].startswith('dashscope/'):
        yield agent_dir, None
        return
    requested = config['model'].split('/', 1)[1]
    error = f"unsupported_model: {config['model']}; configure a valid reviewer.agent_dir"
    try:
        registry = read_pi_config(agent_dir)
        provider = registry.get('providers', {}).get('dashscope')
        if not isinstance(provider, dict):
            raise ValueError('DashScope provider not registered')
        registered = any(isinstance(item, dict) and item.get('id') == requested
                         for item in provider.get('models', []))
        if configured and not registered or not configured and not registered and requested != 'qwen3.8-flash':
            raise ValueError('Pinned model not registered')
        private_provider = deepcopy(provider)
        private_provider['models'] = [next((deepcopy(item) for item in provider.get('models', [])
                                           if isinstance(item, dict) and item.get('id') == requested),
                                          {'id': requested, 'contextWindow': 1048576})]
        auth_file = agent_dir / 'auth.json'
        auth = read_json(auth_file) if auth_file.exists() else {}
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        yield None, error
        return
    if configured:
        yield agent_dir.resolve(), None
        return
    with tempfile.TemporaryDirectory(prefix='verifier-ready-pi-') as directory:
        temporary = Path(directory)
        try:
            private_file = temporary / 'models.json'
            with private_file.open('x', encoding='utf-8') as stream:
                os.chmod(private_file, 0o600)
                json.dump({'providers': {'dashscope': private_provider}}, stream)
            if isinstance(auth, dict) and 'dashscope' in auth:
                private_auth = temporary / 'auth.json'
                with private_auth.open('x', encoding='utf-8') as stream:
                    os.chmod(private_auth, 0o600)
                    json.dump({'dashscope': auth['dashscope']}, stream)
        except OSError:
            yield None, error
            return
        yield temporary, None


def run(out: Path, shard: str, profile: dict, task: str, spawn_id: str | None = None):
    config = profile['reviewer']
    kind = config['spawn']
    if kind not in {'pi', 'claude', 'codex'}:
        raise ValueError(f'Unsupported reviewer harness: {kind}')
    sid = spawn_id or uuid.uuid4().hex
    dest = Path(out) / 'spawn' / safe_id(shard)
    dest.mkdir(parents=True, exist_ok=True)
    prompt = system_prompt()
    task_text = f'spawn_id: {sid}\ncase_id: {shard}\n{task}'
    task_file, system_file = dest / 'task.md', dest / 'system.md'
    task_file.write_text(task_text, encoding='utf-8')
    system_file.write_text(prompt, encoding='utf-8')
    final_file = dest / 'final.txt'
    for stale in (final_file, dest / 'result.json'):
        stale.unlink(missing_ok=True)
    values = {'model': config['model'], 'repo': str(ROOT), 'system_prompt': prompt,
              'system_prompt_file': str(system_file.resolve()), 'stdout_file': str(final_file.resolve()),
              'task': task_text, 'task_with_system_prompt': prompt + '\n\n' + task_text}
    argv = [item.format(**values) for item in config['commands'][kind]]
    if kind == 'pi':
        # Explicitly disable ambient context and extensions; never alter global pi settings.
        for flag in ('--no-skills', '--no-context-files', '--no-prompt-templates', '--no-extensions'):
            if flag not in argv:
                argv.insert(1, flag)
    stdout_path, stderr_path = dest / 'stdout.txt', dest / 'stderr.txt'
    tools_path = dest / 'tool_calls.jsonl'
    meta = {'spawn_id': sid, 'case_id': shard, 'model': config['model'], 'command': argv,
            'reviewer_config_sha256': configuration_digest(profile),
            'started_at': now(), 'ended_at': None, 'exit_code': -1, 'has_result': False,
            'scope_valid': False, 'review_sha256': None, 'stdout': str(stdout_path),
            'stderr': str(stderr_path), 'tool_calls': str(tools_path), 'errors': []}
    env = os.environ.copy()
    start = time.monotonic()
    preparation = pi_agent_dir(config) if kind == 'pi' else nullcontext((None, None))
    with preparation as (agent_dir, unsupported), stdout_path.open('w', encoding='utf-8') as stdout, stderr_path.open('w', encoding='utf-8') as stderr:
        if agent_dir is not None:
            env['PI_CODING_AGENT_DIR'] = str(agent_dir)
        if unsupported:
            meta['errors'].append(unsupported)
        else:
            try:
                process = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=stdout, stderr=stderr,
                                           start_new_session=True)
                meta['pid'] = process.pid
                write_json(dest / 'meta.json', meta)
                try:
                    meta['exit_code'] = process.wait(timeout=config['timeout_s'])
                except subprocess.TimeoutExpired:
                    meta['errors'].append('timeout')
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    meta['exit_code'] = -1
            except OSError as exc:
                meta['errors'].append(f'spawn_error: {exc.__class__.__name__}')
    stdout_text = stdout_path.read_text(encoding='utf-8')
    if kind == 'pi':
        result, tools, messages, errors = extract_pi(stdout_text)
    elif kind == 'claude':
        result, tools, messages, errors = extract_claude(stdout_text)
    else:
        result, tools, messages, errors = extract_codex(
            final_file.read_text(encoding='utf-8') if final_file.exists() else '')
    meta['errors'].extend(errors)
    if kind == 'pi' and messages:
        for message in messages:
            actual = f"{message.get('provider')}/{message.get('model')}"
            if actual != config['model']:
                meta['errors'].append('reviewer_model_mismatch')
                break
    meta.update(ended_at=now(), elapsed_s=round(time.monotonic() - start, 3),
                has_result=result is not None, model_requests=len(messages),
                tool_call_count=len(tools), messages=messages)
    totals = {}
    for message in messages:
        usage = message.get('usage')
        if isinstance(usage, dict):
            for key, value in usage.items():
                if isinstance(value, (float, int)) and not isinstance(value, bool):
                    totals[key] = totals.get(key, 0) + value
    meta['usage'] = totals
    with tools_path.open('w', encoding='utf-8') as stream:
        for call in tools:
            stream.write(json.dumps(call, ensure_ascii=False) + '\n')
    if result is not None:
        write_json(dest / 'result.json', result)
    write_json(dest / 'meta.json', meta)
    return {'meta': meta, 'result': result, 'task': str(task_file)}
