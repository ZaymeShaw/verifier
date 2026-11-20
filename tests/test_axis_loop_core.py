"""axis loop 的定义、材料、校验与验收（spec/alg/axis_loop.md §3–§7；实施 P2、P3）。"""
from __future__ import annotations

import json

import pytest

from impl.core.axis_loop import acceptance, paths
from impl.core.axis_loop.checks import STANDARD, check_params
from impl.core.axis_loop.definitions import Code, parse
from impl.core.axis_loop.materials import Material, MaterialTable, Registry, parse_entry, render
from impl.core.axis_loop.validate import check_definitions, check_scenario
from impl.core.axis_loop.view import CallView, TaskView

TEXT = {"type": "string"}


def obj(**props):
    return {"type": "object", "properties": props, "required": list(props)}


EXPECTATIONS_OUT = obj(
    verdict={"type": "string", "enum": ["complete", "partial"]}, reason=TEXT,
    expectations={"type": "array", "items": obj(expectation_id=TEXT, statement=TEXT)})


def registry():
    return Registry([
        Material("case.deliveries", {"type": "array", "items": obj(turn={"type": "integer"}, text=TEXT)},
                 "每一轮回答", lambda case, ctx: case["deliveries"]),
        Material("scenario.criterion", TEXT, "场景判准", lambda case, ctx: case["criterion"]),
        Material("axis.note", TEXT, "场景对当前轴的描述", lambda case, ctx: f"note for {ctx['axis']}"),
    ])


def store(**axes):
    base = {
        "expectations": {"materials": ["scenario.criterion"], "output": EXPECTATIONS_OUT},
    }
    return {"axes": {**base, **axes}, "loops": {"main": {"start": "case"}}}


# ---- 路径 -------------------------------------------------------------------------------

def test_path_extract_keeps_shape_and_projects_fields():
    value = {"expectations": [{"expectation_id": "E1", "statement": "s1", "x": 1}, {"expectation_id": "E2", "statement": "s2"}]}
    path = paths.parse("expectations[].{expectation_id, statement}")
    assert paths.extract(value, path) == [{"expectation_id": "E1", "statement": "s1"}, {"expectation_id": "E2", "statement": "s2"}]
    assert paths.values(value, paths.parse("expectations[].expectation_id")) == ["E1", "E2"]


def test_path_schema_check_reports_unknown_field_and_missing_brackets():
    assert paths.check_schema(EXPECTATIONS_OUT, paths.parse("expectations[].statement")) is None
    assert "nope" in paths.check_schema(EXPECTATIONS_OUT, paths.parse("expectations[].nope"))
    assert "[]" in paths.check_schema(EXPECTATIONS_OUT, paths.parse("expectations.statement"))
    assert "投影" in paths.check_schema(EXPECTATIONS_OUT, paths.parse("expectations[].{expectation_id, nope}"))


# ---- 材料 -------------------------------------------------------------------------------

def test_entry_parsing_splits_standard_name_from_path():
    entry = parse_entry("result.expectations.expectations[].{expectation_id, statement}")
    assert (entry.name, entry.axis, str(entry.path)) == ("result.expectations", "expectations", "expectations[].{expectation_id, statement}")
    assert parse_entry("case.deliveries").name == "case.deliveries"
    with pytest.raises(ValueError):
        parse_entry("delivery")


def test_material_table_takes_builtin_and_results_and_renders_missing_upstream():
    table = MaterialTable(registry(), {"deliveries": [{"turn": 1, "text": "回答"}], "criterion": "给出值"})
    table.results["expectations"] = {"expectations": [{"expectation_id": "E1", "statement": "s"}]}
    entries = [parse_entry("scenario.criterion"), parse_entry("result.expectations.expectations[].expectation_id"),
               parse_entry("result.truthfulness"), parse_entry("axis.note")]
    got = table.view(entries, axis_id="fulfillment")
    assert got["result.expectations.expectations[].expectation_id"] == ["E1"]
    assert got["axis.note"] == "note for fulfillment"
    text = render(got)
    assert "【scenario.criterion】\n给出值" in text and "【result.truthfulness】\n（未启用或未出现）" in text


# ---- 定义与加载期校验 ---------------------------------------------------------------------

def test_valid_definitions_pass():
    defs = parse(store(claims={"depends": [{"axis": "expectations", "hard": True}],
                               "materials": ["case.deliveries", "result.expectations.expectations[].statement"],
                               "output": obj(verdict=TEXT, reason=TEXT)}))
    assert check_definitions(defs, registry()) == []
    assert check_scenario(defs, ["expectations", "claims"], []) == []


@pytest.mark.parametrize("axis, needle", [
    ({"depends": [{"axis": "a2", "hard": True}], "output": obj(verdict=TEXT, reason=TEXT)}, "依赖会卡死"),
    ({"materials": ["result.expectations"], "output": obj(verdict=TEXT, reason=TEXT)}, "超出读取范围"),
    ({"materials": ["case.nope"], "output": obj(verdict=TEXT, reason=TEXT)}, "不在注册表"),
    ({"depends": [{"axis": "expectations", "hard": True}], "materials": ["result.expectations.nope"],
      "output": obj(verdict=TEXT, reason=TEXT)}, "nope"),
    ({"output": obj(reason=TEXT)}, "缺 ['verdict']"),
    ({"depends": [{"axis": "expectations", "hard": False}], "trigger": {"axis": "expectations", "verdict_in": ["partial"]},
      "output": obj(verdict=TEXT, reason=TEXT)}, "只能引用硬依赖"),
    ({"depends": [{"axis": "expectations", "hard": True}], "trigger": {"axis": "expectations", "verdict_in": ["bogus"]},
      "output": obj(verdict=TEXT, reason=TEXT)}, "不在 expectations 的 verdict 枚举"),
    ({"output": obj(verdict={"type": "string", "x-fill": "program"}, reason=TEXT)}, "synth.py"),
    ({"submit": "per_item", "output": obj(verdict=TEXT, reason=TEXT)}, "items_field"),
    ({"checks": [{"covers": {"field": "reason"}}], "output": obj(verdict=TEXT, reason=TEXT)}, "缺 ['of']"),
    ({"checks": [{"covers": {"field": "reason", "of": "case.deliveries[].text"}}], "output": obj(verdict=TEXT, reason=TEXT)},
     "不在本任务的材料白名单"),
    ({"tools": ["nope"], "output": obj(verdict=TEXT, reason=TEXT)}, "不是 start=tool 的 loop"),
    ({"executor": "program", "tools": ["x"], "output": obj(verdict={**TEXT, "x-fill": "program"}, reason={**TEXT, "x-fill": "program"})},
     "程序任务不能有"),
    ({"loop": "nope", "output": obj(verdict=TEXT, reason=TEXT)}, "未定义的 loop nope"),
])
def test_load_time_errors(axis, needle):
    extra = {"a2": {"depends": [{"axis": "a1", "hard": True}], "output": obj(verdict=TEXT, reason=TEXT)}} if needle == "依赖会卡死" else {}
    defs = parse(store(a1=axis, **extra))
    errors = check_definitions(defs, registry())
    assert any(needle in e for e in errors), errors


def test_scenario_errors_for_missing_hard_dependency_and_required_category():
    defs = parse(store(claims={"depends": [{"axis": "expectations", "hard": True}],
                               "tool_categories": [{"category": "knowledge", "required": True}],
                               "output": obj(verdict=TEXT, reason=TEXT)}))
    errors = check_scenario(defs, ["claims"], [])
    assert any("硬依赖 expectations" in e for e in errors) and any("knowledge" in e for e in errors)


def test_shared_tool_params_need_descriptions():
    defs = parse({"axes": {}, "loops": {"main": {"start": "case"}, "search": {
        "start": "tool", "description": "查知识", "params": obj(items={"type": "array"}), "output": obj(x=TEXT)}}})
    assert any("description" in e for e in check_definitions(defs, registry()))


def test_check_params_lists_known_checks():
    assert check_params("nope", {}).startswith("未知的标准校验")
    assert set(STANDARD) == {"covers", "refs_in", "quote_in_material", "quote_in_call", "searched", "from_call"}


# ---- 标准校验与验收 -----------------------------------------------------------------------

CALLS = (
    CallView("c1", "mcp_call", "knowledge", {}, 0, '{"text": "犹豫期为十五日"}', None, False),
    CallView("c2", "mcp_call", "knowledge", {}, 0, "", None, True),
    CallView("c3", "judge_blocking", "subloop", {}, 0, "{}", {"items": []}, False),
)


def make_work(**over):
    raw = {"output": obj(verdict={"type": "string", "enum": ["ok", "bad"]}, reason=TEXT,
                         items={"type": "array", "items": obj(item_id=TEXT, cites={"type": "array", "items": obj(ref=TEXT, quote=TEXT)},
                                                               searched={"type": "array", "items": TEXT})})}
    raw.update(over)
    return parse({"axes": {"t": raw}, "loops": {"main": {"start": "case"}}}).axes["t"]


def view_for(materials=None):
    return lambda stage, own: TaskView("t", own, materials or {}, calls=CALLS, stage=stage)


def test_quote_in_call_and_searched_and_from_call():
    view = TaskView("t", {}, {}, calls=CALLS)
    run = lambda name, params, scope: STANDARD[name].fn(view, scope, **params)
    assert run("quote_in_call", {"field": "c[]", "category": "knowledge"}, {"c": [{"ref": "c1", "quote": "犹豫期为 十五日"}]}) == []
    assert "没有逐字" in run("quote_in_call", {"field": "c[]"}, {"c": [{"ref": "c1", "quote": "二十日"}]})[0]
    assert "报错" in run("quote_in_call", {"field": "c[]"}, {"c": [{"ref": "c2", "quote": "x"}]})[0]
    assert "此前回复" in run("searched", {"field": "s[]", "category": "knowledge"}, {"s": ["c9"]})[0]
    assert run("searched", {"field": "s[]", "category": "knowledge"}, {"s": []})[0].startswith("s[] 至少")
    assert run("from_call", {"field": "b", "tool": "judge_blocking"}, {"b": "c3"}) == []
    assert "不是 subloop 类" in run("from_call", {"field": "b", "tool": "judge_blocking"}, {"b": "c1"})[0]


def test_unusable_ref_lists_exactly_the_call_ids_that_pass_the_same_check():
    """引不了时列出的编号，正是这同一个检查会放行的那些：照着填一定能过，不依赖编号长什么样。"""
    view = TaskView("t", {}, {}, calls=CALLS)
    run = lambda name, params, scope: STANDARD[name].fn(view, scope, **params)
    nested = run("quote_in_call", {"field": "c[]", "category": "subloop"}, {"c": [{"ref": "judge_blocking#3.c0", "quote": "x"}]})
    assert nested[0].endswith("现在可引的 call_id 是 ['c3']")
    assert run("from_call", {"field": "b", "tool": "judge_blocking"}, {"b": "c1"})[0].endswith("['c3']")
    assert run("searched", {"field": "s[]", "category": "knowledge"}, {"s": ["c2"]})[0].endswith("['c1']")


def test_covers_and_refs_in_against_materials():
    view = TaskView("t", {}, {"result.e": {"ids": ["E1", "E2"]}})
    scope = {"got": ["E1", "E1", "E3"]}
    problems = STANDARD["covers"].fn(view, scope, field="got[]", of="result.e.ids[]")
    assert any("重复" in p for p in problems) and any("漏了" in p for p in problems) and any("多了" in p for p in problems)
    assert STANDARD["refs_in"].fn(view, {"got": ["E1"]}, field="got[]", of="result.e.ids[]") == []


def test_once_submission_schema_then_checks_then_accept():
    work = make_work(output=obj(verdict={"type": "string", "enum": ["ok", "bad"]}, reason=TEXT))
    state = acceptance.Submissions()
    bad = acceptance.submit(work, state, {"verdict": "meh", "reason": "r"}, None, view_for())
    assert not bad.accepted and "verdict" in bad.reasons[0]
    good = acceptance.submit(work, state, {"verdict": "ok", "reason": "r"}, None, view_for())
    assert good.accepted and state.result == {"verdict": "ok", "reason": "r"}
    assert not acceptance.submit(work, state, {"verdict": "ok", "reason": "r"}, "x", view_for()).accepted


def test_per_item_items_are_checked_one_by_one_and_final_carries_them():
    work = make_work(submit="per_item", items_field="items",
                     checks=[{"quote_in_call": {"field": "cites[]", "category": "knowledge", "on": "item"}},
                             {"searched": {"field": "searched[]", "category": "knowledge", "on": "item"}}])
    state = acceptance.Submissions()
    rejected = acceptance.submit(work, state, {"cites": [{"ref": "c1", "quote": "三十日"}], "searched": ["c1"]}, "i1", view_for())
    assert not rejected.accepted and "没有逐字" in rejected.reasons[0]
    assert acceptance.submit(work, state, {"cites": [{"ref": "c1", "quote": "十五日"}], "searched": ["c1"]}, "i1", view_for()).accepted
    final = acceptance.submit(work, state, {"verdict": "ok", "reason": "r"}, None, view_for())
    assert final.accepted and final.result["items"][0]["item_id"] == "i1"


def test_custom_check_and_synthesis_fill_program_fields():
    output = obj(verdict={"type": "string", "enum": ["ok", "bad"], "x-fill": "program"}, reason=TEXT, n={"type": "integer"})
    work = make_work(output=output)
    work = type(work)(**{**work.__dict__, "code": Code(
        check=lambda v: [] if v.own["n"] >= 0 else ["n 不能为负"],
        synthesize=lambda v: {"verdict": "ok" if v.own["n"] else "bad"})})
    state = acceptance.Submissions()
    assert acceptance.submit(work, state, {"reason": "r", "n": -1}, None, view_for()).reasons == ("n 不能为负",)
    assert acceptance.submit(work, state, {"reason": "r", "n": 2}, None, view_for()).result["verdict"] == "ok"
    broken = type(work)(**{**work.__dict__, "code": Code(synthesize=lambda v: {"verdict": "maybe"})})
    with pytest.raises(acceptance.SynthesisError):
        acceptance.submit(broken, acceptance.Submissions(), {"reason": "r", "n": 1}, None, view_for())


def explaining_work():
    output = obj(verdict={"type": "string", "enum": ["ok", "bad"], "x-fill": "program", "x-explain": True}, reason=TEXT,
                 n={"type": "integer"},
                 rows={"type": "array", "x-fill": "program", "x-explain": ["id", "status"],
                       "items": obj(id=TEXT, status=TEXT, note=TEXT)})
    work = make_work(output=output)
    return type(work)(**{**work.__dict__, "code": Code(synthesize=lambda v: {
        "verdict": "ok" if v.own["n"] else "bad",
        "rows": [{"id": "E1", "status": "ok" if v.own["n"] else "bad", "note": v.own["reason"]}]})})


def test_explained_conclusion_is_shown_once_before_it_is_accepted():
    work, state = explaining_work(), acceptance.Submissions()
    first = acceptance.submit(work, state, {"reason": "r", "n": 0}, None, view_for())
    assert not first.accepted and first.explain == {"verdict": "bad", "rows": [{"id": "E1", "status": "bad"}]}
    assert state.result is None
    # 只改 reason：程序结论不变（note 不在 x-explain 的键里），收下
    second = acceptance.submit(work, state, {"reason": "因为 n=0", "n": 0}, None, view_for())
    assert second.accepted and second.result["rows"][0]["note"] == "因为 n=0"


def test_changed_conclusion_is_shown_again_and_reset_clears_what_was_shown():
    work, state = explaining_work(), acceptance.Submissions()
    acceptance.submit(work, state, {"reason": "r", "n": 0}, None, view_for())
    again = acceptance.submit(work, state, {"reason": "r", "n": 1}, None, view_for())
    assert not again.accepted and again.explain["verdict"] == "ok"
    assert acceptance.submit(work, state, {"reason": "r2", "n": 1}, None, view_for()).accepted
    state.reset()
    assert acceptance.submit(work, state, {"reason": "r2", "n": 1}, None, view_for()).explain is not None


def test_explain_text_shows_the_conclusion_and_asks_for_reason():
    text = acceptance.explain_text("fulfillment", {"verdict": "bad"})
    assert "先不收" in text and '"verdict": "bad"' in text and "挑战" in text


@pytest.mark.parametrize("prop, needle", [
    ({"type": "string", "x-explain": True}, "只能标在程序填的字段上"),
    ({"type": "string", "x-fill": "program", "x-explain": "yes"}, "写 true 或非空的键名列表"),
])
def test_x_explain_load_errors(prop, needle):
    defs = parse(store(a1={"output": obj(verdict={"type": "string", "x-fill": "program"}, reason=TEXT, x=prop)}))
    defs = type(defs)(**{**defs.__dict__, "axes": {**defs.axes, "a1": type(defs.axes["a1"])(
        **{**defs.axes["a1"].__dict__, "code": Code(synthesize=lambda v: {})})}})
    assert any(needle in e for e in check_definitions(defs, registry()))


def test_custom_code_is_deterministic_on_same_view():
    view = TaskView("t", {"n": 1}, {})
    check = lambda v: [f"n={v.own['n']}"]
    assert check(view) == check(view)


# ---- 元素筛选、分发、运行方式 -------------------------------------------------------------

REQ = {"sources": [{"id": "t1.user", "turn": "t1"}, {"id": "t2.user", "turn": "t2"}, {"id": "scenario.criterion", "turn": "case"}]}


def test_element_filter_selects_by_field_values_even_with_dots_in_values():
    path = paths.parse("sources[id=t1.user,scenario.criterion].turn")
    assert paths.values(REQ, path) == ["t1", "case"]
    assert paths.extract(REQ, paths.parse("sources[turn=t2]")) == [{"id": "t2.user", "turn": "t2"}]
    pruned = paths.prune(REQ, paths.parse("sources[turn=t1,case]"))
    assert [x["id"] for x in pruned["sources"]] == ["t1.user", "scenario.criterion"]
    schema = obj(sources={"type": "array", "items": obj(id=TEXT, turn=TEXT)})
    assert paths.check_schema(schema, paths.parse("sources[id=a]")) is None
    assert "筛选字段" in paths.check_schema(schema, paths.parse("sources[nope=a]"))
    with pytest.raises(ValueError):
        paths.parse("sources[id=]")


def test_material_table_code_view_keeps_structure_and_applies_filter():
    reg = Registry([Material("case.requirements", obj(sources={"type": "array", "items": obj(id=TEXT, turn=TEXT)}), "需求", lambda c, ctx: REQ)])
    table = MaterialTable(reg, {})
    entries = [parse_entry("case.requirements.sources[turn=t2]")]
    assert table.view(entries) == {"case.requirements.sources[turn=t2]": [{"id": "t2.user", "turn": "t2"}]}
    assert table.for_code(entries) == {"case.requirements": {"sources": [{"id": "t2.user", "turn": "t2"}]}}


def test_dispatched_loop_needs_synth_on_every_member():
    raw = store(a1={"loop": "split", "output": obj(verdict=TEXT, reason=TEXT)})
    raw["loops"]["split"] = {"start": "ready"}
    defs = parse(raw)
    loops = dict(defs.loops)
    loops["split"] = type(loops["split"])(**{**loops["split"].__dict__, "dispatch": lambda v: []})
    errors = check_definitions(type(defs)(axes=defs.axes, loops=loops), registry())
    assert any("必须有 synth.py" in e for e in errors)


def test_loop_store_shape_errors():
    with pytest.raises(ValueError, match="恰好一个"):
        parse({"axes": {}, "loops": {"a": {"start": "ready"}}})
    with pytest.raises(ValueError, match="start"):
        parse({"axes": {}, "loops": {"main": {"start": "case"}, "x": {"start": "bogus"}}})


def test_waits_that_loop_back_are_rejected_including_ones_forced_by_loop_doors():
    out = obj(verdict=TEXT, reason=TEXT)
    # 任务自己的依赖绕回自己
    errors = check_definitions(parse(store(a1={"depends": [{"axis": "a2", "hard": True}], "output": out},
                                           a2={"depends": [{"axis": "a1", "hard": True}], "output": out})), registry())
    assert any("依赖会卡死" in e for e in errors), errors
    # 只看任务依赖没有圈，但 A 房间等 X、B 房间等 Z，房间里的活被迫跟着等：a → Z → Y → X → a
    raw = store(a={"loop": "A", "output": out}, a2={"loop": "A", "depends": [{"axis": "X", "hard": True}], "output": out},
                X={"depends": [{"axis": "Y", "hard": True}], "output": out},
                Y={"loop": "B", "output": out}, y2={"loop": "B", "depends": [{"axis": "Z", "hard": True}], "output": out},
                Z={"depends": [{"axis": "a", "hard": True}], "output": out})
    raw["loops"].update({"A": {"start": "ready"}, "B": {"start": "ready"}})
    errors = check_definitions(parse(raw), registry())
    assert any("依赖会卡死" in e and all(k in e for k in ("a（A）", "X（main）", "Y（B）", "Z（main）")) for e in errors), errors
    # case → ready → case 的来回（说法抽取 → 核事实 → 兑现）是一条直线，不报
    raw = store(c={"output": out}, t={"loop": "T", "depends": [{"axis": "c", "hard": True}], "output": out},
                f={"depends": [{"axis": "t", "hard": False}], "output": out})
    raw["loops"]["T"] = {"start": "ready"}
    assert not any("卡死" in e for e in check_definitions(parse(raw), registry()))


def test_quotes_match_across_json_escaping_layers():
    from impl.core.axis_loop.text import quote_in_value
    inner = json.dumps({"subject_id": "P1", "typed_value": "平安e生保"}, ensure_ascii=False)
    seen = {"text": json.dumps({"rows": [inner]}, ensure_ascii=False)}          # JSON 里套 JSON 字符串
    assert quote_in_value('"subject_id": "P1", "typed_value": "平安e生保"', seen)
    assert quote_in_value('subject_id\\":\\"P1', seen)
    assert not quote_in_value('"subject_id": "P2"', seen)                       # 改字仍判不是原文


def test_escaped_newlines_count_as_whitespace():
    from impl.core.axis_loop.text import quote_in_text
    assert quote_in_text("第一行 第二行", "第一行\\n第二行")
    assert not quote_in_text("第一行 第三行", "第一行\\n第二行")


# ---- 公共资源管理区 ResourceZone + 按需读 Reader（resources.md §11） -----------------------------

def _mount_records(records):
    from impl.core.resources import ResourceTable
    table = ResourceTable()
    for r in records:
        table.mount(f"trace://{r['id']}", "record_set", r, name=r["id"], title=r.get("name"))
    return table


def test_resources_entry_schema_is_validated_at_load_time():
    reg = Registry([
        Material("case.trace", obj(uris={"type": "array", "items": TEXT}, count={"type": "integer"}),
                 "案卷", lambda c, ctx: {"uris": [], "count": 0}),
    ])
    good = parse({"axes": {"a": {"resources": ["case.trace.uris[]"], "output": obj(verdict=TEXT, reason=TEXT)}},
                  "loops": {"main": {"start": "case"}}})
    assert check_definitions(good, reg) == []
    bad = parse({"axes": {"a": {"resources": ["case.trace.count"], "output": obj(verdict=TEXT, reason=TEXT)}},
                 "loops": {"main": {"start": "case"}}})
    errs = check_definitions(bad, reg)
    assert errs and "array[string]" in errs[0]


def test_summarize_keeps_small_materials_and_previews_oversize_plain_materials():
    from impl.core.axis_loop.reader import summarize
    assert summarize("t", {"a": 1}, 100) == {"a": 1}
    over = summarize("t", "z" * 5000, 100)
    assert "preview" in over and "offset" in over["说明"]


def test_resource_zone_deduplicates_push_unlocks_deltas_and_blocks_unopened_fields():
    from impl.core.axis_loop.reader import Reader
    from impl.core.axis_loop.zone import ResourceZone

    table = _mount_records([
        {"id": "r1", "turn": "turn1", "kind": "tool_calls", "name": "search",
         "fields": {"input": {"status": "available", "value": "查 P123"},
                    "output": {"status": "available", "value": "机密输出 P999"}}},
        {"id": "r2", "turn": "turn1", "kind": "model_calls", "name": "llm",
         "fields": {"output": {"status": "available", "value": "最终回复" * 200}}},
    ])
    zone = ResourceZone(table, inline_chars=100)  # 强制走目录模式以测按需读取与门禁
    reader = Reader(lambda: {}, zone)

    # 第 1 波：只开放 r1 的 input 字段 → output 字段读不到也搜不到
    note1 = zone.push(["trace://r1/fields/input"])
    assert "【resources】" in note1 and "catalog" in note1 and "P999" not in note1
    assert zone.push(["trace://r1/fields/input"]) == ""  # 完全相同，静默不重推
    got_r1 = reader.read("resources", ids=["r1"])["records"][0]["content"]
    assert got_r1["fields"] == {"input": {"status": "available", "value": "查 P123"}}
    assert "不在当前已开放范围" in reader.read("resources", ids=["r1/fields/output"])["records"][0]["error"]
    assert reader.search("resources", "P999")["hits"] == []
    assert [h["id"] for h in reader.search("resources", "P123")["hits"]] == ["r1"]

    # 同一开放状态下重复点名读 r1 → 短提示见上文，不重吐正文
    again = reader.read("resources", ids=["r1"])["records"][0]
    assert "already_shown" in again and "content" not in again

    # 第 2 波：开放整条 r1 与 r2 → 顶层只推新增差量，且此时再读 r1 可拿到新开放的 output 字段
    note2 = zone.push(["trace://r1", "trace://r2"])
    assert "【resources（本轮新增开放）】" in note2
    got_r1_full = reader.read("resources", ids=["r1"])["records"][0]["content"]
    assert "output" in got_r1_full["fields"] and got_r1_full["fields"]["output"]["value"] == "机密输出 P999"


def test_reader_structural_preview_2k_and_offset_pagination_never_infinite_loops():
    """结构超限时给 2k 预览 + path 下钻；单段纯文本超限时给满单次上限并支持 offset 翻页续读，绝不死循环。"""
    from impl.core.axis_loop.reader import Reader
    from impl.core.axis_loop.zone import ResourceZone

    huge_leaf = "".join(f"[{i:04d}]" for i in range(3000))  # 18,000 字单段纯文本
    table = _mount_records([
        {"id": "r_struct", "fields": {
            "short": {"status": "available", "value": "保留短字段"},
            "doc": {"status": "available", "value": huge_leaf},
        }},
    ])
    zone = ResourceZone(table, inline_chars=100)
    zone.push(["trace://r_struct"])
    reader = Reader(lambda: {}, zone, read_limit=6_000, stub_chars=2_000)

    # 1) 读整条结构化记录（18k > 6k）：短字段保留全文，长字段给 2,000 字预览 + 明确 path（无 full=true）
    top = reader.read("resources", ids=["r_struct"])["records"][0]
    assert top["content"]["fields"]["short"]["value"] == "保留短字段"
    stub = top["content"]["fields"]["doc"]["value"]
    assert stub.startswith("〔预览，全文 18000 字；读全文请传 path='fields/doc/value'〕")
    assert "full=true" not in stub and len(stub) > 2_000

    # 2) 按 path 下钻到 18,000 字单段纯文本（仍 > 6k）：直接返回 0..6000 + offset=6000 提示，绝不退回 2k 死循环！
    page1 = reader.read("resources", ids=["r_struct"], path="fields/doc/value")["records"][0]
    assert page1["content"] == huge_leaf[:6_000] and "offset=6000" in page1["hint"]
    page2 = reader.read("resources", ids=["r_struct"], path="fields/doc/value", offset=6_000)["records"][0]
    assert page2["content"] == huge_leaf[6_000:12_000] and "offset=12000" in page2["hint"]
    page3 = reader.read("resources", ids=["r_struct"], path="fields/doc/value", offset=12_000)["records"][0]
    assert page3["content"] == huge_leaf[12_000:18_000] and "已到末尾" in page3["hint"]


def test_reader_goes_into_json_text_and_folds_2k_repeats_without_cross_record_citation_trap():
    from impl.core.axis_loop.reader import Reader
    from impl.core.axis_loop.zone import ResourceZone

    sys_prompt = "系统提示词规则" * 400  # 2,800 字（>= 2,000 字，触发跨记录折叠）
    short_ans = "保单等待期为 30 天" * 20   # 220 字（< 2,000 字，普通输出不折叠）
    table = _mount_records([
        {"id": "call1", "fields": {
            "exact_request": {"status": "available", "value": [sys_prompt, "第一问"]},
            "output": {"status": "available", "value": json.dumps({"docs": [{"body": short_ans}]}, ensure_ascii=False)},
        }},
        {"id": "call2", "fields": {
            "exact_request": {"status": "available", "value": [sys_prompt, "第二问"]},
            "output": {"status": "available", "value": short_ans},
        }},
    ])
    zone = ResourceZone(table, inline_chars=100)
    zone.push(["trace://call1", "trace://call2"])
    reader = Reader(lambda: {}, zone)

    # JSON 字符串自动解开搜索与下钻
    hit = reader.search("resources", "等待期")["hits"][0]
    assert hit["id"] == "call1" and hit["path"] == "fields/output/value/docs/0/body"
    assert reader.read("resources", ids=["call1"], path=hit["path"])["records"][0]["content"] == short_ans
    wrong = reader.read("resources", ids=["call1"], path="fields/output/value/nope")["records"][0]["error"]
    assert "'nope' 不在这一层" in wrong and "docs" in wrong

    # 跨记录 >=2k 提示词折叠，但短输出完整保留，且提示语明确要求引用填本记录自己的编号
    c1 = reader.read("resources", ids=["call1"])["records"][0]["content"]
    c2 = reader.read("resources", ids=["call2"])["records"][0]["content"]
    assert c1["fields"]["exact_request"]["value"][0] == sys_prompt
    folded = c2["fields"]["exact_request"]["value"][0]
    assert "内容与本会话前文 call1 完全相同" in folded and "ref 仍填本记录自己的编号" in folded
    assert c2["fields"]["output"]["value"] == short_ans


def test_visible_record_level_citation_on_template_scoped_block():
    from impl.core.axis_loop.visible import Visible

    table = _mount_records([
        {"id": "turn1/records/observations/13", "kind": "tool_calls", "name": "policy_detail", "outcome": "error",
         "fields": {
             "arguments": {"status": "available", "value": "policy_no=P260922"},
             "result": {"status": "available", "value": "查询超时 504"},
             "metadata": {"status": "available", "value": "SECRET_UNUSED_SPAN_METADATA"},
         }},
    ])
    vis = Visible(table, [
        "trace://turn1/records/observations/13/fields/arguments",
        "trace://turn1/records/observations/13/fields/result",
    ])
    # 记录级 ref 命中已开放字段或记录头属性：放行
    assert vis.cite("turn1/records/observations/13", "查询超时 504").ok
    assert vis.cite("turn1/records/observations/13", "policy_detail").ok
    # 记录级 ref 命中同块未开放的 metadata 字段：严格报 out_of_scope，且错引 hint 绝不泄露未开放字段
    blocked = vis.cite("turn1/records/observations/13", "SECRET_UNUSED_SPAN_METADATA")
    assert not blocked.ok and blocked.reason == "out_of_scope"
    miss = vis.cite("turn1/records/observations/13", "SECRET_UNUSED_SPAN_META_TYPO")
    assert not miss.ok and miss.reason == "not_found" and "SECRET_UNUSED" not in miss.hint

