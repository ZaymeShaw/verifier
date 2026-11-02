from types import SimpleNamespace
import pytest
from impl.core.schema import RunTrace, JudgeResult
from impl.projects.llm_probe.judge import ProcessJudgeExecution
from impl.projects.llm_probe import eval_axes


def trace():
    return RunTrace(trace_id='x', project_id='llm_probe', case_id='x', normalized_request={'capability_ref':'insurance'})


DOSSIER = {
    'records': [{'id': 'turn1/records/run', 'kind': 'runs', 'turn': 'turn1', 'scope': 'current',
                'fields': {'output': {'status': 'available', 'value': 'FULL FINAL ANSWER'}}}],
    'contents': {}, 'gaps': [], 'coverage': [], 'sources': [], 'model_calls': [],
    'current': [], 'history': [], 'observed_at_collection': [],
}
ANALYSIS_OUTPUT = {
    'dossier': DOSSIER, 'coverage': [],
    'structure': {'route': [{'action': 'gate', 'purpose': '路由', 'evidence_refs': [], 'input_refs': [], 'output_refs': []}]},
    'selections': {'context_memory': {'refs': ['turn1/records/run'], 'why': ['本轮唯一记录']}},
}


def report():
    from tests.test_expectations_v2_need_judge import frozen
    return {'results':[{'type_id':'trace_analysis','status':'succeeded','verdict':'complete','output':ANALYSIS_OUTPUT},
                       {'type_id':'context_memory','status':'succeeded',
                        'output':{'results':[{'batch':1,'id':'E1','subcapability':'传递保留原义','about':'context_memory:x',
                                              'statement':'原义到达','basis':'通用职责','observed':'上下文缺失','verdict':'没达到',
                                              'quotes':[{'ref':'turn1/records/run','quote':'…'}],'refs':['turn1/records/run'],'links':[]}]}},
                       {'type_id':'expectations', 'status':'succeeded', 'output': frozen()}]}


def test_trace_axes_run_before_main_and_report_consumed_once(monkeypatch):
    order=[]; t=trace(); r=report()
    monkeypatch.setattr('impl.projects.llm_probe.capability.capability_business_trace', lambda _: {'provider':'agno'})
    monkeypatch.setattr(eval_axes,'build_report',lambda *a,**kw: order.append('axes') or r)
    class Judge:
        spec=None
        def build_context(self,t): return {'system_prompt_extras':['old'], 'user_prompt_extras':{}}
        def build_intent_frame(self,*a): return {}
        def run_need_judge(self,spec,t,e,c):
            order.append('main')
            material=c['user_prompt_extras']['process_dossier']
            # 主轴只拿编号+原文（含被引用那条的正文），不拿整份案卷
            assert material['records'][0]['fields']['output']['value']=='FULL FINAL ANSWER'
            assert material['structure']['route'][0]['action']=='gate'
            assert c['user_prompt_extras']['process_axes'][0]['output']['results'][0]['verdict']=='没达到'
            return JudgeResult(trace_id='x',project_id='llm_probe')
    monkeypatch.setattr('impl.projects.llm_probe.need_judge.run_need_judge', Judge().run_need_judge)
    ProcessJudgeExecution().run(Judge(),t,None)
    assert order==['axes','main']
    assert eval_axes.run_for_trace(None,t)==r
    assert eval_axes.run_for_trace(None,t) is None
    ProcessJudgeExecution().run(Judge(),t,None)
    assert order==['axes','main','axes','main']


def test_trace_off_uses_original_execution(monkeypatch):
    # 无 trace、未启用主轴框：沿用轴1
    monkeypatch.setattr('impl.projects.llm_probe.capability.capability_business_trace',lambda _:None)
    monkeypatch.setattr(eval_axes,'main_axis_enabled',lambda *a:False)
    monkeypatch.setattr('impl.core.judge_execution.SinglePassJudgeExecution.run',lambda *a:'original')
    assert ProcessJudgeExecution().run(SimpleNamespace(spec=None),trace(),None)=='original'


MAIN_OUTPUT = {
    'business_expectations': [{'expectation_id': 'e1', 'blocking': True, 'user_intent': 'u', 'expected_outcome': 'o'}],
    'fulfillment_assessments': [{'expectation_id': 'e1', 'status': 'fulfilled', 'actual_evidence': ['a']}],
    'overall_fulfillment': {'status': 'fulfilled'}, 'expected': {}, 'actual': {}, 'missing': [], 'wrong': [], 'extra': [],
    'evidence': [], 'reasoning_summary': '办成', 'summary': {}, 'expectations_source': 'self', 'claims_checked': True,
}


def main_report(**status):
    return {'results': [{'type_id': t, 'title': t, 'status': status.get(t, 'succeeded'), 'error': '',
                         'output': MAIN_OUTPUT if t == 'fulfillment' else {}}
                        for t in ('knowledge_evidence', 'truthfulness', 'fulfillment')]}


def test_main_axis_box_makes_fulfillment_the_main_result_and_report_reused(monkeypatch):
    calls=[]; t=trace(); r=main_report()
    monkeypatch.setattr('impl.projects.llm_probe.capability.capability_business_trace',lambda _:None)
    monkeypatch.setattr(eval_axes,'main_axis_enabled',lambda *a:True)
    monkeypatch.setattr(eval_axes,'build_report',lambda *a,**kw: calls.append('axes') or r)
    monkeypatch.setattr('impl.core.judge_execution.SinglePassJudgeExecution.run',lambda *a: pytest.fail('轴1 不该再跑'))
    result=ProcessJudgeExecution().run(SimpleNamespace(spec=None),t,None)
    assert result.overall_fulfillment['status']=='fulfilled'
    assert result.reasoning_summary=='办成'
    assert {'kind':'main_axis_source','value':'eval_axes.fulfillment'} in result.evidence
    # 判后 pass 直接拿走同一份报告，不重跑
    assert eval_axes.run_for_trace(None,t) is r and calls==['axes']


@pytest.mark.parametrize('failed', ['knowledge_evidence', 'truthfulness', 'fulfillment'])
def test_main_axis_or_its_upstream_failed_blocks_whole_case(monkeypatch, failed):
    monkeypatch.setattr('impl.projects.llm_probe.capability.capability_business_trace',lambda _:None)
    monkeypatch.setattr(eval_axes,'main_axis_enabled',lambda *a:True)
    monkeypatch.setattr(eval_axes,'build_report',lambda *a,**kw: main_report(**{failed:'failed'}))
    result=ProcessJudgeExecution().run(SimpleNamespace(spec=None),trace(),None)
    assert result.overall_fulfillment['status']=='not_evaluable'
    assert 'evaluation_execution_failed' in result.evidence
    assert failed in result.reasoning_summary


def test_main_axis_not_applicable_is_not_a_result(monkeypatch):
    monkeypatch.setattr('impl.projects.llm_probe.capability.capability_business_trace',lambda _:None)
    monkeypatch.setattr(eval_axes,'main_axis_enabled',lambda *a:True)
    monkeypatch.setattr(eval_axes,'build_report',lambda *a,**kw: main_report(fulfillment='not_applicable'))
    result=ProcessJudgeExecution().run(SimpleNamespace(spec=None),trace(),None)
    assert 'evaluation_execution_failed' in result.evidence


def test_main_axis_upstream_is_truthfulness_chain():
    assert eval_axes.main_axis_upstream()=={'expectations','truthfulness','knowledge_evidence'}


def test_main_axis_enabled_only_without_trace_and_with_enabled_box(monkeypatch):
    maps={'a':{'axes':[{'type':'fulfillment','enabled':True,'description':'d'}]},
          'b':{'axes':[{'type':'fulfillment','enabled':False,'description':'d'}]},
          'c':{'axes':[{'type':'fulfillment','enabled':True,'description':'d'}],'business_trace':{'provider':'agno'}}}
    monkeypatch.setattr(eval_axes,'load_capability_map',lambda _:maps)
    monkeypatch.setattr('impl.projects.llm_probe.capability.capability_business_trace',lambda ref:maps.get(ref,{}).get('business_trace'))
    spec=SimpleNamespace(project_id='llm_probe')
    def t(ref): return RunTrace(trace_id='x',project_id='llm_probe',case_id='x',normalized_request={'capability_ref':ref})
    assert eval_axes.main_axis_enabled(spec,t('a')) is True
    assert eval_axes.main_axis_enabled(spec,t('b')) is False
    assert eval_axes.main_axis_enabled(spec,t('c')) is False
    assert eval_axes.main_axis_enabled(spec,t('missing')) is False


def test_collection_failed_never_calls_main(monkeypatch):
    monkeypatch.setattr('impl.projects.llm_probe.capability.capability_business_trace',lambda _:{'provider':'agno'})
    r=report(); r['results'][0].update(status='failed',verdict=None,output=None,error='[需补材料] 业务 Trace 缺失')
    monkeypatch.setattr(eval_axes,'build_report',lambda *a,**kw:r)
    result=ProcessJudgeExecution().run(SimpleNamespace(spec=None),trace(),None)
    assert result.overall_fulfillment['status']=='not_evaluable'


def test_partial_axis_failure_still_calls_main(monkeypatch):
    """部分过程轴 failed 时不再整案自爆，主轴仍用瘦身后的轴结论综合。"""
    monkeypatch.setattr('impl.projects.llm_probe.capability.capability_business_trace', lambda _: {'provider': 'agno'})
    r = report()
    r['results'].append({
        'type_id': 'tool_execution', 'status': 'failed', 'error': 'AxisRequestFailed: boom',
        'output': {
            'assessment': {'verdict': 'not_evaluable'},
            'results': [], 'evidence_refs': [], 'missing_evidence': [],
            'coverage': [{'turn': 'turn1', 'status': 'ok', 'coverage': {}, 'association': {}, 'errors': [], 'limitations': []}],
            'selection': {'refs': [], 'why': []},
            'view': {'chars': 0, 'records': 0, 'excluded': [], 'dropped_refs': [], 'repaired': []},
        },
    })
    monkeypatch.setattr(eval_axes, 'build_report', lambda *a, **kw: r)
    seen = {}

    class Judge:
        spec = None
        def build_context(self, t):
            return {'system_prompt_extras': ['old'], 'user_prompt_extras': {}}
        def build_intent_frame(self, *a):
            return {}
        def run_need_judge(self, spec, t, e, c):
            seen['axes'] = c['user_prompt_extras']['process_axes']
            seen['extras'] = c['system_prompt_extras']
            return JudgeResult(trace_id='x', project_id='llm_probe',
                               overall_fulfillment={'status': 'fulfilled'})

    monkeypatch.setattr('impl.projects.llm_probe.need_judge.run_need_judge', Judge().run_need_judge)
    result = ProcessJudgeExecution().run(Judge(), trace(), None)
    assert result.overall_fulfillment['status'] == 'fulfilled'
    tool = next(a for a in seen['axes'] if a['type_id'] == 'tool_execution')
    assert tool['status'] == 'failed'
    assert tool['error'] == 'AxisRequestFailed: boom'
    assert 'coverage' not in (tool.get('output') or {})
    assert 'view' not in (tool.get('output') or {})
    assert any('部分过程轴执行失败' in s for s in seen['extras'])


@pytest.mark.parametrize('failure', ['analysis', 'collection', 'all_axes'])
def test_process_failure_blocks_main_even_with_readable_answer(monkeypatch, failure):
    monkeypatch.setattr('impl.projects.llm_probe.capability.capability_business_trace', lambda _: {'provider': 'agno'})
    import copy
    r = copy.deepcopy(report())
    if failure == 'analysis':
        r['results'][0].update(status='failed', error='[运行环境] 端点不可用')
    elif failure == 'collection':
        r['results'][0]['output']['dossier']['records'] = []
    else:
        r['results'][1]['status'] = 'failed'
    monkeypatch.setattr(eval_axes, 'build_report', lambda *a, **kw: r)
    t = trace()
    t.extracted_output = {'output_text': '{"answer":"可读答复"}'}

    def forbidden(*args, **kwargs):
        pytest.fail('过程失败不得绕过过程评测调用主裁决')

    monkeypatch.setattr('impl.core.judge_execution.SinglePassJudgeExecution.run', forbidden)
    result = ProcessJudgeExecution().run(SimpleNamespace(spec=None, build_context=forbidden), t, None)
    assert result.overall_fulfillment['status'] == 'not_evaluable'
    assert 'axis1_only_fallback' not in result.evidence
    if failure == 'analysis':
        assert '[运行环境] 端点不可用' in result.reasoning_summary
        # 运行环境失败要带执行失败标记，前端「补跑执行失败」才能挑出来。
        assert 'evaluation_execution_failed' in result.evidence


def test_analysis_material_failure_is_not_execution_failure(monkeypatch):
    import copy
    monkeypatch.setattr('impl.projects.llm_probe.capability.capability_business_trace', lambda _: {'provider': 'agno'})
    r = copy.deepcopy(report())
    r['results'][0].update(status='failed', error='[需补材料] 业务 Trace 缺失')
    monkeypatch.setattr(eval_axes, 'build_report', lambda *a, **kw: r)
    result = ProcessJudgeExecution().run(SimpleNamespace(spec=None), trace(), None)
    assert result.evidence == ['process_trace_analysis_failed']


def test_live_service_unavailable_skips_judge_and_flags_execution_failure(monkeypatch):
    from impl.core import pipeline
    from impl.core.live import fallback_decision
    from impl.core.table_view import build_trace_table_row

    def forbidden(*args, **kwargs):
        pytest.fail('业务服务不可达时不应进入 judge')

    monkeypatch.setattr(pipeline, 'judge', forbidden)
    t = trace()
    t.status = 'error'
    t.error = 'llm_probe target unavailable: Connection refused'
    t.fallbacks = [fallback_decision(
        fallback_id='live-error-x', source_stage='live', fallback_type='live_error', status='error',
        reason=t.error, missing_evidence=['live_response'], recoverable=True, needs_human_review=True,
        quality_flags=['live_service_unavailable'], metadata={})]
    run = pipeline._chain_from_trace('llm_probe', t, {})
    assert run['judge'].evidence == ['evaluation_execution_failed']
    row = build_trace_table_row(t, run['judge'], run['attribute'], None, None, case_context=run)
    assert 'evaluation_execution_failed' in row.quality_flags


def test_slim_process_axis_drops_coverage_and_view():
    from impl.projects.llm_probe.judge import _slim_process_axis_for_main
    met = {'batch': 1, 'id': 'E1', 'subcapability': '传递保留原义', 'about': 'ok', 'statement': 's', 'basis': 'b',
           'observed': 'fine', 'quotes': [], 'refs': [], 'links': [], 'verdict': '达到'}
    missed = {'batch': 1, 'id': 'E2', 'subcapability': '交付保留原义', 'about': 'bad', 'statement': 's2', 'basis': 'b2',
              'observed': 'bad', 'quotes': [{'ref': 'b', 'quote': 'q'}], 'refs': ['b'], 'links': ['L1'],
              'verdict': '没达到', 'needs_external': '否'}
    slim = _slim_process_axis_for_main({
        'type_id': 'context_memory', 'status': 'succeeded', 'verdict': None,
        'output': {
            'assessment': {'verdict': 'problematic'},
            'results': [met, missed],
            'coverage': [{'huge': 'x' * 100}],
            'view': {'chars': 99},
            'selection': {'refs': ['a'], 'why': ['y']},
            'issues': [], 'unexpected': [],
            'evidence_refs': ['b'],
            'missing_evidence': [],
        },
    })
    assert slim['output']['assessment']['verdict'] == 'problematic'
    # 没达到排前、带本应 / 实际 / 引文；达到只留定位与结论。
    assert slim['output']['results'] == [
        {'batch': 1, 'id': 'E2', 'subcapability': '交付保留原义', 'about': 'bad', 'verdict': '没达到',
         'statement': 's2', 'basis': 'b2', 'observed': 'bad', 'quotes': [{'ref': 'b', 'quote': 'q'}], 'links': ['L1']},
        {'batch': 1, 'id': 'E1', 'subcapability': '传递保留原义', 'about': 'ok', 'verdict': '达到'}]
    assert 'coverage' not in slim['output']
    assert 'view' not in slim['output']


def test_successful_expectations_cannot_mask_all_six_axes_failed(monkeypatch):
    monkeypatch.setattr('impl.projects.llm_probe.capability.capability_business_trace',lambda _:{'provider':'agno'})
    r=report()
    r['results'][1].update(status='failed',error='test',output=None)
    r['results'].append({'type_id':'expectations','status':'succeeded','output':{'expectations':[]}})
    monkeypatch.setattr(eval_axes,'build_report',lambda *a,**kw:r)
    out=ProcessJudgeExecution().run(SimpleNamespace(spec=None),trace(),None)
    assert out.overall_fulfillment['status']=='not_evaluable'
    assert out.evidence==['process_axes_execution_failed']
