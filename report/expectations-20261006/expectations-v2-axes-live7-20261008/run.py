"""Six axes against the real model; requirement axis, trace analysis and data-needs
projection are replayed from a recorded run (their prompts are unchanged by this iteration).
Gateway wiring and process axes are the current code. Results/contexts stay here.
usage: python run.py [recorded-run-dir-name]
"""
import json, os, sys, time
from pathlib import Path
OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT))
SRC = ROOT / 'report/expectations-20261006' / (sys.argv[1] if len(sys.argv) > 1 else 'expectations-v2-full-live4-20261008')
INSTANCE = ROOT / '.runtime/instances/inst-16fa340ac786414f'
RUN = OUT.name

from dotenv import dotenv_values

# Reuse configured provider identities; route capture through existing gateways.
# Do not activate the running server's data directory or overwrite its workspace.
for key in ('VERIFIER_INSTANCE_ID', 'VERIFIER_PORT', 'VERIFIER_TRACING_ENABLED'):
    os.environ.pop(key, None)
for suffix, endpoint in [('', 'primary'), ('_FALLBACK_1', 'fallback1'), ('_FALLBACK_2', 'fallback2')]:
    gateway = dotenv_values(INSTANCE / 'tracing' / ('.env.verifier_' + endpoint))
    os.environ['LLM' + suffix + '_BASE_URL'] = 'http://127.0.0.1:' + gateway['LITELLM_PORT'] + '/v1'
    os.environ['DEEPSEEK_API_KEY' if not suffix else 'LLM' + suffix + '_API_KEY'] = gateway['LITELLM_MASTER_KEY']
context_path = OUT.relative_to(ROOT).as_posix() + '/contexts'
os.environ['CONTEXT_STORE_ROOT'] = 'verifier://' + context_path
os.environ['CONTEXT_DATA_ROOT'] = 'verifier://' + OUT.relative_to(ROOT).as_posix() + '/context-runtime'


context_path = OUT.relative_to(ROOT).as_posix() + '/contexts'
os.environ['CONTEXT_STORE_ROOT'] = 'verifier://' + context_path
os.environ['CONTEXT_DATA_ROOT'] = 'verifier://' + OUT.relative_to(ROOT).as_posix() + '/context-runtime'

import dataclasses
from impl.core.llm_client import LlmClient
from impl.core.llm_tracing import trace_scope
from impl.core.pipeline import judge
from impl.core.schema import normalize_run_trace, to_dict
from impl.projects.llm_probe.eval_axes import registry
from impl.projects.llm_probe.eval_axes.types import AxisSummary, RunOutcome
from impl.projects.llm_probe.eval_axes.adapters.trace_analysis import prepare_selections

recorded = {}
import glob
for path in sorted(glob.glob(str(SRC / 'contexts/llm_probe/*/*.json'))):
    row = json.loads(Path(path).read_text())
    stage = ((row.get('response') or {}).get('runtime') or {}).get('stage', '')
    if stage in ('llm_probe_expectations', 'llm_probe_expectations_process_projection') and not row.get('error'):
        recorded[stage] = json.loads(row['response']['content'])  # last valid wins
prior = json.loads((SRC / 'result.json').read_text())
analysis = next(a for a in prior['axes']['results'] if a['axis_id'] == 'trace_analysis')

real = LlmClient.complete_json
def complete_json(self, system, user, *a, stage='', **kw):
    if stage in recorded:
        return json.loads(json.dumps(recorded[stage]))
    return real(self, system, user, *a, stage=stage, **kw)
def analysis_run(inputs, axis, runtime):
    out = json.loads(json.dumps(analysis['output']))
    out['selections'] = prepare_selections(out['dossier'], out['structure'], out['selections'])
    return RunOutcome(output=out, summary=AxisSummary(analysis['summary']['text']))
LlmClient.complete_json = complete_json
registry.AXIS_TYPES['trace_analysis'] = dataclasses.replace(registry.AXIS_TYPES['trace_analysis'], run=analysis_run)

trace = normalize_run_trace(json.loads((SRC / 'input-trace.json').read_text()))
start = time.monotonic()
print(json.dumps({'event': 'started', 'pid': os.getpid(), 'replayed': sorted(recorded)}, ensure_ascii=False), flush=True)
result = {'run_id': RUN}
try:
    with trace_scope(run_id=RUN, project_id='llm_probe', case_id=trace.case_id, execution_id=RUN + ':0', independent=True):
        decision = judge('llm_probe', trace)
    axes = getattr(trace, '_pending_process_report', None)
    result.update(judge=to_dict(decision), axes=axes, status='completed')
except Exception as exc:
    import traceback
    result.update(status='failed', error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
finally:
    result['elapsed_seconds'] = round(time.monotonic() - start, 3)
    (OUT / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + '\n')
    summary = {k: v for k, v in result.items() if k not in ('judge', 'axes', 'traceback')}
    summary['axes'] = [{k: a.get(k) for k in ('axis_id', 'status', 'verdict', 'error')} for a in (result.get('axes') or {}).get('results', [])]
    summary['fulfillment'] = (result.get('judge') or {}).get('overall_fulfillment')
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'event': 'finished', 'elapsed': result['elapsed_seconds']}), flush=True)
