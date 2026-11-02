"""Read-only preflight and required primary/fallback2 generation probes."""
from __future__ import annotations

import json
import time

import requests

from experiment_io import (HERE, JOB, TRACE, digest, init_secret_guard, load_provider,
                           now, progress, protect_snapshot, save_json, save_text)


def probe(provider, model):
    cfg = load_provider(provider)
    base = HERE / 'preflight' / provider
    for attempt, cap in enumerate((4096, 16384, 64000), 1):
        body = {'model': model, 'messages': [{'role': 'user', 'content': 'Return exactly the JSON object {"ok":true}.'}],
                'temperature': 0, 'max_tokens': cap, 'stream': True,
                'stream_options': {'include_usage': True}}
        save_json(base / f'attempt{attempt}.request.json', body)
        started = time.monotonic()
        raw_lines, text, reasoning, models, usage, finishes = [], [], [], set(), {}, []
        meta = {'provider': provider, 'requested_model': model, 'started_at': now(), 'max_tokens': cap}
        try:
            with requests.post(cfg['UPSTREAM_API_BASE'].rstrip('/') + '/chat/completions',
                               headers={'Authorization': 'Bearer ' + cfg['UPSTREAM_API_KEY'],
                                        'Content-Type': 'application/json', 'User-Agent': 'verifier-experiment/1.0'},
                               json=body, stream=True, timeout=(300, 1500)) as response:
                meta['status_code'] = response.status_code
                if response.status_code != 200:
                    raw_lines.append(response.text)
                else:
                    for line in response.iter_lines():
                        line = line.decode('utf-8')
                        raw_lines.append(line)
                        if not line.startswith('data:') or line == 'data: [DONE]':
                            continue
                        item = json.loads(line[5:])
                        if item.get('model'):
                            models.add(item['model'])
                        if item.get('usage'):
                            usage = item['usage']
                        for choice in item.get('choices') or []:
                            delta = choice.get('delta') or {}
                            text.append(delta.get('content') or '')
                            reasoning.append(delta.get('reasoning_content') or '')
                            if choice.get('finish_reason'):
                                finishes.append(choice['finish_reason'])
            meta.update(elapsed_seconds=round(time.monotonic() - started, 3),
                        response_models=sorted(models), usage=usage, finish_reasons=finishes)
            raw = ''.join(text)
            meta['truncated'] = ('length' in finishes or int(usage.get('completion_tokens') or 0) >= cap)
            meta['ok'] = response.status_code == 200 and not meta['truncated'] and json.loads(raw) == {'ok': True}
        except Exception as exc:
            meta.update(ok=False, error_type=type(exc).__name__, elapsed_seconds=round(time.monotonic() - started, 3))
        save_text(base / f'attempt{attempt}.wire.txt', '\n'.join(raw_lines))
        save_text(base / f'attempt{attempt}.raw.txt', ''.join(text))
        save_text(base / f'attempt{attempt}.reasoning.txt', ''.join(reasoning))
        save_json(base / f'attempt{attempt}.meta.json', meta)
        if meta['ok']:
            return meta
        if meta.get('status_code') in (400, 401, 403, 404):
            return meta
        if attempt < 3:
            time.sleep(30 * attempt)
    return meta


def main():
    init_secret_guard()
    save_json('preflight/protected_before.json', protect_snapshot())
    save_json('preflight/input_manifest.json', {'created_at': now(), 'job_id': JOB,
                                               'trace_path': str(TRACE), 'bytes': TRACE.stat().st_size,
                                               'sha256': digest(TRACE.read_bytes()),
                                               'task_sha256': digest((HERE / 'TASK.md').read_bytes())})
    progress('0.约束与必读材料', '完成；HEAD已登记，受保护目录已哈希；原始trace可用，8个候选case均唯一匹配')
    primary = probe('primary', 'gemini-3.8-flash-medium')
    selected = primary
    if not primary['ok']:
        selected = probe('fallback2', 'deepseek-flash')
    save_json('preflight/model_selection.json', {'created_at': now(), 'primary_available': primary['ok'],
                                               'selected_provider': selected['provider'] if selected['ok'] else None,
                                               'selected_model': selected['requested_model'] if selected['ok'] else None,
                                               'response_models': selected.get('response_models'),
                                               'ok': selected['ok'], 'max_concurrency': 3})
    progress('1.同模型预检', '完成；' + selected['requested_model'] if selected['ok'] else '阻塞；两条线路均未取得完整有效回复')
    print(json.dumps({'primary_available': primary['ok'], 'selected_model': selected['requested_model'] if selected['ok'] else None,
                      'response_models': selected.get('response_models'), 'ok': selected['ok']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
