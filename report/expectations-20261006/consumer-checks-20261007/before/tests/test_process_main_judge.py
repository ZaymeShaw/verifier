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
    return {'results':[{'type_id':'trace_analysis','status':'succeeded','verdict':'complete','output':ANALYSIS_OUTPUT},
                       {'type_id':'context_memory','status':'succeeded',
                        'output':{'results':[{'obligation_id':'arrives_intact','link_id':'context_memory:x','outcome':'fail',
                                              'expected':'原义到达','observed':'上下文缺失','source_refs':[],
                                              'evidence':{'input':['turn1/records/run'],'output':[]},'missing':[]}]}}]}


def test_trace_axes_run_before_main_and_report_consumed_once(monkeypatch):
    order=[]; t=trace(); r=report()
    monkeypatch.setattr('impl.projects.llm_probe.capability.capability_business_trace', lambda _: {'provider':'agno'})
    monkeypatch.setattr(eval_axes,'build_report',lambda *a,**kw: order.append('axes') or r)
    class Judge:
        spec=None
        def build_context(self,t): return {'system_prompt_extras':['old'], 'user_prompt_extras':{}}
        def build_intent_frame(self,*a): return {}
        def _run_llm_judge(self,t,c,u):
            order.append('main')
            material=c['user_prompt_extras']['process_dossier']
            # 主轴只拿编号+原文（含被引用那条的正文），不拿整份案卷
            assert material['records'][0]['fields']['output']['value']=='FULL FINAL ANSWER'
            assert material['structure']['route'][0]['action']=='gate'
            assert c['user_prompt_extras']['process_axes'][0]['output']['results'][0]['outcome']=='fail'
            return JudgeResult(trace_id='x',project_id='llm_probe')
    ProcessJudgeExecution().run(Judge(),t,None)
    assert order==['axes','main']
    assert eval_axes.run_for_trace(None,t)==r
    assert eval_axes.run_for_trace(None,t) is None
    ProcessJudgeExecution().run(Judge(),t,None)
    assert order==['axes','main','axes','main']


def test_trace_off_uses_original_execution(monkeypatch):
    monkeypatch.setattr('impl.projects.llm_probe.capability.capability_business_trace',lambda _:None)
    monkeypatch.setattr('impl.core.judge_execution.SinglePassJudgeExecution.run',lambda *a:'original')
    assert ProcessJudgeExecution().run(None,trace(),None)=='original'


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
        def _run_llm_judge(self, t, c, u):
            seen['axes'] = c['user_prompt_extras']['process_axes']
            seen['extras'] = c['system_prompt_extras']
            return JudgeResult(trace_id='x', project_id='llm_probe',
                               overall_fulfillment={'status': 'fulfilled'})

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
    slim = _slim_process_axis_for_main({
        'type_id': 'context_memory', 'status': 'succeeded', 'verdict': None,
        'output': {
            'assessment': {'verdict': 'sound'},
            'results': [{'obligation_id': 'o1', 'link_id': 'context_memory:ok', 'outcome': 'pass', 'expected': 'e', 'observed': 'fine',
                         'source_refs': [], 'evidence': {'input': ['a'], 'output': []}, 'missing': [], 'flags': []},
                        {'obligation_id': 'o1', 'link_id': 'context_memory:bad', 'outcome': 'fail', 'expected': 'e', 'observed': 'bad',
                         'source_refs': [], 'evidence': {'input': ['a'], 'output': ['b']}, 'missing': [],
                         'flags': ['未见读取回执'], 'judged_by': 'llm', 'noise': 1}],
            'coverage': [{'huge': 'x' * 100}],
            'view': {'chars': 99},
            'selection': {'refs': ['a'], 'why': ['y']},
            'evidence_refs': ['a'],
            'missing_evidence': [],
        },
    })
    assert slim['output']['assessment']['verdict'] == 'sound'
    # 偏差排前、给全；pass 只留定位与结论。
    assert slim['output']['results'] == [
        {'obligation_id': 'o1', 'link_id': 'context_memory:bad', 'outcome': 'fail', 'expected': 'e', 'observed': 'bad',
         'source_refs': [], 'evidence': {'input': ['a'], 'output': ['b']}, 'missing': [], 'flags': ['未见读取回执']},
        {'obligation_id': 'o1', 'link_id': 'context_memory:ok', 'outcome': 'pass'}]
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
