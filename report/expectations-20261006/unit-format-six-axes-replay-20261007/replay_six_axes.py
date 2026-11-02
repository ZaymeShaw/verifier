"""Six axes only, real model, frozen upstream (requirements / analysis / projection) from unit-format-full-live-20261007.

Production runner pieces (_run_one, issue registration order); no patched validation or retry logic.
"""
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
RUN = 'unit-format-six-axes-replay-20261007'
PREVIOUS = ROOT / 'report/expectations-20261006/unit-format-full-live-20261007'
INSTANCE = ROOT / '.runtime/instances/inst-16fa340ac786414f'
from dotenv import dotenv_values
for name in ('VERIFIER_INSTANCE_ID', 'VERIFIER_PORT', 'VERIFIER_TRACING_ENABLED'):
    os.environ.pop(name, None)
for suffix, endpoint in [('', 'primary'), ('_FALLBACK_1', 'fallback1'), ('_FALLBACK_2', 'fallback2')]:
    cfg = dotenv_values(INSTANCE / 'tracing' / ('.env.verifier_' + endpoint))
    os.environ['LLM' + suffix + '_BASE_URL'] = 'http://127.0.0.1:' + cfg['LITELLM_PORT'] + '/v1'
    os.environ['DEEPSEEK_API_KEY' if not suffix else 'LLM' + suffix + '_API_KEY'] = cfg['LITELLM_MASTER_KEY']
os.environ['CONTEXT_STORE_ROOT'] = 'verifier://' + OUT.relative_to(ROOT).as_posix() + '/contexts'
from impl.core.schema import normalize_run_trace
from impl.core.project_loader import load_project
from impl.core.llm_tracing import trace_scope
from impl.core.llm_client import extract_json
from impl.projects.llm_probe.eval_axes import registry  # noqa: F401
from impl.projects.llm_probe.eval_axes.runner import _run_one
from impl.projects.llm_probe.eval_axes.types import AxisRuntime, AxisResult, ScenarioAxis, STATUS_SUCCEEDED
from impl.projects.llm_probe.process_loop.expectation_projection import validate_join

prior = json.loads((PREVIOUS / 'result.json').read_text())['axes']
trace = normalize_run_trace(json.loads((PREVIOUS / 'input-trace.json').read_text()))
results = {a['type_id']: AxisResult(**a) for a in prior['results'] if a['type_id'] in ('expectations', 'trace_analysis')}
record = next(json.loads(p.read_text()) for p in (PREVIOUS / 'contexts').rglob('*.json')
              if (json.loads(p.read_text())['response'].get('runtime') or {}).get('stage') == 'llm_probe_expectations_process_projection')
projection = extract_json(record['response']['content'])
validate_join(projection, results['expectations'].output)
projection['expectations_sha256'] = results['expectations'].output['sha256']
six = [a for a in prior['axes'] if a['type'] not in ('expectations', 'trace_analysis')]
runtime = AxisRuntime(spec=load_project('llm_probe'), run_id=RUN, trace_id=RUN + ':' + trace.trace_id,
                      scenario_id=prior['scenario_id'], case_id=trace.case_id,
                      enabled_axes=tuple(a['type'] for a in six), expectation_projection=projection)
start = time.monotonic()
summary = []
with trace_scope(run_id=RUN, project_id='llm_probe', case_id=trace.case_id, execution_id=RUN + ':0', independent=True):
    for configured in six:
        axis = ScenarioAxis(configured['type'], configured['enabled'], configured['description'])
        result = _run_one(axis, trace, runtime, results)
        results[axis.type_id] = result
        if result.status == STATUS_SUCCEEDED:
            for issue in (result.output or {}).get('issues', []):
                runtime.process_issues[issue['problem_id']] = issue
        summary.append({'axis_id': axis.type_id, 'status': result.status, 'verdict': result.verdict,
                        'error': (result.error or '')[:600], 'elapsed_ms': (result.usage or {}).get('elapsed_ms')})
        print(json.dumps(summary[-1], ensure_ascii=False), flush=True)
(OUT / 'result.json').write_text(json.dumps({k: v.as_dict() for k, v in results.items()}, ensure_ascii=False, indent=2, default=str) + '\n')
(OUT / 'summary.json').write_text(json.dumps({'elapsed_seconds': round(time.monotonic() - start, 1), 'axes': summary}, ensure_ascii=False, indent=2) + '\n')
