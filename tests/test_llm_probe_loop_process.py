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


ACTUAL = {"actual": [{"id": "E1", "links": [], "observed": "看过两端", "quotes": [], "verdict": "达到",
                      "attribution": "", "affected_expectations": []}],
          "unexpected": [], "reason": "没发现问题", "scope_note": "无"}
CURRENT: dict = {}


def resources(texts):
    """校验拿到的可见资源：每个编号一条记录，正文是给的那几段。"""
    from impl.core.axis_loop.visible import Visible
    from impl.core.resources import ResourceTable

    table = ResourceTable()
    for ref, parts in texts.items():
        table.mount(f"trace://{ref}", "record_set", {"fields": {"v": {"status": "available", "value": parts}}}, name=ref)
    return Visible(table, [f"trace://{ref}" for ref in texts])


def actual(axis):
    """达到也要引原文：从侦探给这个轴的 full_uris 所指的 ResourceTable 记录里摘一段。"""
    from impl.core.axis_loop.text import leaves
    view = next(v for v in CURRENT["table"].results["trace_analysis"]["views"] if v["axis"] == axis)
    res_table = CURRENT["table"].resources
    found = None
    for uri in view["full_uris"]:
        block = res_table.get(uri)
        if block is None:
            continue
        for s in leaves(block.body.get("fields") or {}):
            if len(s.strip()) >= 4 and "\\" not in s:
                found = (block.descriptor.name, s)
                break
        if found:
            break
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
    """这个轴 full_uris 里有、input_uris 里没有的字段正文（够长、能认出来的那些）。"""
    from impl.projects.llm_probe_loop.process_axes import _uri_pair
    out = set()
    view = next(v for v in table.results["trace_analysis"]["views"] if v["axis"] == axis)
    seen_input = {_uri_pair(u) for u in view["input_uris"]}
    for uri in view["full_uris"]:
        part = table.resources.part(uri)
        if part is None:
            continue
        block, node = part
        rid = block.descriptor.name
        raw_fields = block.body.get("fields") or {}
        _, target_field = _uri_pair(uri)
        cand = [(target_field, raw_fields.get(target_field))] if (node and target_field) else list(raw_fields.items())
        for name, info in cand:
            value = info.get("value") if isinstance(info, dict) else None
            if (rid, name) not in seen_input and (rid, "") not in seen_input and isinstance(value, str) and len(value) >= 30:
                out.add(value[:60])
    return out


def test_process_axes_run_and_expected_loop_never_sees_output_side():
    report, script, table = run(routes())
    assert report.status == "complete", report.reason
    assert [l["id"] for l in report.loops] == ["trace_analysis", "process_expected", "process"]
    groups = sorted({r for r in script.seen if r.startswith("process_expected[")})
    assert 1 <= len(groups) < len(PROCESS_AXES)
    # 公共资源区段落头在 process 首条消息里只出现一次，且被多轴共用的同一记录正文只嵌一份（不再按轴复印多份）
    first_process_msg = "\n".join(str(m.get("content")) for m in script.seen["process"][0])
    assert ("\n" + first_process_msg).count("\n【resources】\n") == 1
    assert first_process_msg.count('"id": "turn1/records/run"') == 1
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
    bad = {**ACTUAL, "actual": [{**ACTUAL["actual"][0], "verdict": "没达到", "attribution": "本轴",
                                 "affected_expectations": ["t1.E1"]}]}
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


# ---- 主轴证据组（spec/alg/fulfilled.md §2.1，实施 S6 + §17 程序汇总过程佐证） ---------------------

def _fulfillment_code():
    return definitions().axes["fulfillment"].code


def _derive(delivered="给了", needs=(("knowledge",), ("trace",)), evidence=None, claims=(), rows=(), claim_refs=(),
            expectation_id="t1.E1", unexpected=()):
    derive = _fulfillment_code().synthesize.__globals__["derive"]
    item = {"expectation_id": expectation_id, "delivered": delivered, "claim_refs": list(claim_refs)}
    return derive(item, [list(g) for g in needs], evidence or {"knowledge": True, "trace": True},
                  {c["claim_id"]: c for c in claims}, {r["ref"]: r for r in rows},
                  {u["ref"]: u for u in unexpected})


def claim(cid, verdict, qualifies=""):
    return {"claim_id": cid, "verdict": verdict, "qualifies": qualifies}


def row(ref, verdict, expectations=("t1.E1",), affected_expectations=None):
    if affected_expectations is None:
        affected_expectations = list(expectations) if verdict == "没达到" else []
    return {"ref": ref, "verdict": verdict, "expectations": list(expectations),
            "affected_expectations": list(affected_expectations)}


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
    assert _derive(evidence=only_t, rows=ok)[:2] == ("fulfilled", ["trace"])
    made_up = [row("tool_execution.E1", "达到"), row("model_capability.E2", "没达到")]
    assert _derive(evidence=only_t, rows=made_up)[0] == "not_fulfilled"
    assert _derive(evidence=only_t, rows=[row("tool_execution.E1", "无法核")])[0] == "not_evaluable"
    assert _derive(evidence=only_t)[0] == "not_evaluable"   # 配了 trace、没有关联本期望的过程条目：判不了


def test_both_configured_both_must_pass():
    k_ok, t_bad = [claim("c1", "verified")], [row("model_capability.E2", "没达到")]
    assert _derive(claims=k_ok, rows=t_bad, claim_refs=["c1"])[0] == "not_fulfilled"  # 蒙对
    k_bad, t_ok = [claim("c1", "refuted")], [row("tool_execution.E1", "达到")]
    assert _derive(claims=k_bad, rows=t_ok, claim_refs=["c1"])[0] == "not_fulfilled"   # 过程像样但被证伪
    status, tier, _, _ = _derive(claims=k_ok, rows=[row("tool_execution.E1", "达到")], claim_refs=["c1"])
    assert status == "fulfilled" and tier == ["knowledge", "trace"]


def test_status_basis_names_what_decided_the_status():
    only_k = {"knowledge": True, "trace": False}
    refuted = [{**claim("c7", "refuted"), "text": "保单状态为无效"}, claim("c1", "verified")]
    assert _derive(evidence=only_k, claims=refuted, claim_refs=["c1", "c7"])[3] == "knowledge 组不过：c7（有矛盾：保单状态为无效）"
    assert _derive(evidence=only_k, claims=[claim("c1", "verified")], claim_refs=["c1"])[3] == "knowledge 组过：1 条结果值说法都核实"
    assert _derive(evidence=only_k)[3] == "knowledge 组判不了：没有引用结果值的说法"
    only_t = {"knowledge": False, "trace": True}
    rows = [{**row("tool_execution.E2", "无法核"), "statement": "按保单号查询"}]
    assert _derive(evidence=only_t, rows=rows)[3] == "trace 组判不了：tool_execution.E2（无法核：按保单号查询）"
    assert _derive(delivered="没给")[3] == "交付没给"


def test_p9_multi_expectation_item_partial_deviation_does_not_penalize_unaffected_expectation():
    """P9（B02 形态）：同一条本应挂了列表与总数两条期望，只因列表截断判没达到、总数未受损 → 总数照样 fulfilled，process_refs 程序自动填。"""
    from types import SimpleNamespace

    expectations = [
        {"expectation_id": "t1.E_list", "turn": "t1", "about": "列表", "statement": "给出全部客户", "condition": "总是",
         "ambiguity_group": "", "source_refs": ["t1.user"], "needs": [["trace"]]},
        {"expectation_id": "t1.E_count", "turn": "t1", "about": "总数", "statement": "告知客户总数", "condition": "总是",
         "ambiguity_group": "", "source_refs": ["t1.user"], "needs": [["trace"]]},
    ]
    materials = {
        "result.expectations": {"expectations": expectations},
        "result.blocking": {"items": [{"expectation_id": "t1.E_list", "blocking": True},
                                      {"expectation_id": "t1.E_count", "blocking": True}]},
        "scenario.evidence": {"knowledge": False, "trace": True},
        "result.planning_routing": {
            "results": [{"id": "E1", "expectations": ["t1.E_list", "t1.E_count"],
                         "affected_expectations": ["t1.E_list"],
                         "statement": "完整返回客户列表与总数", "verdict": "没达到", "observed": "列表截断只剩10条，总数75正确"}],
            "issues": [],
        },
    }
    own = {"reason": "r", "assessments": [
        {"expectation_id": "t1.E_list", "delivered": "给了", "evidence": ["前10位客户"], "claim_refs": [], "reason": "列表截断"},
        {"expectation_id": "t1.E_count", "delivered": "给了", "evidence": ["共75位"], "claim_refs": [], "reason": "总数75由完整统计得出"},
    ]}
    assert _fulfillment_code().check(SimpleNamespace(materials=materials, own=own)) == []
    out = _fulfillment_code().synthesize(SimpleNamespace(materials=materials, own=own))
    by_id = {a["expectation_id"]: a for a in out["fulfillment_assessments"]}
    assert by_id["t1.E_list"]["status"] == "not_fulfilled"
    assert "planning_routing.E1" in by_id["t1.E_list"]["status_basis"]
    assert by_id["t1.E_count"]["status"] == "fulfilled"
    assert by_id["t1.E_list"]["process_refs"] == ["planning_routing.E1"]
    assert by_id["t1.E_count"]["process_refs"] == ["planning_routing.E1"]


def test_unexpected_affecting_expectation_fails_trace_group():
    """本应清单外的意外（如兜底覆盖模型答案）伤及某条期望时，兑现 trace 组不过，并写入 process_refs；未伤及期望的意外不连累它。"""
    from types import SimpleNamespace

    expectations = [{"expectation_id": "t1.E1", "turn": "t1", "about": "保单", "statement": "告知被保人", "condition": "总是",
                     "ambiguity_group": "", "source_refs": ["t1.user"], "needs": [["trace"]]}]
    base = {
        "result.expectations": {"expectations": expectations},
        "result.blocking": {"items": [{"expectation_id": "t1.E1", "blocking": True}]},
        "scenario.evidence": {"knowledge": False, "trace": True},
        "result.tool_execution": {"results": [{"id": "E1", "expectations": ["t1.E1"], "affected_expectations": [],
                                               "statement": "按号查询", "verdict": "达到", "observed": "查到张三"}], "issues": []},
    }
    own = {"reason": "r", "assessments": [
        {"expectation_id": "t1.E1", "delivered": "给了", "evidence": ["李四"], "claim_refs": [], "reason": "r"}]}
    # 伤及 t1.E1 的意外 → trace 组不过
    hurt_materials = {**base, "result.context_memory": {"results": [], "issues": [
        {"item_id": "U1", "origin": "unexpected", "observed": "后处理模板把张三替换成李四",
         "attribution_detail": "本轴", "affected_expectations": ["t1.E1"]}]}}
    out_hurt = _fulfillment_code().synthesize(SimpleNamespace(materials=hurt_materials, own=own))
    a_hurt = out_hurt["fulfillment_assessments"][0]
    assert a_hurt["status"] == "not_fulfilled"
    assert "context_memory.U1（意外：后处理模板把张三替换成李四）" in a_hurt["status_basis"]
    assert a_hurt["process_refs"] == ["tool_execution.E1", "context_memory.U1"]
    # 未伤及 t1.E1 的意外（例如多发了一次无关冗余查询） → t1.E1 仍 fulfilled
    harmless_materials = {**base, "result.planning_routing": {"results": [], "issues": [
        {"item_id": "U2", "origin": "unexpected", "observed": "多发了一次同参重试",
         "attribution_detail": "本轴", "affected_expectations": []}]}}
    out_ok = _fulfillment_code().synthesize(SimpleNamespace(materials=harmless_materials, own=own))
    a_ok = out_ok["fulfillment_assessments"][0]
    assert a_ok["status"] == "fulfilled" and a_ok["process_refs"] == ["tool_execution.E1"]


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
    mk = lambda i, verdict: {"id": i, "links": [], "observed": "o", "quotes": quote, "verdict": verdict,
                             "attribution": "本轴" if verdict == "没达到" else "",
                             "affected_expectations": ["t1.E1"] if verdict == "没达到" else []}
    own = {"actual": [mk("E1", "达到"), mk("E2", "没达到")], "unexpected": [], "reason": "r", "scope_note": "无"}
    problems = check_actual("knowledge_data", own, plan, {"expectations": E}, resources({"r1": ["客户甲"]}))
    assert len(problems) == 1 and "E2 必须独立查证" in problems[0]
    fixed = {**own, "actual": [mk("E1", "达到"), {**mk("E2", "无法核"), "quotes": []}]}
    assert check_actual("knowledge_data", fixed, plan, {"expectations": E}, resources({"r1": ["客户甲"]})) == []
    assert {r["id"]: r["verdict"] for r in actual_result("knowledge_data", fixed, plan)["results"]} == {"E1": "达到", "E2": "无法核"}


def test_met_needs_a_quote_that_is_in_the_record():
    """达到也要引原文：没引、或引文对不上所引记录的，提交时打回（10-27）。"""
    from impl.projects.llm_probe_loop.process_axes import check_actual

    plan = {"expected": [{**expected("tool_execution")["expected"][0], "id": i} for i in ("E1", "E2", "E3")], "not_covered": []}
    own = {"actual": [{"id": "E1", "links": [], "observed": "调用成功", "quotes": [{"ref": "r1", "quote": "outcome ok"}],
                       "verdict": "达到", "attribution": "", "affected_expectations": []},
                      {"id": "E2", "links": [], "observed": "返回与请求一致", "quotes": [],
                       "verdict": "达到", "attribution": "", "affected_expectations": []},
                      {"id": "E3", "links": [], "observed": "返回与请求一致", "quotes": [{"ref": "r1", "quote": "返回了保单"}],
                       "verdict": "达到", "attribution": "", "affected_expectations": []}],
           "unexpected": [], "reason": "r", "scope_note": "无"}
    texts = {"r1": ["outcomeok"]}
    problems = "".join(check_actual("tool_execution", own, plan, {"expectations": E}, resources(texts)))
    assert "E2 判达到但没有引文" in problems and "返回了保单" in problems and "outcome ok" not in problems


def test_detective_routes_a_record_to_every_axis_it_names():
    """侦探偏召回：点名的轴都拿到这个环节的线索（加上环节类型本身对应的轴）；环节本身只归它的类型对应的轴。"""
    from impl.projects.llm_probe_loop.process_axes import axis_links, merge_suspects

    table = {"tool_execution:x": {"link_id": "tool_execution:x", "link_type": "tool_execution",
                                  "input": [{"ref": "r1"}], "output": [{"ref": "r1"}]}}
    suspects = merge_suspects(
        [], [{"link_id": "tool_execution:x", "why": "w", "source_refs": ["r1"], "axes": ["model_capability"]}],
        [{"link_type": "tool_execution", "axes": ["knowledge_data"], "input_refs": ["r2/fields/input"], "output_refs": ["r3/fields/output"],
          "why": "后端返回", "source_refs": ["r3/fields/output"]}], table)
    assert suspects[0]["axes"] == ["tool_execution", "model_capability"]
    assert suspects[1]["axes"] == ["tool_execution", "knowledge_data"]
    assert axis_links("knowledge_data", [], suspects) == []
    assert [l["link_id"] for l in axis_links("tool_execution", [], suspects)] == [suspects[1]["link_id"]]


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
    assert views["model_capability"]["full_uris"] == ["trace://gate"]
    assert views["model_capability"]["input_uris"] == []
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
    mk = lambda i, quotes: {"id": i, "links": [], "observed": "走直达工具，没调大模型", "quotes": quotes,
                            "verdict": "不适用", "attribution": "", "affected_expectations": []}
    own = {"actual": [mk("E1", [{"ref": "r1", "quote": "语义直达判定命中 policy_search"}]), mk("E2", [])],
           "unexpected": [], "reason": "r", "scope_note": "无"}
    assert any("E2 判不适用但没有引文" in p for p in check_actual("model_capability", own, plan, {"expectations": E}, resources(texts)))
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


def test_check_actual_validates_item_attribution_and_affected_expectations_and_builds_issues():
    """删 problems 表后：归因与受损期望直接在条目核对，问题记录与轴级五值由程序从没达到 + unexpected 生成。"""
    from impl.projects.llm_probe_loop.process_axes import actual_result, check_actual

    plan = {"expected": [{**expected("tool_execution")["expected"][0], "id": i} for i in ("E1", "E2")], "not_covered": []}
    q = [{"ref": "r1", "quote": "证据片段"}]
    res = resources({"r1": ["证据片段"]})
    # 1) 没达到却空归因、达到却填归因或受损期望、上游指向自己或非英文轴名、未知期望编号 → 全部打回
    bad = {
        "actual": [
            {"id": "E1", "links": ["L1"], "observed": "成功", "quotes": q, "verdict": "达到",
             "attribution": "本轴", "affected_expectations": ["t1.E1"]},
            {"id": "E2", "links": ["L2"], "observed": "失败", "quotes": q, "verdict": "没达到",
             "attribution": "上游:tool_execution", "affected_expectations": ["t1.NOPE"]},
        ],
        "unexpected": [{"id": "U1", "observed": "额外异常", "quotes": q,
                        "attribution": "上游:规划", "affected_expectations": ["t1.NOPE2"]}],
        "reason": "r", "scope_note": "s",
    }
    errs = "\n".join(check_actual("tool_execution", bad, plan, {"expectations": E}, res))
    assert "E1 判达到时 attribution 必须填空字符串" in errs
    assert "E1 判达到时 affected_expectations 必须为 []" in errs
    assert "E2 的 attribution='上游:tool_execution'" in errs
    assert "t1.NOPE" in errs and "t1.NOPE2" in errs
    assert "unexpected U1 的 attribution='上游:规划'" in errs

    # 2) 修正后通过检查，actual_result 直接从没达到 + unexpected 生成 issues 与五值
    good = {
        "actual": [
            {"id": "E1", "links": ["L1"], "observed": "成功", "quotes": q, "verdict": "达到",
             "attribution": "", "affected_expectations": []},
            {"id": "E2", "links": ["L2"], "observed": "输入参数已被上游改坏", "quotes": q, "verdict": "没达到",
             "attribution": "上游:planning_routing", "affected_expectations": ["t1.E1"]},
        ],
        "unexpected": [{"id": "U1", "observed": "连接超时未正常透出", "quotes": q,
                        "attribution": "本轴", "affected_expectations": []}],
        "reason": "r", "scope_note": "s",
    }
    assert check_actual("tool_execution", good, plan, {"expectations": E}, res) == []
    out = actual_result("tool_execution", good, plan)
    assert out["verdict"] == "problematic"
    assert out["composition"]["counts"]["问题·上游"] == 1 and out["composition"]["counts"]["问题·本轴"] == 1
    assert [(i["problem_id"], i["item_id"], i["origin"], i["attribution"], i["affected_expectations"]) for i in out["issues"]] == [
        ("tool_execution-P1", "E2", "expected", "upstream", ["t1.E1"]),
        ("tool_execution-P2", "U1", "unexpected", "local", []),
    ]


def test_build_report_passes_only_enabled_axis_notes_to_case(monkeypatch):
    """禁用（enabled=false）轴的描述不进入 Case.axis_notes（§17 第 1 项）。"""
    import impl.projects.llm_probe_loop.eval_axes as ea
    from impl.projects.llm_probe_loop.eval_axes.validate import ScenarioAxes

    captured = {}
    monkeypatch.setattr(ea, "load_scenario_axes", lambda sid: ScenarioAxes(
        enabled=["expectations", "blocking", "fulfillment", "main_verdict"],
        notes={"expectations": "只取本轮交付要求", "intent_understanding": "已关闭框的旧说明"},
        warnings=[],
    ))
    monkeypatch.setattr(ea, "load_capability_map", lambda project: {"scn": {}})

    def fake_case(trace, scenario_id, entry, axis_notes):
        captured["notes"] = dict(axis_notes)
        return object()

    monkeypatch.setattr(ea, "Case", fake_case)
    monkeypatch.setattr(ea.business_failure, "matched", lambda trace, entry: "模拟业务错误早退")
    trace = normalize_run_trace(json.loads(FIXTURE.read_text()))
    ea.build_report(None, trace, scenario_id="scn")
    assert captured["notes"] == {"expectations": "只取本轮交付要求", "blocking": "", "fulfillment": "", "main_verdict": ""}
    assert "intent_understanding" not in captured["notes"]


def test_detective_field_refs_open_only_named_fields_and_isolate_expected_output():
    """侦探写到字段层（记录编号/fields/字段名）：下游只开所指字段、不把整条记录的无关重字段全打开；
    同记录既是表外环节输入字段又是输出字段时，本应阶段只保留输入字段、不漏输出字段。"""
    from impl.core.axis_loop.view import CallView, TaskView
    from impl.projects.llm_probe_loop.process_axes import analysis_result, check_analysis
    from impl.projects.llm_probe_loop.eval_axes.registry import definitions as load_defs

    dossier = {
        "sources": [{"id": "turn1", "request_and_response": {"q": "查保单"}}],
        "contents": {},
        "records": [
            {
                "id": "turn1/records/observations/10",
                "kind": "steps",
                "turn": "turn1",
                "name": "backend.policy.search",
                "fields": {
                    "input": {"status": "available", "value": {"query": "伏云平"}},
                    "output": {"status": "available", "value": {"policies": ["P001_SECRET_OUTPUT"]}},
                    "metadata": {"status": "available", "value": {"big_meta": "M" * 500}},
                },
            },
            {
                "id": "turn1/records/observations/28",
                "kind": "steps",
                "turn": "turn1",
                "name": "rag.parent",
                "fields": {
                    "input": {"status": "available", "value": {"q": "条款"}},
                    "output": {"status": "available", "value": {"docs": "BIG_PARENT_DOC_" * 200}},
                    "metadata": {"status": "available", "value": {"trace": "x"}},
                },
            },
        ],
    }
    links = [{
        "link_id": "intent_understanding:turn1",
        "link_type": "intent_understanding",
        "turn": "turn1",
        "input": [{"ref": "turn1", "field": "request_and_response"}],
        "output": [{"ref": "turn1/records/observations/10", "field": "input"}],
        "facts": {},
    }]
    trace = {"dossier": dossier, "links": links, "program_suspects": [], "coverage": [{"status": "succeeded"}]}

    # 1) 校验：把记录头属性 name 写成 /fields/name、或只读了 input 却引 output → 明确拒绝
    bad_own = {
        "existing_link_suspects": [{
            "link_id": "intent_understanding:turn1",
            "why": "看步骤名",
            "source_refs": ["turn1/records/observations/10/fields/name"],
            "axes": ["intent_understanding"],
        }],
        "new_link_suspects": [{
            "link_type": "tool_execution",
            "input_refs": ["turn1/records/observations/10/fields/input"],
            "output_refs": ["turn1/records/observations/10/fields/output"],
            "why": "直连后端调用",
            "source_refs": ["turn1/records/observations/28/fields/input"],
            "axes": ["tool_execution", "knowledge_data"],
        }],
    }
    errs = "\n".join(check_analysis(trace, bad_own, {("turn1/records/observations/10", "input")}))
    assert "fields/name" in errs and "指步骤本身属性" in errs
    assert "turn1/records/observations/10/fields/output" in errs
    assert "turn1/records/observations/28/fields/input" in errs

    # 2) 读过整条记录后，引其下任意真实字段通过校验（通过 checks.py 入口验 CallView 解析）
    good_own = {
        **bad_own,
        "existing_link_suspects": [{
            "link_id": "intent_understanding:turn1",
            "why": "补看 rag 输入",
            "source_refs": ["turn1/records/observations/28/fields/input"],
            "axes": ["intent_understanding", "knowledge_data"],
        }],
    }
    check_fn = load_defs().axes["trace_analysis"].code.check
    read_call = CallView(
        call_id="ta.c0", tool="read_material", category="", args={"name": "resources", "ids": ["obs"]}, batch=0,
        text=json.dumps({"name": "resources", "records": [
            {"id": "turn1/records/observations/10", "content": {}},
            {"id": "turn1/records/observations/28", "path": "fields/input", "content": {}},
            {"id": "turn1/records/observations/99", "error": "本次合计已到 60000 字"},
        ]}),
        structured=None, is_error=False,
    )
    tview = TaskView(task_id="trace_analysis", own=good_own, materials={"case.trace": trace}, calls=(read_call,))
    assert check_fn(tview) == []

    # 3) 合成结果：
    # - tool_execution 本应 input_uris 只有 obs/10/fields/input，绝不含 obs/10/fields/output（同记录输出隔离）
    # - intent_understanding / knowledge_data 实际 full_uris 只含 obs/28/fields/input，不含 3 万字的 obs/28/fields/output 和 metadata
    out = analysis_result(trace, good_own)
    by_axis = {v["axis"]: v for v in out["views"]}
    assert by_axis["tool_execution"]["input_uris"] == ["trace://turn1/records/observations/10/fields/input"]
    assert set(by_axis["tool_execution"]["full_uris"]) == {
        "trace://turn1/records/observations/10/fields/input",
        "trace://turn1/records/observations/10/fields/output",
        "trace://turn1/records/observations/28/fields/input",
    }
    assert "trace://turn1/records/observations/28" not in by_axis["intent_understanding"]["full_uris"]
    assert "trace://turn1/records/observations/28/fields/output" not in by_axis["intent_understanding"]["full_uris"]
    assert "trace://turn1/records/observations/28/fields/input" in by_axis["knowledge_data"]["full_uris"]
    assert "trace://turn1/records/observations/28" not in by_axis["knowledge_data"]["full_uris"]


def test_off_map_link_belongs_only_to_its_link_type_axis_not_named_axes():
    """表外环节按 link_type 归轴：侦探在 context_memory 表外环节多选 knowledge_data 时，不把内层输出端带进 knowledge_data 本应阶段，只走 leads 进实际阶段。"""
    from impl.projects.llm_probe_loop.process_axes import analysis_result

    field = lambda v, ref="": {"status": "available", "value": v, **({"ref": ref} if ref else {})}
    dossier = {
        "sources": [{"id": "turn1", "request_and_response": {"q": "按业务流水号查保单"}}],
        "contents": {},
        "records": [
            {
                "id": "obs/14",
                "kind": "tool_calls",
                "turn": "turn1",
                "name": "tool.policy_search",
                "fields": {
                    "arguments": field({"bizno": "B1"}, "obs/14/in"),
                    "input": field({"bizno": "B1"}, "obs/14/in"),
                    "result": field({"notes": "未提供 clientno"}, "obs/14/out"),
                    "output": field({"notes": "未提供 clientno"}, "obs/14/out"),
                },
            },
            {
                "id": "obs/15",
                "kind": "steps",
                "turn": "turn1",
                "name": "backend.policy.search",
                "fields": {
                    "input": field({"bizno": "B1"}),
                    "output": field({"rows": [{"policy_no": "P1"}]}),
                    "metadata": field({"trace": "t"}),
                },
            },
        ],
    }
    links = [{
        "link_id": "knowledge_data:turn1",
        "link_type": "knowledge_data",
        "turn": "turn1",
        "input": [{"ref": "obs/14", "field": "arguments"}],
        "output": [{"ref": "obs/14", "field": "result"}],
        "facts": {},
    }]
    trace = {"dossier": dossier, "links": links, "program_suspects": [], "coverage": [{"status": "succeeded"}]}
    own = {
        "existing_link_suspects": [],
        "new_link_suspects": [
            {
                "link_type": "knowledge_data",
                "axes": ["knowledge_data", "tool_execution"],
                "input_refs": ["obs/15/fields/input"],
                "output_refs": ["obs/15/fields/output"],
                "why": "内层后端返回",
                "source_refs": ["obs/15/fields/output"],
            },
            {
                "link_type": "context_memory",
                "axes": ["context_memory", "knowledge_data", "tool_execution"],
                "input_refs": ["obs/15/fields/output"],
                "output_refs": ["obs/14/fields/output"],
                "why": "内层返回封装为工具输出",
                "source_refs": ["obs/15/fields/output", "obs/14/fields/output"],
            },
        ],
    }
    res = analysis_result(trace, own)
    views = {v["axis"]: v for v in res["views"]}
    assert [l["link_type"] for l in views["knowledge_data"]["links"]] == ["knowledge_data", "knowledge_data"]
    assert views["tool_execution"]["links"] == []
    # knowledge_data 本应阶段绝不出现 obs/15/output、obs/14/result、obs/14/output
    kd_in = set(views["knowledge_data"]["input_uris"])
    assert "trace://obs/15/fields/output" not in kd_in
    assert "trace://obs/14/fields/result" not in kd_in
    assert "trace://obs/14/fields/output" not in kd_in
    # 侦探点名的线索走 leads 进实际阶段 full_uris
    assert "obs/14/fields/output" in views["knowledge_data"]["leads"]
    assert "trace://obs/14/fields/output" in views["knowledge_data"]["full_uris"]
    assert "trace://obs/15/fields/output" in views["knowledge_data"]["full_uris"]
    assert set(views["tool_execution"]["leads"]) == {"obs/14/fields/output", "obs/15/fields/output"}


def test_check_analysis_rejects_same_endpoint_or_alias_on_both_sides():
    """单条表外环节的 input_refs 与 output_refs 不能写同一位置或同记录同一底层 ref 的别名。"""
    from impl.projects.llm_probe_loop.process_axes import check_analysis

    trace = {
        "links": [],
        "dossier": {
            "sources": [],
            "contents": {},
            "records": [{
                "id": "obs/20",
                "kind": "tool_calls",
                "fields": {
                    "arguments": {"status": "available", "ref": "obs/20/in", "value": {}},
                    "result": {"status": "available", "ref": "obs/20/out", "value": {}},
                    "output": {"status": "available", "ref": "obs/20/out", "value": {}},
                    "metadata": {"status": "available", "ref": "obs/20/meta", "value": {}},
                },
            }],
        },
    }
    mk = lambda ins, outs: {
        "existing_link_suspects": [],
        "new_link_suspects": [{
            "link_type": "knowledge_data", "axes": ["knowledge_data"],
            "input_refs": ins, "output_refs": outs, "why": "w", "source_refs": ["obs/20/fields/metadata"],
        }],
    }
    read_all = {("obs/20", "")}
    assert check_analysis(trace, mk(["obs/20/fields/arguments"], ["obs/20/fields/output"]), read_all) == []
    errs_same = "\n".join(check_analysis(trace, mk(["obs/20/fields/metadata"], ["obs/20/fields/metadata"]), read_all))
    assert "同一个位置不能既是输入端又是输出端" in errs_same
    errs_alias = "\n".join(check_analysis(trace, mk(["obs/20/fields/result"], ["obs/20/fields/output"]), read_all))
    assert "同一个位置不能既是输入端又是输出端" in errs_alias


def test_input_view_strips_same_ref_output_aliases_and_preserves_kept_alias_body():
    """同记录同底层 ref 的 result 与 output：只摘一个时另一个一并摘除；下游显式把其中一个作输入时保留正文不悬空 same_as。"""
    from impl.projects.llm_probe_loop.process_axes import input_view

    dossier = {
        "sources": [],
        "contents": {},
        "records": [
            {
                "id": "msg/1",
                "kind": "messages",
                "turn": "turn1",
                "fields": {
                    "input": {"status": "available", "ref": "msg/1/in", "value": "问题"},
                    "output": {"status": "available", "ref": "msg/1/out", "value": "SECRET_OUT"},
                    "result": {"status": "available", "ref": "msg/1/out", "value": "SECRET_OUT"},
                },
            },
            {
                "id": "step/2",
                "kind": "steps",
                "turn": "turn1",
                "fields": {"output": {"status": "available", "ref": "step/2/out", "value": "NEXT"}},
            },
        ],
    }
    # 1) messages 会展开整条记录字段：link 只声明摘 result 时，同底层 ref 的 output 也一起摘掉
    l1 = {"link_id": "L1", "link_type": "tool_execution", "turn": "turn1",
          "input": [{"ref": "msg/1", "field": "input"}], "output": [{"ref": "msg/1", "field": "result"}]}
    v1 = input_view(dossier, [l1])
    assert set(v1["records"][0]["fields"]) == {"input"}

    # 2) 上游摘 output、同轴下游显式把 result 当输入（keep 胜出）：只留 result 且正文不丢（不留悬空 same_as）
    l2 = {"link_id": "L2", "link_type": "tool_execution", "turn": "turn1",
          "input": [{"ref": "msg/1", "field": "input"}], "output": [{"ref": "msg/1", "field": "output"}]}
    l3 = {"link_id": "L3", "link_type": "tool_execution", "turn": "turn1",
          "input": [{"ref": "msg/1", "field": "result"}], "output": [{"ref": "step/2", "field": "output"}]}
    v2 = input_view(dossier, [l2, l3])
    rec_fields = {r["id"]: r["fields"] for r in v2["records"]}["msg/1"]
    assert set(rec_fields) == {"input", "result"}
    assert "value" in rec_fields["result"] and "same_as" not in rec_fields["result"]


def test_project_requirements_and_user_turns_keep_multi_turn_history_despite_mock_message():
    """Bug1: 有 mock_message 时仍从 request 拆出多轮历史；单条 trace 回放多轮时 user_turns 也不被单句 transcript 短路。"""
    from types import SimpleNamespace
    from impl.projects.llm_probe_loop.business_trace.expectation_material import project_requirements
    from impl.projects.llm_probe_loop.eval_axes.requirements import user_turns

    msgs = [
        {"role": "user", "content": "查伏云平名下保单的累计已交保费"},
        {"role": "assistant", "content": "未查到伏云平"},
        {"role": "user", "content": "名字说错了，是余昕雅，问题不变。"},
    ]
    trace = SimpleNamespace(
        turn_records=[{"mock_message": "名字说错了，是余昕雅，问题不变。", "request": {"body": {"messages": msgs}}, "project_fields": {}}],
        normalized_request={"body": {"messages": msgs}},
        conversation_transcript=[{"role": "user", "query": "名字说错了，是余昕雅，问题不变。"}],
    )
    req = project_requirements(trace)
    sides = [(s["side"], s["value"]) for s in req["sources"]]
    assert ("history", {"role": "user", "content": "查伏云平名下保单的累计已交保费"}) in sides
    assert ("history", {"role": "assistant", "content": "未查到伏云平"}) in sides
    assert ("want", "名字说错了，是余昕雅，问题不变。") in sides
    assert user_turns(trace) == ["查伏云平名下保单的累计已交保费", "名字说错了，是余昕雅，问题不变。"]

    # 在线多轮 stateful session：transcript 有两轮，最新 request 只有本轮一句时，仍保留 transcript 的两轮
    live_trace = SimpleNamespace(
        turn_records=[{"request": {"body": {"messages": [{"role": "user", "content": "追问一句"}]}}}],
        normalized_request={"body": {"messages": [{"role": "user", "content": "第一问"}]}},
        conversation_transcript=[{"role": "user", "query": "第一问"}, {"role": "user", "query": "追问一句"}],
    )
    assert user_turns(live_trace) == ["第一问", "追问一句"]


def test_materials_does_not_inject_same_turn_model_exact_request():
    """Bug2: planning_routing / knowledge_data 不再硬塞同轮未引用的 model_calls.exact_request。"""
    from impl.projects.llm_probe_loop.business_trace.materials import material_view

    dossier = {
        "sources": [],
        "contents": {},
        "records": [
            {"id": "trace", "kind": "runs", "turn": "turn1", "fields": {"input": {"status": "available", "value": "问题"}}},
            {"id": "llm/1", "kind": "model_calls", "turn": "turn1",
             "fields": {"exact_request": {"status": "available", "value": {"messages": ["LEAK"]}}}},
        ],
    }
    link = {"link_id": "planning_routing:path:turn1", "link_type": "planning_routing", "turn": "turn1",
            "input": [{"ref": "trace", "field": "input"}], "output": []}
    view = material_view(dossier, [link], [])
    assert [r["id"] for r in view["records"]] == ["trace"]


def test_input_view_whitelists_input_fields_and_definitions_dropping_tool_shells():
    """Bug3: input_view 除 definitions 外只留 input 声明的字段；纯输出端工具调用整条剔除，输入输出共用工具调用不漏执行态字段。"""
    from impl.projects.llm_probe_loop.business_trace.materials import material_view
    from impl.projects.llm_probe_loop.process_axes import input_view

    dossier = {
        "sources": [],
        "contents": {},
        "records": [
            {"id": "trace", "kind": "runs", "turn": "turn1", "fields": {"input": {"status": "available", "value": "查保单"}}},
            {
                "id": "obs/13",
                "kind": "tool_calls",
                "name": "policy_detail",
                "turn": "turn1",
                "fields": {
                    "arguments": {"status": "available", "value": {"policy_no": "1"}},
                    "result": {"status": "available", "value": {"ok": True}},
                    "start_time": {"status": "available", "value": "2026-11-15T16:25:41Z"},
                    "end_time": {"status": "available", "value": "2026-11-15T16:25:46Z"},
                    "status_message": {"status": "available", "value": "OK"},
                },
            },
            {
                "id": "def/1",
                "kind": "definitions",
                "name": "policy_detail",
                "definition_type": "tool",
                "turn": "turn1",
                "fields": {"description": {"status": "available", "value": "查保单详情"}},
            },
        ],
    }
    # 1) planning_routing: obs/13 只在输出端，input_view 整条删掉 obs/13，保留 trace 与 definitions
    pr_link = {"link_id": "planning_routing:path:turn1", "link_type": "planning_routing", "turn": "turn1",
               "input": [{"ref": "trace", "field": "input"}],
               "output": [{"ref": "obs/13", "field": "arguments"}, {"ref": "obs/13", "field": "result"}]}
    pr_in = input_view(dossier, [pr_link])
    pr_ids = {r["id"] for r in pr_in["records"]}
    assert pr_ids == {"trace", "def/1"}

    # 2) tool_execution: obs/13 的 arguments 在输入端、result 在输出端；本应只留 arguments，实际保留全部执行态字段
    te_link = {"link_id": "tool_execution:obs/13", "link_type": "tool_execution", "turn": "turn1",
               "input": [{"ref": "obs/13", "field": "arguments"}],
               "output": [{"ref": "obs/13", "field": "result"}]}
    te_in = input_view(dossier, [te_link])
    te_in_map = {r["id"]: r["fields"] for r in te_in["records"]}
    assert set(te_in_map) == {"obs/13", "def/1"}
    assert set(te_in_map["obs/13"]) == {"arguments"}

    te_full = material_view(dossier, [te_link], [])
    te_full_map = {r["id"]: r["fields"] for r in te_full["records"]}
    assert {"arguments", "result", "start_time", "end_time", "status_message"} <= set(te_full_map["obs/13"])


