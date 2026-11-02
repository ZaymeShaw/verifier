"""Offline token budget scenarios, calibrated to saved Qwen usage.

Captures every currently scheduled axis batch using a deliberately rejecting
client; no model request, accepted judgment, or production mutation occurs.
Candidate costs are engineering scenarios, NOT tokenizer-exact predictions.
"""
import copy
import json
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from impl.core.llm_client import extract_json
from impl.projects.llm_probe.eval_axes import registry
from impl.projects.llm_probe.eval_axes.adapters import process_common as common
from impl.projects.llm_probe.eval_axes.types import ScenarioAxis
from impl.projects.llm_probe.business_trace.materials import material_view, model_material
from impl.core.structured_output import render_output_constraint

SOURCE = ROOT / 'report/expectations-20261006/unit-format-full-live-20261007'
axes = {a['axis_id']: a for a in json.loads((SOURCE / 'result.json').read_text())['axes']['results']}
e = axes['expectations']['output']
analysis = axes['trace_analysis']['output']
saved = [json.loads(p.read_text()) for p in sorted((SOURCE / 'contexts').rglob('*.json'))]
measured = defaultdict(lambda: defaultdict(int))
axis_ratios = []
observed_checks = 0
projection = None
expectation_system = ''
for call in saved:
    system = call['messages'][0]['content']
    kind = ('expectations' if system.startswith('你读取 sources') else
            'projection' if system.startswith('你负责六轴材料准备') else
            'analysis' if '案卷整理员' in system else 'axes')
    metrics = call['response']['metrics']
    measured[kind]['calls'] += 1
    for key in ('input_tokens', 'output_tokens', 'reasoning_tokens', 'cache_read_tokens'):
        measured[kind][key] += metrics[key]
    if kind == 'projection':
        projection = extract_json(call['response']['content'])
    elif kind == 'expectations':
        expectation_system = system
    elif kind == 'axes':
        axis_ratios.append(metrics['input_tokens'] / call['prompt_size'])
        response = extract_json(call['response']['content'])
        observed_checks += sum(len(u['checks']) for u in response['units'])

class Capture:
    def __init__(self):
        self.batches = {}

    def complete_json(self, system, prompt, **kwargs):
        if kwargs['stage'] not in self.batches:
            self.batches[kwargs['stage']] = (system, json.loads(prompt), kwargs['output_spec'])
        raise ValueError('OFFLINE_COST_CAPTURE_NO_MODEL')

    def usage(self):
        return {}

client = Capture()
runtime = SimpleNamespace(spec=SimpleNamespace(project_id='llm_probe'), scenario_id='none',
                          trace_id='offline-cost-capture', ensure_time_left=lambda *_: None,
                          expectation_projection=projection, process_issues={})
with patch.object(common, 'axis_llm', return_value=client):
    for axis, spec in common.PROCESS_SPECS.items():
        common.run_process_axis(axis, {'expectations': e, 'trace_analysis': analysis},
                                ScenarioAxis(axis, True, ''), runtime, spec)

def chars(value):
    return len(json.dumps(value, ensure_ascii=False))

# Broader than the measured 0.396–0.410 tokens/character to account for changed
# payload composition. Schema/chat overhead is represented by existing prompts.
TOKEN_RATIO = (0.36, 0.46)
sources = {s['id']: s for s in e['sources']}
want_ids = {x['expectation_id'] for x in e['expectations']
            if any(sources[r]['side'] == 'want' for r in x['source_refs'])}
want = [x for x in e['expectations'] if x['expectation_id'] in want_ids]
want_sources = [s for s in e['sources'] if s['side'] in {'want', 'history'}]
declarations = [s for s in e['sources'] if s['side'] == 'commitment']
rule_source_chars = chars(declarations)
schema_suffix = render_output_constraint(next(iter(client.batches.values()))[2])
batch_stats = []
per_boundary_chars = 0
candidate_eval_chars = 0
original_eval_chars = 0
checks = 0
for stage, (system, request, spec) in client.batches.items():
    units = request['units']
    checks += sum(len(u['criteria']) for u in units.values())
    original_eval_chars += len(system) + len(render_output_constraint(spec)) + chars(request)
    draft = copy.deepcopy(request)
    # Remove summarized commitments, preserve all already-delivered raw sources.
    # The actual local rule registry is budgeted separately below.
    draft['expectations'] = [x for x in request['expectations'] if x['expectation_id'] in want_ids]
    draft['criteria'] = {k: v for k, v in draft['criteria'].items()
                         if not v.startswith('expectation:') or v.removeprefix('expectation:') in want_ids}
    for unit in draft['units'].values():
        unit['criteria'] = [k for k in unit['criteria'] if k in draft['criteria']]
    candidate_eval_chars += len(system) + len(schema_suffix) + chars(draft)
    links = {l['link_id']: l for l in request['links']['links']}
    selected_links = {u['link'] for u in units.values()}
    for link_id in selected_links:
        one = copy.deepcopy(draft)
        one['units'] = {uid: u for uid, u in one['units'].items() if u['link'] == link_id}
        one['links']['links'] = [links[link_id]]
        candidates = one['links']['match_candidates']
        selection = analysis['selections'].get(request['dimension'], {})
        one['dossier_view'] = model_material(material_view(
            analysis['dossier'], [links[link_id], *candidates], analysis['structure'].get('suspects', []),
            extra_refs=selection.get('refs', [])))
        # This is conservative: retain the existing reference catalog and
        # source tables. It measures an unoptimized per-boundary split.
        per_boundary_chars += len(system) + len(schema_suffix) + chars(one)
    batch_stats.append({'stage': stage, 'units': len(units), 'boundaries': len(selected_links),
                        'checks': sum(len(u['criteria']) for u in units.values()),
                        'request_chars': chars(request)})

B = len(batch_stats)
N = sum(b['boundaries'] for b in batch_stats)
analysis_in = measured['analysis']['input_tokens']
analysis_out = measured['analysis']['output_tokens']
visible_checks = measured['axes']['output_tokens'] - measured['axes']['reasoning_tokens']
tokens_per_check = visible_checks / observed_checks
baseline_visible = checks * tokens_per_check

# Common new-user preparation budget: 2 calls (wants; external-data necessity).
# Includes original capability declarations; no assumed free external lookup.
prep_chars = 2 * len(expectation_system) + 2 * chars(want_sources) + chars(want) + rule_source_chars + 4000
prep_in = (prep_chars * TOKEN_RATIO[0], prep_chars * TOKEN_RATIO[1])
prep_out = (2500, 7000)
# Each judging call retains semantic reasoning at the scale of observed calls.
judge_thinking = (2000, 5000)
registry_overhead = 2000  # input tokens per rule-registration call
registry_thinking = (1500, 4000)
# Not all declarations become unique rules. Hold rule mass constant across
# candidate scenarios to avoid assuming that savings come from missing checks.
unique_rules = 163
rule_visible = (35, 80)  # locator, scope, disposition; no full duplicate prose
per_check_visible = (tokens_per_check * .8, tokens_per_check * 1.2)

def estimate(name, eval_chars, judging_calls, registry_calls, repeat_rules, registry_raw_repeats,
             *, existing=False):
    result = {'name': name, 'model_calls': [], 'input_tokens': [], 'output_tokens': [],
              'visible_output_tokens': [], 'reasoning_output_tokens': []}
    for edge in range(2):
        k = registry_calls[edge]
        if existing:
            fixed_in = measured['expectations']['input_tokens'] + measured['projection']['input_tokens']
            fixed_out = measured['expectations']['output_tokens'] + measured['projection']['output_tokens']
            fixed_reason = measured['expectations']['reasoning_tokens'] + measured['projection']['reasoning_tokens']
            registry_in = registry_out = registry_reason = ledger_in = 0
        else:
            fixed_in, fixed_out = prep_in[edge], prep_out[edge]
            fixed_reason = (1500, 5000)[edge]
            registry_in = k * registry_overhead + rule_source_chars * TOKEN_RATIO[edge] * registry_raw_repeats[edge]
            registry_reason = k * registry_thinking[edge]
            registry_out = unique_rules * rule_visible[edge] * repeat_rules[edge] + registry_reason
            # Every check receives its corresponding frozen rule reference/scope.
            ledger_in = checks * rule_visible[edge] if k else 0
        judge_visible = checks * per_check_visible[edge]
        # Direct reading still records original rule locators in output.
        if not existing and not registry_calls[edge]:
            judge_visible += checks * rule_visible[edge]
        judge_reason = judging_calls * judge_thinking[edge]
        total_reason = measured['analysis']['reasoning_tokens'] + fixed_reason + registry_reason + judge_reason
        total_out = analysis_out + fixed_out + registry_out + judge_visible + judge_reason
        result['model_calls'].append(4 + 2 + k + judging_calls)
        result['input_tokens'].append(round(analysis_in + fixed_in + eval_chars * TOKEN_RATIO[edge] + registry_in + ledger_in))
        result['output_tokens'].append(round(total_out))
        result['reasoning_output_tokens'].append(round(total_reason))
        result['visible_output_tokens'].append(round(total_out - total_reason))
    return result

scenarios = [
    estimate('A current global extraction + mapping + batch judging', original_eval_chars, B, (0, 0), (0, 0), (0, 0), existing=True),
    estimate('B register and judge every boundary independently', per_boundary_chars, N, (N, N), (3, 6), (8, 16)),
    estimate('C register per existing batch, then batch judge', candidate_eval_chars, B, (B, B), (2, 4), (4, 8)),
    estimate('D register shared scoped rule sets, then batch judge', candidate_eval_chars, B, (2, 6), (1, 2), (1, 3)),
    estimate('E direct batch judging against raw rules, no prior registration', candidate_eval_chars, B, (0, 0), (0, 0), (0, 0)),
]
output = {
    'scope': 'Single frozen business trace, same current 13 scheduled batches; includes current 4-call analysis, '
             'user preparation, rule work and six-axis evaluation. Excludes business execution, retries/failovers, '
             'unobserved billing, final main judge, independent verifier-ready review and future extra batches. '
             'Current full schedule is captured with no accepted results, so later upstream-issue growth is not included.',
    'measured_usage': measured,
    'calibration': {'observed_axis_input_tokens_per_character': axis_ratios,
                    'used_input_tokens_per_character': TOKEN_RATIO,
                    'observed_visible_tokens_per_check': tokens_per_check,
                    'input_char_totals': {'A': original_eval_chars, 'B': per_boundary_chars,
                                          'C_D_E': candidate_eval_chars},
                    'rule_source_chars': rule_source_chars, 'unique_rule_assumption': unique_rules,
                    'new_prep_input_tokens': prep_in, 'new_prep_output_tokens': prep_out,
                    'judge_thinking_tokens_per_call': judge_thinking,
                    'registry_thinking_tokens_per_call': registry_thinking,
                    'registry_input_overhead_per_call': registry_overhead,
                    'rule_locator_scope_tokens_per_item': rule_visible,
                    'registry_rule_repetitions': {'B': [3,6], 'C': [2,4], 'D': [1,2]},
                    'registry_source_repetitions': {'B': [8,16], 'C': [4,8], 'D': [1,3]},
                    'uncertainty': 'Scenario ranges, not confidence intervals. Output lengths, rule-group count, '
                                   'material routing and repetition factors are assumptions, not measured candidate runs.'},
    'scheduled': {'batches': B, 'axis_scoped_positions': N,
                  'unit_count': sum(b['units'] for b in batch_stats), 'criterion_checks': checks, 'details': batch_stats},
    'scenarios': scenarios,
}
Path(__file__).with_name('token-estimates.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'scheduled': output['scheduled'], 'scenarios': scenarios}, ensure_ascii=False, indent=2))
