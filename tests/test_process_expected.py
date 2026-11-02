"""本应清单 / 实际清单判法（spec/alg/process-axes.md §2–§5、§13）。"""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from impl.core.llm_client import with_output_constraint
from impl.projects.llm_probe.eval_axes.adapters import process_expected as px

FULL = {
    "format": "axis-materials-v1",
    "records": [
        {"id": "tool/1", "kind": "tool_calls", "fields": {
            "arguments": {"status": "available", "value": {"shared_ref": "shared#1"}},
            "result": {"status": "available", "value": "累计已交保费 1320"}}},
        {"id": "final", "kind": "steps", "fields": {
            "output": {"status": "available", "value": '{"answer":"保费:0.00","gaps":["部分内容未能在本轮证据中对应"]}'}}},
    ],
    "shared_contents": {"shared#1": {"policy": "P1"}, "shared#2": "只在输出端用到"},
    "contents": {},
    "gaps": [], "missing_endpoints": [],
}
FIRST = {"format": "axis-materials-v1",
         "records": [{"id": "tool/1", "kind": "tool_calls",
                      "fields": {"arguments": {"status": "available", "value": {"policy": "P1"}}}}],
         "gaps": [], "missing_endpoints": [], "reading_guide": "只给输入端"}


def test_split_is_lossless_and_first_part_has_no_output_fields():
    part1, part2 = px.split_views(FIRST, FULL)
    assert [r["id"] for r in part1["records"]] == ["tool/1"]
    assert set(part1["records"][0]["fields"]) == {"arguments"}
    assert part1["shared_contents"] == {"shared#1": {"policy": "P1"}}
    assert {r["id"] for r in part2["records"]} == {"tool/1", "final"}
    assert px.record_fields(px.merge_views(part1, part2)) == px.record_fields(FULL)


def _expected(*items, turn="t1"):
    return {"expected": [dict(id=i, about="a", subcapability="交付保留原义", statement=f"本应{i}", basis="原文",
                              needs_external=ext, turn=turn) for i, ext in items], "not_covered": []}


def _row(i, verdict, quotes=()):
    return dict(id=i, links=["L1"], observed=f"实际{i}", verdict=verdict,
                quotes=[dict(ref=r, quote=q) for r, q in quotes])


TEXTS = px.record_texts(FULL)
GOOD = ("final", "部分内容未能在本轮证据中对应")


def test_check_reports_alignment_orphans_and_fabricated_quotes():
    expected = _expected(("E1", "否"), ("E2", "否"))
    actual = {"actual": [_row("E1", "没达到", [("final", "保费:1320")])], "unexpected": [],
              "problems": [], "reason": "r", "scope_note": "s"}
    structure, quotes = px.check_actual(actual, expected, TEXTS)
    assert any("一一对应" in i for i in structure)
    assert any("没有被任何 problem 引用" in i for i in structure)
    assert any("找不到这段原文" in i for i in quotes)


def test_met_rows_bad_quotes_do_not_force_a_rewrite():
    expected = _expected(("E1", "否"))
    actual = {"actual": [_row("E1", "达到", [("final", "编出来的")])], "unexpected": [], "problems": [],
              "reason": "r", "scope_note": "s"}
    assert px.check_actual(actual, expected, TEXTS) == ([], [])
    settled = px.settle(copy.deepcopy(actual), expected, TEXTS)
    assert settled["actual"][0]["quotes"] == [] and settled["actual"][0]["verdict"] == "达到"


def test_settle_locks_external_checks_and_drops_problems_that_lost_their_basis():
    expected = _expected(("E1", "是"), ("E2", "否"))
    actual = {"actual": [_row("E1", "没达到", [GOOD]), _row("E2", "没达到", [GOOD])], "unexpected": [],
              "problems": [dict(phenomenon="p1", items=["E1"], attribution="本轴", impact="i"),
                           dict(phenomenon="p2", items=["E2"], attribution="本轴", impact="i")],
              "reason": "r", "scope_note": "s"}
    settled = px.settle(actual, expected, TEXTS)
    assert [r["verdict"] for r in settled["actual"]] == ["无法核", "没达到"]
    assert [p["phenomenon"] for p in settled["problems"]] == ["p2"]
    assert settled["demoted"] == [{"id": "E1", "was": "没达到", "why": "必须独立查证"}]
    assert settled["actual"][1]["refs"] == ["final"]


def _batch(rows, problems=(), unexpected=()):
    return {"number": 1, "turns": ["t1"], "duties": {}, "links": ["L1"], "chars": {}, "expected": _expected(*[(r["id"], "否") for r in rows]),
            "actual": {"actual": rows, "unexpected": list(unexpected), "problems": list(problems),
                       "reason": "r", "scope_note": "s", "demoted": []}}


@pytest.mark.parametrize("rows,problems,verdict", [
    ([_row("E1", "没达到", [GOOD])], [dict(phenomenon="p", items=["E1"], attribution="本轴", impact="i")], "problematic"),
    ([_row("E1", "达到"), _row("E2", "无法核")], [], "not_evaluable"),
    ([_row("E1", "没达到", [GOOD])], [dict(phenomenon="p", items=["E1"], attribution="未定位:工具,知识", impact="i")], "not_evaluable"),
    ([_row("E1", "达到"), _row("E2", "没达到", [GOOD])], [dict(phenomenon="p", items=["E2"], attribution="上游:规划", impact="i")], "sound"),
    ([_row("E1", "没达到", [GOOD])], [dict(phenomenon="p", items=["E1"], attribution="上游:规划", impact="i")], "untested"),
    ([], [], "not_applicable"),
])
def test_axis_verdict_follows_spec_order(rows, problems, verdict):
    assert px.aggregate([_batch(rows, problems)])[0] == verdict


def test_issue_records_carry_expected_actual_quotes_and_attribution():
    batch = _batch([_row("E1", "没达到", [GOOD])],
                   [dict(phenomenon="假缺口", items=["E1", "X1"], attribution="本轴", impact="虚报缺口",
                         problem_id="context_memory-B1-P1")],
                   [dict(id="X1", observed="覆盖了答案", links=["L2"], quotes=[dict(ref="final", quote="保费:0.00")], why="丢答案")])
    issue = px.issues_of("context_memory", [batch])[0]
    assert issue["problem_id"] == "context_memory-B1-P1" and issue["attribution"] == "local"
    assert issue["expected"] == "本应E1（依据：原文）" and issue["observed"] == "实际E1；覆盖了答案"
    assert issue["output_refs"] == ["final"] and issue["origin"] == "expected" and issue["links"] == ["L1", "L2"]


def test_batch_sends_second_call_and_correction_as_new_turns(monkeypatch):
    monkeypatch.setattr(px, "input_view", lambda dossier, links: FIRST)
    calls = []
    replies = [
        _expected(("E1", "否")),
        {"actual": [_row("E1", "没达到", [("final", "编出来的")])], "unexpected": [],
         "problems": [dict(phenomenon="p", items=["E1"], attribution="本轴", impact="i")], "reason": "r", "scope_note": "s"},
        {"actual": [_row("E1", "没达到", [GOOD])], "unexpected": [],
         "problems": [dict(phenomenon="p", items=["E1"], attribution="本轴", impact="i")], "reason": "r", "scope_note": "s"},
    ]

    class Client:
        def complete_json(self, system, user, **kwargs):
            calls.append(dict(system=system, user=user, **kwargs))
            return copy.deepcopy(replies[len(calls) - 1])

    spec = SimpleNamespace(question="q", excludes="x", subcapabilities=[SimpleNamespace(name="交付保留原义", when="w", duty="duty")])
    runtime = SimpleNamespace(trace_id="t", ensure_time_left=lambda *_: None)
    out = px.judge_batch(Client(), runtime, "context_memory", spec, 1, ["t1"], {}, [{"link_id": "L1"}], FULL,
                         {"expectations": [], "sources": []}, "limits")
    assert len(calls) == 3 and len({c["system"] for c in calls}) == 1
    assert all(c["constraint_in_user"] for c in calls)
    assert calls[0].get("history") is None and "通用职责" in calls[0]["user"]
    assert "保费:0.00" not in calls[0]["user"] and "保费:0.00" in calls[1]["user"]  # 第一次看不到输出端
    first_sent = with_output_constraint(calls[0]["user"], px.EXPECTED_SPEC)
    assert calls[1]["history"][0] == {"role": "user", "content": first_sent}
    assert calls[1]["history"][1]["role"] == "assistant"
    assert calls[2]["history"][:2] == calls[1]["history"]
    assert calls[2]["history"][2] == {"role": "user", "content": with_output_constraint(calls[1]["user"], px.ACTUAL_SPEC)}
    assert "编出来的" in calls[2]["history"][3]["content"] and "找不到这段原文" in calls[2]["user"]
    assert out["actual"]["actual"][0]["verdict"] == "没达到" and out["actual"]["actual"][0]["refs"] == ["final"]


def test_second_bad_answer_is_an_evaluator_error(monkeypatch):
    monkeypatch.setattr(px, "input_view", lambda dossier, links: FIRST)
    bad = {"actual": [], "unexpected": [], "problems": [], "reason": "r", "scope_note": "s"}
    replies = [_expected(("E1", "否")), bad, bad]

    class Client:
        n = 0

        def complete_json(self, system, user, **kwargs):
            Client.n += 1
            return copy.deepcopy(replies[Client.n - 1])

    spec = SimpleNamespace(question="q", excludes="x", subcapabilities=[])
    runtime = SimpleNamespace(trace_id="t", ensure_time_left=lambda *_: None)
    with pytest.raises(ValueError, match="一一对应"):
        px.judge_batch(Client(), runtime, "intent_understanding", spec, 1, ["t1"], {}, [{"link_id": "L1"}], FULL,
                       {"expectations": [], "sources": []}, "limits")


def test_quotes_still_bad_after_rewrite_are_dropped_not_fatal(monkeypatch):
    """§4：纠错后仍不在所引记录里的引文丢弃；没达到的行丢光引文降成无法核，不是评测器错误。"""
    monkeypatch.setattr(px, "input_view", lambda dossier, links: FIRST)
    fake = {"actual": [_row("E1", "没达到", [("final", "编出来的")])], "unexpected": [],
            "problems": [dict(phenomenon="p", items=["E1"], attribution="本轴", impact="i")], "reason": "r", "scope_note": "s"}
    replies = [_expected(("E1", "否")), fake, fake]

    class Client:
        n = 0

        def complete_json(self, system, user, **kwargs):
            Client.n += 1
            return copy.deepcopy(replies[Client.n - 1])

    spec = SimpleNamespace(question="q", excludes="x", subcapabilities=[])
    runtime = SimpleNamespace(trace_id="t", ensure_time_left=lambda *_: None)
    out = px.judge_batch(Client(), runtime, "intent_understanding", spec, 1, ["t1"], {}, [{"link_id": "L1"}], FULL,
                         {"expectations": [], "sources": []}, "limits")
    assert Client.n == 3
    assert out["actual"]["actual"][0]["verdict"] == "无法核" and out["actual"]["problems"] == []
    assert out["actual"]["demoted"] == [{"id": "E1", "was": "没达到", "why": "没有能核对的引文"}]


def test_same_problem_in_a_later_batch_is_merged_not_counted_twice():
    first = _batch([_row("E1", "没达到", [GOOD])],
                   [dict(phenomenon="假缺口", items=["E1"], attribution="本轴", impact="i", problem_id="cm-B1-P1")])
    second = _batch([_row("E1", "没达到", [("tool/1", "累计已交保费1320")])],
                    [dict(phenomenon="又见假缺口", items=["E1"], attribution="本轴", impact="i", problem_id="cm-B2-P1",
                          same_as="cm-B1-P1")])
    second["number"] = 2
    issues = px.issues_of("cm", [first, second])
    assert len(issues) == 1 and issues[0]["problem_id"] == "cm-B1-P1"
    assert issues[0]["output_refs"] == ["final", "tool/1"]
    assert [u["problem_id"] for u in issues[0]["units"]] == ["cm-B1-P1", "cm-B2-P1"]
    assert px.aggregate([first, second])[2]["counts"]["问题·本轴"] == 1


def test_same_as_must_point_to_an_earlier_problem():
    expected = _expected(("E1", "否"))
    actual = {"actual": [_row("E1", "没达到", [GOOD])], "unexpected": [],
              "problems": [dict(phenomenon="p", items=["E1"], attribution="本轴", impact="i", same_as="cm-B9-P9")],
              "reason": "r", "scope_note": "s"}
    structure, _ = px.check_actual(actual, expected, TEXTS, frozenset({"cm-B1-P1"}))
    assert any("same_as" in i for i in structure)


def test_first_call_gets_one_correction_as_a_new_turn(monkeypatch):
    from impl.core.llm_client import OutputRejected
    monkeypatch.setattr(px, "input_view", lambda dossier, links: FIRST)
    calls = []
    ok_actual = {"actual": [_row("E1", "达到")], "unexpected": [], "problems": [], "reason": "r", "scope_note": "s"}

    class Client:
        def complete_json(self, system, user, **kwargs):
            calls.append(dict(user=user, **kwargs))
            if len(calls) == 1:
                raise OutputRejected("必填字段缺失：needs_external", '{"expected":[{"id":"E1"}]}')
            return copy.deepcopy(_expected(("E1", "否")) if len(calls) == 2 else ok_actual)

    spec = SimpleNamespace(question="q", excludes="x", subcapabilities=[])
    runtime = SimpleNamespace(trace_id="t", ensure_time_left=lambda *_: None)
    out = px.judge_batch(Client(), runtime, "intent_understanding", spec, 1, ["t1"], {}, [{"link_id": "L1"}], FULL,
                         {"expectations": [], "sources": []}, "limits")
    assert calls[1]["history"] == [{"role": "user", "content": with_output_constraint(calls[0]["user"], px.EXPECTED_SPEC)},
                                   {"role": "assistant", "content": '{"expected":[{"id":"E1"}]}'}]
    assert "needs_external" in calls[1]["user"]
    # 第二步只带被采纳的那份本应清单，不带被拒收的那一轮。
    assert calls[2]["history"][0]["content"] == with_output_constraint(calls[0]["user"], px.EXPECTED_SPEC)
    assert json.loads(calls[2]["history"][1]["content"]) == _expected(("E1", "否"))
    assert out["actual"]["actual"][0]["verdict"] == "达到"


@pytest.mark.parametrize("axis_id", ["context_memory", "intent_understanding", "planning_routing",
                                     "tool_execution", "knowledge_data", "model_capability"])
def test_outcome_matches_the_registered_axis_contract(axis_id):
    """运行器按注册表校验：输出键集合与 output_fields 一致、verdict 在枚举内（runner._run_one）。"""
    from impl.projects.llm_probe.eval_axes.registry import AXIS_TYPES

    batch = _batch([_row("E1", "没达到", [GOOD])],
                   [dict(phenomenon="p", items=["E1"], attribution="本轴", impact="i", problem_id=f"{axis_id}-B1-P1")])
    batch["actual"] = px.settle(batch["actual"], batch["expected"], TEXTS)
    out = px.outcome_of(axis_id, [batch], [], {"llm_calls": 2}, {"refs": [], "why": []})
    kind = AXIS_TYPES[axis_id]
    assert set(out.output) == set(kind.output_fields)
    assert out.output["assessment"]["verdict"] in kind.verdict_values
    assert out.summary.items and not out.failed


def test_chinese_quote_marks_stand_for_ascii_quotes_in_verbatim_check():
    """引文要求把原文英文双引号写成“”（免得弄坏输出 JSON），核对时视同。"""
    texts = px.record_texts(FULL)
    assert px.bad_quotes({"quotes": [{"ref": "final", "quote": "“answer”:“保费:0.00”"}]}, texts) == []
    assert px.bad_quotes({"quotes": [{"ref": "final", "quote": "“answer”:“保费:9.99”"}]}, texts)


def _duty_batch(number, turn, verdict, duty="D1"):
    batch = _batch([_row("E1", verdict, [GOOD] if verdict == "没达到" else [])])
    batch["number"], batch["turns"], batch["duties"] = number, [turn], {"E1": duty}
    batch["expected"]["expected"][0]["turn"] = turn
    return batch


def test_standing_duty_is_settled_per_turn_by_any_batch_that_could_check_it():
    """通用职责按轮、按轴取值：同一轮里别的批判过，这一批的无法核不再拖累整轴；整轮都核不了才算一条无法核。"""
    verdict, _, comp = px.aggregate([_duty_batch(1, "t1", "无法核"), _duty_batch(2, "t1", "达到")])
    assert verdict == "sound" and comp["standing_duties"] == {"t1 D1": "达到"} and comp["counts"]["无法核"] == 0
    verdict, _, comp = px.aggregate([_duty_batch(1, "t1", "无法核"), _duty_batch(2, "t1", "无法核"),
                                     _duty_batch(3, "t2", "达到")])
    assert verdict == "not_evaluable" and comp["counts"]["无法核"] == 1
    assert comp["standing_duties"] == {"t1 D1": "无法核", "t2 D1": "达到"}


def test_duty_items_must_carry_the_given_number(monkeypatch):
    monkeypatch.setattr(px, "input_view", lambda dossier, links: FIRST)
    unnumbered = _expected(("E1", "否"))
    unnumbered["expected"][0]["basis"] = "通用职责"
    numbered = copy.deepcopy(unnumbered)
    numbered["expected"][0]["basis"] = "通用职责 D2"
    replies = iter([unnumbered, numbered, {"actual": [_row("E1", "达到")], "unexpected": [], "problems": [],
                                           "reason": "r", "scope_note": "s"}])
    calls = []

    class Client:
        def complete_json(self, system, user, **kwargs):
            calls.append(user)
            return copy.deepcopy(next(replies))

    spec = SimpleNamespace(question="q", excludes="x", subcapabilities=[])
    runtime = SimpleNamespace(trace_id="t", ensure_time_left=lambda *_: None)
    out = px.judge_batch(Client(), runtime, "context_memory", spec, 1, ["t1"], {}, [{"link_id": "L1"}], FULL,
                         {"expectations": [], "sources": []}, "limits")
    assert '"D1"' in calls[0] and "本批不涉及" in calls[0] and "没写给定的编号" in calls[1]
    assert out["duties"] == {"E1": "D2"} and out["turns"] == ["t1"]


def test_axis_without_duties_neither_asks_for_nor_checks_duty_numbers(monkeypatch):
    """没有通用职责的轴：提示词不提通用职责；模型自己在 basis 里写了「通用职责」也不当成格式错误（2026-10-14 整批里 7 个轴因此失败）。"""
    monkeypatch.setattr(px, "input_view", lambda dossier, links: FIRST)
    loose = _expected(("E1", "否"))
    loose["expected"][0]["basis"] = "通用职责"
    replies = iter([loose, {"actual": [_row("E1", "达到")], "unexpected": [], "problems": [],
                            "reason": "r", "scope_note": "s"}])
    calls = []

    class Client:
        def complete_json(self, system, user, **kwargs):
            calls.append(user)
            return copy.deepcopy(next(replies))

    spec = SimpleNamespace(question="q", excludes="x", subcapabilities=[])
    runtime = SimpleNamespace(trace_id="t", ensure_time_left=lambda *_: None)
    out = px.judge_batch(Client(), runtime, "model_capability", spec, 1, ["t1"], {}, [{"link_id": "L1"}], FULL,
                         {"expectations": [], "sources": []}, "limits")
    assert len(calls) == 2 and "通用职责" not in calls[0].split("\n\n")[0]
    assert out["duties"] == {}


def test_each_batch_gets_only_the_needs_of_the_turns_it_holds(monkeypatch):
    seen = []
    monkeypatch.setattr(px, "axis_llm", lambda *a, **k: SimpleNamespace(usage=lambda: {}))
    monkeypatch.setattr(px, "judge_batch", lambda client, runtime, axis_id, spec, number, turns, dossier, links, view, e, *rest:
                        seen.append((turns, [x["expectation_id"] for x in e["expectations"]], [s["id"] for s in e["sources"]]))
                        or {**_batch([{**_row("E1", "达到"), "refs": []}]), "number": number, "turns": turns})
    monkeypatch.setattr("impl.projects.llm_probe.eval_axes.adapters.process_common._scenario_entry", lambda runtime: None)
    analysis = {"dossier": {"records": []}, "structure": {}, "selections": {"intent_understanding": {"materials": [
        {"links": [{"link_id": "A"}], "view": {}, "turns": ["t1", "t2"]}, {"links": [{"link_id": "B"}], "view": {}, "turns": ["t3"]}]}}}
    e = {"expectations": [{"expectation_id": "t1.查伏云平", "turn": "t1"}, {"expectation_id": "t2.查余昕雅", "turn": "t2"},
                          {"expectation_id": "t3.查状态", "turn": "t3"}],
         "sources": [{"id": "t1.user", "turn": "t1"}, {"id": "t2.user", "turn": "t2"}, {"id": "t3.user", "turn": "t3"},
                     {"id": "scenario.description", "turn": "case"}]}
    from dataclasses import dataclass

    @dataclass
    class Spec:
        subcapabilities: tuple = ()
    px.run_expected_axis("intent_understanding", {"trace_analysis": analysis, "expectations": e}, None,
                         SimpleNamespace(spec=None, trace_id="t", ensure_time_left=lambda *_: None), Spec())
    assert seen == [(["t1", "t2"], ["t1.查伏云平", "t2.查余昕雅"], ["t1.user", "t2.user", "scenario.description"]),
                    (["t3"], ["t3.查状态"], ["t3.user", "scenario.description"])]


def test_expected_items_must_belong_to_a_turn_the_batch_holds(monkeypatch):
    """几轮合一批时，本应条目必须标出它属于批里的哪一轮（spec/alg/process-axes.md §2.3），标错的纠错一次。"""
    monkeypatch.setattr(px, "input_view", lambda dossier, links: FIRST)
    replies = iter([_expected(("E1", "否"), turn="t3"), _expected(("E1", "否"), turn="t2"),
                    {"actual": [_row("E1", "达到")], "unexpected": [], "problems": [], "reason": "r", "scope_note": "s"}])
    calls = []

    class Client:
        def complete_json(self, system, user, **kwargs):
            calls.append(user)
            return copy.deepcopy(next(replies))

    spec = SimpleNamespace(question="q", excludes="x", subcapabilities=[])
    runtime = SimpleNamespace(trace_id="t", ensure_time_left=lambda *_: None)
    out = px.judge_batch(Client(), runtime, "intent_understanding", spec, 1, ["t1", "t2"], {}, [{"link_id": "L1"}], FULL,
                         {"expectations": [], "sources": []}, "limits")
    assert "不是本批材料含有的轮" in calls[1] and out["expected"]["expected"][0]["turn"] == "t2"


def test_standing_duty_follows_the_items_own_turn_inside_a_multi_turn_batch():
    batch = _batch([_row("E1", "没达到", [GOOD]), _row("E2", "达到")],
                   [dict(phenomenon="p", items=["E1"], attribution="本轴", impact="i")])
    batch["turns"], batch["duties"] = ["t1", "t2"], {"E1": "D2", "E2": "D2"}
    batch["expected"]["expected"][1]["turn"] = "t2"
    assert px.aggregate([batch])[2]["standing_duties"] == {"t1 D2": "没达到", "t2 D2": "达到"}