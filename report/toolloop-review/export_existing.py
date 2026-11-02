"""只读复用现有轴展示组件，不评分、不聚类、不写候选区、不调用模型。"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from impl.core.axes_clustering import build_material
from impl.core.table_view import eval_axes_summary
from impl.projects.llm_probe.eval_axes.registry import describe_axis_types
from impl.projects.llm_probe.business_trace.reader import redact

OUT = Path(__file__).resolve().parent
sources, cases = [], []


def load(path):
    source = ROOT / path
    sources.append({'path': path, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
    return json.loads(source.read_text())


# Agno旧路径仅作为现有展示接线样例，不冒充新ToolLoop效果。
trace = load('report/business-trace-provider-ab-20261001/traces.json')['agno']
run = load('report/business-trace-provider-ab-20261001/agno-r2.json')
cases.append({'id': 'Agno｜历史旧评判路径（非当前ToolLoop成绩）',
              'scenario': 'insurance-agno-e2e · 旧runner',
              'inputPreview': '客户资料查询；真实业务请求与响应',
              'input': redact(trace['normalized_request']), 'output': redact(trace['extracted_output']),
              'fulfillment': run['judge']['overall_fulfillment']['status'],
              'axes': eval_axes_summary(run['axes'])})

for label in 'BCDE':
    raw = load(f'report/llmtracing-calibration-draft/process-baseline-v0/{label}/result.json')
    frozen = load(f'report/llmtracing-calibration-draft/frozen-inputs/{label}.trace.json')
    messages = []
    for turn in frozen['turn_records']:
        call = turn['project_fields']['business_trace']['records']['calls'][0]
        messages.append([m['content'] for m in call['pre']['messages'] if m.get('role') == 'user'])
    cases.append({'id': f'{label}｜llmtracing历史v0（已暂停推进）',
                  'scenario': '历史过程评判 · 非Agno ToolLoop',
                  'inputPreview': '模型请求中的用户消息；独立业务请求/实收缺失',
                  'input': {'source': 'model_request，不是独立业务原文', 'turns': messages},
                  'output': None, 'fulfillment': '未执行主裁决',
                  'axes': eval_axes_summary(raw['report'])})

for case in cases:
    case['axes'] = [a for a in case['axes'] if a['type_id'] != 'trace_analysis']
types = [t for t in describe_axis_types() if t['type_id'] in {a['type_id'] for c in cases for a in c['axes']}]
# 仅验证现有聚类输入构造可直接复用；不调用cluster_with_llm。
material = build_material([{'pool_index': i, 'request_key': f'preview:{i}', 'axes': c['axes']}
                           for i, c in enumerate(cases)], types)
payload = {'cases': cases, 'types': types,
           'meta': {'project': '历史结果只读预览｜原判分布不是准确率；当前Agno ToolLoop尚无本轮质量结论',
                    'generatedAt': '来自已保存记录；不连接服务、不触发聚类'}}
source = OUT / 'view-data.json'
source.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
node = """
const fs = require('fs');
require(process.argv[1] + '/impl/frontend/axes_overview.js');
require(process.argv[1] + '/impl/frontend/axes_experiment.js');
const d = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
let html = AxesExperiment.renderPage(d.cases, d.types, d.meta);
const csp = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:">`;
html = html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + csp);
fs.writeFileSync(process.argv[3], html);
"""
subprocess.run(['node', '-e', node, str(ROOT), str(source), str(OUT / 'existing-axes-view.html')], check=True)
(OUT / 'provenance.json').write_text(json.dumps({'sources': sources,
    'renderer': ['impl/frontend/axes_overview.js', 'impl/frontend/axes_experiment.js'],
    'records': len(cases), 'clustering_input_refs': len(material['refs']),
    'model_calls': 0, 'workspace_modified': False, 'semantic_clustering_run': False,
    'note': 'Contains local historical business data. Not for publishing. No new grades.'}, ensure_ascii=False, indent=2) + '\n')
print(f"Reused existing renderer: {len(cases)} records, {len(types)} axes; clustering input: {len(material['refs'])} refs; zero model calls")
print(OUT / 'existing-axes-view.html')
