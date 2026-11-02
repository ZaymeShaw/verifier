"""Real single-case evaluation replay: no business call, no patched validators.

Uses current project configuration, substituting only the existing tracing relay
addresses/keys in this child process. Contexts/results stay in this directory.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
RUN = 'analysis-split-full-live-20261007'
INSTANCE = ROOT / '.runtime/instances/inst-16fa340ac786414f'

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

from impl.core.config import get_runtime_config
from impl.core.schema import normalize_run_trace, to_dict
from impl.core.llm_tracing import trace_scope
from impl.core.pipeline import judge
from impl.projects.llm_probe.eval_axes import registry  # load current adapters before starting

source = ROOT / 'report/expectations-20261006/agno-singlecase-20261006T155209Z/run-result.json'
prior = json.loads(source.read_text())
raw_trace = prior['trace']
trace = normalize_run_trace(raw_trace)
assert trace.normalized_request['capability_ref'] == 'insurance-agno-e2e'
assert any((turn.get('project_fields', {}).get('business_trace') or {}).get('provider') == 'agno'
           for turn in trace.turn_records)
(OUT / 'input-trace.json').write_text(json.dumps(raw_trace, ensure_ascii=False, indent=2) + '\n')
config = get_runtime_config()
manifest = {
    'run_id': RUN, 'execution_id': RUN + ':0', 'case_id': trace.case_id,
    'input_source': str(source.relative_to(ROOT)), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
    'trace_sha256': hashlib.sha256(json.dumps(raw_trace, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
    'scope': 'full current Judge pipeline over frozen real Agno business trace; no business execution; no reused expectations/analysis/verdicts',
    'context_root': context_path,
    'model': config.llm.model, 'reasoning_effort': config.llm.reasoning_effort,
    'request_timeout_seconds': config.llm.request_timeout_seconds,
    'implementation': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (ROOT / 'impl').rglob('*') if p.is_file() and p.suffix in ('.py', '.yaml')},
    'protected_documents': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                            for part in ('demand', 'spec') for p in (ROOT / part).rglob('*') if p.is_file()},
    'gateway_offsets': {str(p.relative_to(ROOT)): p.stat().st_size
                        for p in (INSTANCE / 'tracing/logs').glob('*/llm_calls.jsonl')},
}
(OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
start = time.monotonic()
print(json.dumps({'event': 'started', 'pid': os.getpid(), 'run_id': RUN,
                  'case_id': trace.case_id, 'provider': 'agno'}, ensure_ascii=False), flush=True)
result = {'run_id': RUN, 'case_id': trace.case_id}
try:
    with trace_scope(run_id=RUN, project_id='llm_probe', case_id=trace.case_id,
                     execution_id=RUN + ':0', independent=True):
        decision = judge('llm_probe', trace)
    axes = getattr(trace, '_pending_process_report', None)
    result.update(judge=to_dict(decision), axes=axes, status='completed',
                  all_axes_succeeded=bool(axes) and all(a['status'] == 'succeeded' for a in axes['results']))
except Exception as exc:
    result.update(status='failed', error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc(),
                  axes=getattr(trace, '_pending_process_report', None))
finally:
    result['elapsed_seconds'] = round(time.monotonic() - start, 3)
    (OUT / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + '\n')
    summary = {k: v for k, v in result.items() if k not in ('judge', 'axes', 'traceback')}
    summary['axes'] = [{k: a.get(k) for k in ('axis_id', 'status', 'verdict', 'error', 'started_at', 'finished_at')}
                       for a in (result.get('axes') or {}).get('results', [])]
    summary['fulfillment'] = (result.get('judge') or {}).get('overall_fulfillment')
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'event': 'finished', **summary}, ensure_ascii=False), flush=True)
