"""Expectation isolation and six-axis coverage. Scripted outputs test protocols, not model quality."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from impl.core.structured_output import StructuredOutputSpec, enforce_output
from impl.projects.llm_probe.business_trace.expectation_material import project_requirements
from impl.projects.llm_probe.business_trace.providers.llmtracing_transcript import build_transcript
from impl.projects.llm_probe.business_trace.providers.llmtracing_evidence import TranscriptEvidence
from impl.projects.llm_probe.eval_axes.adapters import expectations as axis
from impl.projects.llm_probe.eval_axes.adapters import process_common as common
from impl.projects.llm_probe.eval_axes.types import ScenarioAxis
from impl.projects.llm_probe.process_loop import expectation_projection as projection
from impl.projects.llm_probe.process_loop.llmtracing import TranscriptEvaluation, OUTPUT
from tests.test_llmtracing_tool_loop import make_trace, ScriptClient, payload


def fixture():
    material = {'sources': [
        dict(id='user', side='want', turn='t1', component='user', value='查询保单现金价值', scope='request', trace_refs=['t1.c1.m2']),
        dict(id='tools', side='commitment', turn='t1', component='tools', value={'name': 'lookup'}, scope='request', trace_refs=['t1.c1.tools']),
        dict(id='format', side='commitment', turn='t1', component='format', value={'type': 'json_object'}, scope='request', trace_refs=['t1.c1.params'])],
        'missing': [], 'sha256': 'material'}
    entries = [dict(expectation_id=ident, source_refs=[ref], about=about, statement=statement, condition='总是', ambiguity_group='')
               for ident, ref, about, statement in [('Q','user','保单现金价值','告知金额'), ('T','tools','lookup返回','含现金价值'),
                                                    ('F','format','整个响应','有效 JSON，不含附加文本')]]
    e = dict(expectations=entries, sources=material['sources'], missing=[], verdict='complete', material_sha256='material', sha256='E')
    join = dict(data_needs=[dict(expectation_id='Q', need='tool', tool_expectation_ids=['T'], reason='工具可提供金额')],
                contracts=[dict(expectation_id='T', axes=['tool_execution', 'knowledge_data']), dict(expectation_id='F', axes=['model_capability'])])
    return material, e, join


def result(ob='work_coverage', link='planning_routing:expected:Q', outcome='insufficient_evidence', ids=('Q',), matched=''):
    return dict(obligation_id=ob, link_id=link, outcome=outcome, expectation_ids=list(ids), matched_link_id=matched,
                expectation_checks=[dict(expectation_id=x, outcome=outcome, observed='核对原文') for x in ids],
                observed='没有可见的查询', source_refs=[], evidence={'input':['t1.c1.m2'], 'output':[]},
                missing=['原始产出'] if outcome in {'insufficient_evidence', 'contract_missing'} else [],
                problems=[], upstream_issue_ids=[], judged_by='llm', flags=[])


def test_projection_excludes_outputs_runtime_system_tools_and_caller_ability():
    trace = make_trace()
    records = trace.project_fields['business_trace']['records']
    first = records['calls'][0]['pre']
    first['messages'][0]['content'] = '[本轮 Direct 已执行] 状态=EMPTY; PRIVATE_RUNTIME'
    first['tools'] = [{'type':'function','function':{'name':'lookup','parameters':{'type':'object'}}}]
    first['optional_params'] = {'response_format': {'type':'json_object'}, 'runtime_value':'PRIVATE_PARAM'}
    records['definitions'] = [{'data': {'system_message':'声明的静态规则',
                                      'instruction_templates':[{'template':'状态={status}; 不重复查询','instance':'PRIVATE_INSTANCE'}]}}]
    y = project_requirements(trace, {'criterion':'按原文作答', 'capability':'PRIVATE_CAPABILITY'})
    text = json.dumps(y, ensure_ascii=False)
    assert not any(value in text for value in ('PRIVATE_RUNTIME', 'PRIVATE_PARAM', 'PRIVATE_INSTANCE', 'PRIVATE_CAPABILITY','state unknown'))
    assert '状态={status}' in text and '声明的静态规则' in text
    changed = copy.deepcopy(trace)
    changed.raw_response = {'answer':'changed'}
    changed.project_fields['business_trace']['records']['calls'][1]['outcome'] = {'event':'failure','error':'changed'}
    assert y == project_requirements(changed, {'criterion':'按原文作答', 'capability':'different'})


def test_history_resolves_reference_but_current_assistant_is_not_input_to_e():
    trace = make_trace()
    first = trace.project_fields['business_trace']['records']['calls'][0]['pre']
    first['messages'] = [first['messages'][0], {'role':'user','content':'P001状态'},
                         {'role':'assistant','content':'有效'}, {'role':'user','content':'它的缴费方式呢'}]
    y = project_requirements(trace)
    assert [s['value'] for s in y['sources'] if s['side']=='want'] == ['它的缴费方式呢']
    assert len([s for s in y['sources'] if s['side']=='history']) == 2
    assert any(m['component']=='system' for m in y['missing'])
    assert 'state unknown' not in json.dumps(y)


def test_agno_original_run_input_and_definition_provenance():
    trace = SimpleNamespace(turn_records=[], normalized_request={}, project_fields={'business_trace':{'records':{
        'run':{'run_input':'查P002现金价值','content':'SECRET_RESULT'},
        'definitions':[{'data':{'system_message':'只按工具结果回答'}}]}}})
    y = project_requirements(trace)
    assert y['sources'][0]['value']=='查P002现金价值'
    assert y['sources'][1]['scope']=='observed_at_collection_not_verified_run_version'
    assert 'SECRET_RESULT' not in json.dumps(y)


@pytest.mark.parametrize('change', ['duplicate', 'runtime_ref', 'history_only', 'mixed_sides', 'single_ambiguity', 'empty', 'consumer_field'])
def test_invalid_expectation_sets_rejected(change):
    material,e,_=fixture();p={'expectations':copy.deepcopy(e['expectations'])}
    if change=='duplicate':p['expectations'].append(copy.deepcopy(p['expectations'][0]))
    if change=='runtime_ref':p['expectations'][0]['source_refs']=['t1.c2.response']
    if change=='history_only':material['sources'][0]['side']='history'
    if change=='mixed_sides':p['expectations'][0]['source_refs'].append('tools')
    if change=='single_ambiguity':p['expectations'][0]['ambiguity_group']='g'
    if change=='empty':p['expectations'][0]['about']=' '
    if change=='consumer_field':p['expectations'][0]['blocking']=True
    with pytest.raises(ValueError):axis.validate(p,material)


def test_material_verdict_and_bounded_reprompt_do_not_depend_on_consumers(monkeypatch):
    material,e,_=fixture(); material['missing']=[{'component':'system','reason':'未记录','turn':'t1'}]
    sent=[]
    class Client:
        def complete_json(self,system,prompt,**kwargs):
            sent.append(prompt)
            return {'expectations': e['expectations']} if len(sent)%2==0 else {'expectations':[]}
        def usage(self):return {'llm_calls':len(sent)}
    monkeypatch.setattr(axis,'axis_llm',lambda *a,**kw:Client())
    runtime=SimpleNamespace(spec=None,trace_id='test',ensure_time_left=lambda *_:None,enabled_axes=['model_capability'])
    one=axis.run({'requirements':material},ScenarioAxis('expectations',True,''),runtime)
    runtime.enabled_axes=['model_capability','fulfilled']
    two=axis.run({'requirements':material},ScenarioAxis('expectations',True,''),runtime)
    assert one.output==two.output and one.output['verdict']=='partial'
    assert len(sent)==4 and sent[0]==sent[2]


def test_join_and_required_units_independent_of_runtime():
    _,e,join=fixture();frozen=copy.deepcopy(e);projection.validate_join(join,e)
    for name in common.PROCESS_SPECS:
        units=projection.required_units(name,e,join)
        assert units and units[0]['expectation_ids']==['Q']
        assert not units[0]['output']
    assert e==frozen
    join['data_needs'][0].update(need='unknown',tool_expectation_ids=[])
    assert projection.required_units('knowledge_data',e,join)[0]['contract_missing']
    e['missing']=[{'component':'tools'}];join['data_needs'][0]['need']='not_provided'
    with pytest.raises(ValueError,match='缺失'):projection.validate_join(join,e)


def test_missing_required_coverage_and_false_na_are_errors():
    _,e,join=fixture();units=projection.required_units('planning_routing',e,join)
    obs={o.obligation_id:o for o in common.PROCESS_SPECS['planning_routing'].obligations}
    with pytest.raises(ValueError,match='未覆盖'):projection.bind_results([],obs,e,units)
    with pytest.raises(ValueError,match='不能用未发生'):projection.bind_results([result(outcome='not_applicable')],obs,e,units)
    row=result(outcome='pass')
    with pytest.raises(ValueError,match='未对接'):projection.bind_results([row],obs,e,units)
    row['matched_link_id']='t2.c1.response'
    with pytest.raises(ValueError,match='轮次'):projection.bind_results([row],obs,e,units,runtime_links={'t2.c1.response':{'kind':'response'}})


def test_expected_is_derived_and_each_referenced_contract_checked():
    _,e,join=fixture();row=result();ob={'work_coverage':common.PROCESS_SPECS['planning_routing'].obligations[2]}
    projection.bind_results([row],ob,e,projection.required_units('planning_routing',e,join))
    assert '告知金额' in row['expected'] and row['source_refs']==['expectation:Q']
    row['expectation_ids'].append('F')
    with pytest.raises(ValueError,match='独立核对'):projection.bind_results([row],ob,e)
    with pytest.raises(ValueError,match='未核对'):projection.validate_contract_coverage([], 'model_capability',join)
    old=payload('model_capability');old['results'][0]['expected']='只要片段字段齐全'
    with pytest.raises(ValueError):enforce_output(old,OUTPUT,caller='test')


def test_one_actual_exercise_with_multiple_expectations_is_counted_once():
    rows=[]
    for q in ['Q','Q2']:
        row=result(link='planning_routing:expected:'+q,ids=(q,),matched='planning_routing:path:turn1');row['expected']=q;rows.append(row)
    out=projection.coalesce(rows)
    assert len(out)==1 and len(out[0]['checks'])==2 and out[0]['expectation_ids']==['Q','Q2']


def test_inherited_params_are_actual_input_and_whole_json_is_checked():
    trace=make_trace()
    for call in trace.project_fields['business_trace']['records']['calls']:
        call['pre']['optional_params']={'response_format':{'type':'json_object'}}
    trace.project_fields['business_trace']['records']['calls'][1]['outcome']['response']['choices'][0]['message']['content']='说明\n```json\n{"answer":"ok"}\n```'
    tr=build_transcript(trace,trace.project_fields['business_trace']);idx=TranscriptEvidence(tr)
    assert idx.records['t1.c2.params']['canonical_ref']=='t1.c1.params'
    assert 't1.c1.params' in idx.call_inputs('t1.c2')['input_refs']
    assert idx.records['t1.c2.response']['whole_content_json'] is False
    _,e,_=fixture();row=result('output_contract','t1.c2.response','pass',('F',));row['evidence']={'input':['t1.c1.params'],'output':['t1.c2.response']}
    obs={o.obligation_id:o for o in common.PROCESS_SPECS['model_capability'].obligations}
    projection.bind_results([row],obs,e)
    assert any('完整 content' in err for err in idx.validate([row],obs,set(idx.records),expectations=e))
    row['expectation_ids']=['Q'];e['sources'][0]['trace_refs']=['t2.c1.m2']
    assert any('未证实进入' in err for err in idx.validate([row],obs,set(idx.records),expectations=e))


def test_required_missing_query_cross_axis_full_loop():
    _,e,join=fixture()
    # The only commitment here is the tool capability; don't involve JSON in this test.
    e['expectations']=e['expectations'][:2];e['sources']=e['sources'][:2]
    join['contracts']=[dict(expectation_id='T',axes=['knowledge_data'])]
    axes=('planning_routing','knowledge_data')
    submissions=[]
    for name in axes:
        p=payload(name)
        for unit in projection.required_units(name,e,join):
            for ob in unit['obligation_ids']:
                row=dict(obligation_id=ob,link_ids=[unit['link_id']],outcome='input_invalid',expectation_ids=['Q'],
                    expectation_checks=[dict(expectation_id='Q',outcome='input_invalid',observed='规划漏掉查询')],
                    matched_link_id='',observed='规划漏掉查询',source_refs=[],input_refs=['t1.c1.m2'],output_refs=[],missing=[],
                    problems=[],upstream_issue_ids=['missing-query'])
                if name=='planning_routing':
                    row.update(outcome='fail',matched_link_id='t1.c2.response',upstream_issue_ids=[],output_refs=['t1.c2.response'],
                        expectation_checks=[dict(expectation_id='Q',outcome='fail',observed='已收到要求却直接结束')],problems=[dict(
                        problem_id='missing-query',phenomenon='未安排查询',expectation_ids=['Q'],observed='直接结束',source_refs=[],
                        input_refs=['t1.c1.m2'],output_refs=['t1.c2.response'],attribution_axes=[name],impact='unknown')])
                p['results'].append(row)
        if name=='knowledge_data':
            # Runtime uncertainty must not convert an unexecuted data exercise into a test.
            p['results']=[r for r in p['results'] if ':expected:' in r['link_ids'][0]] + [
                {**r,'outcome':'input_invalid','upstream_issue_ids':['missing-query']} for r in p['results'] if ':expected:' not in r['link_ids'][0]]
            p['results'][0]['expectation_ids'].append('T')
            p['results'][0]['expectation_checks'].append(dict(expectation_id='T',outcome='input_invalid',observed='规划未发起工具调用'))
        submissions.append([(f'eval_{name}',p)])
    trace=make_trace();tr=build_transcript(trace,trace.project_fields['business_trace'])
    client=ScriptClient([[('evidence_read',{'ids':['t1.request','t1.c1.m2','t1.c2.response']})],*submissions,'done'])
    out=TranscriptEvaluation(tr,{a:common.PROCESS_SPECS[a] for a in axes},{a:'' for a in axes},None,client,
                             expectations=e,projection=join,trace_id='missing-query').run()
    assert all(not v.failed for v in out.values()),[(k,v.failure_reason,v.usage) for k,v in out.items()]
    assert out['planning_routing'].output['assessment']['verdict']=='problematic'
    assert out['knowledge_data'].output['assessment']['verdict']=='untested'


def test_frozen_b_projection_has_format_but_no_business_outputs():
    from impl.core.schema import normalize_run_trace
    root=Path(__file__).resolve().parents[1]
    trace=normalize_run_trace(json.loads((root/'report/llmtracing-calibration-draft/frozen-inputs/B.trace.json').read_text()))
    y=project_requirements(trace)
    assert any(s['component']=='format' and s['value']['type']=='json_schema' for s in y['sources'])
    assert all(not ref.endswith('.response') for s in y['sources'] for ref in s['trace_refs'])
    assert any(m['component']=='system' for m in y['missing'])


def test_pending_lists_every_required_pair_and_each_model_call_once():
    _,e,join=fixture();trace=make_trace();tr=build_transcript(trace,trace.project_fields['business_trace'])
    run=TranscriptEvaluation(tr,{'model_capability':common.PROCESS_SPECS['model_capability']},{},None,ScriptClient([]),
        expectations=e,projection=join,trace_id='pending')
    assert run._pending('model_capability')['output_faithful']==['model_capability:expected:Q','t1.c1.response','t1.c2.response']
    assert run._parameters('model_capability')['$defs']['ResultGroup']['properties']['obligation_id']['enum']==list(run.obligations['model_capability'])


def test_missing_final_rejects_claimed_impact():
    trace=make_trace();trace.raw_response=None;trace.extracted_output={}
    tr=build_transcript(trace,trace.project_fields['business_trace']);idx=TranscriptEvidence(tr)
    row=result('output_faithful','t1.c2.response');row['problems']=[dict(source_refs=[],input_refs=[],output_refs=[],impact='yes')]
    ob={'output_faithful':common.PROCESS_SPECS['model_capability'].obligations[0]}
    _,e,_=fixture()
    assert any('impact 必须 unknown' in s for s in idx.validate([row],ob,set(idx.records),expectations=e))


def test_definition_without_actual_model_input_cannot_support_verdict():
    _,e,_=fixture();e['sources'][0]['scope']='observed_at_collection_not_verified_run_version'
    row=result('output_faithful','model_capability:call','pass');row['evidence']['input']=['call'];ob={'output_faithful':common.PROCESS_SPECS['model_capability'].obligations[0]}
    links={'model_capability:call':dict(input=[{'ref':'call','field':'exact_request'}])}
    dossier={'records':[{'id':'call','fields':{'exact_request':{'value':{'messages':[{'role':'user','content':'another request'}]}}}}]}
    with pytest.raises(ValueError,match='期望原文未证实'):projection.validate_dossier_expectations([row],ob,e,links,dossier)
    dossier['records'][0]['fields']['exact_request']['value']['messages'][0]['content']=e['sources'][0]['value']
    projection.validate_dossier_expectations([row],ob,e,links,dossier)


def test_shared_projection_cache_survives_runtime_deadline_copy():
    from dataclasses import replace
    from impl.projects.llm_probe.eval_axes.types import AxisRuntime
    runtime=AxisRuntime(None,'run','trace','scenario','case')
    one=replace(runtime,deadline=1);one.expectation_projection.update({'expectations_sha256':'E'})
    assert replace(runtime,deadline=2).expectation_projection=={'expectations_sha256':'E'}


def test_expectations_are_analysis_and_not_clustering_dimensions():
    from impl.core.table_view import eval_axes_summary
    from impl.core.axes_clustering import build_material
    from impl.projects.llm_probe.eval_axes.registry import AXIS_TYPES
    _,e,_=fixture()
    report={'results':[{'type_id':'expectations','status':'succeeded','verdict':'complete','output':e}]}
    rows=eval_axes_summary(report)
    assert rows[0]['role']=='analysis'
    data=build_material([{'pool_index':0,'request_key':'case','axes':rows}],[AXIS_TYPES['expectations'].describe()])
    assert not data['axes'] and not data['refs']


def test_agno_history_is_context_only_and_current_output_excluded():
    trace=SimpleNamespace(turn_records=[],normalized_request={},project_fields={'business_trace':{'records':{
        'run':{'run_id':'current','run_input':'它的缴费方式呢','content':'CURRENT_SECRET'},
        'history_runs':[{'run_id':'past','run_input':'P001状态','content':'已生效'},
                        {'run_id':'current','run_input':'它的缴费方式呢','content':'CURRENT_SECRET'}]}}})
    y=project_requirements(trace)
    assert len([s for s in y['sources'] if s['side']=='history'])==2
    assert 'CURRENT_SECRET' not in json.dumps(y)


def test_explicit_empty_tool_set_is_present_not_missing():
    trace=make_trace();trace.project_fields['business_trace']['records']['calls'][0]['pre']['tools']=[]
    y=project_requirements(trace)
    assert not any(m['component']=='tools' for m in y['missing'])


@pytest.mark.parametrize('item', json.loads((Path(__file__).parent/'fixtures/expectations_gold.json').read_text())['cases'], ids=lambda item:item['id'])
def test_spec_gold_fixtures_obey_provider_contract(item):
    # These are human-readable semantic baselines, not a claim that a live model matched them.
    axis.validate(item['expected'],item['material'])


def test_expectation_failure_blocks_six_axes_without_starting_consumer(monkeypatch):
    from impl.projects.llm_probe.eval_axes import build_report
    from impl.projects.llm_probe.process_loop import llmtracing
    monkeypatch.setattr(axis,'run',lambda *a: (_ for _ in ()).throw(ValueError('invalid expectations')))
    monkeypatch.setattr(llmtracing,'axis_llm',lambda *a,**kw:pytest.fail('consumer must not start'))
    report=build_report(SimpleNamespace(project_id='llm_probe'),make_trace())
    rows={r['type_id']:r for r in report['results']}
    assert rows['expectations']['status']=='failed'
    assert rows['trace_analysis']['status']=='succeeded'
    assert all(rows[a]['status']=='blocked' and rows[a]['output'] is None for a in common.PROCESS_SPECS)


def test_dossier_order_provides_planning_issues_before_dependent_data(monkeypatch):
    from impl.projects.llm_probe import capability
    from impl.projects.llm_probe.eval_axes import build_report, runner
    seen=[]
    monkeypatch.setattr(capability,'capability_business_trace',lambda _: {'provider':'agno'})
    monkeypatch.setattr(runner,'run_axes',lambda spec,trace,axes,**kw:seen.extend(a.type_id for a in axes) or [])
    trace=make_trace('agno');trace.normalized_request={'capability_ref':'insurance-agno-e2e'}
    build_report(SimpleNamespace(project_id='llm_probe'),trace)
    assert seen.index('expectations')<seen.index('planning_routing')<seen.index('tool_execution')<seen.index('knowledge_data')
    assert seen.index('context_memory')<seen.index('model_capability')


def test_dossier_model_cannot_borrow_other_call_even_without_e_refs():
    row=result('output_faithful','model_capability:call','pass',ids=());row['evidence']['input']=['other-call']
    ob={'output_faithful':common.PROCESS_SPECS['model_capability'].obligations[0]}
    with pytest.raises(ValueError,match='不属于该次实际输入'):
        projection.validate_dossier_expectations([row],ob,{'expectations':[],'sources':[]},
            {'model_capability:call':{'input':[{'ref':'call','field':'exact_request'}]}},{'records':[]})


def test_transcript_pending_never_looks_like_an_optional_empty_obligation():
    from tests.support.expectations import E, PROJECTION
    trace=make_trace();tr=build_transcript(trace,trace.project_fields['business_trace'])
    run=TranscriptEvaluation(tr,{'context_memory':common.PROCESS_SPECS['context_memory']},{},None,ScriptClient([]),
        expectations=E,projection=PROJECTION,trace_id='pending')
    assert all(refs==['transcript'] for refs in run._pending('context_memory').values())


def test_all_accepted_results_finish_before_requesting_deadline_expired_prose():
    from tests.support.expectations import E, PROJECTION
    trace=make_trace();tr=build_transcript(trace,trace.project_fields['business_trace'])
    axes=tuple(common.PROCESS_SPECS)
    client=ScriptClient([[('evidence_read',{'ids':['t1.request']})],[(f'eval_{a}',payload(a)) for a in axes]])
    run=TranscriptEvaluation(tr,{a:common.PROCESS_SPECS[a] for a in axes},{},None,client,
        expectations=E,projection=PROJECTION,trace_id='completed')
    original=run.post_batch_hook.post_batch
    def expire_after_submission(history,calls):
        notes=original(history,calls)
        if set(run.submitted)==set(axes):run.meter.deadline=0
        return notes
    run.post_batch_hook.post_batch=expire_after_submission
    out=run.run()
    assert all(not value.failed for value in out.values())
    assert len(client.requests)==2
    assert run.completion_hook.checks[-1]['decision']=='done'


@pytest.mark.parametrize('path', ['dossier', 'shared_dossier', 'transcript'])
def test_model_schema_accepts_empty_match_and_still_requires_it(path):
    from impl.projects.llm_probe.process_loop.evaluation import OUTPUT_SPEC
    from impl.core.structured_output import render_output_constraint
    spec = {'dossier': StructuredOutputSpec.from_dataclass(common.ProcessAssessment, required_nonempty=['reason','scope_note']),
            'shared_dossier': OUTPUT_SPEC, 'transcript': OUTPUT}[path]
    value = payload('context_memory')
    group_schema = spec.json_schema()['$defs']['ResultGroup']
    assert 'matched_link_id' in group_schema['required']
    match_schema = group_schema['properties']['matched_link_id']
    assert match_schema['type'] == 'string'
    assert len(value['results'][0]['matched_link_id']) >= match_schema.get('minLength', 0)
    enforce_output(value,spec,caller='test')
    value['results'][0].pop('matched_link_id')
    with pytest.raises(ValueError,match='matched_link_id'):enforce_output(value,spec,caller='test')
    rendered = render_output_constraint(spec)
    assert '不得省略' in rendered


def test_expectations_native_schema_accepts_no_ambiguity_group():
    material,e,_ = fixture()
    raw={'expectations':e['expectations']}
    item_schema = axis.OUTPUT.json_schema()['$defs']['Expectation']
    assert 'ambiguity_group' in item_schema['required']
    assert all(len(e['ambiguity_group']) >= item_schema['properties']['ambiguity_group'].get('minLength', 0) for e in raw['expectations'])
    axis.validate(raw,material)
    raw['expectations'][0].pop('ambiguity_group')
    with pytest.raises(ValueError,match='ambiguity_group'):axis.validate(raw,material)
