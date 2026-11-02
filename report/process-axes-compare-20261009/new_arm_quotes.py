"""新方案 v3 臂（new2）：在 new_arm 的两次调用上只加两件事，不再有任何逐 case 的程序检查。

1. 第二次调用的每个判定行必须带 1–2 段**逐字短引文**（记录 id + 原文）；程序只做一件通用的事：
   引文是否真在那条记录里。不在 → 带着清单让模型重写一次；仍不在 → 这条判定降成「无法核」。
2. context_memory 轴在第一次调用里带两条通用职责（交付缺口说明须来自上游、执行余量提示须随用量更新），
   由模型写成本 case 的具体条目，然后和别的条目一样判。

用法：python new_arm_quotes.py --pass 1 [--tags a,b]    （结果在 runs/new3/pass<N>/）
"""
from __future__ import annotations

import json
import sys
import traceback
from dataclasses import dataclass

import experiment_io as io

sys.path.insert(0, str(io.ROOT))
sys.path.insert(0, str(io.HERE))

import new_arm as N  # noqa: E402
from cmp_view import normalize  # noqa: E402
from impl.core.structured_output import StructuredOutputSpec  # noqa: E402
from llm_transport import Transport  # noqa: E402

ARM = "new3"  # new2 = 每行都强制引文（已跑一遍，结果留作对照）；new3 = 只对「没达到/意外」强制
N.ARM = ARM


@dataclass
class Quote:
    ref: str      # 引文所在记录的 id（材料里 records[].id）
    quote: str    # 从该记录逐字摘录的短句（建议 40 字以内，不要改写、不要省略号拼接）


@dataclass
class ActualItem:
    id: str
    links: list[str]
    observed: str
    quotes: list[Quote]
    verdict: str


@dataclass
class UnexpectedItem:
    id: str
    observed: str
    links: list[str]
    quotes: list[Quote]
    why: str


@dataclass
class Problem:
    phenomenon: str
    items: list[str]
    attribution: str
    impact: str


@dataclass
class ActualList:
    actual: list[ActualItem]
    unexpected: list[UnexpectedItem]
    problems: list[Problem]
    reason: str
    scope_note: str


ACTUAL_SPEC = StructuredOutputSpec.from_dataclass(
    ActualList, required_nonempty=["actual", "reason", "scope_note"],
    description="逐条对应本应清单的实际结果；verdict 取 达到/没达到/无法核；attribution 取 本轴/上游:<轴>/未定位:<候选轴>。")

ACTUAL_SYSTEM = N.ACTUAL_SYSTEM.replace(
    "refs` 写记录 id 或原文片段；", "quotes` 写 1–2 段逐字短引文；").replace(
    "- 程序判定条目是程序逐字比对的机械结果，可能只是表示形式不同，必须读两端原文再下结论，不得直接照抄为问题；\n", "") + """
引文规则（程序会逐条核对，「没达到」和 unexpected 的引文不在对应记录里的会让你重写，仍不对则该条降成「无法核」）：
- 每个 verdict=没达到 的行和每个 unexpected，至少 1 段 `quotes`：{ref: 记录 id, quote: 从该记录逐字摘出的短句}；verdict=达到 的行引文可选（有能直接证明的原文就引，没有就留空，不要硬凑）；
- 判「没达到」，如果要靠两处对比才能看出（例如上游写了什么、下游变成了什么；前一次请求里的某句、后一次请求里同一句），两处都要引；
- 引文要短而关键（一般 40 字以内），只摘支撑结论的那一句，不改写、不用省略号拼接；
- 无法核的行可以没有引文，但 observed 要说清为什么没法核。"""

STANDING = {
    "context_memory": [
        "交付里的缺口说明（gaps/limitations）和完整度状态，必须来自上游步骤或模型产出，包裹/交付步骤不得凭空新增缺口或把状态改成 PARTIAL。",
        "同一轮内多次模型请求里的「执行余量」提示必须随已用的调用/工具次数更新，不得逐字不变。",
    ],
}

_expected_prompt = N.expected_prompt


def expected_prompt(axis, body, material):
    base = json.loads(_expected_prompt(axis, body, material))
    if STANDING.get(axis):
        base["每个 case 必带的通用职责"] = STANDING[axis]
        base["写作要求"] += "「通用职责」每条各写成一条 expected（about 点出本 case 对应的环节），不要省略。"
    return json.dumps(base, ensure_ascii=False)


N.expected_prompt = expected_prompt


def _leaves(value):
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


def _squash(text):
    return "".join(str(text).split())


def record_leaves(view):
    out = {}
    for rec in normalize(view):
        texts = []
        for info in rec["fields"].values():
            texts += [_squash(t) for t in _leaves(info.get("value"))]
        out[rec["id"]] = texts
    return out


def _bad_quotes(row, leaves):
    out = []
    for q in row.get("quotes") or []:
        ref, quote = q.get("ref"), _squash(q.get("quote") or "")
        if not quote or ref not in leaves or not any(quote in t for t in leaves[ref]):
            out.append({"row": row.get("id"), "ref": ref, "quote": q.get("quote"),
                        "why": "记录 id 不在材料里" if ref not in leaves else "原文里找不到这段"})
    return out


def check_quotes(actual, leaves):
    """返回 (必须修的坏引文, 引文总数)。只有「没达到」行和 unexpected 的坏引文会触发重写；
    「达到」行的坏引文直接丢弃，不要求重写。"""
    bad, total = [], 0
    for kind in ("actual", "unexpected"):
        for row in actual.get(kind) or []:
            total += len(row.get("quotes") or [])
            if kind == "unexpected" or row.get("verdict") == "没达到":
                bad += _bad_quotes(row, leaves)
    return bad, total


def run_batch(axis, frozen, dossier, analysis, body, links, suspects, extra_refs, index, tag_label):
    transport = Transport(N.PROVIDER, N.MODEL, arm=ARM, tag=tag_label)
    c1 = N.input_only_view(dossier, links)
    c2 = N.full_view(dossier, links, suspects, extra_refs)
    leaves = record_leaves(c2)
    record = {"axis": axis, "batch": index, "links": [l["link_id"] for l in links],
              "leak_check": N.leak_check(c1, c2, links), "prompts": [], "http_attempts": [], "program_entries": []}
    trace = f"{frozen['run_id']}:{axis}:b{index}"
    try:
        expected = transport.complete_json(N.EXPECTED_SYSTEM, expected_prompt(axis, body, c1), trace_id=trace,
                                           reasoning_effort="low", output_spec=N.EXPECTED_SPEC,
                                           stage=f"expected_{axis}_b{index}")
        record["expected"] = expected
        record["expected_sha256"] = io.digest(json.dumps(expected, ensure_ascii=False, sort_keys=True))
        user = N.actual_prompt(axis, body, c2, expected, links, [])
        actual = transport.complete_json(ACTUAL_SYSTEM, user, trace_id=trace, reasoning_effort="low",
                                         output_spec=ACTUAL_SPEC, stage=f"actual_{axis}_b{index}")
        bad, total = check_quotes(actual, leaves)
        stats = {"total": total, "bad_first": len(bad), "retried": False, "bad_final": len(bad), "demoted": []}
        if bad:
            fix = json.dumps({"上次输出": actual, "引文核对未通过": bad,
                              "要求": "只改这些引文：换成对应记录里逐字存在的短句（或换对的记录 id）；"
                                      "找不到支撑就把该行改成无法核。其余内容保持不变，完整重新输出。"}, ensure_ascii=False)
            actual = transport.complete_json(ACTUAL_SYSTEM, user + "\n\n" + fix, trace_id=trace, reasoning_effort="low",
                                             output_spec=ACTUAL_SPEC, stage=f"actual_fix_{axis}_b{index}")
            bad, total = check_quotes(actual, leaves)
            stats.update(retried=True, bad_final=len(bad), total_final=total)
        for kind in ("actual", "unexpected"):
            for row in actual.get(kind) or []:
                row["quotes"] = [q for q in row.get("quotes") or [] if not _bad_quotes({"quotes": [q]}, leaves)]
        for row in actual.get("actual") or []:
            if row.get("verdict") == "没达到" and not row.get("quotes"):
                stats["demoted"].append({"id": row["id"], "was": row["verdict"]})
                row["verdict"] = "无法核"
        by_id = {r["id"]: r for r in (actual.get("actual") or []) + (actual.get("unexpected") or [])}
        for problem in actual.get("problems") or []:
            problem["refs"] = sorted({q["ref"] for i in problem.get("items") or [] for q in (by_id.get(i) or {}).get("quotes") or []})
        for row in by_id.values():
            row["refs"] = sorted({q["ref"] for q in row.get("quotes") or []})
        record["actual"] = actual
        record["quote_stats"] = stats
    except Exception as exc:  # noqa: BLE001
        record["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()[-3000:]}
    record["prompts"] = [{"stage": "expected"}, {"stage": "actual"}]
    record["http_attempts"] = [{k: v for k, v in a.items() if k not in {"arm", "started_at"}} for a in transport.attempts]
    return record


N.run_batch = run_batch

if __name__ == "__main__":
    N.main()
