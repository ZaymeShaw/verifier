"""AxisLoop 运行（spec/alg/axis_loop.md §5、§6；实施 P4、R1–R3）。

模型用脚本代替：按 stage 分路（case loop、各 ready loop、被调用启动的 loop），每路一串回复。
ready loop 与被调用 loop 的 call_id 前缀运行时才定，脚本里需要引用时由 `fill_refs` 从那一路刚看到的工具返回里取。
"""
from __future__ import annotations

import itertools
import json
from collections import defaultdict, deque

from impl.core.axis_loop.definitions import Code, parse
from impl.core.axis_loop.loop import AxisLoop, Governor, RunState, Settings
from impl.core.axis_loop.materials import Material, MaterialTable, Registry
from impl.core.tool_loop import Call, History, LoopContext, Step
from impl.tools.protocol import VerifiableTool

DELIVERY = "您的保单现金价值为 12345 元。"
T1_TEXT = "这张保单现在退保能拿多少？"
T2_TEXT = "不对，我问的是另一张保单"
EVIDENCE = "保单 P1 现金价值 12345 元"
TEXT = {"type": "string"}
STRS = {"type": "array", "items": TEXT}
CITE = {"type": "array", "items": {"type": "object", "properties": {"ref": TEXT, "quote": TEXT}, "required": ["ref", "quote"]}}
REF = "<上一次工具返回的 call_id>"


def obj(**props):
    return {"type": "object", "properties": props, "required": list(props)}


def prog(schema):
    return {**schema, "x-fill": "program"}


REQUIREMENTS = {"sources": [
    {"id": "t1.user", "turn": "t1", "component": "user", "value": T1_TEXT},
    {"id": "t2.user", "turn": "t2", "component": "user", "value": T2_TEXT},
]}


def registry():
    return Registry([
        Material("case.requirements", obj(sources={"type": "array", "items": obj(id=TEXT, turn=TEXT, component=TEXT, value=TEXT)}),
                 "需求侧材料", lambda case, ctx: REQUIREMENTS),
        Material("case.deliveries", {"type": "array", "items": obj(turn=TEXT, text=TEXT)}, "回答",
                 lambda case, ctx: [{"turn": "t1", "text": DELIVERY}]),
        Material("axis.note", TEXT, "场景对轴的描述", lambda case, ctx: f"（{ctx['axis']} 的场景描述）"),
    ])


def per_turn(view):
    turns = sorted({s["turn"] for s in view.materials["case.requirements"]["sources"]})
    return [{"id": t, "materials": [f"case.requirements.sources[turn={t}]"]} for t in turns]


def merge_turns(view):
    items = [{**e, "expectation_id": f"{p['id']}.{e['expectation_id']}"} for p in view.parts for e in p["result"]["expectations"]]
    return {"verdict": "complete", "reason": "合并", "expectations": items}


def main_synth(view):
    f, c = view.materials["result.fulfillment"], view.materials["result.carry"]
    verdict = "done" if f["verdict"] == "fulfilled" else ("cannot" if c and c["verdict"] == "cannot" else "not_done")
    return {"verdict": verdict, "reason": "合成"}


def definitions(*, synth_main=None, dispatch=per_turn, truth_checks=True):
    v = lambda *values: {"type": "string", "enum": list(values)}
    expectation = obj(expectation_id=TEXT, statement=TEXT)
    store = {"axes": {
        "expectations": {"title": "需求", "loop": "expectations", "role": "analysis", "instruction": "写这一轮的期望",
                         "materials": ["case.requirements"],
                         "output": obj(verdict=prog(v("complete")), reason=TEXT, expectations={"type": "array", "items": expectation})},
        "blocking": {"title": "blocking", "loop": "blocking", "instruction": "判每条期望是不是 blocking",
                     "depends": [{"axis": "expectations", "hard": True}],
                     "materials": ["result.expectations.expectations[].{expectation_id, statement}"],
                     "output": obj(verdict=v("ok"), reason=TEXT, items={"type": "array", "items": obj(expectation_id=TEXT, blocking={"type": "boolean"})}),
                     "checks": [{"covers": {"field": "items[].expectation_id", "of": "result.expectations.expectations[].expectation_id"}}]},
        "claims": {"title": "说法", "instruction": "抽说法", "role": "analysis", "depends": [{"axis": "expectations", "hard": True}],
                   "materials": ["case.deliveries"],
                   "output": obj(verdict=v("some", "none"), reason=TEXT, spans=STRS),
                   "checks": [{"quote_in_material": {"field": "spans[]", "material": "case.deliveries"}}]},
        "truth": {"title": "真实性", "loop": "truth", "instruction": "先调 search 取证再判", "tools": ["search"],
                  "depends": [{"axis": "claims", "hard": True}], "materials": ["result.claims"],
                  "output": obj(verdict=v("verified", "refuted"), reason=TEXT, basis=CITE),
                  "checks": [{"quote_in_call": {"field": "basis[]", "category": "subloop"}}] if truth_checks else []},
        "fulfillment": {"title": "兑现", "instruction": "判给到没有",
                        "depends": [{"axis": "expectations", "hard": True}, {"axis": "blocking", "hard": True},
                                    {"axis": "truth", "hard": False}],
                        "materials": ["case.deliveries", "result.expectations", "result.blocking", "result.truth"],
                        "output": obj(verdict=v("fulfilled", "not_fulfilled"), reason=TEXT)},
        "carry": {"title": "承载性", "instruction": "判做不做得了", "depends": [{"axis": "fulfillment", "hard": True}],
                  "trigger": {"axis": "fulfillment", "verdict_in": ["not_fulfilled"]},
                  "tool_categories": [{"category": "knowledge", "required": False}],
                  "output": obj(verdict=v("cannot", "wrong"), reason=TEXT)},
        "main": {"title": "主轴", "executor": "program", "depends": [{"axis": "fulfillment", "hard": True}, {"axis": "carry", "hard": False}],
                 "materials": ["result.fulfillment", "result.carry"],
                 "output": obj(verdict=prog(v("done", "not_done", "cannot")), reason=prog(TEXT))},
    }, "loops": {
        "main": {"start": "case"}, "expectations": {"start": "ready"}, "blocking": {"start": "ready"}, "truth": {"start": "ready"},
        "search": {"start": "tool", "description": "查知识源", "instruction": "按清单取证", "params": obj(items={**STRS, "description": "待查项"}),
                   "tool_categories": [{"category": "knowledge", "required": True}],
                   "output": obj(found=CITE), "checks": [{"quote_in_call": {"field": "found[]", "category": "knowledge"}}]},
    }}
    defs = parse(store)
    axes = dict(defs.axes)
    axes["expectations"] = type(axes["expectations"])(**{**axes["expectations"].__dict__, "code": Code(synthesize=merge_turns)})
    axes["main"] = type(axes["main"])(**{**axes["main"].__dict__, "code": Code(synthesize=synth_main or main_synth)})
    loops = dict(defs.loops)
    loops["expectations"] = type(loops["expectations"])(**{**loops["expectations"].__dict__, "dispatch": dispatch})
    return type(defs)(axes=axes, loops=loops)


class FakeSources:
    def __init__(self):
        self.tools = [VerifiableTool(tool_id="kb_search", description="查知识源", execute_fn=lambda source, query: {"text": EVIDENCE},
                                     parameters={"type": "object", "properties": {
                                         "source": {"type": "string", "description": "登记"},
                                         "query": {"type": "string", "description": "查询"}}, "required": ["source", "query"]})]

    def route(self, call):
        return ("knowledge", call.args.get("source", "")) if call.tool == "kb_search" else ("", "")

    def instances(self, category):
        return ["kb"] if category == "knowledge" else []

    def describe(self, category, instances):
        return f"{category}: {instances}，用 kb_search(source, query)"


_ids = itertools.count()


def call(_tool, **args):
    return {"id": f"t{next(_ids)}", "type": "function", "function": {"name": _tool, "arguments": json.dumps(args, ensure_ascii=False)}}


def submit(task, payload, item_id=None):
    args = {"task_id": task, "payload": payload}
    if item_id:
        args["item_id"] = item_id
    return call("submit", **args)


def fill_refs(reply, messages):
    """把回复里的占位 REF 换成这一路最近一次工具返回的 call_id。"""
    refs = [json.loads(m["content"]).get("call_id") for m in messages if m.get("role") == "tool"
            and str(m.get("content")).startswith("{") and "call_id" in str(m.get("content"))]
    return json.loads(json.dumps(reply, ensure_ascii=False).replace(REF, refs[-1] if refs else REF))


class Script:
    """按 stage 分路：路名按优先顺序匹配 stage 子串（被调用的 loop > ready loop > case loop）。"""

    def __init__(self, routes, order):
        self.routes = {k: deque(v) for k, v in routes.items()}
        self.order = order
        self.seen = defaultdict(list)

    def complete_step(self, messages, functions, *, trace_id, stage):
        route = next((k for k in self.order if k in stage), "main")
        self.seen[route].append([dict(m) for m in messages])
        reply = self.routes[route].popleft() if self.routes.get(route) else None
        if not reply or isinstance(reply, str):
            return Step({"role": "assistant", "content": reply or "完成"})
        return Step({"role": "assistant", "content": "", "tool_calls": fill_refs(reply, messages)})

    def texts(self, route):
        return [str(m.get("content")) for request in self.seen[route] for m in request]


ORDER = ["search", "truth", "blocking", "expectations[t1]", "expectations[t2]"]
ALL = ("expectations", "blocking", "claims", "truth", "fulfillment", "carry", "main")


def run(script, defs=None, enabled=ALL, **settings):
    loop = AxisLoop(defs or definitions(), list(enabled), MaterialTable(registry(), {}), FakeSources(), script,
                    Settings(llm_calls=settings.get("llm_calls", 60), tool_calls=80, seconds=60,
                             context_limit_tokens=settings.get("context", 200_000)))
    return loop.run("case 头", LoopContext(trace_id="t", stage="axis_loop"))


CLAIMS = {"verdict": "some", "reason": "r", "spans": ["12345 元"]}


def happy_routes(fulfillment="not_fulfilled"):
    return {
        "expectations[t1]": [[submit("expectations", {"reason": "r", "expectations": [{"expectation_id": "E1", "statement": "给出现金价值"}]})]],
        "expectations[t2]": [[submit("expectations", {"reason": "r", "expectations": [{"expectation_id": "E1", "statement": "改问另一张"}]})]],
        "blocking": [[submit("blocking", {"verdict": "ok", "reason": "r", "items": [
            {"expectation_id": "t1.E1", "blocking": True}, {"expectation_id": "t2.E1", "blocking": True}]})]],
        "truth": [[call("search", items=["现金价值 12345 元"])],
                  [submit("truth", {"verdict": "verified", "reason": "原文一致", "basis": [{"ref": REF, "quote": "12345 元"}]})]],
        "search": [[call("kb_search", source="kb", query="现金价值")],
                   [submit("search", {"found": [{"ref": REF, "quote": "现金价值 12345 元"}]})]],
        "main": [[submit("claims", CLAIMS)],
                 [submit("fulfillment", {"verdict": fulfillment, "reason": "r"})],
                 [call("kb_search", source="kb", query="团险")],
                 [submit("carry", {"verdict": "cannot", "reason": "知识源里没有"})],
                 "完成"],
    }


def test_end_to_end_ready_loops_dispatch_and_tool_loop():
    script = Script(happy_routes(), ORDER)
    report = run(script)
    assert report.status == "complete", report.reason
    assert all(state in ("done", "absent") for state in report.states.values()), report.states
    assert [e["expectation_id"] for e in report.results["expectations"]["expectations"]] == ["t1.E1", "t2.E1"]
    assert report.results["truth"]["verdict"] == "verified"
    assert report.results["main"] == {"verdict": "cannot", "reason": "合成"}
    kinds = [(e.kind, e.task_id) for e in report.events]
    assert {("loop_start", "expectations"), ("loop_start", "blocking"), ("loop_start", "truth"),
            ("shared_tool", "search"), ("program", "main")} <= set(kinds)
    assert [l["id"] for l in report.loops] == ["expectations", "blocking", "truth"] and all(l["status"] == "complete" for l in report.loops)
    # 分发：每轮只看到自己那一轮
    assert any(T1_TEXT in t for t in script.texts("expectations[t1]")) and not any(T2_TEXT in t for t in script.texts("expectations[t1]"))
    assert any(T2_TEXT in t for t in script.texts("expectations[t2]")) and not any(T1_TEXT in t for t in script.texts("expectations[t2]"))
    # blocking 看不到交付；取证原文只在真实性 loop 里，case loop 看不到
    assert not any(DELIVERY in t for t in script.texts("blocking"))
    assert any(EVIDENCE in t for t in script.texts("search"))
    assert any("现金价值 12345 元" in t for t in script.texts("truth"))   # 真实性 loop 拿到的是取证结果
    before_carry = [r for r in script.seen["main"] if not any("【任务 carry" in str(m.get("content")) for m in r)]
    assert before_carry and not any(EVIDENCE in str(m.get("content")) or "现金价值 12345 元" in str(m.get("content"))
                                    for r in before_carry for m in r)
    # case loop 里只推了属于它的任务
    pushed = " ".join(script.texts("main"))
    assert "【任务 claims" in pushed and "【任务 fulfillment" in pushed
    assert not any(f"【任务 {k}" in pushed for k in ("expectations", "blocking", "truth"))


def test_ready_loop_failure_fails_the_case():
    routes = happy_routes()
    routes["blocking"] = [[submit("blocking", {"verdict": "ok", "reason": "r", "items": []})]] * 30  # 一直交不过覆盖校验
    report = run(Script(routes, ORDER), llm_calls=20)
    assert report.status == "failed"


def test_dispatch_selection_outside_whitelist_fails_the_case():
    defs = definitions(dispatch=lambda view: [{"id": "t1", "materials": ["case.deliveries"]}])
    report = run(Script(happy_routes(), ORDER), defs=defs)
    assert report.status == "failed" and "不在这个 loop 的材料白名单里" in report.reason


def test_source_tools_in_main_are_gated_until_a_main_task_brings_the_category():
    routes = happy_routes()
    routes["main"] = [[call("kb_search", source="kb", query="x"), submit("claims", CLAIMS)]] + routes["main"][1:]
    report = run(Script(routes, ORDER))
    denied = [m for m in report.messages if m.get("role") == "tool" and "现在不能用" in str(m.get("content"))]
    assert denied and report.status == "complete", report.reason


def test_revising_a_case_axis_reruns_the_downstream_ready_loop():
    routes = happy_routes("fulfilled")
    # 交说法又改说法 → 真实性 loop 刚跑完就因上游修改整个作废、自动重起
    routes["main"] = [[submit("claims", CLAIMS)],
                      [submit("claims", {**CLAIMS, "reason": "改了"})],
                      [submit("fulfillment", {"verdict": "fulfilled", "reason": "r"})], "完成"]
    routes["truth"] = [[submit("truth", {"verdict": "refuted", "reason": "r", "basis": []})]] * 2
    report = run(Script(routes, ORDER), defs=definitions(truth_checks=False))
    assert report.status == "complete", report.reason
    assert [e.task_id for e in report.events if e.kind == "loop_start" and e.task_id == "truth"] == ["truth", "truth"]
    assert ("invalidate", "truth") in [(e.kind, e.task_id) for e in report.events]


def test_synthesis_error_fails_the_case():
    routes = happy_routes("fulfilled")
    routes["main"] = [[submit("claims", CLAIMS)], [submit("fulfillment", {"verdict": "fulfilled", "reason": "r"})], "完成"]
    routes["truth"] = [[submit("truth", {"verdict": "refuted", "reason": "r", "basis": []})]]
    defs = definitions(synth_main=lambda view: {"verdict": "bogus", "reason": "x"}, truth_checks=False)
    report = run(Script(routes, ORDER), defs=defs)
    assert report.status == "failed" and "不合输出 schema" in report.reason


def test_rejection_reasons_are_returned_to_the_model():
    routes = happy_routes("fulfilled")
    routes["main"] = [[submit("claims", {"verdict": "some", "reason": "r", "spans": ["编造的原文"]})], [submit("claims", CLAIMS)],
                      [submit("fulfillment", {"verdict": "fulfilled", "reason": "r"})], "完成"]
    routes["truth"] = [[submit("truth", {"verdict": "refuted", "reason": "r", "basis": []})]]
    report = run(Script(routes, ORDER), defs=definitions(truth_checks=False))
    rejected = [m for m in report.messages if m.get("role") == "tool" and "被拒" in str(m.get("content"))]
    assert rejected and "没有逐字出现" in rejected[0]["content"] and report.status == "complete"


def test_explained_conclusion_goes_back_to_the_model_before_it_is_accepted():
    defs = definitions()
    axes = dict(defs.axes)
    f = axes["fulfillment"]
    output = {**f.output, "properties": {**f.output["properties"],
                                        "verdict": {"type": "string", "enum": ["fulfilled", "not_fulfilled"], "x-fill": "program", "x-explain": True},
                                        "delivered": {"type": "string"}},
              "required": ["verdict", "reason", "delivered"]}
    axes["fulfillment"] = type(f)(**{**f.__dict__, "output": output, "code": Code(
        synthesize=lambda v: {"verdict": "fulfilled" if v.own["delivered"] == "给了" else "not_fulfilled"})})
    routes = happy_routes()
    routes["main"] = [[submit("claims", CLAIMS)],
                      [submit("fulfillment", {"delivered": "给了", "reason": "r"})],
                      [submit("fulfillment", {"delivered": "给了", "reason": "程序算出兑现，因为给了"})], "完成"]
    report = run(Script(routes, ORDER), defs=type(defs)(axes=axes, loops=defs.loops))
    assert report.status == "complete", report.reason
    shown = [m["content"] for m in report.messages if m.get("role") == "tool" and "先不收" in str(m.get("content"))]
    assert len(shown) == 1 and '"verdict": "fulfilled"' in json.loads(shown[0])["reason"]
    assert [e.kind for e in report.events if e.task_id == "fulfillment"] == ["appear", "explain", "accept"]
    assert report.results["fulfillment"]["reason"] == "程序算出兑现，因为给了"


def test_context_still_over_limit_after_archiving_fails_with_reason():
    defs = definitions()
    claims = defs.axes["claims"]
    only = type(defs)(axes={"claims": type(claims)(**{**claims.__dict__, "depends": ()})}, loops=defs.loops)
    report = run(Script({"main": ["停"]}, ORDER), defs=only, enabled=("claims",), context=10)
    assert report.status == "failed" and "上下文超限" in report.reason


def test_governor_archives_old_tool_returns_but_keeps_last_batch():
    big = json.dumps({"text": "x" * 400, "call_id": "c0"})
    history = History(messages=[{"role": "system", "content": "s"},
                                {"role": "tool", "tool_call_id": "a", "content": big},
                                {"role": "tool", "tool_call_id": "b", "content": json.dumps({"text": "y" * 400, "call_id": "c1"})}],
                      calls=[Call(0, "kb_search", {}, 0), Call(1, "kb_search", {}, 1)])
    run_state = RunState(Settings(llm_calls=5, tool_calls=5, seconds=60, context_limit_tokens=400, archive_ratio=0.5))
    assert Governor(run_state)._fit_context(history) == ""
    assert history.messages[1]["content"].startswith("[已归档] call_id=c0")
    assert history.messages[2]["content"].startswith('{"text"')
    assert run_state.archived == 1


def test_governor_archives_same_batch_returns_except_last_when_still_over():
    history = History(messages=[{"role": "system", "content": "s"},
                                {"role": "tool", "tool_call_id": "a", "content": json.dumps({"text": "x" * 400, "call_id": "c0"})},
                                {"role": "tool", "tool_call_id": "b", "content": json.dumps({"text": "y" * 400, "call_id": "c1"})}],
                      calls=[Call(0, "kb_search", {}, 0), Call(1, "kb_search", {}, 0)])
    run_state = RunState(Settings(llm_calls=5, tool_calls=5, seconds=60, context_limit_tokens=400, archive_ratio=0.5))
    assert Governor(run_state)._fit_context(history) == ""
    assert history.messages[1]["content"].startswith("[已归档] call_id=c0")
    assert history.messages[2]["content"].startswith('{"text"')


def test_governor_does_not_mistake_c11_for_recent_c1():
    history = History(messages=[{"role": "tool", "tool_call_id": "a", "content": json.dumps({"text": "x" * 400, "call_id": "c11"})},
                                {"role": "tool", "tool_call_id": "b", "content": json.dumps({"text": "y" * 400, "call_id": "c1"})}],
                      calls=[Call(1, "kb_search", {}, 1), Call(11, "kb_search", {}, 0)])
    run_state = RunState(Settings(llm_calls=5, tool_calls=5, seconds=60, context_limit_tokens=400, archive_ratio=0.5))
    assert Governor(run_state)._fit_context(history) == ""
    assert history.messages[0]["content"].startswith("[已归档] call_id=c11")
    assert history.messages[1]["content"].startswith('{"text"')


def test_governor_single_return_over_limit_still_fails():
    history = History(messages=[{"role": "tool", "tool_call_id": "a", "content": json.dumps({"text": "x" * 4000, "call_id": "c0"})}],
                      calls=[Call(0, "kb_search", {}, 0)])
    run_state = RunState(Settings(llm_calls=5, tool_calls=5, seconds=60, context_limit_tokens=400, archive_ratio=0.5))
    assert "上下文超限" in Governor(run_state)._fit_context(history)


# ---- 大材料：读取范围 = 已出现任务白名单的合集（S2） ------------------------------------------------

STORE = {"catalog": [{"id": "r1", "summary": "一次工具调用"}, {"id": "r2", "summary": "又一次"}],
         "records": [{"id": "r1", "input": {"q": "按 P123 查"}, "output": {"rows": ["返回了 P999 的记录"]}},
                     {"id": "r2", "input": {"q": "按 P456 查"}, "output": {"rows": ["返回了 P888 的记录"]}}]}


def test_big_material_pushes_catalog_and_read_tool_only_sees_whitelisted_fields():
    reg = Registry([Material("case.store", obj(catalog={"type": "array"}, records={"type": "array", "items": obj(
        id=TEXT, input={"type": "object"}, output={"type": "object"})}), "记录库", lambda case, ctx: STORE)])
    v = lambda *values: {"type": "string", "enum": list(values)}
    defs = parse({"axes": {"expect": {"title": "本应", "materials": ["case.store.records[].{id, input}"],
                                      "output": obj(verdict=v("ok"), reason=TEXT)}},
                  "loops": {"main": {"start": "case"}}})
    script = Script({"main": [[call("read_material", **{"name": "case.store.records[].{id, input}", "ids": ["r1"]})],
                              [submit("expect", {"verdict": "ok", "reason": "r"})], "完成"]}, [])
    loop = AxisLoop(defs, ["expect"], MaterialTable(reg, {}), FakeSources(), script,
                    Settings(llm_calls=10, tool_calls=10, seconds=60, material_inline_chars=60))  # 整份超、单条不超
    report = loop.run("case 头", LoopContext(trace_id="t", stage="axis_loop"))
    assert report.status == "complete", report.reason
    pushed = " ".join(script.texts("main"))
    assert "只给目录" in pushed or "只给开头" in pushed
    read_back = [m["content"] for m in report.messages if m.get("role") == "tool" and "按 P123 查" in str(m.get("content"))]
    assert read_back and not any("P999" in str(m.get("content")) for m in report.messages)


# ---- 信息源检查、材料取不到、轴与信息源对不上（S3） ------------------------------------------------

class CheckedSources(FakeSources):
    def __init__(self, broken=""):
        super().__init__()
        self.broken, self.asked = broken, []

    def check(self, instance):
        self.asked.append(instance)
        return f"{instance} 连不上" if instance == self.broken else ""


def test_required_source_check_failure_fails_before_its_loop_starts():
    sources = CheckedSources(broken="kb")  # 真实性选用的 search 必需 knowledge：真实性 loop 起前要查
    loop = AxisLoop(definitions(), list(ALL), MaterialTable(registry(), {}), sources, Script(happy_routes(), ORDER),
                    Settings(llm_calls=60, tool_calls=80, seconds=60))
    report = loop.run("case 头", LoopContext(trace_id="t", stage="axis_loop"))
    assert report.status == "failed" and "kb 连不上" in report.reason
    assert [l for l in report.loops if l["id"] == "truth"][0]["status"] == "failed"
    assert sources.asked == ["kb"]


def test_unavailable_builtin_material_fails_without_any_model_call():
    from impl.core.axis_loop.materials import MaterialUnavailable

    def broken(case, ctx):
        raise MaterialUnavailable("trace 采集失败：等待超时")
    reg = Registry([*[registry().get(n) for n in registry().names() if n != "case.deliveries"],
                    Material("case.deliveries", {"type": "array"}, "回答", broken)])
    script = Script(happy_routes(), ORDER)
    loop = AxisLoop(definitions(), list(ALL), MaterialTable(reg, {}), FakeSources(), script,
                    Settings(llm_calls=60, tool_calls=80, seconds=60))
    report = loop.run("case 头", LoopContext(trace_id="t", stage="axis_loop"))
    assert report.status == "failed" and "trace 采集失败" in report.reason and report.llm_calls == 0
    assert not script.seen


def test_selected_source_category_without_an_axis_using_it_is_a_warning():
    from impl.core.axis_loop.validate import scenario_warnings
    defs = definitions()
    assert scenario_warnings(defs, ["claims"], ["knowledge"]) == ["场景选用了 knowledge 类信息源，但没有启用的轴用它"]
    assert scenario_warnings(defs, ["claims", "truth"], ["knowledge"]) == []   # truth 选用的 search 用 knowledge


def test_stuck_case_fails_at_once_and_says_who_waits_for_whom():
    """加载检查之外的运行时兜底：真卡住了马上失败，不空转到 max_blocked（这里用没开的上游造一个卡住）。"""
    defs = definitions()
    fulfillment = defs.axes["fulfillment"]
    stuck = type(defs)(axes={**defs.axes, "fulfillment": type(fulfillment)(**{**fulfillment.__dict__, "depends": (
        *fulfillment.depends, type(fulfillment.depends[0])("carry", True))})}, loops=defs.loops)
    script = Script(happy_routes(), ORDER)
    loop = AxisLoop(stuck, ["expectations", "blocking", "claims", "truth", "fulfillment", "carry"], MaterialTable(registry(), {}),
                    FakeSources(), script, Settings(llm_calls=60, tool_calls=80, seconds=60))
    report = loop.run("case 头", LoopContext(trace_id="t", stage="axis_loop"))
    assert report.status == "failed" and "依赖卡住" in report.reason and "fulfillment 在等" in report.reason
    assert "max_blocked" not in report.reason


# ---- 分发给先后对：一份只跑列出的任务，[前, 后] 的后一个等前一个交了才出现、出现后前一个锁住；没先后的同时出现（§6.2，10-26） ----

def ordered_defs(dispatch):
    v = lambda *values: {"type": "string", "enum": list(values)}
    task = lambda materials: {"title": "t", "loop": "pair", "instruction": "写", "materials": materials,
                              "output": obj(verdict=prog(v("ok")), reason=TEXT)}
    defs = parse({"axes": {"first": task(["case.deliveries"]), "second": task(["case.requirements"]),
                           "third": task(["case.requirements"])},
                  "loops": {"main": {"start": "case"}, "pair": {"start": "ready"}}})
    merge = Code(synthesize=lambda view: {"verdict": "ok", "reason": "；".join(p["result"]["reason"] for p in view.parts)})
    axes = {k: type(a)(**{**a.__dict__, "code": merge}) for k, a in defs.axes.items()}
    loops = dict(defs.loops)
    loops["pair"] = type(loops["pair"])(**{**loops["pair"].__dict__, "dispatch": dispatch})
    return type(defs)(axes=axes, loops=loops)


def run_ordered(dispatch, routes):
    script = Script(routes, ["pair[g1]", "pair[g2]"])
    loop = AxisLoop(ordered_defs(dispatch), ["first", "second", "third"], MaterialTable(registry(), {}), FakeSources(), script,
                    Settings(llm_calls=20, tool_calls=20, seconds=60))
    return script, loop.run("case 头", LoopContext(trace_id="t", stage="axis_loop"))


def test_ordered_part_releases_the_later_after_the_earlier_and_locks_it():
    groups = lambda view: [{"id": "g1", "tasks": ["first", "second"], "after": [["first", "second"]]}, {"id": "g2", "tasks": ["third"]}]
    script, report = run_ordered(groups, {
        "pair[g1]": [[submit("first", {"reason": "一"})],
                     [submit("first", {"reason": "改"}), submit("second", {"reason": "二"})], "完成"],
        "pair[g2]": [[submit("third", {"reason": "三"})], "完成"]})
    assert report.status == "complete", report.reason
    g1 = script.seen["pair[g1]"]
    assert not any(T1_TEXT in str(m.get("content")) for m in g1[0])          # first 交之前看不到 second 的材料
    assert any(T1_TEXT in str(m.get("content")) for m in g1[1])              # first 交完，second 出现、材料推进来
    assert report.results["first"]["reason"] == "一"                          # 回头改被拒
    assert [e.reasons for e in report.events if e.kind == "reject" and e.task_id == "first"] == [("已锁：后面的任务已出现",)]
    assert not any(DELIVERY in t for t in script.texts("pair[g2]"))           # 另一份是另一个上下文
    assert report.results["third"]["reason"] == "三"


def test_tasks_without_order_in_one_part_appear_together():
    script, report = run_ordered(lambda view: [{"id": "g1", "tasks": ["first", "second", "third"]}], {
        "pair[g1]": [[submit("first", {"reason": "一"}), submit("second", {"reason": "二"}), submit("third", {"reason": "三"})], "完成"]})
    assert report.status == "complete", report.reason
    assert len(script.seen["pair[g1]"]) == 1                                  # 三个同时出现，一次回复交齐就结束
    assert [report.results[k]["reason"] for k in ("first", "second", "third")] == ["一", "二", "三"]


def test_dispatch_order_pairs_must_not_cycle():
    script, report = run_ordered(lambda view: [{"id": "g1", "tasks": ["first", "second", "third"],
                                                "after": [["first", "second"], ["second", "first"]]}], {})
    assert report.status == "failed" and "成环" in report.reason


def test_dispatch_must_put_every_task_in_some_part():
    script, report = run_ordered(lambda view: [{"id": "g1", "tasks": ["first", "second"]}], {})
    assert report.status == "failed" and "没把 ['third'] 分进任何一份" in report.reason


class NoKnowledge(FakeSources):
    def instances(self, category):
        return []


def test_optional_shared_loop_without_its_sources_is_withheld_and_said_so():
    """可选的被调用 loop：它要的必需信息源场景没选 → 不提供，任务文本写明不可用（spec/alg/axis_loop.md §6.3）。"""
    from impl.core.axis_loop.loop import _task_text
    from impl.core.axis_loop.validate import check_scenario
    defs = definitions()
    truth = defs.axes["truth"]
    axes = {**defs.axes, "truth": type(truth)(**{**truth.__dict__, "optional_tools": ("search",)})}
    defs = type(defs)(axes=axes, loops=defs.loops)
    assert check_scenario(defs, list(ALL), []) == []
    assert check_scenario(definitions(), list(ALL), []) == ["truth（search）必需 knowledge 类信息源，场景一个都没选"]
    loop = AxisLoop(defs, list(ALL), MaterialTable(registry(), {}), NoKnowledge(), Script({}, []),
                    Settings(llm_calls=10, tool_calls=10, seconds=10, context_limit_tokens=200_000))
    assert loop.withheld == {"search": ["knowledge"]} and "search" not in loop.shared_impl
    text = _task_text(loop, axes["truth"], "truth", axes["truth"].materials, "【任务 truth】", ("search",), ["truth"])
    assert "工具 search：本场景不可用（场景没选 knowledge 类信息源）" in text
    from impl.core.axis_loop.loop import _LoopGate
    gate = _LoopGate(loop, "truth", {"truth": axes["truth"]}, None, "truth")
    assert "search" not in gate.shared and "search" not in {t.tool_id for t in gate.tool_loop("truth", []).tools}
