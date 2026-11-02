"""试验台独立模型连接；不读取公共 LLM Key、模型或 fallback。"""
from __future__ import annotations

import os
import hashlib
import json
import tempfile
import fcntl
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from impl.core.config_bootstrap import parse_dotenv
from impl.core.config_schema import LlmCapabilities, LlmConfig, openai_compatible_base_url

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / '.env.tool_loop'
DEFAULT_TIMEOUT_SECONDS = 300.0
NAMES = {'TOOL_LOOP_BASE_URL', 'TOOL_LOOP_MODEL', 'TOOL_LOOP_API_KEY',
         'TOOL_LOOP_REASONING_EFFORT', 'TOOL_LOOP_REQUEST_TIMEOUT_SECONDS', 'TOOL_LOOP_TEMPERATURE'}


@dataclass(frozen=True)
class Connection:
    base_url: str = ''
    model: str = ''
    api_key: str = field(default='', repr=False)
    reasoning_effort: str = ''
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    temperature: float = 0

    def problems(self):
        errors = []
        for name, value in [('TOOL_LOOP_BASE_URL', self.base_url), ('TOOL_LOOP_MODEL', self.model), ('TOOL_LOOP_API_KEY', self.api_key)]:
            if not value.strip(): errors.append(f'请在 .env.tool_loop 中填写 {name}')
        if self.base_url:
            url = urlsplit(self.base_url)
            if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
                errors.append('TOOL_LOOP_BASE_URL 必须是 HTTP(S) 地址，不能在 URL 中放凭证、查询参数或片段')
            try:
                url.port
            except ValueError:
                errors.append('TOOL_LOOP_BASE_URL 端口不合法')
        if not 1 <= self.timeout <= 3600:
            errors.append('TOOL_LOOP_REQUEST_TIMEOUT_SECONDS 应在 1–3600 秒内')
        if not 0 <= self.temperature <= 2:
            errors.append('TOOL_LOOP_TEMPERATURE 应在 0–2 内，具体支持值以供应商要求为准')
        return errors

    def public(self):
        errors = self.problems()
        url = urlsplit(self.base_url)
        return {'protocol': 'openai_compatible', 'model': self.model,
                'base_url': self.base_url if not (url.username or url.password or url.query or url.fragment) else '(地址含敏感部分，请修正)',
                'key_configured': bool(self.api_key), 'request_timeout_seconds': self.timeout,
                'reasoning_effort': self.reasoning_effort, 'temperature': self.temperature, 'ready': not errors, 'errors': errors,
                'source': '.env.tool_loop / TOOL_LOOP_* 进程环境变量'}

    def client(self):
        errors = self.problems()
        if errors:
            raise ValueError('；'.join(errors))
        from impl.core.llm_client import LlmClient
        config = LlmConfig(protocol='openai_compatible', provider='openai_compatible',
                           model=self.model, base_url=openai_compatible_base_url(self.base_url, 'TOOL_LOOP_BASE_URL'),
                           api_key=self.api_key, temperature=self.temperature, reasoning_effort=self.reasoning_effort,
                           request_timeout_seconds=self.timeout, capabilities=LlmCapabilities(True, True, 0),  # 窗口未声明，不猜供应商容量
                           role_policies={}, fallbacks=(), stream=True)
        client = LlmClient(role='tool_loop_lab', config=config)
        client._project_id = 'tool_loop_lab'
        client._caller = 'tool_loop_lab'
        return client


@contextmanager
def _settings_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _revision(path, environ):
    digest = hashlib.sha256(path.read_bytes() if path.exists() else b'')
    digest.update(json.dumps({key: environ[key] for key in sorted(NAMES) if key in environ}, sort_keys=True).encode())
    return digest.hexdigest()


def connection_state(path=None, environ=None):
    path = Path(path or ENV_PATH)
    env = os.environ if environ is None else environ
    with _settings_lock(path):
        return {'config': load_connection(path, env).public(), 'revision': _revision(path, env),
                'editable': not any(key in env for key in NAMES),
                'managed_by_environment': sorted(key for key in NAMES if key in env)}


def save_connection(*, base_url, model, api_key, reasoning_effort, timeout, expected_revision, temperature=0, path=None, environ=None):
    """页面只写独立 .env.tool_loop。Key 留空保留，跨地址不能偷偷复用旧 Key。"""
    path = Path(path or ENV_PATH)
    env = os.environ if environ is None else environ
    with _settings_lock(path):
        if any(key in env for key in NAMES):
            raise ValueError('模型由 TOOL_LOOP_* 进程环境变量管理，页面不能覆盖；请先移除对应启动环境覆盖')
        if _revision(path, env) != expected_revision:
            raise ValueError('模型配置已在其他页面或文件中更新，请读取最新配置后再保存')
        previous = load_connection(path, env)
        old_url, new_url = urlsplit(previous.base_url), urlsplit(base_url.strip())
        if not api_key.strip() and previous.api_key and (old_url.scheme, old_url.netloc) != (new_url.scheme, new_url.netloc):
            raise ValueError('更换供应商地址时请重新填写 API Key，不能自动把旧 Key 发往新地址')
        selected = Connection(base_url.strip(), model.strip(), api_key.strip() or previous.api_key,
                              reasoning_effort.strip(), timeout, temperature)
        errors = selected.problems()
        if errors: raise ValueError('；'.join(errors))
        values = {'TOOL_LOOP_BASE_URL': selected.base_url, 'TOOL_LOOP_MODEL': selected.model,
                  'TOOL_LOOP_API_KEY': selected.api_key, 'TOOL_LOOP_REASONING_EFFORT': selected.reasoning_effort,
                  'TOOL_LOOP_REQUEST_TIMEOUT_SECONDS': str(selected.timeout), 'TOOL_LOOP_TEMPERATURE': str(selected.temperature)}
        if any('\n' in value or '\r' in value for value in values.values()):
            raise ValueError('模型配置不接受换行字符')
        fd, temporary = tempfile.mkstemp(prefix='.env.tool_loop.', dir=path.parent)
        temporary = Path(temporary)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as output:
                output.write('# ToolLoop 试验台独立模型配置；含密钥，请勿提交。\n')
                output.write(''.join(key + '=' + json.dumps(value, ensure_ascii=False) + '\n' for key, value in values.items()))
                output.flush();os.fsync(output.fileno())
            # 复用运行时解析器验证写入格式，失败时原配置不变。
            parse_dotenv(temporary)
            os.replace(temporary, path)
        finally:
            if temporary.exists(): temporary.unlink()
        return {'config': selected.public(), 'revision': _revision(path, env), 'editable': True, 'managed_by_environment': []}


def load_connection(path=None, environ=None):
    values = parse_dotenv(Path(path or ENV_PATH))
    unknown = set(values) - NAMES
    if unknown:
        raise ValueError('试验台环境变量未识别：' + ', '.join(sorted(unknown)))
    env = os.environ if environ is None else environ
    values.update({key: env[key] for key in NAMES if key in env})
    try:
        timeout = float(values.get('TOOL_LOOP_REQUEST_TIMEOUT_SECONDS') or DEFAULT_TIMEOUT_SECONDS)
    except ValueError:
        raise ValueError('TOOL_LOOP_REQUEST_TIMEOUT_SECONDS 必须是数字') from None
    try:
        temperature = float(values.get('TOOL_LOOP_TEMPERATURE', '0'))
    except ValueError:
        raise ValueError('TOOL_LOOP_TEMPERATURE 必须是数字') from None
    return Connection(base_url=values.get('TOOL_LOOP_BASE_URL', '').strip(), model=values.get('TOOL_LOOP_MODEL', '').strip(),
                      api_key=values.get('TOOL_LOOP_API_KEY', '').strip(), reasoning_effort=values.get('TOOL_LOOP_REASONING_EFFORT', '').strip(),
                      timeout=timeout, temperature=temperature)
