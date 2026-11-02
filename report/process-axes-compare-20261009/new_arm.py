"""新方案臂（草稿 `spec/draft/process-axes-expected-actual.md`）：本应清单 / 实际清单。

每个 case、每个轴、每个材料批次两次调用：
1. 第一次只看本轴输入（输出端字段不注入），写 `expected` + `not_covered`，原样冻结并记哈希；
2. 第二次看完整材料 + 冻结的本应清单，逐条写 `actual`（id 一一对应）、`unexpected`、`problems`。

程序负责（草稿 §5）：切输入、冻结、对齐校验、`needs_external=是` 锁「无法核」、
传递检查（逐字比对，作为程序条目并入 actual）、泄漏检查。

模型通道与现行臂完全相同（`llm_transport.Transport`）：输出结构注入 + 仓库解析 + `enforce_output`
强校验 + 纠错轮；请求体字段与生产一致（不设 max_tokens、不带 response_format、转发 reasoning_effort）。

用法：python new_arm.py --pass 1 [--tag X] [--tags a,b] [--force]
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import experiment_io as io

sys.path.insert(0, str(io.ROOT))
sys.path.insert(0, str(io.HERE))

import doc_rebuild as D  # noqa: E402
import replay  # noqa: E402
from cmp_view import normalize  # noqa: E402
from llm_transport import Transport  # noqa: E402

from impl.core.structured_output import StructuredOutputSpec  # noqa: E402
from impl.projects.llm_probe.business_trace.materials import material_view, model_material  # noqa: E402
from impl.projects.llm_probe.eval_axes.adapters.process_common import _axis_links  # noqa: E402

MODEL = "gemini-3.8-flash-medium"  # 任务书 §0.5：primary 可用就用它，两臂同一个模型
PROVIDER = "primary"
ARM = "new"

SUBCAPS = {
    "intent_understanding": ["对象与字段一致", "子问题均识别", "约束保留", "指代解析", "歧义识别"],
    "planning_routing": ["路径选择", "工作覆盖", "分支按声明条件", "失败分支有产出", "重复调用有依据",
                         "工具返回后的整合与交付", "结束时机", "系统策略"],
    "tool_execution": ["调用无执行错误", "返回对象与请求一致", "耗时在限"],
    "knowledge_data": ["数据存在（对象存在、字段有值、条目存在）", "对象版本时点匹配"],
    "model_capability": ["输出忠实（不改义、不丢关键信息）", "不编造", "工具调用决策一致", "输出契约遵循"],
    "context_memory": ["传递保留原义", "模型输入组装", "历史与状态使用", "交付保留原义"],
}


@dataclass
class ExpectedItem:
    id: str
    about: str
    subcapability: str
    statement: str
    basis: str
    needs_external: str


@dataclass
class ExpectedList:
    expected: list[ExpectedItem]
    not_covered: list[str]


@dataclass
class ActualItem:
    id: str
    links: list[str]
    observed: str
    refs: list[str]
    verdict: str


@dataclass
class UnexpectedItem:
    id: str
    observed: str
    links: list[str]
    refs: list[str]
    why: str


@dataclass
class Problem:
    phenomenon: str
    items: list[str]
    attribution: str
    impact: str
    refs: list[str]


@dataclass
class ActualList:
    actual: list[ActualItem]
    unexpected: list[UnexpectedItem]
    problems: list[Problem]
    reason: str
    scope_note: str


EXPECTED_SPEC = StructuredOutputSpec.from_dataclass(
    ExpectedList, required_nonempty=["expected"],
    description="做对时必须成立的条目清单；needs_external 取 是/否/不确定；subcapability 取给定的子能力标签或「其他」。")
ACTUAL_SPEC = StructuredOutputSpec.from_dataclass(
    ActualList, required_nonempty=["actual", "reason", "scope_note"],
    description="逐条对应本应清单的实际结果；verdict 取 达到/没达到/无法核；attribution 取 本轴/上游:<轴>/未定位:<候选轴>。")

EXPECTED_SYSTEM = """你是过程评测的「本应清单」整理员。你只看得到这个轴在本次运行里能看到的输入，看不到运行实际产出了什么。

写：在这样的输入下，做对时必须成立什么。要求：
- 每条 `statement` 要具体到能核对（点得出对象、地点、条件、数量），不写通用职责原文；
- 只写这个输入本身提出的要求，不猜运行结果，不写"如果…则…"的假设条目；
- `basis` 必须引用输入里的原文片段或记录 id（如 turn1/records/... 或 E1）；
- `subcapability` 取给定标签之一，都不合适写「其他」；
- `needs_external`：这条是否必须独立查证（例如库里到底有没有、数据源是否真缺失）才判得了，取 是/否/不确定；
- 写不全的部分放进 `not_covered`，不要为了凑数写没把握的条目。"""

ACTUAL_SYSTEM = """你是过程评测的「实际清单」核对员。下面是已冻结的「本应清单」和本次运行的完整材料。

写：逐条实际是什么。要求：
- `actual` 的 id 必须与「本应清单」一一对应，不得增删改；落在哪些实际环节写进 `links`（link id）；`refs` 写记录 id 或原文片段；verdict 取 达到/没达到/无法核；
- 「本应清单」没料到、但实际发生的行为（例如多调了不该调的、改了措辞重复查询）写进 `unexpected`；
- `problems` 只能由 verdict=没达到 的条目或 `unexpected` 生成，`items` 写它们的 id；`attribution` 取 本轴 / 上游:<轴> / 未定位:<候选轴>；
- 程序判定条目是程序逐字比对的机械结果，可能只是表示形式不同，必须读两端原文再下结论，不得直接照抄为问题；
- needs_external=是 的条目由程序锁成「无法核」，你不得改；
- `reason` 一句话说本轴结论，`scope_note` 写这次没覆盖到的范围。"""


# ---------- 材料切分 ----------

def input_only_view(dossier, links):
    """第一次调用只看到输入端材料：把本轴每条 link 的**输出端字段**从材料里摘掉再生成视图。

    构造成立的保证：材料里的输出端只有 link 声明的 output 字段，逐个摘掉后第一次调用
    不可能看到任何输出端值（不靠"扫一遍看有没有重复"来判断）。字段选择和去重口径与
    完整视图完全一致，两边只差输出端。
    """
    drop = {(end["ref"], end.get("field", "")) for link in links for end in link.get("output") or []}
    view = copy.deepcopy(material_view(dossier, links, [], extra_refs=[]))
    for rec in view.get("records") or []:
        fields = rec.get("fields") or {}
        for name in [n for n in fields if (rec.get("id"), n) in drop]:
            fields.pop(name)
    view["missing_endpoints"] = [m for m in view.get("missing_endpoints", []) if m.get("side") != "output"]
    view["reading_guide"] = ("本轴第一次调用只看到输入端材料：记录里只有本轴实际读到的输入字段，"
                             "输出端（返回、报错、模型产出、交付）没有注入。")
    return model_material(view)


def full_view(dossier, links, suspects, extra_refs):
    return model_material(material_view(dossier, links, suspects, extra_refs=extra_refs))


def _output_strings(view):
    """本轴所有输出端字段的正文（用于泄漏检查）。"""
    out = []
    for rec in normalize(view):
        for name, info in rec["fields"].items():
            value = info.get("value")
            if value is not None:
                out.append((rec["id"], name, json.dumps(value, ensure_ascii=False)))
    return out


def leak_check(call1_view, full, links):
    """第一次调用只能看到输入端材料：结构上校验本轴的输出端点字段没有出现在里面。

    另外记一份逐字命中（`byte_hits`）仅供人工复核：案卷本身会把模型发出的工具调用参数
    既存成输出端点（tools/N.arguments）、又存进后续请求的 `exact_request`，于是输出端口的
    正文天然也会被输入端引用到。逐字命中不等于泄漏，是否泄漏看 `output_fields_visible`。
    """
    from cmp_view import normalize

    rows = {r["id"]: r for r in normalize(call1_view)}
    input_ends = {(e["ref"], e.get("field", "")) for link in links for e in link.get("input") or []}
    visible = []
    for link in links:
        for end in link.get("output") or []:
            if (end["ref"], end.get("field", "")) in input_ends:
                continue  # 同一字段同时是本轴输入端（如步骤自身产出），出现在里面不算泄漏
            row = rows.get(end["ref"])
            if row and end.get("field") in row["fields"]:
                visible.append({"ref": end["ref"], "field": end.get("field")})
    text = json.dumps(call1_view, ensure_ascii=False)
    hits = []
    full_rows = {r["id"]: r for r in normalize(full)}
    for link in links:
        for end in link.get("output") or []:
            row = full_rows.get(end["ref"])
            if row is None or end.get("field") not in row["fields"]:
                continue
            value = row["fields"][end["field"]].get("value")
            body = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            if len(body) >= 60 and body in text:
                hits.append({"ref": end["ref"], "field": end["field"], "chars": len(body)})
    return {"output_fields_visible": visible, "real_leak": len(visible), "byte_hits": hits}


# ---------- 程序判定条目（草稿 §5 最后一类） ----------

def _json(value):
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return None


def model_output_text(full):
    """本轮所有模型调用的产出正文（用于判别缺口说明是不是模型自己写的）。"""
    from cmp_view import share_map, unshare
    shared = share_map(full)
    texts = []
    for rec in full.get("records") or []:
        if rec.get("kind") != "model_calls":
            continue
        value = unshare((rec.get("fields") or {}).get("output", {}).get("value"), shared)
        texts.append(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
    return json.dumps(texts, ensure_ascii=False)


def program_entries(full, links, order=None):
    """逐字比对，产出程序条目：每条 {id, check, verdict, observed, refs}。

    只做能逐字判定、不靠语义解释的比对；拿不准就记「无法核」，不制造问题。
    `order` 是记录顺序（trace_analysis.record_order），用来确认「后续输入」真的在该工具调用之后。
    """
    order = order or {}
    rows = normalize(full)
    by_id = {r["id"]: r for r in rows}
    entries = []

    def value_of(rid, field):
        row = by_id.get(rid)
        if not row or field not in row["fields"]:
            return None
        return row["fields"][field].get("value")

    # (1) 交付链上的包裹步骤：产出信封里的 gaps 没写进任何模型产出，是包裹步骤自己加的。
    model_text = model_output_text(full)
    for link in links:
        outs = [(e["ref"], e.get("field", "")) for e in link.get("output") or []]
        if not outs:
            continue
        in_text = json.dumps([[value_of(e["ref"], e.get("field", "")) for e in link.get("input") or []]],
                             ensure_ascii=False)
        for ref, field in outs:
            envelope = _json(value_of(ref, field))
            if not isinstance(envelope, dict) or "gaps" not in envelope or not envelope.get("gaps"):
                continue
            added = [str(g) for g in (envelope.get("gaps") or [])
                     if str(g).strip() and str(g) not in in_text and str(g) not in model_text]
            if added:
                entries.append({"id": f"程序-缺口-{ref.split('/')[-1]}", "check": "交付链未新增缺口",
                                "verdict": "没达到",
                                "observed": f"该环节产出带 status={envelope.get('status')!r}，新增缺口说明"
                                            f"（本轮所有模型产出里都找不到出处，是包裹步骤自己加的）：{added[0][:200]}",
                                "refs": [e["ref"] for e in (link.get("input") or [])] + [ref]})
                break

    # (2) 执行余量提示是否随用量更新。
    pattern = re.compile(r"本轮执行余量\]\s*剩余\s*(\d+)\s*次模型调用[^/]{0,80}?约\s*(\d+)\s*秒")
    seen = []
    for row in rows:
        for info in row["fields"].values():
            body = info.get("value")
            body = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
            match = pattern.search(body or "")
            if match:
                seen.append((row["id"], match.group(1), match.group(2)))
    if len(seen) >= 2 and len({(n, t) for _, n, t in seen}) == 1:
        entries.append({"id": "程序-执行余量提示", "check": "执行余量提示随用量更新",
                        "verdict": "没达到",
                        "observed": f"{len(seen)} 处提示逐字相同（剩余 {seen[0][1]} 次调用、约 {seen[0][2]} 秒），"
                                    f"期间已有新的调用与结果，提示未刷新",
                        "refs": [r for r, _, _ in seen][:6]})

    # (3) 工具返回是否原样进入后续模型输入。
    # 只拿该工具调用**之后**的记录里的请求侧正文字段来比；没有可比的就记「无法核」。
    # 记录里的请求字段本身是投影（可能被压缩），逐字未命中但取值出现在后续输入里时仍记「无法核」。
    for row in rows:
        if "arguments" not in row["fields"] or "result" not in row["fields"]:
            continue
        body = value_of(row["id"], "result")
        body = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        if not body or len(body) < 200:
            continue
        at = order.get(row["id"])
        after = []
        for r in rows:
            if r["id"] == row["id"]:
                continue
            other = order.get(r["id"])
            if at is None or other is None or other <= at:
                continue
            after += [info.get("value") for name, info in r["fields"].items()
                      if name in {"exact_request", "input", "content", "last_user"}]
        if not after:
            entries.append({"id": f"程序-工具返回-{row['id'].split('/')[-1]}", "check": "工具返回原样进入下一次模型输入",
                            "verdict": "无法核", "observed": "材料里没有该调用之后可比的请求侧正文",
                            "refs": [row["id"]]})
            continue
        joined = json.dumps(after, ensure_ascii=False)
        if body[:200] in joined:
            continue
        tokens = {t for t in re.findall(r"[A-Za-z0-9]{6,}|[\u4e00-\u9fa5]{2,}", body) if len(t) >= 2}
        appeared = [t for t in list(tokens)[:400] if t in joined]
        if len(appeared) >= 2:
            entries.append({"id": f"程序-工具返回-{row['id'].split('/')[-1]}", "check": "工具返回原样进入下一次模型输入",
                            "verdict": "无法核",
                            "observed": f"逐字未命中；但结果的取值（如 {'、'.join(appeared[:3])}）出现在后续输入，"
                                        f"记录里的请求字段是投影，无法据此断定未送达",
                            "refs": [row["id"]]})
        else:
            entries.append({"id": f"程序-工具返回-{row['id'].split('/')[-1]}", "check": "工具返回原样进入下一次模型输入",
                            "verdict": "没达到",
                            "observed": "该调用之后的所有请求侧正文里找不到返回正文，也找不到返回里的取值",
                            "refs": [row["id"]]})
    return entries


# ---------- 一轴一次 ----------

def build_case(tag):
    frozen = io.load_json(io.HERE / "frozen" / f"case_{tag}.json")
    dossier = D.build(frozen)
    analysis = D.analysis_output(frozen, dossier)
    return frozen, dossier, analysis


def expected_prompt(axis, body, material):
    return json.dumps({"轴": axis, "轴在问什么": body["dimension_question"], "本轴不判": body["dimension_excludes"],
                       "本轴的子能力提纲": SUBCAPS[axis],
                       "需求侧期望": body.get("expectations") or [],
                       "期望出处": body.get("expectation_sources") or [],
                       "本轴的输入材料": material,
                       "写作要求": "逐条写 expected：about 写输入里可见的对象（如记录 id、E 编号、原话里的条件），"
                                   "statement 写做对时必须成立什么，basis 引原文，needs_external 取 是/否/不确定；"
                                   "not_covered 写这次拿不准、没覆盖的部分。"}, ensure_ascii=False)


def actual_prompt(axis, body, material, expected, links, entries):
    return json.dumps({"轴": axis, "轴在问什么": body["dimension_question"], "本轴不判": body["dimension_excludes"],
                       "需求侧期望": body.get("expectations") or [],
                       "本应清单（已冻结，id 不得增删改）": expected,
                       "本轴实际环节表": {"limits": (body.get("links") or {}).get("limits", ""), "links": links},
                       "本轴完整材料": material,
                       "程序判定条目": entries,
                       "写作要求": "逐条写 actual（id 与冻结清单一一对应）、unexpected、problems；"
                                   "problems.items 只能引用 no-go 的条目 id 或 unexpected 的 id。"}, ensure_ascii=False)


def run_batch(axis, frozen, dossier, analysis, body, links, suspects, extra_refs, index, tag_label):
    transport = Transport(PROVIDER, MODEL, arm=ARM, tag=tag_label)
    selection = analysis.get("selections", {}) or {}
    c1 = input_only_view(dossier, links)
    c2 = full_view(dossier, links, suspects, extra_refs)
    leak = leak_check(c1, c2, links)
    record = {"axis": axis, "batch": index, "links": [l["link_id"] for l in links],
              "leak_check": leak, "prompts": [], "http_attempts": []}
    try:
        record["prompts"].append({"stage": "expected", "user_chars": len(expected_prompt(axis, body, c1))})
        expected = transport.complete_json(EXPECTED_SYSTEM, expected_prompt(axis, body, c1),
                                           trace_id=f"{frozen['run_id']}:{axis}:b{index}", reasoning_effort="low",
                                           output_spec=EXPECTED_SPEC, stage=f"expected_{axis}_b{index}")
        record["expected"] = expected
        record["expected_sha256"] = io.digest(json.dumps(expected, ensure_ascii=False, sort_keys=True))
        entries = program_entries(c2, links,
                                 {p: i for i, p in enumerate(frozen.get("trace_analysis", {}).get("record_order") or [])})
        record["program_entries"] = entries
        record["prompts"].append({"stage": "actual", "user_chars": len(actual_prompt(axis, body, c2, expected, links, entries))})
        actual = transport.complete_json(ACTUAL_SYSTEM, actual_prompt(axis, body, c2, expected, links, entries),
                                         trace_id=f"{frozen['run_id']}:{axis}:b{index}", reasoning_effort="low",
                                         output_spec=ACTUAL_SPEC, stage=f"actual_{axis}_b{index}")
        record["actual"] = actual
    except Exception as exc:  # noqa: BLE001
        record["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()[-3000:]}
    record["http_attempts"] = [{k: v for k, v in a.items() if k not in {"arm", "started_at"}} for a in transport.attempts]
    return record


def reconcile(record):
    """对齐校验 + needs_external 锁定 + problems 引用合法性（草稿 §5）。"""
    expected = record.get("expected") or {}
    actual = record.get("actual") or {}
    items = expected.get("expected") or []
    ids = [i["id"] for i in items]
    external = {i["id"] for i in items if str(i.get("needs_external", "")).startswith("是")}
    violations, problems, adjusted = [], [], 0
    rows, seen = [], set()
    pre_failed = set()
    for row in actual.get("actual") or []:
        row = dict(row)
        if row.get("verdict") == "没达到":
            pre_failed.add(row.get("id"))
        if row.get("id") not in ids or row["id"] in seen:
            violations.append({"kind": "actual_id_mismatch", "id": row.get("id")})
            continue
        seen.add(row["id"])
        if row["id"] in external and row.get("verdict") != "无法核":
            row["verdict"], adjusted = "无法核", adjusted + 1
        rows.append(row)
    missing = [i for i in ids if i not in seen]
    if missing:
        violations.append({"kind": "actual_missing", "ids": missing})
    unexpected = [dict(u) for u in actual.get("unexpected") or []]
    uids = [u.get("id") for u in unexpected]
    failed = {r["id"] for r in rows if r.get("verdict") == "没达到"}
    for problem in actual.get("problems") or []:
        problem = dict(problem)
        legit = [i for i in (problem.get("items") or []) if i in failed or i in uids]
        locked = [i for i in (problem.get("items") or []) if i in pre_failed and i not in failed]
        if locked:
            violations.append({"kind": "problem_item_locked_unverifiable",
                               "problem": problem.get("phenomenon", "")[:80], "items": locked})
        bogus = [i for i in (problem.get("items") or []) if i not in failed and i not in uids and i not in pre_failed]
        if bogus:
            violations.append({"kind": "problem_items_not_grounded", "problem": problem.get("phenomenon", "")[:80],
                               "items": bogus})
        problem["items"] = legit
        if legit:
            problems.append(problem)
    record["actual_rows"] = rows
    record["unexpected"] = unexpected
    record["problems"] = problems
    # 程序条目并入 actual（草稿 §5），不经过模型；模型已经点名的条目不再重复加一条。
    known = {r["id"] for r in rows}
    for entry in record.get("program_entries") or []:
        if entry["id"] in known:
            continue
        rows.append({"id": entry["id"], "links": [], "observed": entry["observed"],
                     "refs": entry["refs"], "verdict": entry["verdict"], "verified_by": "程序"})
    record["alignment"] = {"violations": violations, "needs_external_locked": adjusted,
                           "expected_count": len(ids), "matched": len(seen), "program_entries": len(rows) - len(seen),
                           "failed_count": len({r["id"] for r in rows if r.get("verdict") == "没达到"})}
    for entry in record.get("program_entries") or []:
        if entry["verdict"] != "没达到":
            continue
        related = [p for p in problems if entry["id"] in (p.get("items") or [])]
        for problem in related:
            problem["verified_by"] = "程序"
            problem["program_ref"] = entry["id"]
        if related:
            continue
        problems.append({"phenomenon": f"[程序判定] {entry['check']}：{entry['observed']}",
                         "items": [entry["id"]], "attribution": "本轴", "impact": "程序逐字比对",
                         "refs": entry["refs"], "verified_by": "程序"})
    local = [p.get("attribution", "") for p in problems]
    insufficient = [r["id"] for r in rows if r.get("verdict") == "无法核"]
    if any(a.startswith("本轴") for a in local):
        verdict = "problematic"
    elif not rows and not problems:
        verdict = "not_applicable"
    else:
        verdict = "sound"
    record["verdict"] = verdict
    record["insufficient"] = insufficient
    record["reason"] = (actual.get("reason") or "")[:2000]
    record["scope_note"] = (actual.get("scope_note") or "")[:2000]
    record["attribution_counts"] = {a: local.count(a) for a in set(local)}
    return record


def do_axis(tag, axis, pass_no, frozen, dossier, analysis, force):
    target = io.HERE / "runs" / ARM / f"pass{pass_no}" / tag / f"{axis}.json"
    if target.exists() and not force:
        return {"skipped": True}
    spec = replay.specs()[axis]
    suspects = list(analysis["structure"].get("suspects") or [])
    extra = list((analysis.get("selections", {}).get(axis) or {}).get("refs") or [])
    links = _axis_links(axis, dossier, analysis["structure"])
    batches = frozen["axes"][axis]
    out = {"arm": ARM, "tag": tag, "axis": axis, "model": MODEL, "provider": PROVIDER,
           "axis_links": len(links), "batches": []}
    started = time.monotonic()
    for index, entry in enumerate(batches, 1):
        body = entry["body"]
        links_batch = (body.get("links") or {}).get("links") or []
        got = run_batch(axis, frozen, dossier, analysis, body, links_batch, suspects, extra, index,
                        f"pass{pass_no}/{tag}__{axis}__b{index}")
        out["batches"].append(reconcile(got))
    out["elapsed_seconds"] = round(time.monotonic() - started, 3)
    out["failed"] = any(b.get("error") for b in out["batches"])
    out["failure_reason"] = next((b["error"]["message"] for b in out["batches"] if b.get("error")), None)
    out["verdicts"] = {b["batch"]: b.get("verdict") for b in out["batches"]}
    out["problem_count"] = sum(len(b.get("problems") or []) for b in out["batches"])
    out["program_problems"] = sum(1 for b in out["batches"] for p in (b.get("problems") or []) if p.get("verified_by") == "程序")
    out["leaked"] = sum(b["leak_check"]["real_leak"] for b in out["batches"])
    out["byte_hits"] = sum(len(b["leak_check"]["byte_hits"]) for b in out["batches"])
    out["alignment_violations"] = sum(len(b["alignment"]["violations"]) for b in out["batches"])
    io.save_json(target, out, exclusive=False)
    return {"verdicts": out["verdicts"], "problems": out["problem_count"], "program": out["program_problems"],
            "leaked": out["leaked"], "byte_hits": out["byte_hits"], "violations": out["alignment_violations"], "failed": out["failed"],
            "elapsed": out["elapsed_seconds"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pass", dest="pass_no", default="1")  # 可为 1b：整案重跑放 pass<N>b
    parser.add_argument("--tag", default=None)
    parser.add_argument("--tags", default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    io.init_secret_guard()
    io.verify_prereg()
    tags = [args.tag] if args.tag else ([t for t in args.tags.split(",") if t] if args.tags else list(io.CASES))
    started = time.monotonic()

    def one(tag):
        cached = build_case(tag)
        frozen, dossier, analysis = cached
        rows = {}
        for axis in io.AXES:
            rows[axis] = do_axis(tag, axis, args.pass_no, frozen, dossier, analysis, args.force)
        return {"tag": tag, "axes": rows}

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(one, tags))
    io.save_json(io.HERE / "runs" / ARM / f"pass{args.pass_no}" / "manifest.json",
                 {"arm": ARM, "pass": args.pass_no, "model": MODEL, "provider": PROVIDER,
                  "elapsed_seconds": round(time.monotonic() - started, 3), "cases": results}, exclusive=False)
    for case in results:
        print(case["tag"], {a: r for a, r in case["axes"].items()}, flush=True)
    print(f"{ARM} pass{args.pass_no}: elapsed={round(time.monotonic() - started, 1)}s")


if __name__ == "__main__":
    main()
