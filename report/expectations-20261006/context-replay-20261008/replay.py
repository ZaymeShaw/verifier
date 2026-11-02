"""Offline context replay: rebuild every six-axis prompt from a recorded run, no model calls.

Upstream model outputs (requirement axis payload, trace-analysis structure,
data-needs projection payload) come from the recorded run; all program logic
(materials, units, prompt assembly) is the current code. Six-axis calls are
captured and stopped before any request. Writes prompts/<stage>.json and
report.json next to this file.

usage: python replay.py [recorded-run-dir-name]
"""
import dataclasses
import glob
import json
from pathlib import Path
import sys

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT))
SRC = ROOT / 'report/expectations-20261006' / (sys.argv[1] if len(sys.argv) > 1 else 'expectations-v2-full-live3-20261007')
BUDGET = 40_000  # demand/context.md: judge ≈40k

from impl.core.llm_client import LlmClient
from impl.core.project_loader import load_project
from impl.core.schema import normalize_run_trace
from impl.projects.llm_probe.eval_axes import build_report, registry
from impl.projects.llm_probe.eval_axes.types import AxisSummary, RunOutcome
from impl.projects.llm_probe.eval_axes.adapters.trace_analysis import prepare_selections


class Captured(ValueError):
    """Raised instead of sending a six-axis request."""


recorded = {}
for path in sorted(glob.glob(str(SRC / 'contexts/llm_probe/*/*.json'))):
    row = json.loads(Path(path).read_text())
    stage = ((row.get('response') or {}).get('runtime') or {}).get('stage', '')
    if stage in ('llm_probe_expectations', 'llm_probe_expectations_process_projection') and not row.get('error'):
        recorded.setdefault(stage, json.loads(row['response']['content']))
result = json.loads((SRC / 'result.json').read_text())
analysis = next(a for a in result['axes']['results'] if a['axis_id'] == 'trace_analysis')

prompts = {}


def complete_json(self, system, user, trace_id=None, reasoning_effort=None, output_spec=None, stage='', **_):
    if stage in recorded:
        return json.loads(json.dumps(recorded[stage]))
    if stage.startswith('llm_probe_process_'):
        prompts.setdefault(stage, {"system": system, "user": user})
        raise Captured(stage)
    raise RuntimeError(f'offline replay: unexpected model stage {stage!r}')


def analysis_run(inputs, axis, runtime):
    # Recorded analyst structure; deterministic handoff rebuilt by current code.
    output = json.loads(json.dumps(analysis['output']))
    output['selections'] = prepare_selections(output['dossier'], output['structure'], output['selections'])
    return RunOutcome(output=output, summary=AxisSummary(analysis['summary']['text']))


LlmClient.complete_json = complete_json
registry.AXIS_TYPES['trace_analysis'] = dataclasses.replace(registry.AXIS_TYPES['trace_analysis'], run=analysis_run)

trace = normalize_run_trace(json.loads((SRC / 'input-trace.json').read_text()))
report = build_report(load_project('llm_probe'), trace, run_id='context-replay')

rows = []
(OUT / 'prompts').mkdir(exist_ok=True)
for stage, prompt in prompts.items():
    (OUT / 'prompts' / f'{stage}.json').write_text(json.dumps(prompt, ensure_ascii=False, indent=1))
    body = json.loads(prompt['user'])
    parts = {k: len(json.dumps(v, ensure_ascii=False)) for k, v in body.items()}
    total = len(prompt['system']) + len(prompt['user'])
    rows.append({'stage': stage, 'system': len(prompt['system']), 'user': len(prompt['user']), 'total': total,
                 'over_budget': total > BUDGET, 'parts': dict(sorted(parts.items(), key=lambda kv: -kv[1]))})
axes = {r['axis_id']: (r['status'], (r.get('error') or '')[:160]) for r in report['results']}
summary = {'source': SRC.name, 'budget_chars': BUDGET, 'calls': len(rows),
           'total_chars': sum(r['total'] for r in rows), 'max_chars': max((r['total'] for r in rows), default=0),
           'over_budget': sum(r['over_budget'] for r in rows), 'axes': axes, 'prompts': rows}
(OUT / 'report.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1))
print(f"calls={summary['calls']} total={summary['total_chars']} max={summary['max_chars']} over_budget={summary['over_budget']}")
for r in rows:
    top = ', '.join(f'{k}={v}' for k, v in list(r['parts'].items())[:4])
    print(f"{r['stage'][18:]:34s} {r['total']:7d}  {top}")
for k, (status, err) in axes.items():
    if not err.endswith('offline') and 'Captured' not in err and status != 'succeeded':
        print('  axis', k, status, err[:120])
