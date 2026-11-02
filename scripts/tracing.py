#!/usr/bin/env python3
"""Project-owned relay lifecycle; original verifier .env is never rewritten."""
from __future__ import annotations

import argparse
import hashlib
from contextlib import contextmanager
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

import yaml
from html import escape
import re

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from impl.core.instances import resolve_instance, instance_root, instance_lock, activate, rebind_port, INSTANCE_ENV
from impl.core.tracing_retention import log_lock, cleanup, workspace_trace_selection

RUNTIME = None
NAMES = ['verifier_primary', 'verifier_fallback1', 'verifier_fallback2']


def settings():
    path = ROOT / 'tracing' / 'config.yaml'
    cfg = yaml.safe_load(path.read_text())
    dependency = (ROOT / cfg['llmtracing_root']).resolve()
    for rel in ['llm_gateway/gatewayctl.py', 'llm_gateway/.venv/bin/python', 'llmtrace']:
        if not (dependency / rel).is_file():
            raise ValueError(f'llmtracing dependency missing: {dependency / rel}; edit {path}')
    port = cfg['relay_port_start']
    if type(port) is not int or not 1024 <= port <= 65533:
        raise ValueError('tracing.relay_port_start must be an integer from 1024 to 65533')
    return cfg, dependency


def controller(dependency):
    spec = importlib.util.spec_from_file_location('_verifier_gatewayctl', dependency / 'llm_gateway/gatewayctl.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def upstream_routes(llm, ports):
    roles = list(llm.role_policies.values())
    if any(p.base_url for p in roles):
        raise ValueError('Explicit role base_url would bypass the relay; use the shared base_url before enabling tracing')
    endpoints = [(llm.base_url, llm.api_key, list(dict.fromkeys([llm.model] + [p.model for p in roles if p.model])))]
    endpoints += [(f.base_url, f.api_key, [f.model]) for f in llm.fallbacks]
    if len(endpoints) > len(ports):
        raise ValueError('Not enough tracing ports for configured endpoints')
    local_urls = {f'http://127.0.0.1:{port}/v1' for port in ports}
    routes = []
    for i, (url, key, models) in enumerate(endpoints):
        if url.rstrip('/') in local_urls:
            raise ValueError('Resolved upstream already points at this relay. Keep original upstream values in .env and do not nest tracing launchers.')
        routes.append(dict(name=NAMES[i], port=ports[i], upstream_url=url, upstream_key=key,
                           models=models, local_url=f'http://127.0.0.1:{ports[i]}/v1'))
    return routes


def write_private(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp-' + secrets.token_hex(4))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(data)
    tmp.replace(path)


@contextmanager
def runtime_lock():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with (RUNTIME / '.launch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def prepare(routes, cfg, ctl):
    # LiteLLM resolves custom callbacks beside the YAML, even with PYTHONPATH.
    # Link the existing entry point; its implementation stays in llmtracing.
    RUNTIME.mkdir(parents=True, exist_ok=True)
    callback = RUNTIME / 'custom_callbacks.py'
    source = ctl.GATEWAY_DIR / 'custom_callbacks.py'
    if not source.is_file():
        raise ValueError(f'Missing llmtracing callback: {source}')
    if callback.is_symlink() and callback.resolve() != source.resolve():
        callback.unlink()
    if not callback.exists():
        callback.symlink_to(source)
    elif not callback.is_symlink():
        raise ValueError(f'Expected generated callback symlink: {callback}')
    overlay = {}
    for i, route in enumerate(routes):
        env_path = RUNTIME / ('.env.' + route['name'])
        old = ctl.parse_env(env_path) if env_path.exists() else {}
        master = old.get('LITELLM_MASTER_KEY') or 'sk-local-verifier-' + secrets.token_hex(24)
        config_path = RUNTIME / ('config.' + route['name'] + '.yaml')
        model_params = dict(cfg['litellm_params'])
        # The original upstream remains the single source of model, URL and key.
        models = [dict(model_name=model, litellm_params={**model_params, 'model': 'openai/' + model,
            'api_base': 'os.environ/UPSTREAM_API_BASE', 'api_key': 'os.environ/UPSTREAM_API_KEY'}) for model in route['models']]
        config = dict(model_list=models, litellm_settings=cfg['litellm_settings'],
                      general_settings={'master_key': 'os.environ/LITELLM_MASTER_KEY'})
        write_private(config_path, yaml.safe_dump(config, sort_keys=False))
        values = dict(UPSTREAM_API_BASE=route['upstream_url'], UPSTREAM_API_KEY=route['upstream_key'],
            UPSTREAM_MODEL=route['models'][0], UPSTREAM_PROTOCOL='openai', LITELLM_HOST='127.0.0.1',
            LITELLM_PORT=str(route['port']), LITELLM_MASTER_KEY=master, LITELLM_CONFIG=str(config_path),
            LLM_GATEWAY_THINKING_POLICY='passthrough', GATEWAY_DIRECT_UPSTREAM='1',
            LLM_GATEWAY_LOG_DIR=str(RUNTIME / 'logs' / route['name']))
        if any('\n' in v or '\r' in v or '"' in v for v in values.values()):
            raise ValueError('Unsupported newline/quote in generated relay value')
        write_private(env_path, ''.join(f'{k}="{v}"\n' for k, v in values.items()))
        if i == 0:
            overlay.update(LLM_BASE_URL=route['local_url'], DEEPSEEK_API_KEY=master)
        else:
            overlay.update({f'LLM_FALLBACK_{i}_BASE_URL': route['local_url'], f'LLM_FALLBACK_{i}_API_KEY': master})
    return overlay


def start_relays(instance, llm):
    global RUNTIME
    RUNTIME = instance_root(instance['id']) / 'tracing'
    cfg, dependency = settings()
    cfg = dict(cfg, ports=instance['relay_ports'])
    ctl = controller(dependency)
    routes = upstream_routes(llm, cfg['ports'])
    with runtime_lock():
        overlay = prepare(routes, cfg, ctl)
        gateways = [ctl.load(r['name'], RUNTIME) for r in routes]
        for gateway in gateways:
            ctl.up(gateway, universe=gateways, out=sys.stderr)
    return overlay


def query_command(dependency):
    return [str(dependency / 'llm_gateway/.venv/bin/python'), str(dependency / 'llmtrace'),
            'query', 'calls', '--log', str(RUNTIME / 'logs'), '--include-rotated']


def captured_calls(dependency, run_id=None):
    if not (RUNTIME / 'logs').is_dir():
        return []
    selection = ['--run-id', run_id] if run_id else ['--since', '1970-01-01T00:00:00Z']
    result = subprocess.run([*query_command(dependency), *selection, '--format', 'json'],
                            cwd=ROOT, capture_output=True, text=True)
    if result.returncode not in (0, 1, 3):
        raise ValueError(result.stderr.strip() or 'llmtracing query failed')
    return json.loads(result.stdout)['calls']


def recorded_runs(calls):
    runs = {}
    for call in calls:
        run_id = call.get('run_id')
        if not run_id or call.get('case_id') == '__health_probe__':
            continue
        row = runs.setdefault(run_id, dict(run_id=run_id, last_call='', cases=set(),
                                          succeeded=0, failed=0, pending=0))
        row['last_call'] = max(row['last_call'], call.get('ts') or '')
        row['cases'].add(call.get('case_id'))
        row[call['state']] += 1
    return sorted(runs.values(), key=lambda row: row['last_call'], reverse=True)


def report(dependency, run_id, out, open_browser=False, project=None):
    calls = captured_calls(dependency, run_id)
    unbound_rows = []
    if project:
        scope = workspace_trace_selection(RUNTIME.parent / 'data/latest_runs.sqlite3', project)
        execution_ids, unbound_rows = scope['execution_ids'], scope['unbound_rows']
        selected = [c for c in calls if c.get('execution_id') in execution_ids]
        selection = [value for eid in execution_ids for value in ('--execution-id', eid)]
        run_ids = sorted({c['run_id'] for c in selected if c.get('run_id')})
    else:
        if run_id is None:
            runs = recorded_runs(calls)
            if not runs:
                print('没有已采集的运行记录。请先通过 tracing run 执行评测。', file=sys.stderr)
                return 1
            run_id = runs[0]['run_id']
        run_ids = [run_id]
        selected = [c for c in calls if c.get('run_id') == run_id]
        execution_ids = sorted({c['execution_id'] for c in selected if c.get('execution_id')})
        selection = ['--run-id', run_id]
    if not selected:
        print('当前选择没有可用采集记录；旧结果可能缺少执行身份、日志已清理，或执行未发出模型请求。', file=sys.stderr)
        return 1  # Never query without selectors: that would export unrelated calls.
    if out is None:
        from impl.core.llm_tracing import _wire
        label = project or run_id
        name = _wire(label)[:80] + '-' + hashlib.sha256(','.join(execution_ids or run_ids).encode()).hexdigest()[:8]
        out = RUNTIME / 'reports' / name
    out = out.resolve()
    print('execution_ids: ' + ', '.join(execution_ids), flush=True)
    if any(c['state'] == 'pending' for c in selected):
        print('仍有未结束的模型请求；导出当前快照，完成后可重新导出。', file=sys.stderr)
    rc = subprocess.call([*query_command(dependency), *selection, '--html', str(out)], cwd=ROOT)
    if rc:
        return rc
    html = out / 'llm_trace.html'
    if not html.is_file():
        raise ValueError(f'HTML was not generated: {html}')
    missing_execution_ids = sorted(set(execution_ids) - {c.get('execution_id') for c in selected})
    if project:
        warnings = []
        if unbound_rows:
            warnings.append(f'有 {len(unbound_rows)} 行旧结果没有保存执行身份，无法精确关联日志；重新运行这些行后即可展示。不会按整批日志代替。')
        if missing_execution_ids:
            warnings.append(f'有 {len(missing_execution_ids)} 次执行没有可用采集日志（可能未发出模型请求或日志已清理），当前报告无法展示。')
        # The native report fills 100vh and disables body scrolling. Our notice
        # must share that viewport with the report, rather than push it below it.
        notice = ('<style id="verifier-report-layout">'
                  'body{display:flex;flex-direction:column;}'
                  'body>.app{flex:1 1 0%;height:auto;min-height:0;}'
                  'body>.app>aside,body>.app>.calls,body>.app>.detail{min-height:0;}'
                  '.verifier-report-notice{flex:0 0 auto;max-height:25vh;overflow:auto;'
                  'padding:12px 16px;margin:8px 12px;border:1px solid #888;border-radius:8px;font-size:12px;}'
                  '.verifier-report-notice p{margin:6px 0;}'
                  '</style><section class="verifier-report-notice" role="note">'
                  '<b>当前用例池 LLM Trace</b><p>每行只展示当前结果对应的执行：保留未补跑行的原执行，补跑行展示新执行。一次执行内部的自动重试仍包含在内。</p>'
                  + ''.join('<p>' + escape(w) + '</p>' for w in warnings) + '</section>')
        content = html.read_text(encoding='utf-8')
        html.write_text(re.sub(r'(<body\b[^>]*>)', lambda m: m.group(0) + notice,
                               content, count=1, flags=re.IGNORECASE), encoding='utf-8')
    (out / 'verifier-report.json').write_text(json.dumps({'run_ids': run_ids, 'execution_ids': execution_ids,
        'project': project, 'missing_execution_ids': missing_execution_ids, 'unbound_rows': unbound_rows}) + '\n')
    print(f'HTML: {html}', flush=True)
    if open_browser:
        opener = ['open'] if sys.platform == 'darwin' else ['xdg-open']
        return subprocess.call([*opener, str(html)])
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action')
    for action in ['up', 'down', 'status', 'show', 'cleanup']:
        command = sub.add_parser(action)
        command.add_argument('--port', type=int, help='服务端口；自动查询实例映射')
        if action == 'cleanup':
            command.add_argument('--dry-run', action='store_true')
    bind = sub.add_parser('bind', help='将已停止实例从旧端口移动到新端口，保留数据')
    bind.add_argument('--from-port', type=int, required=True)
    bind.add_argument('--port', type=int, required=True)
    run = sub.add_parser('run', help='通过 tracing 启动 server/uat，端口自动映射实例')
    run.add_argument('--port', type=int, help='CLI/Python 使用的实例服务端口')
    run.add_argument('command', nargs=argparse.REMAINDER)
    listings = sub.add_parser('runs', help='列出本实例已采集批次，最新的在前（仅模型请求统计）')
    listings.add_argument('--port', type=int)
    rep = sub.add_parser('report', help='从已有日志导出 HTML，默认选择最新批次')
    selection = rep.add_mutually_exclusive_group()
    selection.add_argument('--run-id', help='指定单次执行批次；可用 tracing runs 查看')
    selection.add_argument('--project', help='按行导出当前用例池的执行，排除补跑前被替换的执行')
    selection.add_argument('--latest', action='store_true', help='导出最近有模型请求的批次（默认）')
    rep.add_argument('--out', type=Path, help='输出目录，默认 .runtime/tracing/reports/<run-id>/')
    rep.add_argument('--port', type=int, help='服务端口；只导出该实例日志')
    rep.add_argument('--open', action='store_true', dest='open_browser', help='导出后在默认浏览器打开 HTML')
    args = parser.parse_args(argv)
    if args.action is None:
        parser.print_help()
        print('\n查看已有批次：bash run.sh tracing runs\n导出并打开最新批次：bash run.sh tracing report --open')
        return 0
    if args.action == 'bind':
        print(rebind_port(args.from_port, args.port))
        return 0
    # Server owns the instance lock before any relays or database are opened.
    if args.action == 'run' and args.command and args.command[0] in ('server', 'uat'):
        os.environ['VERIFIER_TRACING_ENABLED'] = '1'
        os.execvpe('bash', ['bash', str(ROOT / 'run.sh'), *args.command], os.environ)
    from impl.core.config import resolve_runtime_config
    configured = resolve_runtime_config()
    port = getattr(args, 'port', None) or int(os.environ.get('VERIFIER_PORT') or configured.server.port)
    instance = resolve_instance(port)
    global RUNTIME
    RUNTIME = instance_root(instance['id']) / 'tracing'
    if args.action == 'run':
        if not args.command or args.command[0] not in ('cli', 'python', 'config-check'):
            parser.error('run requires server / uat / cli / python / config-check')
        with instance_lock(instance):
            activate(instance)
            overlay = start_relays(instance, configured.llm)
            return subprocess.call(['bash', str(ROOT / 'run.sh'), *args.command],
                                   cwd=ROOT, env=dict(os.environ, **overlay))
    cfg, dependency = settings()
    cfg = dict(cfg, ports=instance['relay_ports'])
    if args.action == 'report':
        with log_lock(RUNTIME):
            return report(dependency, args.run_id, args.out, args.open_browser, args.project)
    if args.action == 'runs':
        with log_lock(RUNTIME):
            rows = recorded_runs(captured_calls(dependency))
        print('last_call (UTC)\trun_id\tcases\tsucceeded\tfailed\tpending')
        for row in rows:
            print('\t'.join(str(v) for v in [row['last_call'], row['run_id'], len(row['cases']),
                                             row['succeeded'], row['failed'], row['pending']]))
        if not rows:
            print('没有已采集的运行记录。请先通过 tracing run 执行评测。')
        return 0
    ctl = controller(dependency)
    if args.action == 'cleanup':
        database = instance_root(instance['id']) / 'data/latest_runs.sqlite3'
        print(json.dumps(cleanup(RUNTIME, ctl, database=database, dry_run=args.dry_run), ensure_ascii=False))
        return 0
    if args.action in ('status', 'down'):
        gateways = ctl.discover(RUNTIME)
        if args.action == 'status':
            for g in gateways:
                state = ctl.status(g, universe=gateways)
                print(json.dumps({k: state.get(k) for k in ('name', 'pid', 'running', 'healthy', 'stale_config')}, ensure_ascii=False))
        else:
            with runtime_lock():
                for g in gateways:
                    ctl.down(g)
        return 0
    routes = upstream_routes(configured.llm, cfg['ports'])
    if args.action == 'show':
        print(json.dumps({'original_config': str(ROOT / '.env'), 'tracing_config': str(ROOT / 'tracing/config.yaml'),
            'instance_id': instance['id'], 'server_port': port, 'runtime': str(RUNTIME), 'routes': [{k: v for k, v in r.items() if k != 'upstream_key'} for r in routes]}, indent=2))
        return 0
    with runtime_lock():
        overlay = prepare(routes, cfg, ctl)
        gateways = [ctl.load(r['name'], RUNTIME) for r in routes]
        for g in gateways:
            ctl.up(g, universe=gateways, out=sys.stderr)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
