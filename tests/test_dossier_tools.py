"""案卷取证件：正文按需读取、路径可下钻、每次调用留回执、引句可逐字核验。"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from impl.projects.llm_probe.business_trace.dossier import (
    VIEW_BUDGET_CHARS, _text, build_axis_view, build_dossier, render_value)
from impl.projects.llm_probe.business_trace import tools as evidence_tools
from impl.projects.llm_probe.business_trace.tools import EvidenceIndex

SNAPSHOTS = Path(__file__).resolve().parents[1] / 'report/business-trace-agno-20260913/snapshots'


def dossier():
    snap = json.loads((SNAPSHOTS / 'snap-cash-value.json').read_text())
    return build_dossier(SimpleNamespace(turn_records=[]), snap)


def test_read_returns_full_original_text_and_records_a_receipt():
    d = dossier()
    index = EvidenceIndex(d)
    row = next(r for r in d['records'] if r['kind'] == 'runs')
    result = index.read(row['id'])
    assert result['chars'] == len(result['text'])
    assert '保单 P002 的现金价值是多少？' in result['text']
    assert json.loads(result['text'])['id'] == row['id']
    assert index.receipts == [{'tool': 'dossier_read', 'id': row['id'], 'path': '',
                               'chars': result['chars'], 'call': 1}]
    assert index.calls == 1
    assert index.read_ids == {row['id']}


def test_read_descends_by_path_and_never_silently_truncates(monkeypatch):
    d = dossier()
    index = EvidenceIndex(d)
    row = next(r for r in d['records'] if r['kind'] == 'steps')
    monkeypatch.setattr(evidence_tools, 'MAX_READ_CHARS', 120)
    big = index.read(row['id'])
    assert big['too_large'] is True and 'text' not in big
    assert 'shape' in big and 'fields' in big['shape']
    # 结构图指路后能精确读到那一支，且这一支本身没过上限
    leaf = index.read(row['id'], '/fields/output/value')
    assert not leaf.get('too_large') and leaf['text']
    with pytest.raises(ValueError, match='路径不存在'):
        index._resolve(index._body(row['id']), '/fields/nope')


def test_shape_only_read_is_not_a_citable_receipt(monkeypatch):
    """只看结构图不等于读过正文：否则整理员能把没看过的整棵树交给下游轴。"""
    d = dossier()
    index = EvidenceIndex(d)
    row = next(r for r in d['records'] if r['kind'] == 'steps')
    monkeypatch.setattr(evidence_tools, 'MAX_READ_CHARS', 120)
    index.read(row['id'])
    assert index.read_ids == set()
    assert index.shape_only_ids == {row['id']}
    assert index.receipts[0]['shape_only'] is True
    # 下钻读到正文后，同一条记录才可引用；回执里带上了读过的路径，供视图只渲染这几段。
    index.read(row['id'], '/fields/output/value')
    assert index.read_ids == {row['id']}
    assert index.read_receipts == [
        {'id': row['id'], 'path': '', 'chars': index.receipts[0]['chars'], 'shape_only': True, 'full': False},
        {'id': row['id'], 'path': '/fields/output/value',
         'chars': len(index.read(row['id'], '/fields/output/value')['text']), 'shape_only': False, 'full': False}]
    assert index.calls == 3          # 三次工具调用：读结构图、下钻读正文、重复读一次


def test_full_read_brings_an_oversized_node_body_into_the_axis_view(monkeypatch):
    """下游确实需要整段（整页工具回填、系统提示词）时，整理员可申请完整读取：
    这次回执算读过正文，轴视图带上整段，去留仍由轴视图预算决定。"""
    d = dossier()
    index = EvidenceIndex(d)
    row = next(r for r in d['records'] if r['kind'] == 'steps')
    monkeypatch.setattr(evidence_tools, 'MAX_READ_CHARS', 120)
    monkeypatch.setattr('impl.projects.llm_probe.business_trace.dossier.EVIDENCE_NODE_CHARS', 120)
    assert index.read(row['id'])['too_large'] is True
    full = index.read(row['id'], full=True)
    assert full['chars'] > 120 and full['text']
    assert index.read_ids == {row['id']}
    assert index.receipts[-1]['full'] is True and 'shape_only' not in index.receipts[-1]
    view = build_axis_view(d, {'refs': [row['id']]}, budget_chars=VIEW_BUDGET_CHARS, axis_id='context_memory',
                           structure={'evidence_audit': {'reads': index.read_receipts}})
    rendered = view['records'][0]
    # 轴看到的正是整理员读到的同一份正文（读取粒度 = 引用粒度 = 渲染粒度）
    assert rendered['read_paths']['/'] == json.loads(full['text'])
    assert rendered['chars'] == full['chars']


def test_search_locates_body_and_its_path_can_be_read_back():
    d = dossier()
    index = EvidenceIndex(d)
    hit = index.search('P002')
    assert hit['hits']
    first = hit['hits'][0]
    assert first['id'] in {row['id'] for row in d['records']} and first['path'].startswith('/')
    assert 'P002' in first['snippet']
    read = index.read(first['id'], first['path'])
    assert 'P002' in read['text']


def test_search_is_honest_about_truncation_and_unknown_scope():
    d = dossier()
    index = EvidenceIndex(d)
    none = index.search('这个词案卷里不会有xyzzy')
    assert none['hits'] == [] and none['total_hits'] == 0
    scoped = index.search('P002', record_id='turn1/records/run')
    assert scoped['hits'] and all(hit['id'] == 'turn1/records/run' for hit in scoped['hits'])
    with pytest.raises(ValueError, match='query 不能为空'):
        index.search('   ')


def test_timeline_states_unknown_timestamps_instead_of_ordering_them():
    d = dossier()
    index = EvidenceIndex(d)
    rows = index.timeline('turn1')['rows']
    assert rows and all(row['turn'] == 'turn1' for row in rows)
    assert 'at' in rows[0] and 'bucket' in rows[0]


def test_verify_quote_accepts_exact_text_only():
    d = dossier()
    index = EvidenceIndex(d)
    good = index.verify_quote('turn1/records/run', '保单 P002 的现金价值是多少？', '/fields/input/value')
    assert good['found'] is True
    bad = index.verify_quote('turn1/records/run', '保单 P002 的现金价值是一万元', '/fields/input/value')
    assert bad['found'] is False


def test_source_number_can_be_read_and_collected():
    """实测缺陷：source 编号从来读不了（content_ref 塞了个 dict），新目录把 source 列出来后就踩到了。"""
    d = dossier()
    index = EvidenceIndex(d)
    source_id = d['sources'][0]['id']
    read = index.read(source_id)
    assert not read.get('error') and read['chars'] > 0
    if read.get('too_large'):
        # 整条超单次上限：给结构图，按 path 下钻到要的那一部分
        assert sorted(read['shape']) == ['original_records', 'request_and_response']
        part = index.read(source_id, '/request_and_response')
        assert not part.get('error') and part['chars'] > 0
    else:
        assert 'request_and_response' in read['text'] and 'original_records' in read['text']
    collected = index.collect([source_id])
    assert collected['items'][0]['chars'] == read['chars']
    assert source_id in index.read_ids


def test_unknown_number_is_refused_with_a_receipt():
    index = EvidenceIndex(dossier())
    out = index.read('turn9/records/nope')
    assert 'error' in out and not index.read_ids
    assert index.receipts[0]['error']


def test_collect_brings_several_bodies_in_one_call_and_counts_as_read():
    """价格关键在于会话长度：一次取回多条，不能逼侦探逐条往返。"""
    d = dossier()
    index = EvidenceIndex(d)
    ids = [row['id'] for row in d['records'] if row['kind'] == 'runs'][:1]
    ids += [row['id'] for row in d['records'] if row['kind'] == 'steps'][:2]
    out = index.collect(ids)
    assert [item['id'] for item in out['items']] == ids
    assert all(item['text'] for item in out['items'])
    assert out['deferred'] == [] and out['unknown'] == []
    # 一次调用多条回执：每条都可被引用（与单读同口径）
    assert index.read_ids == set(ids)
    assert [receipt['id'] for receipt in index.read_receipts] == ids
    assert all(receipt['path'] == '' for receipt in index.read_receipts)


def test_collect_lists_what_it_could_not_bring_instead_of_silently_dropping(monkeypatch):
    d = dossier()
    index = EvidenceIndex(d)
    monkeypatch.setattr(evidence_tools, 'MAX_COLLECT_CHARS', 60)
    ids = [row['id'] for row in d['records'] if row['kind'] in {'runs', 'steps'}][:4]
    out = index.collect(ids + ['turn9/records/nope'])
    assert len(out['items']) == 1
    assert out['deferred'] == ids[1:]
    assert out['unknown'] == ['turn9/records/nope']
    assert ids[1] in out['hint'] and '未取回' in out['hint']


def test_collect_returns_the_small_pieces_of_an_oversized_record_with_receipts(monkeypatch):
    """大记录（几万字的会话状态）里真正要看的往往是小时限/耗时/计数：一趟装回来，逐段留回执，
    装不下的只登记路径——否则侦探要花两轮才能拿到一个字段，工具预算瞬间烧光。"""
    d = dossier()
    index = EvidenceIndex(d)
    row = max(d['records'], key=lambda r: len(_text(evidence_tools.record_body(d, r))))
    monkeypatch.setattr(evidence_tools, 'MAX_READ_CHARS', 400)
    out = index.collect([row['id']])
    item = out['items'][0]
    assert item['partial'] is True and item['slices']
    assert item['slice_chars'] <= 400 and item['map'] and item['not_read_here']
    # 每个装回来的片段都有正文读取回执，路径与片段一致；轴视图就按这些路径渲染
    assert {r['path'] for r in index.read_receipts} == set(item['slices'])
    assert row['id'] in index.read_ids and row['id'] not in index.shape_only_ids
    view = build_axis_view(d, {'refs': [row['id']]}, budget_chars=VIEW_BUDGET_CHARS, axis_id='context_memory',
                           structure={'evidence_audit': {'reads': index.read_receipts}})
    assert set(view['records'][0]['read_paths']) == set(item['slices'])


def test_collect_large_record_slices_share_the_total_budget(monkeypatch):
    d = dossier()
    row = max(d['records'], key=lambda r: len(_text(evidence_tools.record_body(d, r))))
    duplicate = dict(row, id=row['id'] + '-second')
    d['records'].append(duplicate)
    monkeypatch.setattr(evidence_tools, 'MAX_READ_CHARS', 400)
    monkeypatch.setattr(evidence_tools, 'MAX_COLLECT_CHARS', 450)
    out = EvidenceIndex(d).collect([row['id'], duplicate['id']])
    assert out['chars'] <= 450
    assert all(item['slice_chars'] <= 400 for item in out['items'] if item.get('partial'))


def test_collect_falls_back_to_shape_when_no_piece_fits(monkeypatch):
    d = dossier()
    index = EvidenceIndex(d)
    row = next(r for r in d['records'] if r['kind'] == 'steps')
    monkeypatch.setattr(evidence_tools, 'MAX_READ_CHARS', 120)
    monkeypatch.setattr(evidence_tools, 'MAX_SLICE_CHARS', 1)
    out = index.collect([row['id']])
    assert out['items'][0]['too_large'] is True and 'shape' in out['items'][0]
    assert index.read_ids == set() and index.shape_only_ids == {row['id']}


def test_tools_are_built_from_the_index():
    index = EvidenceIndex(dossier())
    built = evidence_tools.build_dossier_tools(index)
    assert [getattr(tool, 'name', '') for tool in built] == [
        'dossier_collect', 'dossier_read', 'dossier_search', 'dossier_timeline', 'dossier_verify_quote']
