"""离线接线回归；不把假模型返回当作真实 LLM 遵守证据边界的证明。"""
import json
from types import SimpleNamespace

from tests.support.expectations import E, PROJECTION

import pytest

from impl.core.tool_loop import Step
from impl.projects.llm_probe.eval_axes import registry
from impl.projects.llm_probe.eval_axes.adapters import process_common, transcript_axes
from impl.projects.llm_probe.eval_axes.types import ScenarioAxis
from impl.projects.llm_probe.business_trace.providers.llmtracing_transcript import KIND
from impl.projects.llm_probe.judge import _main_judge_material
from impl.projects.llm_probe.process_loop import llmtracing as loop_adapter


def transcript():
    return {'kind': KIND, 'records': [
        {'id': 't1.request', 'kind': 'request', 'text': '查询设备状态'},
        {'id': 't1.c1.response', 'kind': 'response', 'text': '状态未知'},
        {'id': 't1.final', 'kind': 'final', 'text': '状态未知'},
    ], 'coverage': [], 'model_calls': 1}


@pytest.mark.parametrize('axis_id', tuple(process_common.PROCESS_SPECS))
def test_real_axis_dispatch_receives_boundary_without_changing_grades(monkeypatch, axis_id):
    spec = process_common.PROCESS_SPECS[axis_id]
    observed = []

    class Client:
        def complete_step(self, messages, functions, **kwargs):
            observed.append(messages)
            if len(observed) == 1:
                name, args = 'evidence_read', {'ids': ['t1.request', 't1.c1.response']}
            elif len(observed) == 2:
                name = f'eval_{axis_id}'
                args = {'reason': '缺少独立的上游产出', 'scope_note': '当前可见调用',
                        'results': [{'obligation_id': ob.obligation_id, 'link_ids': ['t1.c1.response'],
                                     'outcome': 'insufficient_evidence', 'expectation_ids': [], 'matched_link_id': '', 'expectation_checks': [],
                                     'observed': '仅有一端', 'source_refs': [], 'input_refs': [],
                                     'output_refs': ['t1.c1.response'], 'missing': ['独立上游产出']}
                                    for ob in spec.obligations]}
            else:
                return Step({'role': 'assistant', 'content': 'done'})
            return Step({'role': 'assistant', 'tool_calls': [{'id': str(len(observed)), 'type': 'function',
                         'function': {'name': name, 'arguments': json.dumps(args)}}]})

        def usage(self):
            return {}

    monkeypatch.setattr(loop_adapter, 'prepare', lambda *a: PROJECTION)
    monkeypatch.setattr(loop_adapter, 'axis_llm', lambda *a, **kw: Client())
    runtime = SimpleNamespace(spec=SimpleNamespace(project_id='llm_probe'), scenario_id='no-such-scenario',
                              trace_id='boundary-test', ensure_time_left=lambda _: None, expectation_projection=PROJECTION)
    result = registry.AXIS_TYPES[axis_id].run(
        {'expectations': E, 'trace_analysis': {'dossier': transcript(), 'coverage': []}},
        ScenarioAxis(axis_id, True, '按设备服务契约判断'), runtime)
    assert len(observed) == 2
    assert transcript_axes._EVIDENCE_BOUNDARY in observed[0][0]['content']
    assert '不同调用所需证据不同就分别输出' in observed[0][0]['content']
    assert result.output['assessment']['verdict'] == 'not_evaluable'
    assert result.output['view']['execution'] == 'tool_loop'
    assert all(r['missing'] == ['独立上游产出'] for r in result.output['results'])


def test_main_judge_receives_same_boundary_and_unchanged_evidence():
    view = _main_judge_material([], {'output': {}}, transcript())
    assert transcript_axes._EVIDENCE_BOUNDARY in view['reading_guide']
    assert '[t1.final] final\n状态未知' in view['text']
    assert '不能证明最终 UI 已展示' in view['reading_guide']
    assert '工具调用参数不是工具原始产出' in view['reading_guide']
    assert '不可见不等于未发生' in view['reading_guide']
    assert view['final_sources'] == [{'id': 't1.final', 'origin': 'unverified_extracted_output'}]
