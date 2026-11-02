"""需求 §3 的 P1–P7 在本应 / 实际判法下的落位（spec/alg/process-axes.md §9、§14）。

只测程序侧：给定各轴已落定的判定与问题（模型产出由脚本代替），汇总、组成、问题记录、聚类输入是否按 §9 落位。
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from impl.core.axes_clustering import build_material
from impl.projects.llm_probe.eval_axes.adapters import process_expected as px
from impl.projects.llm_probe.eval_axes.adapters.process_common import AxisSpec, Subcapability

TEXTS = {"rec": ["证据原文"]}
QUOTE = {"ref": "rec", "quote": "证据原文"}


def axis(axis_id, rows, problems=(), not_covered=(), unexpected=()):
    expected = {"expected": [dict(id=r[0], about="a", subcapability=r[3] if len(r) > 3 else "s", statement=f"本应{r[0]}",
                                  basis="b", needs_external="否", turn="t1") for r in rows],
                "not_covered": list(not_covered)}
    actual = {"actual": [dict(id=r[0], links=["L"], observed=f"实际{r[0]}", verdict=r[1],
                              quotes=[QUOTE] if r[2] else []) for r in rows],
              "unexpected": [dict(u, quotes=[QUOTE], links=[]) for u in unexpected],
              "problems": [dict(phenomenon=p[0], items=p[1], attribution=p[2], impact="i",
                                problem_id=f"{axis_id}-B1-P{k}") for k, p in enumerate(problems, 1)],
              "reason": "r", "scope_note": "s"}
    batch = {"number": 1, "turns": ["t1"], "duties": {}, "links": ["L"], "chars": {}, "expected": expected,
             "actual": px.settle(actual, expected, TEXTS)}
    return px.outcome_of(axis_id, [batch], [], {"llm_calls": 2}, {"refs": [], "why": []})


def test_p1a_missing_query_is_planning_problem_and_data_untested():
    planning = axis("planning_routing", [("E1", "没达到", True, "工作覆盖完整")],
                    [("Q1 没发查询", ["E1"], "本轴")])
    data = axis("knowledge_data", [("E1", "没达到", True, "子问题数据已给出")],
                [("Q1 数据没拿到", ["E1"], "上游:planning_routing")])
    assert planning.output["assessment"]["verdict"] == "problematic"
    assert data.output["assessment"]["verdict"] == "untested"
    assert data.output["issues"][0]["attribution"] == "upstream"
    assert data.output["assessment"]["composition"]["counts"]["问题·上游"] == 1


def test_p1b_queried_and_source_really_lacks_it_is_data_problem():
    data = axis("knowledge_data", [("E1", "没达到", True)], [("库里没有这张保单", ["E1"], "本轴")])
    assert data.output["assessment"]["verdict"] == "problematic"


def test_p2_empty_return_unresolved_between_tool_and_data_is_not_evaluable_on_both():
    """同一事件多轴各记（§3.3），归因都写未定位，两轴都不抬高缺陷率。"""
    tool = axis("tool_execution", [("E1", "没达到", True)], [("返回为空", ["E1"], "未定位:tool_execution,knowledge_data")])
    data = axis("knowledge_data", [("E1", "没达到", True)], [("返回为空", ["E1"], "未定位:tool_execution,knowledge_data")])
    for out in (tool, data):
        assert out.output["assessment"]["verdict"] == "not_evaluable"
        assert [i["attribution"] for i in out.output["issues"]] == ["unresolved"]


def test_p3_lost_prompt_blames_context_while_model_stays_sound_with_upstream_shown():
    context = axis("context_memory", [("E1", "没达到", True)], [("提示没送到", ["E1"], "本轴")])
    model = axis("model_capability", [("E1", "没达到", True, "输出忠实于输入"), ("E2", "达到", False, "不编造")],
                 [("答错，因提示缺失", ["E1"], "上游:context_memory")])
    assert context.output["assessment"]["verdict"] == "problematic"
    assert model.output["assessment"]["verdict"] == "sound"
    assert model.output["assessment"]["composition"]["counts"]["问题·上游"] == 1


def test_p4_problem_keeps_uncheckable_items_visible():
    out = axis("tool_execution", [("E1", "没达到", True), ("E2", "无法核", False), ("E3", "无法核", False)],
               [("返回对象不对", ["E1"], "本轴")])
    assert out.output["assessment"]["verdict"] == "problematic"
    assert out.output["assessment"]["composition"]["counts"]["无法核"] == 2


def test_p5_sound_still_reports_what_was_not_covered():
    out = axis("intent_understanding", [("E1", "达到", False)], not_covered=["本轮没有历史，指代解析没测到"])
    assert out.output["assessment"]["verdict"] == "sound"
    assert out.output["assessment"]["composition"]["counts"]["未覆盖"] == 1
    assert out.output["assessment"]["gaps"] == ["本轮没有历史，指代解析没测到"]


def test_p6_invalid_evaluator_output_is_a_run_error_not_an_item_value(monkeypatch):
    monkeypatch.setattr(px, "input_view", lambda dossier, links: {"records": []})
    bad = {"actual": [], "unexpected": [], "problems": [], "reason": "r", "scope_note": "s"}
    replies = iter([{"expected": [dict(id="E1", about="a", subcapability="s", statement="x", basis="b",
                                       needs_external="否", turn="t1")], "not_covered": []}, bad, bad])
    client = SimpleNamespace(complete_json=lambda *a, **k: copy.deepcopy(next(replies)), usage=lambda: {})
    monkeypatch.setattr(px, "axis_llm", lambda *a, **k: client)
    monkeypatch.setattr("impl.projects.llm_probe.eval_axes.adapters.process_common._scenario_entry", lambda runtime: None)
    analysis = {"dossier": {"records": []}, "structure": {}, "selections": {"intent_understanding": {
        "materials": [{"links": [{"link_id": "L", "link_type": "intent_understanding", "input": [], "output": []}],
                       "view": {"records": []}, "turns": ["t1"]}]}}}
    spec = AxisSpec("q", "x", (Subcapability("对象与字段一致", "w", "d"),))
    out = px.run_expected_axis("intent_understanding", {"trace_analysis": analysis, "expectations": {}}, None,
                               SimpleNamespace(spec=None, trace_id="t", ensure_time_left=lambda *_: None), spec)
    assert out.failed and "一一对应" in out.failure_reason
    assert out.output["assessment"]["verdict"] is None and out.output["results"] == []


def test_p7_clustering_members_are_issue_records_not_axis_reason():
    out = axis("context_memory", [("E1", "没达到", True), ("E2", "没达到", True)],
               [("假缺口", ["E1"], "本轴"), ("余量提示不更新", ["E2"], "本轴")])
    row = {"pool_index": 0, "request_key": "req-1", "axes": [{"type_id": "context_memory", "status": "succeeded",
                                      "verdict": out.output["assessment"]["verdict"], "issues": out.output["issues"]}]}
    types = [{"type_id": "context_memory", "verdict_scope": "axis", "title": "上下文", "verdict_enum": []}]
    material = build_material([row], types)
    members = [r for label in material["axes"][0]["labels"] for r in label["records"]]
    assert [m["subject"] for m in members] == ["context_memory-B1-P1", "context_memory-B1-P2"]
    assert members[0]["reason"].startswith("假缺口；预期：本应E1")
