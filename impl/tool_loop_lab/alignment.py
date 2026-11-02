"""试验台单向读取 verifier 现有 API。只写试验台快照，不修改源侧接口或数据。"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from urllib.parse import urlsplit

import requests

from impl.core.axes_clustering import build_material


def source_url(value):
    parsed = urlsplit(value.strip())
    if (parsed.scheme not in ('http', 'https') or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise ValueError('目前只对齐本机 verifier 实例，请填写 http(s)://127.0.0.1:端口，不带路径或凭证')
    try:
        parsed.port
    except ValueError:
        raise ValueError('源服务端口不合法') from None
    return value.strip().rstrip('/')


class Source:
    """白名单仅含已有查询 API，拒绝跳转，不带模型 Key、cookie 或认证头。"""
    PATHS = {'/api/run_workspace', '/api/eval_axes/types', '/api/axes_clustering/state'}

    def __init__(self, base_url):
        self.base_url = source_url(base_url)
        self.session = requests.Session()
        self.session.trust_env = False

    def read(self, path, payload):
        if path not in self.PATHS: raise ValueError('不是允许的源侧查询接口')
        response = self.session.post(self.base_url + path, json=payload, timeout=(5, 90), allow_redirects=False)
        if 300 <= response.status_code < 400: raise ValueError('源查询不允许 HTTP 跳转')
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict): raise ValueError('源接口未返回对象')
        return data

    def close(self): self.session.close()


def project_cases(workspace):
    runs = {run['request_key']: run for run in workspace.get('runs') or [] if run.get('request_key')}
    cases = []
    for position, entry in enumerate(workspace.get('cases') or []):
        case = entry['case']
        run = runs.get(entry.get('request_key'))
        row = ((run or {}).get('table_row') or ((run or {}).get('frontend_view') or {}).get('table_row') or {})
        trace = (run or {}).get('trace') or {}
        input_value = trace.get('input') or case.get('live_request')
        # 与现有 caseView / fromWorkspace 同一显示边界：实际运行输出，不用 reference 充当答案。
        output = trace.get('extracted_output') if run else case.get('output')
        axes = []
        for source in row.get('eval_axes_summary') or []:
            axes.append({key: source.get(key) for key in ('axis_id', 'type_id', 'title', 'status', 'verdict', 'text', 'items')})
        cases.append({'id': row.get('id') or case['id'], 'pool_index': position, 'request_key': entry.get('request_key'),
                      'scenario': row.get('scenario') or case.get('scenario') or '', 'input': input_value, 'output': output,
                      'inputPreview': str(row['input']) if isinstance(row.get('input'), (str, int, float, bool)) else '',
                      'fulfillment': row.get('fulfillment_status') or row.get('status') or entry.get('status') or '',
                      'run_status': entry.get('status'), 'axes': axes})
    return cases


def fingerprint(cases):
    return hashlib.sha256(json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def collect(base_url, project, *, reader=None):
    base_url = source_url(base_url)
    if not project.strip(): raise ValueError('请填写源项目')
    own = Source(base_url) if reader is None else None
    read = own.read if own else reader
    try:
        workspace = read('/api/run_workspace', {'project': project})
        if (workspace.get('batch') or {}).get('status') in ('pending', 'running'):
            raise ValueError('源侧批次正在运行，请完成后再对齐，避免把变化中的结果作为比较样本')
        cases = project_cases(workspace)
        del workspace  # 查询接口携带完整 Trace；投影完成后立即释放，不持久化它。
        if not cases: raise ValueError('源候选区为空，未替换上次对齐快照')
        types = read('/api/eval_axes/types', {'project': project}).get('types') or []
        if not types: raise ValueError('源服务未提供扩展轴类型声明')
        selections = [{'pool_index': c['pool_index'], 'request_key': c['request_key']} for c in cases]
        state = read('/api/axes_clustering/state', {'project': project, 'selections': selections})
        version = (state.get('data_revision'), state.get('job_id'), state.get('criteria_version'), state.get('status'))
        # 旧聚类可能只针对候选区的一个子集。按它自己保存的范围读取，不要求源侧新增 API。
        baseline_scope = state.get('selections') or []
        if state.get('status') == 'completed' and not state.get('scope_matches') and baseline_scope:
            state = read('/api/axes_clustering/state', {'project': project, 'selections': baseline_scope})
            if version != (state.get('data_revision'), state.get('job_id'), state.get('criteria_version'), state.get('status')):
                raise ValueError('源聚类在对齐期间发生变化，请重新对齐')
        baseline_result = state.get('result') if state.get('status') == 'completed' and state.get('scope_matches') else None
        if baseline_result:
            for ref in baseline_result.get('refs', {}).values():
                position = ref.get('pool_index')
                if not isinstance(position, int) or not 0 <= position < len(cases) or cases[position]['request_key'] != ref.get('request_key'):
                    raise ValueError('源聚类引用与当前 case 不一致，请先在源页确认结果')
        # 只比较紧凑投影，第二次读取用于发现同请求编号下的内容变化，绝不按 case_id 猜测合并。
        check = read('/api/run_workspace', {'project': project})
        if (check.get('batch') or {}).get('status') in ('pending', 'running') or fingerprint(project_cases(check)) != fingerprint(cases):
            raise ValueError('源候选区在对齐期间发生变化，请重新对齐')
        del check
        material = build_material([{'pool_index': c['pool_index'], 'request_key': c['request_key'], 'axes': c['axes']} for c in cases], types)
        return {'id': uuid.uuid4().hex, 'source_url': base_url, 'project': project, 'synced_at': time.time(),
                'data_source': 'aligned-verifier', 'cases': cases, 'types': types, 'fingerprint': fingerprint(cases),
                'criteria': state.get('criteria') or '',
                'baseline': {'status': state.get('status'), 'criteria': state.get('criteria') or '',
                             'criteria_version': state.get('job_version'), 'job_id': state.get('job_id'),
                             'selections': baseline_scope, 'clustering': baseline_result,
                             'note': '仅供人工对照，不作为实验模型的输入' if baseline_result else '源侧没有与当前案例匹配的已完成聚类；仍可对齐 case、输入输出和 reason'},
                'counts': {'cases': len(cases), 'with_run': sum(bool(c['request_key']) for c in cases),
                           'with_reasons': len({r['pool_index'] for r in material['refs'].values()}), 'reasons': len(material['refs'])}}
    finally:
        if own: own.close()


def public(snapshot):
    if snapshot is None: return None
    return {key: snapshot[key] for key in ('id', 'source_url', 'project', 'synced_at', 'fingerprint', 'criteria', 'counts')} | {
        'baseline_available': bool(snapshot['baseline'].get('clustering')), 'baseline_note': snapshot['baseline']['note'],
        'cases': [{'id': c['id'], 'pool_index': c['pool_index'], 'request_key': c['request_key'],
                   'scenario': c['scenario'], 'run_status': c['run_status']} for c in snapshot['cases']]}
