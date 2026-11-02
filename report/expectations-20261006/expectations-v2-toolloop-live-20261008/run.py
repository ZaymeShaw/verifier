"""Real-model check of the llmtracing ToolLoop entry on the synthetic test transcript.
The submit tool's parameters are the shared static-union schema; no business call is made."""
import json, os, sys, time
from pathlib import Path
OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT))
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
from impl.projects.llm_probe.eval_axes.llm import axis_llm
from impl.projects.llm_probe.eval_axes.adapters import process_common as common
from impl.projects.llm_probe.process_loop.llmtracing import TranscriptEvaluation
from impl.core.project_loader import load_project
from tests.support.expectations import E, PROJECTION
from tests.test_llmtracing_tool_loop import material

spec = load_project('llm_probe')
client = axis_llm(spec, role='judge')
axes = ('model_capability', 'planning_routing')
t0 = time.monotonic()
run = TranscriptEvaluation(material(), {a: common.PROCESS_SPECS[a] for a in axes}, None, client,
                           trace_id='toolloop-real', expectations=E, projection=PROJECTION)
out = run.run()
res = {a: dict(failed=o.failed, reason=o.failure_reason, verdict=(o.output.get('assessment') or {}).get('verdict'),
               units=len(o.output.get('results') or []), usage=o.usage) for a, o in out.items()}
(OUT / 'result.json').write_text(json.dumps({'elapsed': round(time.monotonic() - t0, 1), 'axes': res}, ensure_ascii=False, indent=1, default=str))
print(json.dumps({'elapsed': round(time.monotonic() - t0, 1), 'axes': {a: {k: v for k, v in r.items() if k != 'usage'} for a, r in res.items()}}, ensure_ascii=False, indent=1, default=str))
