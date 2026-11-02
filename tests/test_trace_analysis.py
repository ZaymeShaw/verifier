"""The case file preserves all available evidence before any judgment; the organizer only selects."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from impl.core.schema import RunTrace

from impl.projects.llm_probe.business_trace.dossier import (
    EVIDENCE_NODE_CHARS, _render_record, _text, build_axis_view, build_catalog, build_dossier,
    catalog_ids, expand_content, render_catalog, view_ids)
from impl.projects.llm_probe.business_trace.links import AXIS_LINK_TYPES
from impl.projects.llm_probe.business_trace.reader import redact
from impl.projects.llm_probe.business_trace.tools import EvidenceIndex
from impl.projects.llm_probe.eval_axes.adapters import trace_analysis
from impl.projects.llm_probe.eval_axes.types import ScenarioAxis

SNAPSHOTS = Path(__file__).resolve().parents[1] / 'report/business-trace-agno-20260913/snapshots'
AXES = ('intent_understanding', 'context_memory')


def _downstream(user: str) -> dict:
    """prompt 是分节文本：把「下游轴与需求」那一节解回 JSON（其余节原样留在文本里）。"""
    text = str(user)
    start = text.index('## 启用的下游轴与需求') + len('## 启用的下游轴与需求')
    end = text.find('\n## ', start)
    return {item['axis']: item for item in json.loads(text[start:end if end != -1 else None])}


def snapshot(name='snap-cash-value.json'):
    return json.loads((SNAPSHOTS / name).read_text())


@pytest.mark.parametrize('path', sorted(SNAPSHOTS.glob('snap-*.json')), ids=lambda p: p.stem)
def test_every_original_record_survives_without_summary_or_truncation(path):
    snap = json.loads(path.read_text())
    dossier = build_dossier(SimpleNamespace(turn_records=[]), snap)
    assert expand_content(dossier['sources'][0]['original_records'], dossier['contents']) == redact(snap['records'])
    assert dossier['records'] and dossier['model_calls']
    assert all(c['id'] in dossier['evidence_ids'] for c in dossier['model_calls'])
    assert any('exact_model_request' in g['id'] for g in dossier['gaps'])


def test_all_turns_and_missing_turn_are_visible():
    snap = snapshot()
    trace = SimpleNamespace(turn_records=[{'project_fields': {'business_trace': snap}}, {}])
    dossier = build_dossier(trace, snap)
    assert len(dossier['sources']) == 2
    assert dossier['coverage'][1]['status'] == 'failed'
    assert any(g['id'] == 'turn2.collection' for g in dossier['gaps'])
    # 采集记录都属于 turn1；turn1.final_output 是本轮最终回答的登记项，也属于 turn1。
    assert all(r['id'].startswith('turn1') for r in dossier['records'])
    assert {r['id'] for r in dossier['records'] if not r['id'].startswith('turn1/records/')} == {'turn1.final_output'}


def test_failed_collection_is_missing_not_zero_calls():
    d = build_dossier(SimpleNamespace(turn_records=[]), {'provider': 'agno', 'status': 'failed'})
    assert not d['model_calls']
    assert d['coverage'][0]['status'] == 'failed'
    assert d['gaps']


def test_record_numbers_are_unique_even_when_one_path_has_two_kinds():
    d = build_dossier(SimpleNamespace(turn_records=[]), snapshot())
    ids = [row['id'] for row in d['records']]
    assert len(ids) == len(set(ids))
    assert len(ids) == len(d['records'])


def _run(monkeypatch, script):
    from tests.test_trace_analysis_submission import _run_script
    return _run_script(monkeypatch, script)


def test_organizer_reads_the_index_and_only_cites_what_it_read(monkeypatch):
    from tests.test_trace_analysis_submission import _structure
    d = build_dossier(SimpleNamespace(turn_records=[]), snapshot())
    read_ref, unread_ref = [r['id'] for r in d['records'][:2]]
    bad = _structure([read_ref, unread_ref], [_suspect(link_id='intent_understanding:turn1',
                        source_refs=[read_ref, unread_ref, 'turn1/nope'])])
    good = _structure([read_ref], [_suspect(link_id='intent_understanding:turn1', source_refs=[read_ref])])
    client, out = _run(monkeypatch, [[('dossier_read', {'record_id': read_ref})],
                                    [('submit_structure', bad)], [('submit_structure', good)], '完成'])
    assert not out.failed
    prompt = client.requests[0][1]['content']
    assert '## 案卷目录' in prompt and '## 取证工具' in prompt and '## 环节表' in prompt
    assert _downstream(prompt)[AXES[0]]['requires']
    audit = out.output['structure']['evidence_audit']
    assert [s['accepted'] for s in audit['submissions']] == [False, True]
    assert unread_ref in audit['submissions'][0]['reason'] and 'turn1/nope' in audit['submissions'][0]['reason']
    assert out.output['structure']['route'][0]['evidence_refs'] == [read_ref]
    [suspect] = out.output['suspects']
    assert suspect['source_refs'] == [read_ref] and suspect['origin'] == ['analysis']
    assert out.output['selections']['intent_understanding']['refs'][0] == read_ref
    assert out.usage['read_ids'] == 1 and out.usage['tool_calls'] == 3


def _suspect(link_id, why='输出与输入对不上', source_refs=()):
    return {'link_id': link_id, 'why': why, 'source_refs': list(source_refs)}


def _new_suspect(link_type, input_refs=(), output_refs=(), why='发现表外调用', source_refs=()):
    return {'link_type': link_type, 'input_refs': list(input_refs), 'output_refs': list(output_refs),
            'why': why, 'source_refs': list(source_refs)}


def test_read_receipts_travel_with_the_structure_even_when_nothing_is_wrong(monkeypatch):
    d = build_dossier(SimpleNamespace(turn_records=[]), snapshot())
    ref = next(r['id'] for r in d['records'] if r['kind'] == 'runs')
    payload = {'route': [], 'coverage_note': '', 'new_link_suspects': [],
               'existing_link_suspects': [_suspect(link_id='intent_understanding:turn1', source_refs=[ref])]}
    _, out = _run(monkeypatch, [[('dossier_read', {'record_id': ref})],
                               [('submit_structure', payload)], '完成'])
    assert not out.failed
    audit = out.output['structure']['evidence_audit']
    assert [r['id'] for r in audit['reads']] == [ref]
    assert [s['accepted'] for s in audit['submissions']] == [True]


def test_every_axis_view_carries_all_its_link_ends_even_without_suspects(monkeypatch):
    from impl.projects.llm_probe.business_trace.links import build_links, link_ends
    d = build_dossier(SimpleNamespace(turn_records=[]), snapshot())
    payload = {'route': [], 'coverage_note': '', 'existing_link_suspects': [], 'new_link_suspects': []}
    client, out = _run(monkeypatch, [[('submit_structure', payload)], '完成'])
    assert not out.failed
    downstream = _downstream(client.requests[0][1]['content'])
    assert '模型调用' in downstream['context_memory']['requires']
    assert downstream['context_memory']['link_types'] == ['context_memory']
    gaps = sorted(gap['id'] for gap in d['gaps'])
    for axis in AXES:
        ends = [ref for link in build_links(d)['links'] if link['link_type'] in AXIS_LINK_TYPES[axis]
                for ref in link_ends(link)]
        assert out.output['selections'][axis]['refs'] == list(dict.fromkeys(ends + gaps))
        assert out.output['selections'][axis]['why'] == []


def test_catalog_lists_every_number_the_axes_can_resolve():
    d = build_dossier(SimpleNamespace(turn_records=[]), snapshot())
    listed = catalog_ids(build_catalog(d))
    citable = set()
    for row in d['records']:
        citable.add(row['id'])
    citable |= set(d['contents'])
    citable |= {gap['id'] for gap in d['gaps']}
    citable |= {source['id'] for source in d['sources']}
    assert citable <= listed


def test_index_only_material_needs_no_read_but_records_do(monkeypatch):
    d = build_dossier(SimpleNamespace(turn_records=[]), snapshot())
    gap, record = d['gaps'][0]['id'], d['records'][0]['id']
    bad = {'route': [], 'coverage_note': '', 'new_link_suspects': [],
           'existing_link_suspects': [_suspect(link_id='intent_understanding:turn1', source_refs=[gap, record], why='缺证本身就是材料')]}
    good = {**bad, 'existing_link_suspects': [_suspect(link_id='intent_understanding:turn1', source_refs=[gap], why='缺证本身就是材料')]}
    _, out = _run(monkeypatch, [[('submit_structure', bad)], [('submit_structure', good)], '完成'])
    assert not out.failed and out.output['suspects'][0]['source_refs'] == [gap]
    audit = out.output['structure']['evidence_audit']
    assert [s['accepted'] for s in audit['submissions']] == [False, True]
    assert record in audit['submissions'][0]['reason']
    assert audit['reads'] == []


def _assert_analysis_failed(out):
    assert out.failed and out.output == {}
    assert out.failure_reason.startswith('[轴实现] 案卷整理未通过验收')


def test_unparseable_output_fails_the_analysis_after_one_retry(monkeypatch):
    # 现在按统一 LLM 轮次预算纠错；耗尽仍不合规，明确失败，不再 salvage。
    payload = {'route': 'not-a-list', 'coverage_note': '', 'existing_link_suspects': [], 'new_link_suspects': []}
    client, out = _run(monkeypatch, [[('submit_structure', payload)]] * trace_analysis.LLM_CALL_LIMIT)
    _assert_analysis_failed(out)
    assert len(client.requests) == trace_analysis.LLM_CALL_LIMIT
    assert '结构输出字段类型错误' in str(client.requests[-1])


def test_protocol_layer_block_twice_fails_the_analysis(monkeypatch):
    # 工具参数不是 JSON 对象时会把错误回给模型，不能伪装成已提交。
    _, out = _run(monkeypatch, [[('submit_structure', 'not-an-object')]] * trace_analysis.LLM_CALL_LIMIT)
    _assert_analysis_failed(out)
    assert 'arguments 必须是 JSON 对象' in out.failure_reason


@pytest.mark.parametrize('garbage', [['route-ish'], [], 'plain text'])
def test_garbage_analysis_output_fails_the_analysis(monkeypatch, garbage):
    # 保留全部非法输出样本，经真实工具参数通道送入。
    _, out = _run(monkeypatch, [[('submit_structure', garbage)]] * trace_analysis.LLM_CALL_LIMIT)
    _assert_analysis_failed(out)


def test_flat_list_of_parts_is_coerced_into_route_and_suspects(monkeypatch):
    # 用户确认不再自动重写/删减模型成果；原先强制转换的输入现在必须拒绝。
    payload = [{'action': 'gate', 'purpose': '路由', 'evidence_refs': [], 'input_refs': [], 'output_refs': []},
               _suspect(link_id='intent_understanding:turn1', why='本轴')]
    _, out = _run(monkeypatch, [[('submit_structure', payload)]] * trace_analysis.LLM_CALL_LIMIT)
    _assert_analysis_failed(out)


def _fat_record(d):
    fat = max(d['records'], key=lambda r: len(_text(_render_record(r, d, preview_chars=None))))
    assert len(_text(_render_record(fat, d, preview_chars=None))) > EVIDENCE_NODE_CHARS
    return fat


def test_oversized_record_gives_the_axis_exactly_the_slices_the_organizer_read():
    """实测口子：整理员按 12k 结构图下钻读了几个片段，视图却把 29.7k 整棵子树倒给 4 个轴。"""
    d = build_dossier(SimpleNamespace(turn_records=[]), snapshot())
    fat = _fat_record(d)
    paths = [p for p in (fat.get('fields') or {})][:2]
    structure = {'evidence_audit': {'reads': [{'id': fat['id'], 'path': f'/fields/{name}', 'chars': 10}
                                             for name in paths]}}
    view = build_axis_view(d, {'refs': [fat['id']]}, budget_chars=10_000_000, axis_id='context_memory',
                           structure=structure)
    row = view['records'][0]
    assert set(row['read_paths']) == {f'/fields/{name}' for name in paths}
    # 逐字一致：视图里的片段与取证件读到的是同一个东西
    index = EvidenceIndex(d)
    for name in paths:
        assert json.dumps(row['read_paths'][f'/fields/{name}'], ensure_ascii=False, default=str) == \
            index.read(fat['id'], f'/fields/{name}')['text']
    assert row['chars'] > EVIDENCE_NODE_CHARS
    assert 'shape' in row and '缺证' in row['note']
    assert len(_text(row)) < len(_text(_render_record(fat, d, preview_chars=None)))
    # 回执只决定渲染哪几段，渲染后不再随视图进提示词；其余结构照常下传。
    view = build_axis_view(d, {'refs': [fat['id']]}, budget_chars=10_000_000, axis_id='context_memory',
                           structure={**structure, 'route': [{'action': 'gate'}]})
    assert 'evidence_audit' not in view['structure'] and view['structure']['route'] == [{'action': 'gate'}]
    assert view['records'][0]['read_paths'] == row['read_paths']


def test_oversized_record_read_only_as_shape_hands_the_axis_no_body():
    d = build_dossier(SimpleNamespace(turn_records=[]), snapshot())
    fat = _fat_record(d)
    view = build_axis_view(d, {'refs': [fat['id']]}, budget_chars=10_000_000, axis_id='context_memory',
                           structure={'evidence_audit': {'reads': [{'id': fat['id'], 'path': '', 'shape_only': True}]}})
    row = view['records'][0]
    assert row['read_paths'] == {} and row['not_read_here'] == ['/']
    assert 'shape' in row


def test_small_records_render_exactly_as_before():
    """上限只触及胖节点：绝大多数记录仍然逐字全文给轴，行为不变。"""
    d = build_dossier(SimpleNamespace(turn_records=[]), snapshot())
    small = min(d['records'], key=lambda r: len(_text(_render_record(r, d, preview_chars=None))))
    view = build_axis_view(d, {'refs': [small['id']]}, budget_chars=10_000_000, axis_id='x')
    assert view['records'][0] == _render_record(small, d, preview_chars=None)
    assert 'read_paths' not in view['records'][0]


def test_selection_renders_only_that_material_for_the_axis():
    d = build_dossier(SimpleNamespace(turn_records=[]), snapshot())
    chosen = d['records'][0]['id']
    view = build_axis_view(d, {'refs': [chosen], 'why': ['本轴需要的记录']}, budget_chars=10_000_000,
                           axis_id='context_memory', structure={'route': []})
    assert [row['id'] for row in view['records']] == [chosen]
    assert {row['id'] for row in d['records']} - {chosen}
    assert all(item not in view['contents'] for item in set(d['contents']) - set(view['contents']))
    assert view['structure'] == {'route': []}
    assert view['excluded'] == []


def test_sibling_representation_requires_its_own_read():
    d = build_dossier(SimpleNamespace(turn_records=[]), snapshot())
    pairs = [r['id'] for r in d['records'] if '#' in r['id']]
    assert pairs
    twin = pairs[0]
    base = twin.split('#', 1)[0]
    view = build_axis_view(d, {'refs': [base]}, budget_chars=10_000_000, axis_id='planning_routing')
    assert twin not in {row['id'] for row in view['records']}
    assert twin not in view_ids(view)
    read_twin = build_axis_view(d, {'refs': [base, twin]}, budget_chars=10_000_000, axis_id='planning_routing')
    assert twin in view_ids(read_twin)


def test_selection_over_budget_is_listed_not_silently_dropped():
    d = build_dossier(SimpleNamespace(turn_records=[]), snapshot())
    refs = [row['id'] for row in d['records']]
    view = build_axis_view(d, {'refs': refs}, budget_chars=8_000, axis_id='model_capability')
    assert view['records']
    excluded = {item['ref'] for item in view['excluded']}
    rendered = {row['id'] for row in view['records']}
    assert excluded
    assert rendered | excluded >= set(refs)


def test_suspect_shape_is_checked_against_the_link_table():
    links = {'intent_understanding:turn1'}
    route = [{'action': 'x', 'purpose': 'x', 'evidence_refs': ['invented'], 'input_refs': [], 'output_refs': []}]
    ok = {'route': route, 'coverage_note': '',
          'existing_link_suspects': [_suspect(link_id='intent_understanding:turn1', source_refs=['invented', 'known'])],
          'new_link_suspects': [_new_suspect('tool_execution', input_refs=['known'], output_refs=['known'], source_refs=['known'])]}
    trace_analysis._validate(ok, links)
    for field, bad, message in (
        ('existing_link_suspects', _suspect('intent_understanding:turn9', source_refs=['known']), '不在环节表'),
        ('existing_link_suspects', {**_suspect('intent_understanding:turn1', source_refs=['known']), 'link_type': 'tool_execution'}, '必须恰好含'),
        ('new_link_suspects', _new_suspect('bridge', input_refs=['known'], source_refs=['known']), 'link_type'),
        ('new_link_suspects', _new_suspect('tool_execution', source_refs=['known']), '输入端或输出端'),
        ('existing_link_suspects', _suspect('intent_understanding:turn1', why=' ', source_refs=['known']), 'why'),
    ):
        with pytest.raises(ValueError, match=message):
            trace_analysis._validate({**ok, field: [bad]}, links)
    # 结构检查不认证证据；引用检查单独拒绝，且不改写候选结果。
    from impl.core.tool_loop import Call, Deny, History
    from impl.projects.llm_probe.process_loop.analysis import ReceiptGate, payload_refs
    dossier = build_dossier(SimpleNamespace(turn_records=[]), snapshot())
    gate = ReceiptGate(EvidenceIndex(dossier), {'submit_structure'}, payload_refs)
    before = json.loads(json.dumps(ok))
    decision = gate.pre_tool(History(), Call(0, 'submit_structure', ok, 0))
    assert isinstance(decision, Deny) and 'invented' in decision.reason
    assert ok == before


def test_off_map_suspect_without_backed_ends_is_dropped_and_recorded():
    # 未读端点须拒绝提交，不能删掉整个表外发现后假装成功。
    from impl.core.tool_loop import Call, Deny, History
    from impl.projects.llm_probe.process_loop.analysis import ReceiptGate, payload_refs
    d = build_dossier(SimpleNamespace(turn_records=[]), snapshot())
    ref = d['records'][0]['id']
    structure = trace_analysis._normalize_structure({'route': [], 'coverage_note': '', 'existing_link_suspects': [],
        'new_link_suspects': [_new_suspect('tool_execution', input_refs=[ref], why='直连后端', source_refs=[ref])]})
    before = json.loads(json.dumps(structure))
    gate = ReceiptGate(EvidenceIndex(d), {'submit_structure'}, payload_refs)
    verdict = gate.pre_tool(History(), Call(0, 'submit_structure', structure, 0))
    assert isinstance(verdict, Deny) and ref in verdict.reason
    assert structure == before


def test_program_and_analysis_suspects_merge_and_route_to_owning_axes():
    links = {'planning_routing:repeat:t1': {'link_id': 'planning_routing:repeat:t1', 'link_type': 'planning_routing', 'input': [], 'output': []},
             'tool_execution:t1': {'link_id': 'tool_execution:t1', 'link_type': 'tool_execution', 'input': [{'ref': 'a', 'field': 'arguments'}],
                      'output': [{'ref': 't1', 'field': 'result'}]}}
    program = [{'link_id': 'planning_routing:repeat:t1', 'why': '同名同参再次调用', 'origin': 'program'}]
    existing = [_suspect(link_id='planning_routing:repeat:t1', why='状态说不可重试', source_refs=['t0'])]
    discovered = [_new_suspect('knowledge_data', input_refs=['a'], output_refs=['t1'], why='返回为空', source_refs=['t1']),
                  _new_suspect('unclassified', input_refs=['s'], why='状态写入', source_refs=['s'])]
    enabled = trace_analysis.PROCESS_AXES
    merged = trace_analysis.merge_suspects(program, existing, discovered, links, enabled)
    assert merged[0]['origin'] == ['program', 'analysis'] and merged[0]['source_refs'] == ['t0']
    assert merged[0]['axes'] == ['planning_routing']
    assert merged[1]['off_map'] and merged[1]['axes'] == ['knowledge_data']
    assert merged[2]['axes'] == list(enabled)
    views = trace_analysis.axis_selections(list(links.values()), merged, ['gap'], ('tool_execution', 'knowledge_data'))
    # 明确的发现依据优先，再带两端；新提交必须给 source_refs，因此 t1 在 a 之前。
    assert views['knowledge_data']['refs'] == ['t1', 'a', 's', 'gap']
    assert views['tool_execution']['why'] == ['new:2：状态写入']


def test_program_suspects_reach_the_axes_without_the_analyst(monkeypatch):
    from impl.projects.llm_probe.process_loop import analysis
    flagged = [{'link_id': 'intent_understanding:turn1', 'why': '程序命中', 'origin': 'program'}]
    monkeypatch.setattr(analysis, 'program_suspects', lambda links: flagged)
    client, out = _run(monkeypatch, [[('submit_structure', {'route': [], 'coverage_note': '',
                         'existing_link_suspects': [], 'new_link_suspects': []})], '完成'])
    assert not out.failed and '程序命中' in client.requests[0][1]['content']
    assert out.output['suspects'][0]['origin'] == ['program']
    assert out.output['selections']['intent_understanding']['why'] == ['intent_understanding:turn1：程序命中']


def test_citing_without_a_receipt_is_sent_back_once_then_fixed_by_collecting(monkeypatch):
    d = build_dossier(SimpleNamespace(turn_records=[]), snapshot())
    ref = next(r['id'] for r in d['records'] if r['kind'] == 'runs')
    payload = {'route': [], 'coverage_note': '', 'new_link_suspects': [],
               'existing_link_suspects': [_suspect(link_id='intent_understanding:turn1', source_refs=[ref])]}
    client, out = _run(monkeypatch, [[('submit_structure', payload)], [('dossier_collect', {'ids': [ref]})],
                                    [('submit_structure', payload)], '完成'])
    assert not out.failed and out.output['suspects'][0]['source_refs'] == [ref]
    assert '此前批次没有正文读取回执' in str(client.requests[1])
    audit = out.output['structure']['evidence_audit']
    assert [s['accepted'] for s in audit['submissions']] == [False, True]
    assert ref in {r['id'] for r in audit['reads']}
