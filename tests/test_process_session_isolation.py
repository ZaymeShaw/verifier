from types import SimpleNamespace
from impl.core import pipeline
from impl.core.schema import RunTrace


def test_interactive_judge_retry_never_replays_backend(monkeypatch):
    trace=RunTrace(trace_id='original',project_id='llm_probe',case_id='case')
    calls=[]
    monkeypatch.setattr(pipeline,'load_project',lambda _:None)
    monkeypatch.setattr(pipeline,'load_adapter',lambda _:SimpleNamespace(live=lambda:object()))
    monkeypatch.setattr(pipeline,'trace_from_live',lambda *a:calls.append('backend') or trace)
    monkeypatch.setattr(pipeline,'get_runtime_config',lambda:SimpleNamespace(execution=SimpleNamespace(case_retry_attempts=2)))
    def chain(project,t,timings):
        assert t is trace
        calls.append('judge')
        if calls.count('judge')==1: raise RuntimeError('judge unavailable')
        return {'trace':t}
    monkeypatch.setattr(pipeline,'_chain_from_trace',chain)
    result=pipeline._run_interactive_case('llm_probe',SimpleNamespace(interaction={'seed_level':'transcript'}))
    assert calls==['backend','judge','judge']
    assert result['trace'] is trace


def test_exhausted_retry_preserves_actual_trace(monkeypatch):
    trace=RunTrace(trace_id='original',project_id='llm_probe',case_id='case')
    monkeypatch.setattr(pipeline,'load_project',lambda _:None)
    monkeypatch.setattr(pipeline,'load_adapter',lambda _:SimpleNamespace(live=lambda:object()))
    monkeypatch.setattr(pipeline,'trace_from_live',lambda *a:trace)
    monkeypatch.setattr(pipeline,'get_runtime_config',lambda:SimpleNamespace(execution=SimpleNamespace(case_retry_attempts=2)))
    def fail(*a): raise RuntimeError('judge down')
    monkeypatch.setattr(pipeline,'_chain_from_trace',fail)
    monkeypatch.setattr(pipeline,'_run_payload',lambda t,*a,**kw:{'trace':t,'error':kw['error']})
    result=pipeline._run_interactive_case('llm_probe',SimpleNamespace(interaction={'seed_level':'transcript'}))
    assert result['trace'] is trace
    assert result['error']=='judge down'
