"""过程六轴的「本应清单 / 实际清单」判法（spec/alg/process-axes.md §2–§5、§13）。

每个轴、每批材料两次调用，第二次以多轮追加方式发送（前缀命中缓存）：

  第一次  [system, user1]                                 user1 = 本应清单任务 + 输入端材料
  第二次  [system, user1, assistant(冻结的本应清单), user2] user2 = 实际清单任务 + 第一次没给的字段
  纠错    [..., assistant(被拒收的实际清单), user3]        至多一轮：引文核对与结构检查的全部问题一次给出

程序负责：材料切分（第一次看不到输出端字段）、冻结、条目对齐、引文核对、needs_external 锁无法核、
轴 verdict 汇总与组成、问题记录。模型负责：本应清单、实际与判定、意外、问题与归因。
依据：report/process-axes-compare-20261009（实验 new4）。
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from impl.core.llm_client import OutputRejected, with_output_constraint
from impl.core.structured_output import StructuredOutputSpec
from impl.projects.llm_probe.business_trace.materials import material_view, model_material

from ..llm import axis_llm
from ..types import AxisSummary, RunOutcome, raise_for_error_payload

# ---- 输出结构 -------------------------------------------------------------------------------

MET, NOT_MET, UNCHECKABLE = "达到", "没达到", "无法核"
LOCAL, UPSTREAM, UNRESOLVED = "本轴", "上游:", "未定位:"


@dataclass
class ExpectedItem:
    id: str = field(metadata={'description': '本批内唯一的短编号，如 E1'})
    about: str = field(metadata={'description': '针对输入里的哪个对象或环节（记录编号、需求编号、原话里的条件）'})
    subcapability: str = field(metadata={'description': '取给定子能力之一；都不合适写「其他」'})
    statement: str = field(metadata={'description': '做对时必须成立什么；具体到能核对（对象、地点、条件、数量）'})
    basis: str = field(metadata={'description': '依据：输入里的原文片段或记录编号（给了通用职责时写「通用职责 D1」这样带编号）'})
    needs_external: Literal['是', '否', '不确定'] = field(
        metadata={'description': '是否必须独立查证（例如库里到底有没有）才判得了'})
    turn: str = field(metadata={'description': '这条属于哪一轮（tN，取本批材料含有的轮）'})


@dataclass
class ExpectedList:
    expected: list[ExpectedItem] = field(metadata={'nonempty': True})
    not_covered: list[str] = field(metadata={'description': '写不全、拿不准、本次看不到的范围；本次不需要的子能力也写在这里并说明'})


@dataclass
class Quote:
    ref: str = field(metadata={'description': '原文所在记录的编号（records[].id），只写编号'})
    quote: str = field(metadata={'description': '从该记录逐字摘出的短句（一般 40 字以内），不改写、不用省略号拼接'})


@dataclass
class ActualItem:
    id: str = field(metadata={'description': '与本应清单的 id 一一对应'})
    links: list[str] = field(metadata={'description': '落在哪些实际环节（link_id）'})
    observed: str = field(metadata={'nonempty': True, 'description': '实际是什么'})
    quotes: list[Quote] = field(metadata={'description': '没达到时至少一段；要靠两处对比才看得出的两处都引；达到时可选'})
    verdict: Literal['达到', '没达到', '无法核'] = field(metadata={'description': '无法核时 observed 说清为什么核不了'})


@dataclass
class UnexpectedItem:
    id: str = field(metadata={'description': '短编号，如 X1'})
    observed: str = field(metadata={'nonempty': True})
    links: list[str]
    quotes: list[Quote] = field(metadata={'nonempty': True})
    why: str = field(metadata={'nonempty': True, 'description': '为什么这是个问题'})


@dataclass
class Problem:
    phenomenon: str = field(metadata={'nonempty': True})
    items: list[str] = field(metadata={'nonempty': True, 'description': '只引用没达到的条目 id 或 unexpected 的 id'})
    attribution: str = field(metadata={'pattern': r'^(本轴|上游:.+|未定位:.+)$',
                                       'description': '本轴 / 上游:<轴> / 未定位:<候选轴，逗号分隔>'})
    impact: str = field(metadata={'nonempty': True, 'description': '对最终交付的影响'})
    same_as: str = field(default='', metadata={'allow_empty': True,
                         'description': '与「本轴前面批次已记录的问题」里某条是同一个问题时填它的 problem_id；否则留空'})


@dataclass
class ActualList:
    actual: list[ActualItem] = field(metadata={'nonempty': True})
    unexpected: list[UnexpectedItem]
    problems: list[Problem]
    reason: str = field(metadata={'nonempty': True, 'description': '一句话本轴结论'})
    scope_note: str = field(metadata={'nonempty': True, 'description': '这次没覆盖到的范围'})


EXPECTED_SPEC = StructuredOutputSpec.from_dataclass(
    ExpectedList, description="做对时必须成立的条目清单（本应清单）。")
ACTUAL_SPEC = StructuredOutputSpec.from_dataclass(
    ActualList, description="逐条对应本应清单的实际结果、意外与问题。")

# ---- 提示词 ---------------------------------------------------------------------------------

SYSTEM = ("你是过程评测员。这次评测分两步：第一步只看输入端材料，写「本应清单」；第二步拿到输出端补充材料，"
          "逐条核对，写「实际清单」。每一步的具体要求和输出结构写在该步的消息里；前一步给过的材料后一步仍然有效，编号沿用。")

EXPECTED_TASK = """【第一步：本应清单】你只看得到这个轴在本次运行里的输入端材料，看不到运行实际产出了什么。

写：在这样的输入下，做对时必须成立什么。要求：
- 每条 statement 具体到能核对（点得出对象、地点、条件、数量）；
- 只写这个输入本身提出的要求，不猜运行结果，不写"如果…则…"的假设条目；
- 要求系统应该发生的动作（例如必须取数），先想清：要不要外部数据、系统有什么办法拿到、当时是否仍必须行动（已有有效数据或等价路径就不写）；
- basis 引输入里的原文片段或记录编号；
- 本批可能含几轮的材料（记录编号里的 turnN 是第 N 轮），需求清单每条也标了 turn：每条本应只依据同一轮的需求和该轮的材料写，turn 填那一轮；不拿一轮的需求去要求另一轮的材料（例如用户在后一轮更正了对象，前一轮按原对象处理不算错）；
- subcapability 取给定子能力之一，都不合适写「其他」；
- needs_external：这条是否必须独立查证（例如库里到底有没有、数据源是否真缺失）才判得了；
- 写不全、拿不准、本次看不到的放进 not_covered；本次确实不需要的子能力也在 not_covered 里点名说明。"""

ACTUAL_TASK = """【第二步：实际清单】下面是本轴的输出端补充材料。上一步你写的本应清单已冻结。

写：逐条实际是什么。要求：
- actual 的 id 与本应清单一一对应，不得增删改；落在哪些实际环节写进 links（link_id）；verdict 取 达到 / 没达到 / 无法核；
- 本应清单没料到、但实际发生的行为（多调了不该调的、改措辞重复查询、交付覆盖了模型产出等）写进 unexpected；
- problems 只能由没达到的条目或 unexpected 生成，items 写它们的 id；每个没达到的条目、每个 unexpected 都要被至少一条 problem 引用；
- attribution：本轴（这个部件在有效输入下做错了）/ 上游:<轴>（它依赖的输入已被上游弄坏）/ 未定位:<候选轴>（看得出不对、说不清是哪一段）；
- 「本轴前面批次已记录的问题」里已有的同一个问题（同一处毛病，即使引的是另一种记录形式），照常写进 problems，same_as 填它的 problem_id；
- needs_external=是 的条目由程序锁成无法核；
- reason 一句话说本轴结论，scope_note 写这次没覆盖到的范围。

引文规则（程序逐条核对，不在所引记录里的会退回，仍不对则丢弃；没达到的行丢光引文就降成无法核）：
- 没达到的行和每个 unexpected 至少一段 quotes：{ref: 记录编号, quote: 从该记录逐字摘出的短句}；
- 要靠两处对比才看得出的（上游写了什么、下游变成了什么；前一次请求里的某句、后一次请求里同一句），两处都引；
- 引文短而关键（一般 40 字以内），不改写、不用省略号拼接；达到的行引文可选，有能直接证明的原文就引；
- 原文里的英文双引号在引文里一律写成中文引号“”（程序核对时视为同一字符），反斜杠不要抄进引文；尽量摘不带引号的那一段。"""

# 只在本轴有通用职责时接在第一步要求后面；没有通用职责的轴不提这件事。
DUTY_RULE = ("- 「通用职责」逐条、逐轮看：本批材料涉及它说的环节时，每轮写成一条（about 点出本 case 对应的环节，"
             "statement 写本 case 的具体要求而不是职责原文，basis 写「通用职责 D1」这样带编号）；"
             "本批材料不涉及时不写，在 not_covered 里写「通用职责 D1：本批不涉及」。")

# spec/alg/process-axes.md §3.4：每个 case 都带的固定条目（需求 §5 ⟡ 待补）。
STANDING_DUTIES = {
    "context_memory": (
        "交付里的缺口说明（gaps / limitations）与完整度状态必须来自上游步骤或模型产出，包裹、交付步骤不得凭空新增缺口或改成 PARTIAL。",
        "同一轮内多次模型请求里的「执行余量」提示必须随已用的调用、工具次数更新，不得逐字不变。",
    ),
}

# ---- 材料：第一次只给输入端（§2.1），第二次只发第一次没给的 ---------------------------------

_TOKEN = re.compile(r"(?:shared|content)#\d+")
_META = ("format", "gaps", "missing_endpoints", "excluded", "input_limitations", "reading_guide")


def input_view(dossier: Mapping[str, Any], links: list[Mapping[str, Any]]) -> dict[str, Any]:
    """第一步的材料：本批环节的记录，摘掉每条 link 声明的输出端字段。结构保证，不靠事后扫描。"""
    drop = {(end["ref"], end.get("field", "")) for link in links for end in link.get("output") or []}
    keep = {(end["ref"], end.get("field", "")) for link in links for end in link.get("input") or []}
    view = copy.deepcopy(material_view(dossier, links, []))
    for rec in view.get("records") or []:
        fields = rec.get("fields") or {}
        for name in [n for n in fields if (rec.get("id"), n) in drop and (rec.get("id"), n) not in keep]:
            fields.pop(name)
    view["missing_endpoints"] = [m for m in view.get("missing_endpoints", []) if m.get("side") != "output"]
    view["reading_guide"] = ("第一步只给输入端材料：记录里只有本轴读到的输入字段，"
                             "输出端（返回、报错、模型产出、交付）没有注入。")
    return model_material(view)


def _closure(obj: Any, shared: Mapping[str, Any], contents: Mapping[str, Any]) -> set[str]:
    todo, seen = set(_TOKEN.findall(json.dumps(obj, ensure_ascii=False))), set()
    while todo:
        key = todo.pop()
        if key in seen:
            continue
        seen.add(key)
        body = shared.get(key) if key.startswith("shared#") else contents.get(key)
        todo |= set(_TOKEN.findall(json.dumps(body, ensure_ascii=False))) - seen
    return seen


def split_views(first: Mapping[str, Any], full: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """把完整材料切成（第一次材料, 第二次补充）。第一次的记录与字段 ⊆ first；两者合起来 = full。"""
    shared, contents = dict(full.get("shared_contents") or {}), dict(full.get("contents") or {})
    allowed = {rec.get("id"): rec for rec in first.get("records") or []}
    part1, part2 = [], []
    for rec in full.get("records") or []:
        seen = allowed.get(rec.get("id"))
        if seen is None:
            part2.append(rec)
            continue
        fields = rec.get("fields") or {}
        keep = {k: v for k, v in fields.items() if k in (seen.get("fields") or {})}
        part1.append({**{k: v for k, v in rec.items() if k != "fields" and k in seen}, "fields": keep})
        rest_top = {k: v for k, v in rec.items() if k != "fields" and k not in seen}
        rest_fields = {k: v for k, v in fields.items() if k not in keep}
        if rest_top or rest_fields:
            part2.append({"id": rec.get("id"), **rest_top, "fields": rest_fields})
    keys1 = _closure(part1, shared, contents)
    keys2 = _closure(part2, shared, contents) - keys1

    def pack(records, keys, meta):
        return {**meta, "records": records,
                "shared_contents": {k: shared[k] for k in sorted(keys) if k in shared},
                "contents": {k: contents[k] for k in sorted(keys) if k in contents}}

    meta1 = {k: first[k] for k in _META if k in first}
    meta2 = {k: full[k] for k in _META if k in full and k != "format"}
    meta2["reading_guide"] = "补充材料：上一步没给的记录与字段（含输出端），以及它们新引用到的共享内容；编号与上一步一致。"
    return pack(part1, keys1, meta1), pack(part2, keys2, meta2)


def merge_views(part1: Mapping[str, Any], part2: Mapping[str, Any]) -> dict[str, Any]:
    """split_views 的逆运算（核对切分无损用）。"""
    out = copy.deepcopy(dict(part1))
    by_id = {rec.get("id"): rec for rec in out["records"]}
    for rec in copy.deepcopy(part2["records"]):
        old = by_id.get(rec.get("id"))
        if old is None:
            out["records"].append(rec)
            by_id[rec.get("id")] = rec
            continue
        fields = rec.pop("fields", {})
        old.update(rec)
        old.setdefault("fields", {}).update(fields)
    out["shared_contents"] = {**out["shared_contents"], **part2["shared_contents"]}
    out["contents"] = {**out["contents"], **part2["contents"]}
    return out


def _unshare(value: Any, shared: Mapping[str, Any]) -> Any:
    if isinstance(value, dict):
        if set(value) == {"shared_ref"}:
            return _unshare(shared.get(value["shared_ref"]), shared)
        return {k: _unshare(v, shared) for k, v in value.items()}
    if isinstance(value, list):
        return [_unshare(v, shared) for v in value]
    return value


def record_fields(view: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """记录编号 → 字段（共享内容已还原）。"""
    shared = view.get("shared_contents") or {}
    return {rec.get("id"): {name: _unshare(info, shared) for name, info in (rec.get("fields") or {}).items()}
            for rec in view.get("records") or []}


# ---- 引文核对 ---------------------------------------------------------------------------------

def _leaves(value: Any):
    if isinstance(value, str):
        yield value
        try:
            parsed = json.loads(value)
        except ValueError:
            return
        if not isinstance(parsed, str):
            yield from _leaves(parsed)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _leaves(v)
    elif isinstance(value, list):
        for v in value:
            yield from _leaves(v)


_QUOTE_MARKS = str.maketrans({"“": '"', "”": '"'})


def _squash(text: Any) -> str:
    """逐字核对的规范形：去空白；中文引号视同英文双引号（引文里的原文双引号要求写成“”，免得弄坏输出 JSON）。"""
    return "".join(str(text).split()).translate(_QUOTE_MARKS)


def record_texts(view: Mapping[str, Any]) -> dict[str, list[str]]:
    """记录编号 → 该记录全部正文叶子（去空白），供逐字核对。"""
    return {rid: [_squash(t) for info in fields.values() for t in _leaves(info.get("value") if isinstance(info, Mapping) else info)]
            for rid, fields in record_fields(view).items()}


def bad_quotes(row: Mapping[str, Any], texts: Mapping[str, list[str]]) -> list[dict[str, str]]:
    out = []
    for q in row.get("quotes") or []:
        ref, quote = q.get("ref"), _squash(q.get("quote") or "")
        if ref not in texts:
            out.append({"row": row.get("id"), "ref": ref, "quote": q.get("quote"), "why": "记录编号不在材料里"})
        elif not quote or not any(quote in t for t in texts[ref]):
            out.append({"row": row.get("id"), "ref": ref, "quote": q.get("quote"), "why": "所引记录里找不到这段原文"})
    return out


# ---- 结构检查（纠错轮的依据） ------------------------------------------------------------------

def check_actual(actual: Mapping[str, Any], expected: Mapping[str, Any],
                 texts: Mapping[str, list[str]], earlier_ids: frozenset[str] = frozenset()) -> tuple[list[str], list[str]]:
    """返回（结构问题, 引文问题）。纠错轮把两类一起给模型；纠错后仍有结构问题是评测器错误，
    仍有引文问题则由 settle 丢弃坏引文、降级（§4）。达到行的坏引文不在这里报（直接丢弃）。"""
    structure: list[str] = []
    quotes: list[str] = []
    ids = [item["id"] for item in expected["expected"]]
    got = [row["id"] for row in actual["actual"]]
    if sorted(got) != sorted(ids) or len(set(got)) != len(got):
        structure.append(f"actual 的 id 必须与本应清单一一对应：本应 {ids}，实际 {got}")
    failed = {row["id"] for row in actual["actual"] if row["verdict"] == NOT_MET}
    unexpected = {row["id"] for row in actual["unexpected"]}
    cited: set[str] = set()
    for problem in actual["problems"]:
        stray = [i for i in problem["items"] if i not in failed and i not in unexpected]
        if stray:
            structure.append(f"问题「{problem['phenomenon'][:40]}」引用了不是没达到、也不是 unexpected 的 id：{stray}")
        if problem.get("same_as") and problem["same_as"] not in earlier_ids:
            structure.append(f"问题「{problem['phenomenon'][:40]}」的 same_as={problem['same_as']} 不在前面批次已记录的问题里")
        cited |= set(problem["items"])
    orphan = sorted((failed | unexpected) - cited)
    if orphan:
        structure.append(f"这些没达到的条目或 unexpected 没有被任何 problem 引用：{orphan}")
    for row in actual["actual"]:
        if row["verdict"] == NOT_MET and not row.get("quotes"):
            quotes.append(f"{row['id']} 判没达到但没有引文")
        if row["verdict"] == NOT_MET:
            quotes += [json.dumps(b, ensure_ascii=False) for b in bad_quotes(row, texts)]
    for row in actual["unexpected"]:
        quotes += [json.dumps(b, ensure_ascii=False) for b in bad_quotes(row, texts)]
    return structure, quotes


def settle(actual: dict[str, Any], expected: Mapping[str, Any], texts: Mapping[str, list[str]]) -> dict[str, Any]:
    """纠错之后的程序处理：丢坏引文、锁 needs_external、没引文的没达到降无法核、清掉失去依据的问题。"""
    locked = {item["id"] for item in expected["expected"] if item["needs_external"] == "是"}
    demoted: list[dict[str, str]] = []
    for kind in ("actual", "unexpected"):
        for row in actual[kind]:
            row["quotes"] = [q for q in row.get("quotes") or [] if not bad_quotes({"quotes": [q]}, texts)]
            row["refs"] = sorted({q["ref"] for q in row["quotes"]})
    for row in actual["actual"]:
        if row["id"] in locked and row["verdict"] != UNCHECKABLE:
            demoted.append({"id": row["id"], "was": row["verdict"], "why": "必须独立查证"})
            row["verdict"] = UNCHECKABLE
        elif row["verdict"] == NOT_MET and not row["quotes"]:
            demoted.append({"id": row["id"], "was": row["verdict"], "why": "没有能核对的引文"})
            row["verdict"] = UNCHECKABLE
    actual["unexpected"] = [row for row in actual["unexpected"] if row["quotes"]]
    live = {row["id"] for row in actual["actual"] if row["verdict"] == NOT_MET} | {row["id"] for row in actual["unexpected"]}
    kept = []
    for problem in actual["problems"]:
        problem["items"] = [i for i in problem["items"] if i in live]
        if problem["items"]:
            kept.append(problem)
    actual["problems"] = kept
    actual["demoted"] = demoted
    return actual


# ---- 一批两次调用 -----------------------------------------------------------------------------

def _clean(payload: Any) -> dict[str, Any]:
    raise_for_error_payload(payload)
    return {k: v for k, v in payload.items() if k not in {"raw_model_response", "metrics", "_tool_call_log"}}


def expected_prompt(axis_id: str, spec: Any, material: Mapping[str, Any], expectations: Mapping[str, Any]) -> str:
    body: dict[str, Any] = {
        "轴": axis_id, "轴在问什么": spec.question, "本轴不判": spec.excludes,
        "子能力": [{"name": c.name, "什么时候用到": c.when, "做对必须成立": c.duty} for c in spec.subcapabilities],
        "需求清单": expectations.get("expectations") or [], "需求出处": expectations.get("sources") or [],
        "本轴输入端材料": material,
    }
    task = EXPECTED_TASK
    if STANDING_DUTIES.get(axis_id):
        body["通用职责"] = {f"D{k}": duty for k, duty in enumerate(STANDING_DUTIES[axis_id], 1)}
        task += "\n" + DUTY_RULE
    return task + "\n\n" + json.dumps(body, ensure_ascii=False, default=str)


def actual_prompt(axis_id: str, links: list[Mapping[str, Any]], limits: str, material: Mapping[str, Any],
                  earlier: list[Mapping[str, Any]]) -> str:
    return ACTUAL_TASK + "\n\n" + json.dumps({
        "轴": axis_id, "本应清单": "见上一步你的回答（已冻结，id 不得增删改）",
        "本轴前面批次已记录的问题": [{k: p[k] for k in ("problem_id", "phenomenon", "attribution")} for p in earlier],
        "本轴实际环节表": {"limits": limits, "links": [{k: v for k, v in l.items() if k != "data_need"} for l in links]},
        "本轴补充材料": material}, ensure_ascii=False, default=str)


def duty_of(item: Mapping[str, Any], duties: int) -> str:
    """本应条目对应的通用职责编号（D1…）；不是通用职责或编号不在给定范围时为空。"""
    found = re.search(r"通用职责\s*(D\d+)", item.get("basis") or "")
    return found.group(1) if found and 1 <= int(found.group(1)[1:]) <= duties else ""


def _expected_list(client: Any, runtime: Any, axis_id: str, stage: str, user1: str, turns: list[str]) -> dict[str, Any]:
    """第一次调用；不合格时以新一轮追加纠错一次，仍不合格是评测器错误。"""
    history, prompt, duties = None, user1, len(STANDING_DUTIES.get(axis_id) or ())
    for attempt in (1, 2):
        runtime.ensure_time_left(axis_id)
        try:
            expected = _clean(client.complete_json(
                SYSTEM, prompt, trace_id=runtime.trace_id, stage=stage + ("_expected" if attempt == 1 else "_expected_fix"),
                reasoning_effort="low", output_spec=EXPECTED_SPEC, history=history, constraint_in_user=True))
            ids = [item["id"] for item in expected["expected"]]
            issue = f"本应清单的 id 不能重复：{ids}" if len(set(ids)) != len(ids) else ""
            unnumbered = [item["id"] for item in expected["expected"]
                          if duties and "通用职责" in item["basis"] and not duty_of(item, duties)]
            if not issue and unnumbered:
                issue = f"这些条目的 basis 写了通用职责但没写给定的编号（如「通用职责 D1」）：{unnumbered}"
            stray = [item["id"] for item in expected["expected"] if item["turn"] not in turns]
            if not issue and stray:
                issue = f"这些条目的 turn 不是本批材料含有的轮 {turns}：{stray}"
            content = json.dumps(expected, ensure_ascii=False)
        except OutputRejected as exc:
            issue, content = str(exc), exc.content
        if not issue:
            return expected
        if attempt == 2:
            raise ValueError(issue)
        history = [{"role": "user", "content": with_output_constraint(user1, EXPECTED_SPEC)},
                   {"role": "assistant", "content": content}]
        prompt = "上次输出未通过程序检查，请按原任务完整重新输出本应清单，并修正全部问题：\n" + issue
    raise AssertionError("unreachable")


def judge_batch(client: Any, runtime: Any, axis_id: str, spec: Any, number: int, turns: list[str], dossier: Mapping[str, Any],
                links: list[Mapping[str, Any]], full_view: Mapping[str, Any], expectations: Mapping[str, Any],
                limits: str, earlier: list[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """一批（含 turns 这几轮）：本应（冻结）→ 实际（多轮追加）→ 至多一轮纠错 → 程序处理。
    expectations 是这几轮的需求，每条带轮次。不合格抛 ValueError（评测器错误）。"""
    full = model_material(full_view)
    first = input_view(dossier, links)
    part1, part2 = split_views(first, full)
    texts = record_texts(full)
    stage = f"llm_probe_process_{axis_id}_batch{number}"
    user1 = expected_prompt(axis_id, spec, part1, expectations)
    expected = _expected_list(client, runtime, axis_id, stage, user1, turns)
    turn1 = [{"role": "user", "content": with_output_constraint(user1, EXPECTED_SPEC)},
             {"role": "assistant", "content": json.dumps(expected, ensure_ascii=False)}]
    user2 = actual_prompt(axis_id, links, limits, part2, list(earlier))
    earlier_ids = frozenset(p["problem_id"] for p in earlier)
    history = turn1
    prompt = user2
    for attempt in (1, 2):
        runtime.ensure_time_left(axis_id)
        try:
            actual = _clean(client.complete_json(SYSTEM, prompt, trace_id=runtime.trace_id,
                                                 stage=stage + ("_actual" if attempt == 1 else "_actual_fix"),
                                                 reasoning_effort="low", output_spec=ACTUAL_SPEC,
                                                 history=history, constraint_in_user=True))
            content = json.dumps(actual, ensure_ascii=False)
            structure, quotes = check_actual(actual, expected, texts, earlier_ids)
        except OutputRejected as exc:
            content, structure, quotes, actual = exc.content, [str(exc)], [], None
        issues = structure + quotes
        if not issues or (attempt == 2 and not structure):
            break
        if attempt == 2:
            raise ValueError("；".join(structure))
        history = turn1 + [{"role": "user", "content": with_output_constraint(user2, ACTUAL_SPEC)},
                           {"role": "assistant", "content": content}]
        prompt = json.dumps({"未通过程序检查": issues,
                             "要求": "只改这些地方：引文换成所引记录里逐字存在的短句（或换对的记录编号），"
                                     "找不到支撑就把该行改成无法核；id 与本应清单一一对应；"
                                     "每个没达到的条目和 unexpected 都被 problem 引用；same_as 只填前面批次已记录的 problem_id。"
                                     "其余内容不变，完整重新输出。"},
                            ensure_ascii=False)
    actual = settle(actual, expected, texts)
    for k, problem in enumerate(actual["problems"], 1):
        problem["problem_id"] = f"{axis_id}-B{number}-P{k}"
    duties = len(STANDING_DUTIES.get(axis_id) or ())
    return {"number": number, "turns": turns, "links": [l["link_id"] for l in links], "expected": expected, "actual": actual,
            "duties": {item["id"]: duty_of(item, duties) for item in expected["expected"] if duty_of(item, duties)},
            "chars": {"first": len(user1), "second": len(user2)}}


# ---- 汇总（§5）与问题记录（§4） ----------------------------------------------------------------

def _kind(attribution: str) -> str:
    if attribution.startswith(UPSTREAM):
        return "upstream"
    if attribution.startswith(UNRESOLVED):
        return "unresolved"
    return "local"


def standing_duties(batches: list[Mapping[str, Any]]) -> dict[str, str]:
    """通用职责按轮、按轴取值（§3.4）：一条职责在某一轮里（按条目自己的 turn），任一批判出达到 / 没达到即为该值
    （没达到优先），写了但都无法核才是无法核；没有一批写它 = 本轮不涉及，不出现。"""
    found: dict[str, set[str]] = {}
    for b in batches:
        turn_of = {item["id"]: item["turn"] for item in b["expected"]["expected"]}
        for row in b["actual"]["actual"]:
            duty = b["duties"].get(row["id"])
            if duty:
                found.setdefault(f"{turn_of[row['id']]} {duty}", set()).add(row["verdict"])
    return {key: next(v for v in (NOT_MET, MET, UNCHECKABLE) if v in verdicts) for key, verdicts in found.items()}


def aggregate(batches: list[Mapping[str, Any]]) -> tuple[str, str, dict[str, Any]]:
    duties = standing_duties(batches)
    rows = [row for b in batches for row in b["actual"]["actual"] if row["id"] not in b["duties"]]
    problems = [p for b in batches for p in b["actual"]["problems"] if not p.get("same_as")]
    kinds = [_kind(p["attribution"]) for p in problems]
    verdicts = [r["verdict"] for r in rows] + list(duties.values())
    counts = {MET: verdicts.count(MET),
              NOT_MET: verdicts.count(NOT_MET),
              UNCHECKABLE: verdicts.count(UNCHECKABLE),
              "意外": sum(len(b["actual"]["unexpected"]) for b in batches),
              "问题·本轴": kinds.count("local"), "问题·上游": kinds.count("upstream"),
              "问题·未定位": kinds.count("unresolved"),
              "未覆盖": sum(len(b["expected"].get("not_covered") or []) for b in batches)}
    composition = {"counts": counts, "standing_duties": duties,
                   "not_covered": [n for b in batches for n in b["expected"].get("not_covered") or []],
                   "demoted": [d for b in batches for d in b["actual"].get("demoted") or []]}
    if "local" in kinds:
        return "problematic", "local_problem", composition
    if counts[UNCHECKABLE] or "unresolved" in kinds:
        return "not_evaluable", "uncheckable_or_unresolved", composition
    if counts[MET]:
        return "sound", "any_met", composition
    if "upstream" in kinds:
        return "untested", "only_upstream", composition
    return "not_applicable", "nothing_required", composition


def issues_of(axis_id: str, batches: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """每条 problem 一条问题记录；same_as 指向前面批次的同一问题时并进那一条（同一轴内同一问题只记一条）。"""
    issues: dict[str, dict[str, Any]] = {}
    for b in batches:
        expected = {item["id"]: item for item in b["expected"]["expected"]}
        rows = {row["id"]: row for row in b["actual"]["actual"]}
        unexpected = {row["id"]: row for row in b["actual"]["unexpected"]}
        for problem in b["actual"]["problems"]:
            ids = problem["items"]
            from_expected = [expected[i] for i in ids if i in expected]
            found = [rows.get(i) or unexpected[i] for i in ids]
            quotes = [q for row in found for q in row["quotes"]]
            unit = {"axis_id": axis_id, "batch": b["number"], "items": ids, "problem_id": problem["problem_id"]}
            target = issues.get(problem.get("same_as") or "")
            if target is not None:
                target["quotes"] += [q for q in quotes if q not in target["quotes"]]
                target["output_refs"] = sorted(set(target["output_refs"]) | {q["ref"] for q in quotes})
                target["links"] = sorted(set(target["links"]) | {l for row in found for l in row["links"]})
                target["units"].append(unit)
                issues[problem["problem_id"]] = target
                continue
            issues[problem["problem_id"]] = {
                "problem_id": problem["problem_id"],
                "phenomenon": problem["phenomenon"],
                "expected": "；".join(f"{e['statement']}（依据：{e['basis']}）" for e in from_expected)
                            or "；".join("本应清单未覆盖：" + unexpected[i]["why"] for i in ids if i in unexpected),
                "observed": "；".join(row["observed"] for row in found),
                "attribution": _kind(problem["attribution"]), "attribution_detail": problem["attribution"],
                "impact": problem["impact"],
                "origin": "expected" if from_expected else "unexpected",
                "subcapability": sorted({e["subcapability"] for e in from_expected}),
                "links": sorted({l for row in found for l in row["links"]}),
                "quotes": quotes,
                "input_refs": [], "output_refs": sorted({q["ref"] for q in quotes}), "source_refs": [],
                "units": [unit],
            }
    return list({id(issue): issue for issue in issues.values()}.values())


def outcome_of(axis_id: str, batches: list[dict[str, Any]], failures: list[str], usage: dict[str, Any],
               selection: Mapping[str, Any]) -> RunOutcome:
    verdict, rule, composition = aggregate(batches)
    reason = "；".join(b["actual"]["reason"] for b in batches)
    scope = "；".join(b["actual"]["scope_note"] for b in batches)
    issues = issues_of(axis_id, batches)
    results = [{"batch": b["number"], "standing_duty": b["duties"].get(item["id"], ""), **item,
                **{k: v for k, v in row.items() if k != "id"}}
               for b in batches
               for item in b["expected"]["expected"]
               for row in [next(r for r in b["actual"]["actual"] if r["id"] == item["id"])]]
    counts = composition["counts"]
    note = "；组成：" + "、".join(f"{k} {v}" for k, v in counts.items() if v)
    outcome = RunOutcome(
        output={"assessment": {"verdict": verdict, "verdict_rule": rule, "reason": reason, "scope_note": scope,
                               "gaps": composition["not_covered"], "composition": composition},
                "results": results, "issues": issues,
                "unexpected": [{"batch": b["number"], **row} for b in batches for row in b["actual"]["unexpected"]],
                "evidence_refs": sorted({ref for r in results for ref in r["refs"]}
                                        | {ref for i in issues for ref in i["output_refs"]}),
                "missing_evidence": composition["not_covered"],
                "selection": dict(selection),
                "view": {"batches": [{"number": b["number"], "turns": b["turns"], "links": b["links"], "chars": b["chars"]} for b in batches],
                         "failed_batches": failures}},
        summary=AxisSummary(reason + note, [
            {"key": f"{r['subcapability']} @ {r['about']}", "value": r["verdict"],
             "reason": f"本应：{r['statement']}；实际：{r['observed']}",
             "citations": [{"source": "引文", "ref": q["ref"], "note": q["quote"]} for q in r["quotes"]]}
            for r in results]),
        usage=usage)
    if failures:
        # 评测器输出不合格是运行错误（§6），不进条目取值；已通过批次留作诊断。
        outcome.output["assessment"].update(verdict=None, verdict_rule="evaluator_failed")
        outcome.failed = True
        outcome.failure_reason = f"评测器输出未通过校验，{len(failures)}/{len(batches) + len(failures)} 个批次失败：" + "\n".join(failures)
    return outcome


# ---- 入口 -------------------------------------------------------------------------------------

def turn_expectations(expectations: Mapping[str, Any], turns: list[str]) -> dict[str, Any]:
    """一批只用它含有的那几轮的需求与出处（整案出处如业务背景各批都带）。"""
    return {**expectations, "expectations": [e for e in expectations.get("expectations") or [] if e.get("turn") in turns],
            "sources": [s for s in expectations.get("sources") or [] if s.get("turn") in [*turns, "case"]]}


def run_expected_axis(axis_id: str, inputs: Mapping[str, Any], axis: Any, runtime: Any, spec: Any) -> RunOutcome:
    """案卷入口的一轴：批次沿用分析轴的产物，逐批用批里那几轮的需求 judge_batch，再按 §5 汇总。"""
    from impl.projects.llm_probe.business_trace.links import LIMITS
    from dataclasses import replace
    from .process_common import _scenario_entry, project_subcapabilities

    analysis = inputs["trace_analysis"]
    dossier = analysis["dossier"]
    selection = (analysis.get("selections") or {}).get(axis_id) or {}
    batches = selection.get("materials")
    if not batches:
        raise ValueError("分析轴未交付的环节材料")
    client = axis_llm(runtime.spec, role="judge")
    spec = replace(spec, subcapabilities=spec.subcapabilities + project_subcapabilities(_scenario_entry(runtime), axis_id))
    judged, failures = [], []
    for number, batch in enumerate(batches, 1):
        try:
            judged.append(judge_batch(client, runtime, axis_id, spec, number, batch["turns"], dossier, batch["links"],
                                      batch["view"], turn_expectations(inputs["expectations"], batch["turns"]), LIMITS,
                                      [p for b in judged for p in b["actual"]["problems"] if not p.get("same_as")]))
        except ValueError as exc:
            failures.append(f"批次{number}（{len(batch['links'])} 个环节）：{exc}")
    why = selection.get("why") or []
    return outcome_of(axis_id, judged, failures, {**client.usage(), "tool_calls": 0},
                      {"refs": list(selection.get("refs") or []), "why": [why] if isinstance(why, str) else list(why)})
