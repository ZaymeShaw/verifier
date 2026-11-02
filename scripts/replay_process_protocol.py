"""Replay one frozen trace with the current process protocol; never call the business system.

bash run.sh python scripts/replay_process_protocol.py --trace <trace.json> --old <result.json> --out <new-directory>
Outputs retain raw judgments, evaluator failures, composition, atomic issues and source hashes for human comparison.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def compare(old, new):
    before = {a['type_id']: a for a in old.get('results', [])}
    rows = []
    for after in new.get('results', []):
        axis = after['type_id']
        if axis == 'trace_analysis':
            continue
        previous = before.get(axis, {})
        def detail(value):
            output = value.get('output') or {}
            assessment = output.get('assessment') or {}
            return {'status': value.get('status'), 'verdict': value.get('verdict'), 'error': value.get('error'),
                    'reason': assessment.get('reason') or (value.get('summary') or {}).get('text'),
                    'composition': assessment.get('composition'), 'issues': output.get('issues'),
                    'results': output.get('results'), 'execution_trace_ref': value.get('execution_trace_ref')}
        rows.append({'axis': axis, 'old': detail(previous), 'new': detail(after)})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', required=True, type=Path)
    parser.add_argument('--old', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    raw = args.trace.read_bytes()
    old_raw = args.old.read_bytes()
    old = json.loads(old_raw)
    old_report = old.get('report') or old.get('axes') or old
    manifest = {'trace_file': str(args.trace.resolve()), 'trace_sha256': hashlib.sha256(raw).hexdigest(),
                'old_file': str(args.old.resolve()), 'old_sha256': hashlib.sha256(old_raw).hexdigest(),
                'scope': 'process axes only, frozen business input, human semantic review required'}
    def save(name, data):
        (args.out/name).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str)+'\n')
    save('manifest.json', manifest)
    from impl.core.project_loader import load_project
    from impl.core.schema import normalize_run_trace
    from impl.projects.llm_probe.eval_axes import build_report
    trace = normalize_run_trace(json.loads(raw))
    report = build_report(load_project('llm_probe'), trace)
    save('result.json', {'report': report})
    rows = compare(old_report, report)
    save('comparison.json', rows)
    def cell(value):
        return '<pre>'+html.escape(json.dumps(value, ensure_ascii=False, indent=2))+'</pre>'
    body = ''.join('<tr><th>'+html.escape(row['axis'])+'</th><td>'+cell(row['old'])+'</td><td>'+cell(row['new'])+'</td></tr>' for row in rows)
    (args.out/'comparison.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><title>过程六轴冻结对照</title>'
        '<style>body{font:15px system-ui;padding:24px;background:#fafafa}table{border-collapse:collapse;width:100%}'
        'th,td{border:1px solid #ddd;padding:12px;vertical-align:top}pre{white-space:pre-wrap;overflow-wrap:anywhere}'
        'td{width:44%}</style><h1>过程六轴：旧输出与新协议</h1><p>同一冻结轨迹。运行失败单列，业务含义待人工核对。</p>'
        '<table><tr><th>轴</th><th>旧输出</th><th>新输出（组成与独立问题）</th></tr>'+body+'</table></html>')
    print(json.dumps({r['axis']: r['new']['status']+':'+str(r['new']['verdict']) for r in rows}, ensure_ascii=False))


if __name__ == '__main__':
    main()
