"""llm_probe_loop 过程六轴（spec/alg/axis_loop.md §12.2，实施 S5）：真实 trace 存档 + 脚本模型。

样本：tests/fixtures/loop_trace_case.json（verify-insurance-agno 的 neg-unknown 一轮，10-19 存档）。
需求轴换成程序任务给一份固定期望，只验过程那一段：侦探 → 6 个本应（process_expected，按分组分发）→ 6 个实际（process）。
"""
from __future__ import annotations

import itertools
import json
from collections import defaultdict, deque
from dataclasses import replace
from pathlib import Path

from impl.core.axis_loop.definitions import EXECUTOR_PROGRAM, Code
from impl.core.axis_loop.loop import AxisLoop, Settings
from impl.core.axis_loop.materials import MaterialTable
from impl.core.axis_loop.text import quote_in_text
from impl.core.tool_loop import LoopContext, Step
from impl.projects.llm_probe_loop.eval_axes.materials import Case, registry
from impl.projects.llm_probe_loop.eval_axes.registry import definitions
from impl.projects.llm_probe_loop.process_axes import PROCESS_AXES
from impl.server.service import normalize_run_trace

FIXTURE = Path(__file__).parent / "fixtures" / "loop_trace_case.json"
E = [{"expectation_id": "t1.E1", "turn": "t1", "about": "保单 P260922000099999", "statement": "告知这张保单的被保人",
      "condition": "总是", "ambiguity_group": "", "source_refs": ["t1.user"], "needs": [["knowledge"], ["trace"]]}]
_ids = itertools.count()


def call(_tool, **args):
    return {"id": f"x{next(_ids)}", "type": "function", "function": {"name": _tool, "arguments": json.dumps(args, ensure_ascii=False)}}


def submit(task, payload):
    return call("submit", task_id=task, payload=payload)


class Script:
    """按 loop 分路：stage 是 axis_loop/<loop id>:…，取 loop id。"""

    def __init__(self, routes):
        self.routes = {k: v if callable(v) else deque(v) for k, v in routes.items()}
        self.seen = defaultdict(list)
        self.replies = defaultdict(list)

    def complete_step(self, messages, functions, *, trace_id, stage):
        parts = stage.split(":")[0].split("/")
        route = parts[1] if len(parts) > 1 else "main"
        self.seen[route].append([dict(m) for m in messages])
        if route.startswith("process_expected[") and "process_expected" in self.routes:
            reply = self.routes["process_expected"](messages)   # 分组是每个 case 现算的：交刚推进来的那个本应
        else:
            reply = self.routes.get(route) and self.routes[route].popleft()
            reply = reply() if callable(reply) else reply   # 现算的回复（如要引侦探给出的记录原文）
        self.replies[route].append(reply or [])
        if not reply:
            return Step({"role": "assistant", "content": "完成"})
        return Step({"role": "assistant", "content": "", "tool_calls": reply})

    def text(self, route):
        return "\n".join(str(m.get("content")) for request in self.seen[route] for m in request)


def run(routes):
    defs = definitions()
    fixed = lambda view: {"verdict": "complete", "reason": "固定期望", "expectations": E, "sources": [], "missing": []}
    axes = dict(defs.axes)
    axes["expectations"] = replace(axes["expectations"], executor=EXECUTOR_PROGRAM, loop="main", code=Code(synthesize=fixed))
    defs = type(defs)(axes=axes, loops=defs.loops)
    enabled = ["expectations", "trace_analysis", *(f"{a}_expected" for a in PROCESS_AXES), *PROCESS_AXES]
    trace = normalize_run_trace(json.loads(FIXTURE.read_text()))
    table = MaterialTable(registry(), Case(trace, "s", {}, {}))
    script = Script(routes)
    CURRENT["table"] = table
    loop = AxisLoop(defs, enabled, table, _NoSources(), script,
                    Settings(llm_calls=60, tool_calls=80, seconds=120, material_inline_chars=10 ** 7))
    return loop.run("case 头", LoopContext(trace_id="t", stage="axis_loop")), script, table


class _NoSources:
    tools = []

    def route(self, call):
        return ("", "")

    def instances(self, category):
        return []

    def describe(self, category, instances):
        return ""


def expected(axis):
    return {"expected": [{"id": "E1", "about": "保单", "subcapability": "其他", "statement": "按 P260922000099999 处理",
                          "basis": "需求 t1.E1", "expectations": ["t1.E1"], "needs_external": "否", "turn": "t1"}],
            "not_covered": []}


ACTUAL = {"actual": [{"id": "E1", "links": [], "observed": "看过两端", "quotes": [], "verdict": "达到"}],
          "unexpected": [], "problems": [], "reason": "没发现问题", "scope_note": "无"}
CURRENT: dict = {}


def actual(axis):
    """达到也要引原文：从侦探给这个轴的记录里摘一段（运行到实际阶段时才有）。"""
    from impl.projects.llm_probe_loop.process_axes import record_texts
    view = next(v for v in CURRENT["table"].results["trace_analysis"]["views"] if v["axis"] == axis)
    found = next(((ref, t) for ref, texts in record_texts(view["full"]).items() for t in texts if len(t) >= 4), None)
    if not found:   # 侦探没给这个轴任何记录：看不到就引不出，只能无法核
        return {**ACTUAL, "actual": [{**ACTUAL["actual"][0], "verdict": "无法核"}]}
    return {**ACTUAL, "actual": [{**ACTUAL["actual"][0], "quotes": [{"ref": found[0], "quote": found[1][:30]}]}]}


def pushed_expected(messages, payload=expected):
    """本应分组的一份：交最近推进来、还没交过的那个本应任务。"""
    text = "\n".join(str(m.get("content")) for m in messages)
    accepted = {json.loads(c["function"]["arguments"])["task_id"] for m, nxt in zip(messages, messages[1:])
                for c in m.get("tool_calls") or [] if "被拒" not in str(nxt.get("content"))}
    for axis in reversed(PROCESS_AXES):
        task = f"{axis}_expected"
        if f"【任务 {task}" in text and task not in accepted:
            return [submit(task, payload(axis))]
    return None


def routes():
    return {"trace_analysis": [[submit("trace_analysis", {"existing_link_suspects": [], "new_link_suspects": []})]],
            "process_expected": pushed_expected,
            # 第一次交收到程序算出的轴级结论（说明回合），看过后原样再交
            "process": [lambda: [submit(a, actual(a)) for a in PROCESS_AXES]] * 2}


def before_submit(script, task):
    """这个本应任务交上去之前（含交的那一次）模型收到的全部请求。"""
    for route, replies in script.replies.items():
        for i, reply in enumerate(replies):
            if any(json.loads(c["function"]["arguments"]).get("task_id") == task for c in reply):
                return "\n".join(str(m.get("content")) for request in script.seen[route][: i + 1] for m in request)
    raise AssertionError(f"{task} 没交")


def _output_only_texts(table, axis):
    """这个轴 full 里有、input 里没有的字段正文（够长、能认出来的那些）。"""
    out = set()
    view = next(v for v in table.results["trace_analysis"]["views"] if v["axis"] == axis)
    seen_input = {(r["id"], f) for r in view["input"]["records"] for f in r["fields"]}
    for r in view["full"]["records"]:
        for name, info in r["fields"].items():
            value = info.get("value") if isinstance(info, dict) else None
            if (r["id"], name) not in seen_input and isinstance(value, str) and len(value) >= 30:
                out.add(value[:60])
    return out


def test_process_axes_run_and_expected_loop_never_sees_output_side():
    report, script, table = run(routes())
    assert report.status == "complete", report.reason
    assert [l["id"] for l in report.loops] == ["trace_analysis", "process_expected", "process"]
    groups = sorted({r for r in script.seen if r.startswith("process_expected[")})
    assert 1 <= len(groups) < len(PROCESS_AXES)
    # 样本这一轮没调大模型、程序环节表也没列出后端调用（脚本侦探不补环节），这两个轴拿不到记录：引不出原文，只能无法核
    blind = {"tool_execution", "model_capability"}
    assert {a: report.results[a]["verdict"] for a in PROCESS_AXES} == {a: "not_evaluable" if a in blind else "sound" for a in PROCESS_AXES}
    # 比对忽略空白与转义（推送是 JSON 序列化的，原文里的换行、引号在上下文里是转义写法）
    checked = 0
    for axis in PROCESS_AXES:
        outputs = _output_only_texts(table, axis)
        leaked = [t for t in outputs if quote_in_text(t, before_submit(script, f"{axis}_expected"))]
        assert not leaked, (axis, leaked[:3])
        if outputs:
            checked += 1
            assert any(quote_in_text(t, script.text("process")) for t in outputs)   # 实际阶段看得到
    assert checked >= 3, "样本里应当有几个轴有输出端正文"


def test_not_met_without_quote_is_rejected_and_rows_must_match_expected():
    bad = {**ACTUAL, "actual": [{**ACTUAL["actual"][0], "verdict": "没达到"}],
           "problems": [{"phenomenon": "x", "items": ["E1"], "attribution": "本轴", "impact": "y"}]}
    r = routes()
    r["process"] = [lambda: [submit(a, bad if a == "tool_execution" else actual(a)) for a in PROCESS_AXES],
                    lambda: [submit(a, actual(a)) for a in PROCESS_AXES]] + [lambda: [submit("tool_execution", actual("tool_execution"))]] * 2
    report, script, _ = run(r)
    assert report.status == "complete", report.reason
    assert "判没达到但没有引文" in script.text("process")


def test_expected_must_cite_known_expectation_ids():
    r = routes()
    wrong = {**expected("x"), "expected": [{**expected("x")["expected"][0], "expectations": ["t9.NOPE"]}]}
    tries = []

    def first_wrong(messages):
        reply = pushed_expected(messages, lambda a: wrong if a == "intent_understanding" and not tries else expected(a))
        if reply and json.loads(reply[0]["function"]["arguments"])["task_id"] == "intent_understanding_expected":
            tries.append(1)
        return reply
    r["process_expected"] = first_wrong
    report, script, _ = run(r)
    assert report.status == "complete", report.reason
    assert len(tries) == 2 and any("不在需求清单里" in script.text(g) for g in script.seen if g.startswith("process_expected["))


# ---- 主轴证据组（spec/alg/fulfilled.md §2.1，实施 S6） ------------------------------------------

def _fulfillment_code():
    return definitions().axes["fulfillment"].code


def _derive(delivered="给了", needs=(("knowledge",), ("trace",)), evidence=None, claims=(), rows=(), claim_refs=(), process_refs=()):
    derive = _fulfillment_code().synthesize.__globals__["derive"]
    item = {"delivered": delivered, "claim_refs": list(claim_refs), "process_refs": list(process_refs)}
    return derive(item, [list(g) for g in needs], evidence or {"knowledge": True, "trace": True},
                        {c["claim_id"]: c for c in claims}, {r["ref"]: r for r in rows})


def claim(cid, verdict, qualifies=""):
    return {"claim_id": cid, "verdict": verdict, "qualifies": qualifies}


def row(ref, verdict):
    return {"ref": ref, "verdict": verdict}


def test_delivery_only_and_missing_evidence():
    assert _derive(delivered="没给")[0] == "not_fulfilled"
    assert _derive(delivered="交付不可读")[0] == "not_evaluable"
    assert _derive(needs=())[:2] == ("fulfilled", ["delivery"])
    status, tier, missing, basis = _derive(evidence={"knowledge": False, "trace": False})
    assert status == "not_evaluable" and missing == [["knowledge"], ["trace"]]
    assert basis == "缺证据：需要 knowledge 或 trace，场景都没配"


def test_knowledge_only_scenario():
    only_k = {"knowledge": True, "trace": False}
    assert _derive(evidence=only_k, claims=[claim("c1", "verified")], claim_refs=["c1"])[:2] == ("fulfilled", ["knowledge"])
    assert _derive(evidence=only_k, claims=[claim("c1", "refuted")], claim_refs=["c1"])[0] == "not_fulfilled"
    assert _derive(evidence=only_k, claims=[claim("c1", "unverifiable")], claim_refs=["c1"])[0] == "not_evaluable"
    # 值核实了、修饰它的单位核实不了，不挡
    unit = [claim("c1", "verified"), claim("c2", "unverifiable", qualifies="c1")]
    assert _derive(evidence=only_k, claims=unit, claim_refs=["c1", "c2"])[0] == "fulfilled"


def test_trace_only_scenario():
    only_t = {"knowledge": False, "trace": True}
    ok = [row("tool_execution.E1", "达到"), row("model_capability.E2", "达到")]
    assert _derive(evidence=only_t, rows=ok, process_refs=["tool_execution.E1", "model_capability.E2"])[:2] == ("fulfilled", ["trace"])
    made_up = [row("tool_execution.E1", "达到"), row("model_capability.E2", "没达到")]
    assert _derive(evidence=only_t, rows=made_up, process_refs=["tool_execution.E1", "model_capability.E2"])[0] == "not_fulfilled"
    assert _derive(evidence=only_t, rows=[row("tool_execution.E1", "无法核")], process_refs=["tool_execution.E1"])[0] == "not_evaluable"
    assert _derive(evidence=only_t)[0] == "not_evaluable"   # 配了 trace、没有可引的过程条目：判不了


def test_both_configured_both_must_pass():
    k_ok, t_bad = [claim("c1", "verified")], [row("model_capability.E2", "没达到")]
    assert _derive(claims=k_ok, rows=t_bad, claim_refs=["c1"], process_refs=["model_capability.E2"])[0] == "not_fulfilled"  # 蒙对
    k_bad, t_ok = [claim("c1", "refuted")], [row("tool_execution.E1", "达到")]
    assert _derive(claims=k_bad, rows=t_ok, claim_refs=["c1"], process_refs=["tool_execution.E1"])[0] == "not_fulfilled"   # 过程像样但被证伪
    status, tier, _, _ = _derive(claims=k_ok, rows=[row("tool_execution.E1", "达到")], claim_refs=["c1"], process_refs=["tool_execution.E1"])
    assert status == "fulfilled" and tier == ["knowledge", "trace"]


def test_status_basis_names_what_decided_the_status():
    only_k = {"knowledge": True, "trace": False}
    refuted = [{**claim("c7", "refuted"), "text": "保单状态为无效"}, claim("c1", "verified")]
    assert _derive(evidence=only_k, claims=refuted, claim_refs=["c1", "c7"])[3] == "knowledge 组不过：c7（有矛盾：保单状态为无效）"
    assert _derive(evidence=only_k, claims=[claim("c1", "verified")], claim_refs=["c1"])[3] == "knowledge 组过：1 条结果值说法都核实"
    assert _derive(evidence=only_k)[3] == "knowledge 组判不了：没有引用结果值的说法"
    only_t = {"knowledge": False, "trace": True}
    rows = [{**row("tool_execution.E2", "无法核"), "statement": "按保单号查询"}]
    assert _derive(evidence=only_t, rows=rows, process_refs=["tool_execution.E2"])[3] == "trace 组判不了：tool_execution.E2（无法核：按保单号查询）"
    assert _derive(delivered="没给")[3] == "交付没给"


def test_process_items_based_on_an_expectation_must_all_be_cited():
    from types import SimpleNamespace
    materials = {"result.tool_execution": {"results": [{"id": "E1", "expectations": ["t1.E1"], "verdict": "没达到"},
                                                      {"id": "E2", "expectations": ["t1.E1"], "verdict": "达到"}]},
                 "result.expectations": {"expectations": [{"expectation_id": "t1.E1", "turn": "t1"}]}}
    own = {"assessments": [{"expectation_id": "t1.E1", "claim_refs": [], "process_refs": ["tool_execution.E2"]}]}
    problems = _fulfillment_code().check(SimpleNamespace(materials=materials, own=own))
    assert any("tool_execution.E1" in p and "必须引上" in p for p in problems)


def test_expected_stage_gets_neither_link_facts_nor_detective_reasons():
    """facts（contains / tool_error / vs_stored）是比过两端才有的；侦探的理由只给页面（spec/alg/axis_loop.md §12.2.2）。"""
    defs = definitions()
    for axis in PROCESS_AXES:
        entries = " ".join(defs.axes[f"{axis}_expected"].materials)
        assert "facts" not in entries and "basis" not in entries and "leads" not in entries and ".full" not in entries
    from impl.projects.llm_probe_loop.process_axes import axis_links
    off_map = [{"link_id": "new:0", "link_type": "tool_execution", "axes": ["tool_execution"], "off_map": True,
                "why": ["函数里藏着一次后端调用，返回为空"], "input_refs": ["a"], "output_refs": ["b"]}]
    assert "返回为空" not in json.dumps(axis_links("tool_execution", [], off_map), ensure_ascii=False)


def test_needs_external_not_met_is_sent_back_not_rewritten():
    """必须独立查证：trace 看得到做到了的达到照收；判没达到的提交时打回让模型改，合成不改模型的判断（10-27）。"""
    from impl.projects.llm_probe_loop.process_axes import actual_result, check_actual

    plan = {"expected": [{**expected("knowledge_data")["expected"][0], "id": i, "needs_external": "是"} for i in ("E1", "E2")],
            "not_covered": []}
    quote = [{"ref": "r1", "quote": "客户甲"}]
    row = lambda i, verdict: {"id": i, "links": [], "observed": "o", "quotes": quote, "verdict": verdict}
    own = {"actual": [row("E1", "达到"), row("E2", "没达到")], "unexpected": [],
           "problems": [{"phenomenon": "返回为空", "items": ["E2"], "attribution": "本轴", "impact": "y"}], "reason": "r", "scope_note": "无"}
    problems = check_actual(own, plan, {"r1": ["客户甲"]})
    assert len(problems) == 1 and "E2 必须独立查证" in problems[0]
    fixed = {**own, "actual": [row("E1", "达到"), row("E2", "无法核")], "problems": []}
    assert check_actual(fixed, plan, {"r1": ["客户甲"]}) == []
    assert {r["id"]: r["verdict"] for r in actual_result("knowledge_data", fixed, plan)["results"]} == {"E1": "达到", "E2": "无法核"}


def test_met_needs_a_quote_that_is_in_the_record():
    """达到也要引原文：没引、或引文对不上所引记录的，提交时打回（10-27）。"""
    from impl.projects.llm_probe_loop.process_axes import check_actual

    plan = {"expected": [{**expected("tool_execution")["expected"][0], "id": i} for i in ("E1", "E2", "E3")], "not_covered": []}
    own = {"actual": [{"id": "E1", "links": [], "observed": "调用成功", "quotes": [{"ref": "r1", "quote": "outcome ok"}], "verdict": "达到"},
                      {"id": "E2", "links": [], "observed": "返回与请求一致", "quotes": [], "verdict": "达到"},
                      {"id": "E3", "links": [], "observed": "返回与请求一致", "quotes": [{"ref": "r1", "quote": "返回了保单"}], "verdict": "达到"}],
           "unexpected": [], "problems": [], "reason": "r", "scope_note": "无"}
    texts = {"r1": ["outcomeok"]}
    problems = "".join(check_actual(own, plan, texts))
    assert "E2 判达到但没有引文" in problems and "返回了保单" in problems and "outcome ok" not in problems


def test_detective_routes_a_record_to_every_axis_it_names():
    """侦探偏召回：点名的轴都拿到这个环节（加上环节类型本身对应的轴）。"""
    from impl.projects.llm_probe_loop.process_axes import axis_links, merge_suspects

    table = {"tool_execution:x": {"link_id": "tool_execution:x", "link_type": "tool_execution",
                                  "input": [{"ref": "r1"}], "output": [{"ref": "r1"}]}}
    suspects = merge_suspects(
        [], [{"link_id": "tool_execution:x", "why": "w", "source_refs": ["r1"], "axes": ["model_capability"]}],
        [{"link_type": "tool_execution", "axes": ["knowledge_data"], "input_refs": ["r2"], "output_refs": ["r3"],
          "why": "后端返回", "source_refs": ["r3"]}], table)
    assert suspects[0]["axes"] == ["tool_execution", "model_capability"]
    assert suspects[1]["axes"] == ["tool_execution", "knowledge_data"]
    assert [l["link_id"] for l in axis_links("knowledge_data", [], suspects)] == [suspects[1]["link_id"]]


def test_detective_named_record_reaches_that_axis_material():
    """侦探把挂在别轴环节上的记录点名给本轴（如没调大模型时的网关判定给模型能力轴）：本轴的实际材料里要有这条记录。"""
    from impl.projects.llm_probe_loop.process_axes import analysis_result

    rec = lambda i, text: {"id": i, "kind": "observations", "turn": "turn1", "fields": {"output": {"status": "available", "value": text}}}
    trace = {"dossier": {"records": [rec("gate", "语义直达命中 policy_search"), rec("tool", "返回 2 张保单")], "contents": {}, "sources": []},
             "links": [{"link_id": "planning_routing:path:turn1", "link_type": "planning_routing", "turn": "turn1",
                        "input": [{"ref": "gate", "field": "output"}], "output": [{"ref": "tool", "field": "output"}]}],
             "program_suspects": [], "coverage": []}
    own = {"existing_link_suspects": [{"link_id": "planning_routing:path:turn1", "why": "走了直达、没调模型",
                                       "source_refs": ["gate"], "axes": ["model_capability"]}], "new_link_suspects": []}
    views = {v["axis"]: v for v in analysis_result(trace, own)["views"]}
    assert views["model_capability"]["links"] == []
    assert [r["id"] for r in views["model_capability"]["full"]["records"]] == ["gate"]
    assert views["model_capability"]["input"]["records"] == []
    assert views["model_capability"]["leads"] == ["gate"]
    assert views["planning_routing"]["links"][0]["leads"] == ["gate"] and views["planning_routing"]["leads"] == []


def test_detective_refs_for_a_link_ride_on_that_link_not_the_flat_list():
    """侦探给本轴环节指的记录写进那个环节（外层只记结构、内容在子记录上）；views.leads 只留指向别轴环节的，不重复。"""
    from impl.projects.llm_probe_loop.process_axes import analysis_result

    rec = lambda i, text: {"id": i, "kind": "observations", "turn": "turn1", "fields": {"output": {"status": "available", "value": text}}}
    trace = {"dossier": {"records": [rec("wrap", ""), rec("child", "返回客户何承琪"), rec("path", "规划")], "contents": {}, "sources": []},
             "links": [{"link_id": "tool_execution:wrap", "link_type": "tool_execution", "turn": "turn1",
                        "input": [{"ref": "wrap", "field": "output"}], "output": [{"ref": "wrap", "field": "output"}]},
                       {"link_id": "planning_routing:path", "link_type": "planning_routing", "turn": "turn1",
                        "input": [{"ref": "path", "field": "output"}], "output": [{"ref": "path", "field": "output"}]}],
             "program_suspects": [], "coverage": []}
    own = {"existing_link_suspects": [
        {"link_id": "tool_execution:wrap", "why": "外层无正文", "source_refs": ["wrap", "child"], "axes": ["tool_execution"]},
        {"link_id": "planning_routing:path", "why": "路径", "source_refs": ["path"], "axes": ["tool_execution"]}],
        "new_link_suspects": [{"link_type": "tool_execution", "axes": ["tool_execution"], "input_refs": ["child"],
                               "output_refs": ["child"], "why": "后端", "source_refs": ["child"]}]}
    view = {v["axis"]: v for v in analysis_result(trace, own)["views"]}["tool_execution"]
    by_id = {link["link_id"]: link for link in view["links"]}
    assert by_id["tool_execution:wrap"]["leads"] == ["child", "wrap"]
    assert by_id["new:2"]["leads"] == ["child"]
    assert view["leads"] == ["path"]


def test_trace_analysis_result_with_link_leads_fits_its_schema():
    from impl.core.axis_loop.acceptance import schema_errors

    defs = json.load(open("impl/data/llm_probe_loop/axis_definitions.json", encoding="utf-8"))
    link_schema = defs["axes"]["trace_analysis"]["output"]["properties"]["views"]["items"]["properties"]["links"]
    assert schema_errors(link_schema, [{"link_id": "x", "link_type": "tool_execution", "leads": ["r1"]}]) == []
    assert schema_errors(link_schema, [{"link_id": "x", "link_type": "tool_execution", "leads": "r1"}])


def test_not_applicable_needs_evidence_and_leaves_results():
    """不适用：这一步这次没发生、换了路办成——要引原文说明实际的路；移出逐条结果，不进兑现；全都不适用轴级落 not_applicable。"""
    from impl.projects.llm_probe_loop.process_axes import actual_result, check_actual

    plan = {"expected": [{**expected("model_capability")["expected"][0], "id": i, "expectations": ["t1.E1"]} for i in ("E1", "E2")],
            "not_covered": []}
    texts = {"r1": ["语义直达判定命中policy_search"]}
    row = lambda i, quotes: {"id": i, "links": [], "observed": "走直达工具，没调大模型", "quotes": quotes, "verdict": "不适用"}
    own = {"actual": [row("E1", [{"ref": "r1", "quote": "语义直达判定命中 policy_search"}]), row("E2", [])],
           "unexpected": [], "problems": [], "reason": "r", "scope_note": "无"}
    assert any("E2 判不适用但没有引文" in p for p in check_actual(own, plan, texts))
    out = actual_result("model_capability", {**own, "actual": own["actual"][:1] + [{**own["actual"][0], "id": "E2"}]}, plan)
    assert out["results"] == [] and out["verdict"] == "not_applicable"
    assert [r["id"] for r in out["composition"]["not_applicable"]] == ["E1", "E2"]


def test_main_verdict_pending_items_do_not_decide():
    """blocking 为空的期望（如隐性期望"回答里的事实都对"）没达到：不决定结论、列进 pending_unmet；附带说法不再直接挡。"""
    from impl.projects.llm_probe_loop.eval_axes.main_verdict import main_verdict

    def run(*items, claims=()):
        ff = {"business_expectations": [{"expectation_id": k, "blocking": b} for k, b, _ in items],
              "fulfillment_assessments": [{"expectation_id": k, "status": s} for k, _, s in items]}
        truth = {"claims": [{"claim_id": c, "verdict": v} for c, v in claims]}
        return main_verdict([{"type_id": "fulfillment", "status": "succeeded", "output": ff},
                             {"type_id": "truthfulness", "status": "succeeded", "output": truth}])

    out = run(("t1.days", True, "fulfilled"), ("t1.implicit_correct", None, "not_fulfilled"), claims=[("c2", "refuted")])
    assert out["verdict"] == "做成了" and out["composition"]["pending_unmet"] == ["t1.implicit_correct"] and "待定项没达到" in out["basis"]
    assert run(("t1.days", True, "not_fulfilled"), ("t1.implicit_correct", None, "fulfilled"))["verdict"] == "没做成"
    assert run(("t1.days", True, "not_evaluable"))["verdict"] == "不确定"


def test_expected_groups_are_fewest_acyclic_parts_with_fewest_rounds():
    """本应分组：feeds 成环的拆到不同组；组数最少，同组数取轮数最少；组内只给真实先后对。"""
    loop = definitions().loops["process_expected"].dispatch
    groups = loop.__globals__["groups"]
    axes = ["intent_understanding", "planning_routing", "tool_execution"]
    assert groups(axes, {("planning_routing", "intent_understanding")}) == [axes]
    cyc = {("planning_routing", "tool_execution"), ("tool_execution", "planning_routing"), ("intent_understanding", "tool_execution")}
    out = groups(axes, cyc)
    assert len(out) == 2 and not any({"planning_routing", "tool_execution"} <= set(g) for g in out)
    # 两种两组分法里，取轮数少的：intent→tool 拆开，各组都只要 1 轮
    assert sorted(map(sorted, out)) == [["intent_understanding", "planning_routing"], ["tool_execution"]]
    view = type("V", (), {"params": {"tasks": [a + "_expected" for a in axes]},
                          "materials": {"result.trace_analysis": {"feeds": [{"from": "planning_routing", "to": "intent_understanding"}]}}})()
    assert loop(view) == [{"id": "g1", "tasks": [a + "_expected" for a in axes],
                           "after": [["planning_routing_expected", "intent_understanding_expected"]]}]


def test_whole_record_output_of_an_off_map_link_is_not_in_the_expected_material():
    """侦探补的表外环节端点不写字段 = 整条记录：输出端整条不进本应材料；同一条也是本轴输入端时照给。"""
    from impl.projects.llm_probe_loop.process_axes import input_view

    rec = lambda i, text: {"id": i, "kind": "observations", "turn": "turn1", "fields": {"output": {"status": "available", "value": text}}}
    dossier = {"records": [rec("ask", "查保单 P1"), rec("answer", "P1 的被保人是张三"), rec("next", "下一步")], "contents": {}, "sources": []}
    off = lambda i, o: {"link_id": f"new:{i}", "link_type": "model_capability", "turn": "turn1",
                        "input": [{"ref": i, "field": ""}], "output": [{"ref": o, "field": ""}]}
    ids = lambda links: [r["id"] for r in input_view(dossier, links)["records"]]
    assert ids([off("ask", "answer")]) == ["ask"]
    assert ids([off("ask", "answer"), off("answer", "next")]) == ["ask", "answer"]


def test_main_verdict_basis_tells_wrong_from_missing():
    """没兑现的分开写给错了（附兑现的程序依据）和没给到（demand/main_axis.md M9）。"""
    from impl.projects.llm_probe_loop.eval_axes.main_verdict import main_verdict

    ff = {"business_expectations": [{"expectation_id": k, "blocking": True} for k in ("t1.A", "t1.B")],
          "fulfillment_assessments": [
              {"expectation_id": "t1.A", "status": "not_fulfilled", "delivered": "给了", "status_basis": "knowledge 组不过：c7（有矛盾：保单状态为无效）"},
              {"expectation_id": "t1.B", "status": "not_fulfilled", "delivered": "没给", "status_basis": "交付没给"}]}
    carry = {"placements": [{"expectation_id": k, "placement": "做错了"} for k in ("t1.A", "t1.B")]}
    out = main_verdict([{"type_id": "fulfillment", "status": "succeeded", "output": ff},
                        {"type_id": "carryability", "status": "succeeded", "output": carry}])
    assert out["verdict"] == "没做成"
    assert out["basis"] == "给错了：t1.A（knowledge 组不过：c7（有矛盾：保单状态为无效））；没给到：t1.B；系统本可以给出"



def test_uniqueness_principle_is_defined_once_and_cited_where_lists_are_made():
    """唯一性原则的定义只写在主 loop 的系统提示里，列清单的轴只点名（demand/axis_loop.md §3.8，2026-11-01）。"""
    from impl.core.axis_loop.loop import SYSTEM
    assert SYSTEM.count("唯一性原则") == 1 and "一份只装一件事" in SYSTEM
    axes = definitions().axes
    assert not [k for k, a in axes.items() if "一份只装一件事" in a.instruction or "看实质" in a.instruction]
    listing = ["claims", "expectations", *(f"{axis}_expected" for axis in PROCESS_AXES)]
    assert all("遵循唯一性原则（系统规则 10）" in axes[k].instruction for k in listing)
