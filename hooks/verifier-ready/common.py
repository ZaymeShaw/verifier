"""File and identity operations for the standalone verifier-ready command."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from datetime import datetime, timezone

import yaml

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CATEGORIES = tuple(range(1, 8))
SEVERITIES = ('blocking', 'high', 'diagnostic')
RULE_KEYS = ('role', 'output_structure', 'axis_identifiers', 'reference_format',
             'coverage', 'evidence_authority', 'outcome_semantics')


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]+', value) or value in {'.', '..'}:
        raise ValueError(f'Unsafe artifact identifier: {value!r}')
    return value


def snapshot(root=ROOT, report=None, scope=False):
    root = Path(root)
    paths = [root / 'impl', root / 'projects/llm_probe']
    if scope:
        paths += [root / 'hooks/verifier-ready', root / 'spec', root / 'AGENTS.md']
        if report:
            paths.append(Path(report))
    result = {}
    for base in paths:
        files = [base] if base.is_file() else base.rglob('*') if base.exists() else []
        for path in files:
            if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            if report and path.is_relative_to(Path(report) / 'spawn'):
                continue
            result[str(path.relative_to(root)) if path.is_relative_to(root) else str(path)] = digest(path)
    return dict(sorted(result.items()))


def fingerprint(root=ROOT, profile=None):
    code = hashlib.sha256(json.dumps(snapshot(root), sort_keys=True).encode()).hexdigest()
    config = profile or load_profile()
    assets = {str(p.relative_to(HERE)): digest(p) for folder in ('roles', 'checklists')
              for p in (HERE / folder).rglob('*') if p.is_file()}
    engine = {p.name: digest(p) for p in HERE.glob('*.py')}
    return {'code': code, 'engine': hashlib.sha256(json.dumps(engine, sort_keys=True).encode()).hexdigest(),
            'profile': hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
            'role_card': hashlib.sha256(json.dumps(assets, sort_keys=True).encode()).hexdigest(),
            'models': {'reviewer': config['reviewer']['model']}}


def load_profile():
    return yaml.safe_load((HERE / 'profile.yaml').read_text(encoding='utf-8'))


def finding_key(shard, finding):
    return f'{safe_id(shard)}::{safe_id(finding)}'
