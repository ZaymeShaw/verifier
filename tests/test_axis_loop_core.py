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


# ---- 大材料：目录 + 按需读（spec §4.4，S2） -----------------------------------------------------

STORE_VALUE = {"catalog": [{"id": "r1", "summary": "工具调用"}, {"id": "r2", "summary": "模型输出"}],
               "records": [{"id": "r1", "input": {"q": "P123"}, "output": {"rows": ["x" * 50]}},
                           {"id": "r2", "input": {"prompt": "短"}, "output": {"text": "y" * 20000}}]}


def test_summarize_keeps_small_values_and_gives_catalog_for_big_stores():
    from impl.core.axis_loop.reader import summarize
    assert summarize("t", {"a": 1}, 100) == {"a": 1}
    out = summarize("t", STORE_VALUE, 500)
    assert out["catalog"] == STORE_VALUE["catalog"] and out["records"] == 2 and "y" * 100 not in json.dumps(out)
    assert "preview" in summarize("t", "z" * 5000, 100)
    # 记录库旁的字段照推，单个太大的只给开头与读法
    side = summarize("t", {**STORE_VALUE, "links": [{"link_id": "L1"}], "notes": "n" * 3000}, 2000)
    assert side["links"] == [{"link_id": "L1"}] and "path='notes'" in side["notes"]["说明"] and side["records"] == 2


def test_reader_reads_by_id_previews_long_text_in_big_records_and_drills_by_path():
    from impl.core.axis_loop.reader import Reader
    reader = Reader(lambda: {"case.store": STORE_VALUE}, 8_000)
    got = reader.read("case.store", ids=["r1", "r9"])
    assert got["records"][0]["content"]["input"] == {"q": "P123"} and got["records"][1]["error"] == "没有这个编号"
    big = reader.read("case.store", ids=["r2"])["records"][0]
    assert big["content"]["input"] == {"prompt": "短"} and big["content"]["output"]["text"].startswith("〔预览，全文 20000 字")
    assert reader.read("case.store", ids=["r2"], path="input")["records"][0]["content"] == {"prompt": "短"}
    assert reader.read("case.other", ids=["r1"])["isError"]


def test_reader_search_returns_ids_and_snippets_only():
    from impl.core.axis_loop.reader import Reader
    hits = Reader(lambda: {"case.store": STORE_VALUE}, 8_000).search("case.store", "P123")
    assert [h["id"] for h in hits["hits"]] == ["r1"] and "不算读过" in hits["hint"]
    assert hits["hits"][0]["path"] == "input/q" and hits["hits"][0]["snippet"] == "P123"


def test_reader_goes_into_json_text_and_says_what_a_layer_has():
    """工具返回常是 JSON 文本：按字段搜、按位置下钻都先解开；走不通时报出这一层有什么。"""
    from impl.core.axis_loop.reader import Reader
    store = {"records": [{"id": "r1", "output": json.dumps({"documents": [{"title": "e生保条款", "body": "等待期 30 天"}]}, ensure_ascii=False)}]}
    reader = Reader(lambda: {"case.store": store}, 8_000)
    hit = reader.search("case.store", "等待期")["hits"][0]
    assert hit == {"id": "r1", "path": "output/documents/0/body", "snippet": "等待期 30 天"}
    assert reader.read("case.store", ids=["r1"], path=hit["path"])["records"][0]["content"] == "等待期 30 天"
    wrong = reader.read("case.store", ids=["r1"], path="output/docs")["records"][0]["error"]
    assert "'docs' 不在这一层" in wrong and "documents" in wrong


def test_reader_gives_a_long_passage_once_per_loop():
    """被测系统每次调模型都带着累积对话：别的记录里已给过的长段只给指向，重读同一条照常全文。"""
    from impl.core.axis_loop.reader import Reader
    prompt = "系统提示词" * 100
    store = {"records": [{"id": "call1", "messages": [prompt, "问一"]}, {"id": "call2", "messages": [prompt, "问二"]}]}
    reader = Reader(lambda: {"case.calls": store}, 20_000)
    first = reader.read("case.calls", ids=["call1"])["records"][0]["content"]
    second = reader.read("case.calls", ids=["call2"])["records"][0]["content"]
    assert first["messages"][0] == prompt and second["messages"][0].startswith("〔同 case.calls 的 call1")
    assert reader.read("case.calls", ids=["call1"])["records"][0]["content"]["messages"][0] == prompt
    tiny = Reader(lambda: {"case.calls": store}, 100)
    assert "shape" in tiny.read("case.calls", ids=["call1"])["records"][0] and not tiny.given


def test_reader_previews_long_parts_and_gives_the_rest_in_full():
    """超限时长段只给预览（带读全文的 path），小的部分照给全文；按 path + full 能读到全文。"""
    from impl.core.axis_loop.reader import Reader
    big = "工具返回" * 3000
    store = {"records": [{"id": "call", "messages": ["系统提示", "用户问题", big, "模型回答"]}]}
    reader = Reader(lambda: {"case.calls": store}, 2_000)
    got = reader.read("case.calls", ids=["call"])["records"][0]
    msgs = got["content"]["messages"]
    assert msgs[0] == "系统提示" and msgs[3] == "模型回答"
    assert msgs[2].startswith("〔预览，全文 12000 字；读全文：path='messages/2', full=true〕") and big not in msgs[2]
    assert big not in reader.given
    full = reader.read("case.calls", ids=["call"], path="messages/2", full=True)["records"][0]
    assert full["content"] == big
