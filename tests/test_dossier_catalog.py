"""目录是索引，也是侦探唯一的信息来源：每个可引用编号都在，正文一段都不进目录。"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from impl.core.schema import normalize_run_trace

from impl.projects.llm_probe.business_trace.dossier import (
    CATALOG_STATE_SUMMARY_CHARS, CATALOG_SUMMARY_CHARS, VIEW_BUDGET_CHARS, build_axis_view, build_catalog,
    build_dossier, catalog_ids, dossier_ids, render_catalog, render_value)

SNAPSHOTS = Path(__file__).resolve().parents[1] / 'report/business-trace-agno-20260913/snapshots'
CLEAN = Path(__file__).resolve().parents[1] / 'report/process-dossier-20260920/clean-traces'
BIG_TRACE = CLEAN / 'llm-probe-insurance-real-ctx-ellipsis.json'


def snapshot(name='snap-cash-value.json'):
    return json.loads((SNAPSHOTS / name).read_text())


def dossier(snap=None):
    return build_dossier(SimpleNamespace(turn_records=[]), snap if snap is not None else snapshot())


def clean_dossier(path):
    trace = normalize_run_trace(json.loads(path.read_text()))
    return build_dossier(SimpleNamespace(turn_records=[]), trace.project_fields['business_trace'])


def test_catalog_lists_every_number_an_axis_view_can_resolve():
    d = dossier()
    # 目录必须覆盖 build_axis_view 能解析的全部编号，否则侦探按目录取不到证 = 造缺证。
    assert dossier_ids(d) <= catalog_ids(build_catalog(d))


def test_catalog_never_carries_bodies():
    d = clean_dossier(BIG_TRACE)
    blob = json.dumps(build_catalog(d), ensure_ascii=False)
    bodies = [json.dumps(body, ensure_ascii=False) for body in (d.get('contents') or {}).values()]
    large = [body for body in bodies if len(body) > 600]
    assert large, '样本里必须有长于预览上限的正文，否则这条检查没有意义'
    assert not [body for body in large if body in blob]


def test_catalog_entry_reports_kind_turn_size_and_a_bounded_summary():
    d = dossier()
    entries = {entry['id']: entry for entry in build_catalog(d)['entries']}
    row = next(row for row in d['records'] if any(
        isinstance(info, dict) and info.get('value') is not None for info in row['fields'].values()))
    entry = entries[row['id']]
    assert entry['kind'] == row['kind'] and entry['turn'] == row['turn']
    assert entry['chars'] > 0
    assert entry['summary']
    for item in build_catalog(d)['entries']:
        limit = CATALOG_STATE_SUMMARY_CHARS if item['kind'] == 'states' else CATALOG_SUMMARY_CHARS
        assert len(str(item.get('summary') or '')) <= limit


def test_out_of_line_body_says_whose_field_it_came_from():
    """content#N 是外置寄存的正文：目录必须把它讲成「谁的什么字段的正文」，而不是半截 JSON。"""
    d = clean_dossier(BIG_TRACE)
    entries = build_catalog(d)['entries']
    hosted = [entry for entry in entries
              if entry['kind'] == 'content' and entry.get('host_path') and int(entry.get('depth') or 0) == 0]
    assert hosted, '样本里必须有直接挂在记录字段上的外置正文块'
    for entry in hosted[:10]:
        host = next(row for row in d['records'] if row['id'] == entry['host'])
        assert host['id'] != entry['id']
        assert entry['host_path'] in entry['summary'], entry['summary']
        assert entry['id'] not in entry['summary'][:12]
    # 深嵌正文块只留编号与去处（明细在宿主那一块里），不再重复路径与开头。
    nested = [entry for entry in entries if entry['kind'] == 'content' and int(entry.get('depth') or 0) > 0]
    assert nested and all('嵌在' in entry['summary'] for entry in nested)


def test_catalog_text_keeps_every_id_and_stays_within_budget():
    """目录文本是侦探实际看到的东西：可以折叠、可以压缩，但编号一个都不能丢。"""
    for path in sorted(CLEAN.glob('*.json'))[:6] + sorted(SNAPSHOTS.glob('snap-*.json'))[:2]:
        d = clean_dossier(path) if path.parent == CLEAN else dossier(json.loads(path.read_text()))
        catalog = build_catalog(d)
        text = render_catalog(catalog)
        missing = [entry['id'] for entry in catalog['entries'] if entry['id'] not in text]
        assert not missing, f'{path.name} 目录丢了编号 {missing[:3]}'
        assert len(text) <= catalog['budget_chars'], f'{path.name} 目录 {len(text)} 超预算'


def test_catalog_shows_case_size_and_collection_status():
    d = clean_dossier(BIG_TRACE)
    text = render_catalog(build_catalog(d))
    assert '案卷目录' in text and '采集' in text
    assert f"{len(d['records'])} 条记录" in text


def test_catalog_replaces_the_full_body_dump_with_a_far_smaller_index():
    """整理员不再逐段读正文：目录必须比「全文逐段念一遍」小一个量级。"""
    d = clean_dossier(BIG_TRACE)
    bodies = json.dumps([render_value(d, row) for row in d['records']], ensure_ascii=False, default=str)
    now = len(json.dumps({'case_overview': build_catalog(d)['stats'], 'records': bodies}, ensure_ascii=False))
    text = render_catalog(build_catalog(d))
    assert len(text) < 0.35 * now, f'目录 {len(text)} 未达 65% 压缩（全文 {now}）'
    # 同一个轴视图：目录化之后仍受预算约束，且比全文小
    refs = [row['id'] for row in d['records']]
    view = build_axis_view(d, {'refs': refs}, budget_chars=VIEW_BUDGET_CHARS, axis_id='worst')
    assert len(json.dumps(view, ensure_ascii=False)) < now


@pytest.mark.parametrize('path', sorted(SNAPSHOTS.glob('snap-*.json')), ids=lambda p: p.stem)
def test_catalog_is_never_larger_than_the_expanded_records(path):
    d = dossier(json.loads(path.read_text()))
    text = render_catalog(build_catalog(d))
    expanded = sum(len(json.dumps(row, ensure_ascii=False, default=str)) for row in d['records'])
    assert len(text) < expanded
