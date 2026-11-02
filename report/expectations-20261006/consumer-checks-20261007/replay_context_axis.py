"""Real context-axis replay with frozen upstream results; uses the production runner.

No business execution, no reused unit judgments, no patched validation or retry logic.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
RUN = 'consumer-checks-context-live-20261007'
PREVIOUS = ROOT / 'report/expectations-20261006/analysis-split-full-live-20261007'
INSTANCE = ROOT / '.runtime/instances/inst-16fa340ac786414f'
from dotenv import dotenv_values
for name in ('VERIFIER_INSTANCE_ID', 'VERIFIER_PORT', 'VERIFIER_TRACING_ENABLED'):
    os.environ.pop(name, None)
for suffix, endpoint in [('', 'primary'), ('_FALLBACK_1', 'fallback1'), ('_FALLBACK_2', 'fallback2')]:
    cfg = dotenv_values(INSTANCE / 'tracing' / ('.env.verifier_' + endpoint))
    os.environ['LLM' + suffix + '_BASE_URL'] = 'http://127.0.0.1:' + cfg['LITELLM_PORT'] + '/v1'
    os.environ['DEEPSEEK_API_KEY' if not suffix else 'LLM' + suffix + '_API_KEY'] = cfg['LITELLM_MASTER_KEY']
os.environ['CONTEXT_STORE_ROOT'] = 'verifier://' + OUT.relative_to(ROOT).as_posix() + '/live-contexts'
from impl.core.schema import normalize_run_trace
from impl.core.project_loader import load_project
from impl.core.llm_tracing import trace_scope
from impl.core.llm_client import extract_json
from impl.projects.llm_probe.eval_axes import registry
from impl.projects.llm_probe.eval_axes.runner import _run_one
from impl.projects.llm_probe.eval_axes.types import AxisRuntime, AxisResult, ScenarioAxis
from impl.projects.llm_probe.process_loop.expectation_projection import validate_join

prior = json.loads((PREVIOUS / 'result.json').read_text())['axes']
trace = normalize_run_trace(json.loads((PREVIOUS / 'input-trace.json').read_text()))
upstream = {a['type_id']: AxisResult(**a) for a in prior['results'] if a['type_id'] in ('expectations', 'trace_analysis')}
projection_records = []
for path in (PREVIOUS / 'contexts').rglob('*.json'):
    record = json.loads(path.read_text())
    if (record.get('response') or {}).get('runtime', {}).get('stage') == 'llm_probe_expectations_process_projection':
        projection_records.append((path, record))
assert len(projection_records) == 1
path, record = projection_records[0]
projection = extract_json(record['response']['content'])
validate_join(projection, upstream['expectations'].output)
projection['expectations_sha256'] = upstream['expectations'].output['sha256']
configured = next(a for a in prior['axes'] if a['type'] == 'context_memory')
axis = ScenarioAxis(configured['type'], configured['enabled'], configured['description'])
runtime = AxisRuntime(spec=load_project('llm_probe'), run_id=RUN, trace_id=RUN + ':' + trace.trace_id,
                      scenario_id=prior['scenario_id'], case_id=trace.case_id,
                      enabled_axes=('context_memory',), expectation_projection=projection)
manifest = {'run_id': RUN, 'case_id': trace.case_id, 'scope': 'context_memory only, same frozen requirements/analysis/projection; new unit judgments',
            'upstream_run_id': prior['run_id'], 'expectations_sha256': upstream['expectations'].output['sha256'],
            'projection_record': str(path.relative_to(ROOT)),
            'gateway_offsets': {str(p.relative_to(ROOT)): p.stat().st_size for p in (INSTANCE / 'tracing/logs').glob('*/llm_calls.jsonl')},
            'implementation': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (ROOT / 'impl').rglob('*.py')}}
(OUT / 'live-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
start = time.monotonic()
print(json.dumps({'event': 'started', 'run_id': RUN, 'case_id': trace.case_id}, ensure_ascii=False), flush=True)
with trace_scope(run_id=RUN, project_id='llm_probe', case_id=trace.case_id, execution_id=RUN + ':0', independent=True):
    result = _run_one(axis, trace, runtime, upstream)
value = result.as_dict()
(OUT / 'live-result.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
summary = {k: value[k] for k in ('axis_id', 'status', 'verdict', 'error', 'usage', 'execution_trace_ref')}
summary['elapsed_seconds'] = round(time.monotonic() - start, 3)
(OUT / 'live-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'event': 'finished', **summary}, ensure_ascii=False), flush=True)
