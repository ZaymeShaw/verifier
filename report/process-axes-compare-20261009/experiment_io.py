"""Offline experiment I/O. Writes are confined to this directory; credentials stay in memory."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TRACE = Path('/private/tmp/claude-501/-Users-xiaozijian-WorkSpace-projects-claude-code-verifier-runC-verifier/84d49b1f-9f6b-4ebc-bf2a-665a1fc62378/scratchpad/trace2.json')
INSTANCE = ROOT / '.runtime/instances/inst-16fa340ac786414f'
JOB = 'fb5fda5628174ef6967116bd4ecca493'
CASES = (
    'smoke-customer-profile-fuyunping',
    'smoke-policy-list-fuyunping',
    'smoke-agg-paid-prem-fuyunping',
    'smoke-multi-policy-anjinning',
    'main-A01-fuyunping-list-aggprem',
    'main-B01-meeting-prep-fuyunping',
    'main-D01-same-surname-clarify',
    'smoke-policy-detail-renyanlin',
)
UNSEEN = (  # 泛化验证用：同一个 job 里没进入 gold 的 case，职责写成之后才抽的
    'main-A02-yuxinya-status',
    'main-C01-two-policies-roles',
    'main-D05-year-pay-filter',
    'smoke-neg-unknown-policy',
)
AXES = ('context_memory', 'intent_understanding', 'planning_routing',
        'tool_execution', 'knowledge_data', 'model_capability')
PREFIX = 'llm-probe-insurance-real-'
_SECRETS: set[str] = set()


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value: bytes | str):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n'


def load_provider(name):
    # python-dotenv is already installed in the project's runtime; it removes both
    # single and double quotes. Never return a repr of this mapping to a log.
    from dotenv import dotenv_values
    cfg = dict(dotenv_values(INSTANCE / 'tracing' / f'.env.verifier_{name}', interpolate=False))
    for key, value in cfg.items():
        if value and any(part in key.upper() for part in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')):
            _SECRETS.add(value)
    return cfg


def init_secret_guard():
    for name in ('primary', 'fallback1', 'fallback2'):
        load_provider(name)


def check_text(text):
    if any(secret in text for secret in _SECRETS if secret):
        raise RuntimeError('Credential guard blocked an artifact; no credential value was printed or written.')


def target(path):
    path = Path(path)
    path = path if path.is_absolute() else HERE / path
    if not path.resolve().is_relative_to(HERE):
        raise RuntimeError('Write outside the experiment directory is forbidden')
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def save_text(path, text, *, exclusive=True):
    check_text(text)
    path = target(path)
    with path.open('x' if exclusive else 'w', encoding='utf-8') as f:
        f.write(text)
    return digest(text)


def save_json(path, value, *, exclusive=True):
    return save_text(path, json_text(value), exclusive=exclusive)


def load_json(path):
    return json.loads((HERE / path).read_text())


def progress(stage, status):
    line = f'{now()}\t{stage}\t{status}\n'
    check_text(line)
    with target('PROGRESS.log').open('a', encoding='utf-8') as f:
        f.write(line)


# 冻结的判据与输入：只有这些文件在跑模型后不允许再改。工具脚本（doc_rebuild/replay/transport
# 等）的哈希留在 PREREG.sha256 里做留痕，但允许被派发方要求的管道修正改动（见 DEVIATIONS.md）。
FROZEN_INPUTS = ('TASK.md', 'known_issues.md', 'triage_rules.md', 'frozen/')


def verify_prereg():
    for line in (HERE / 'PREREG.sha256').read_text().splitlines():
        if line.startswith('#') or '  ' not in line:
            continue
        sha, relative = line.split('  ', 1)
        if not any(relative == item or relative.startswith(item) for item in FROZEN_INPUTS):
            continue
        if digest((HERE / relative).read_bytes()) != sha:
            raise RuntimeError(f'Preregistration changed: {relative}')


def protect_snapshot():
    import subprocess
    protected = {}
    for directory in ('demand', 'spec/alg', 'spec/draft', 'impl', 'tests'):
        for path in sorted((ROOT / directory).rglob('*')):
            if path.is_file():
                protected[path.relative_to(ROOT).as_posix()] = digest(path.read_bytes())
    return {
        'created_at': now(),
        'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'tracked_status': subprocess.check_output(['git', 'status', '--short', '--untracked-files=no'], cwd=ROOT, text=True),
        'protected_files': protected,
    }


os.environ['PYTHONDONTWRITEBYTECODE'] = '1'


def bookkeeping_ok(record: dict) -> bool:
    """每次逻辑请求都恰好有一次成功的 HTTP 尝试经过本实验 transport（连接被重置后的重试不算账目不符）。"""
    if "prompts" not in record:
        return record.get("bookkeeping_ok") is not False
    return sum(1 for attempt in record.get("http_attempts") or [] if attempt.get("ok")) == len(record["prompts"])
