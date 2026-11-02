"""Build the complete source dossier, then list the suspect links (W1 §1: S → Λ*).

The program enumerates link instances from Agno structure and marks those whose facts depart
from identity. The analyst reads the index, pulls bodies on demand, and adds semantic suspects
and off-map links, each with the source text it relied on. Every number it cites must have a read
receipt. It never writes or summarizes evidence, and never decides whether a link behaved correctly.
Each process axis then gets its own link types: suspects first, then the ends of every other link.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from impl.core.structured_output import StructuredOutputSpec
from impl.projects.llm_probe.business_trace.dossier import (
    VIEW_BUDGET_CHARS, build_catalog, build_dossier, catalog_ids, render_catalog)
from impl.projects.llm_probe.business_trace.tools import MAX_COLLECT_CHARS, TOOL_GUIDE, EvidenceIndex, build_dossier_tools
from impl.projects.llm_probe.business_trace.links import (
    AXIS_LINK_TYPES, LINK_TYPES, TYPE_AXES, build_links, link_ends, program_suspects)
from ..llm import axis_llm
from ..types import FAILURE_AXIS, FAILURE_MATERIAL, AxisSummary, RunOutcome, ScenarioAxis, raise_for_error_payload

# 分析轴整理阶段：读遍整份案卷的正文不再必要；它按自己的问题定位着读，上限由工具调用数兜住。
PROCESS_AXES = ("intent_understanding", "planning_routing", "tool_execution",
                "context_memory", "knowledge_data", "model_capability")
# 工具调用上限：取回正文用一次批量 collect，剩下的预算只够下钻几个大节点。
# 实测（b3i 系列）：48~64 次往返把会话滚到 61 万字，其中 95% 是重复发送——预算砍到 12，逼「先规划后取」。
TOOL_CALL_LIMIT = 12
# 地图外环节找不到六类之一时的归类：交给用户，所有启用轴都能看到。
UNCLASSIFIED = "unclassified"
_SUSPECT_KEYS = {"link_id", "new_link_type", "input_refs", "output_refs", "why", "source_refs"}


@dataclass(frozen=True)
class Action:
    action: str
    purpose: str
    evidence_refs: list[str]
    input_refs: list[str]
    output_refs: list[str]


@dataclass(frozen=True)
class Suspect:
    link_id: str
    new_link_type: str
    input_refs: list[str]
    output_refs: list[str]
    why: str
    source_refs: list[str]


@dataclass(frozen=True)
class Structure:
    route: list[Action]
    coverage_note: str
    suspects: list[Suspect]


_SYSTEM = """你是业务执行案卷整理员。案卷完整保存在程序里，你拿到的是目录：每条编号的类别、在哪一轮、多大、以及一行程序生成的语义摘要（名字/状态/大小/宿主引用/正文开头）。
你还拿到程序从 Agno 结构枚举的环节表：每个环节有类型（ι 表达、ρ 编排、χ 执行、μ 模型、κ 传递；σ 数据源读 χ 的返回）、输入端与输出端编号和机器事实，以及程序按事实已标出的可疑环节（program_suspects）。
正文不在目录里，按两步工作，不要边逛边拿：
第一步，看完目录、环节表和每个下游轴的 requires，判断要读哪些编号，用 dossier_collect **一次把要的编号全取回来**（ids 是数组，可带几十条）。
第二步，看完取回的正文再补取，定稿 route 与 suspects；只有超大的节点才用 dossier_read 带 path 下钻，确需整段时 full=true。每次工具调用都尽量一次带多条（并行发多个调用）：一次只发一个调用会把预算耗光。
**读到结构图不算读过**：结构图只让你知道里面有什么、多大。
只理解结构，不评判表现、不猜根因：按当前轮和历史轮区分行动路线；解释各步正在做什么。
特别检查函数步骤的完整输出和状态：直连后端可能没有工具 span，识别其中已有记录的后端调用、参数、返回及其所在案卷编号。
route 每项 action/purpose 只能解释行动和用途，evidence_refs/input_refs/output_refs 只写案卷编号，指向你确实读过的原文。不能生成、改写或摘要任何证据正文。不要凭历史 EMPTY 声称本轮无数据，不把 token 数吻合当作请求完整。
时间未知就说明未知；不能靠排序猜因果。原始请求未保存时，明确说明持久化消息只是重建。
suspects 是本轴的主要产出，偏召回：宁可多列一个值得下游核对的环节，不要漏。程序已标出的不必重复；你补两类：
1. 环节表里的环节，读了正文觉得值得核对（输出与输入对不上、状态说明与后续行为不一致、重复/遗漏/替换、返回对象与请求不符等）：填 link_id，new_link_type/input_refs/output_refs 留空。
2. 环节表外的环节（如函数步骤内部直连后端、某段状态读写、表中未列的传递）：link_id 留空，new_link_type 填六类之一（ι/ρ/χ/σ/μ/κ），实在归不进就填 unclassified；input_refs/output_refs 写两端编号。
why 一句话写为什么值得核对，只写观察，不写结论（不写"模型错了""工具故障"）。source_refs 写你据此起疑的原文编号，必须是读过的。
一个事件可以让多个环节都可疑，分别列出；不要替下游判断谁对谁错。
每条被引用的编号都必须是你取回并看过正文的；没看过就不要引用。gaps 的 id 例外：它的理由已写在目录里。目录摘要、结构图、检索片段都不算看过；引用里出现没取回正文的编号会被打回重做一次，仍不改就自动剔除。先取回再引用，不要先引用再补取。引用要精确到你读的那一段（读的是 a/b 就别引 a）。遇到超过单条上限的大节点（如整页工具回填、系统提示词）：先用 collect 取回（超限会返回结构图）再下钻；确实需要整段而切不开时，带 full=true 申请完整读取。
coverage_note 只解释结构可还原程度。不要给 sound/problematic 等评测结论。
只输出 schema 中的 JSON。"""


def _validate(payload: Any, link_ids: set[str]) -> None:
    if not isinstance(payload, dict) or set(payload) != {"route", "coverage_note", "suspects"}:
        raise ValueError("结构输出必须含 route/coverage_note/suspects")
    if not isinstance(payload["route"], list) or not isinstance(payload["coverage_note"], str):
        raise ValueError("结构输出字段类型错误")
    if not isinstance(payload["suspects"], list):
        raise ValueError("suspects 必须是列表")
    for item in payload["route"]:
        if not isinstance(item, dict) or set(item) != {"action", "purpose", "evidence_refs", "input_refs", "output_refs"}:
            raise ValueError("route 项格式错误")
        if not all(isinstance(item[k], str) for k in ("action", "purpose")):
            raise ValueError("action/purpose 必须是字符串")
        for key in ("evidence_refs", "input_refs", "output_refs"):
            refs = item[key]
            if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
                raise ValueError(f"{key} 必须是字符串列表")
    for item in payload["suspects"]:
        _check_suspect(item, link_ids)


def _check_suspect(item: Any, link_ids: set[str]) -> None:
    if not isinstance(item, dict) or set(item) != _SUSPECT_KEYS:
        raise ValueError(f"suspects 项必须恰好含 {sorted(_SUSPECT_KEYS)}")
    if not isinstance(item["why"], str) or not item["why"].strip():
        raise ValueError("suspect.why 必须是非空字符串")
    for key in ("input_refs", "output_refs", "source_refs"):
        if not isinstance(item[key], list) or any(not isinstance(ref, str) for ref in item[key]):
            raise ValueError(f"suspect.{key} 必须是字符串列表")
    if item["link_id"]:
        if item["link_id"] not in link_ids:
            raise ValueError(f"suspect.link_id 不在环节表里：{item['link_id']}（表外环节请留空 link_id 并填 new_link_type）")
        if item["new_link_type"] or item["input_refs"] or item["output_refs"]:
            raise ValueError("填了 link_id 的 suspect，new_link_type/input_refs/output_refs 必须留空")
    elif item["new_link_type"] not in (*LINK_TYPES, UNCLASSIFIED):
        raise ValueError(f"表外环节的 new_link_type 必须是 {[*LINK_TYPES, UNCLASSIFIED]} 之一")
    elif not (item["input_refs"] or item["output_refs"]):
        raise ValueError("表外环节必须写出输入端或输出端编号")


def _suspect_refs(item: Mapping[str, Any]) -> list[str]:
    return [ref for key in ("source_refs", "input_refs", "output_refs")
            for ref in (item.get(key) or []) if isinstance(ref, str)]


def enforce_receipts(structure: dict[str, Any], ids: set[str], read_ids: set[str],
                     index_only: set[str], shape_only: set[str] = frozenset()) -> dict[str, list[str]]:
    """Layer 4: 编号必须在清单里、且正文必须被真正读过，否则剔除并在案卷里留痕。

    规则的目的不是惩罚模型，而是让「没读就选」在物理上做不到：下游轴看不到没被读过的材料，
    缺证会以缺证的形式暴露，而不是以看似有据的结论暴露。
    """
    backed = set(read_ids) | set(index_only)
    unread: list[str] = []
    unknown: list[str] = []
    looked_only: list[str] = []

    def keep(refs: list[str]) -> list[str]:
        kept = []
        for ref in refs:
            if ref not in ids:
                unknown.append(ref)
            elif ref not in backed:
                (looked_only if ref in shape_only else unread).append(ref)
            else:
                kept.append(ref)
        return kept

    for item in structure["route"]:
        for key in ("evidence_refs", "input_refs", "output_refs"):
            item[key] = keep(item[key])
    kept_suspects, endless = [], []
    for item in structure["suspects"]:
        for key in ("source_refs", "input_refs", "output_refs"):
            item[key] = keep(item[key])
        # 表外环节没有两端就无处可核，只能丢弃并留痕；表内环节的两端由程序给出。
        if item["link_id"] or item["input_refs"] or item["output_refs"]:
            kept_suspects.append(item)
        else:
            endless.append(item["why"][:60])
    structure["suspects"] = kept_suspects
    return {"unread": sorted(set(unread)), "unknown": sorted(set(unknown)),
            "shape_only": sorted(set(looked_only)), "suspects_without_ends": endless}


def _refs_without_receipt(payload: Mapping[str, Any], read_ids: set[str], index_only: set[str]) -> list[str]:
    """机械核验：哪些被引用的编号没有正文读取回执（目录/片段/结构图都不算）。

    这是「打回重试」的入口：与其等输出后在闸门里静默剔除，
    不如先把这一轮打回去，让侦探自己决定「补取回正文」还是「从引用里删掉」。
    """
    refs: list[str] = []
    for item in payload.get("route") or []:
        if not isinstance(item, Mapping):
            continue
        for key in ("evidence_refs", "input_refs", "output_refs"):
            refs.extend(ref for ref in (item.get(key) or []) if isinstance(ref, str))
    for item in payload.get("suspects") or []:
        if isinstance(item, Mapping):
            refs.extend(_suspect_refs(item))
    backed = set(read_ids) | set(index_only)
    return sorted({ref for ref in refs if ref not in backed})


def _coerce(payload: Any) -> Any:
    """Accept the shapes a model actually returns: bare object, single-element list, or a flat list of parts."""
    if isinstance(payload, Mapping):
        return payload
    if not isinstance(payload, list):
        return payload
    route = [item for item in payload if isinstance(item, Mapping) and "action" in item]
    suspects = [item for item in payload if isinstance(item, Mapping) and "why" in item]
    if route or suspects:
        return {"route": route, "coverage_note": "", "suspects": suspects}
    return next((item for item in payload if isinstance(item, Mapping)), payload)


def _salvage(payload: Any, ids: set[str], link_ids: set[str]) -> tuple[dict[str, Any], list[str], list[str]]:
    """Second attempt: keep whatever is usable and record what was repaired or lost.

    What cannot be parsed is noted, never guessed: a dropped suspect only means the program's own
    suspects and every link end still reach the axes, without the analyst's extra pointer.
    """
    notes: list[str] = []
    dropped: list[str] = []
    payload = _coerce(payload)
    if not isinstance(payload, Mapping):
        return ({"route": [], "coverage_note": "分析输出无法解析", "suspects": []},
                [f"整个输出未能整理（输出为 {type(payload).__name__}）"], dropped)

    def known(refs: Any) -> list[str]:
        refs = [ref for ref in (refs or []) if isinstance(ref, str)]
        dropped.extend(ref for ref in refs if ref not in ids)
        return [ref for ref in refs if ref in ids]

    route = []
    for item in payload.get("route") or []:
        if not isinstance(item, Mapping) or not str(item.get("action") or "").strip():
            notes.append("丢弃无法解析的 route 项")
            continue
        route.append({"action": str(item.get("action")), "purpose": str(item.get("purpose") or ""),
                      **{key: known(item.get(key)) for key in ("evidence_refs", "input_refs", "output_refs")}})
    suspects = []
    for item in payload.get("suspects") or []:
        entry = ({"link_id": str(item.get("link_id") or ""), "new_link_type": str(item.get("new_link_type") or ""),
                  "why": str(item.get("why") or ""),
                  **{key: known(item.get(key)) for key in ("input_refs", "output_refs", "source_refs")}}
                 if isinstance(item, Mapping) else None)
        try:
            _check_suspect(entry, link_ids)
        except ValueError as exc:
            notes.append(f"丢弃无法解析的 suspect（{exc}）：{str(item)[:60]}")
            continue
        suspects.append(entry)
    note = str(payload.get("coverage_note") or "").strip() or "本次结构输出已修复"
    return {"route": route, "coverage_note": note, "suspects": suspects}, notes, dropped


def _normalize_structure(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {"route": [dict(item) for item in payload.get("route") or [] if isinstance(item, Mapping)],
            "coverage_note": str(payload.get("coverage_note") or ""),
            "suspects": [dict(item) for item in payload.get("suspects") or [] if isinstance(item, Mapping)]}


def _refs_not_in_manifest(payload: Mapping[str, Any], ids: set[str]) -> list[str]:
    """先记录清单外的编号，随后统一由 enforce_receipts 剔除（保持一条剔除路径）。"""
    refs: list[str] = []
    for item in payload["route"]:
        for key in ("evidence_refs", "input_refs", "output_refs"):
            refs.extend(ref for ref in item[key] if ref not in ids)
    for item in payload["suspects"]:
        refs.extend(ref for ref in _suspect_refs(item) if ref not in ids)
    return refs


def merge_suspects(program: list[dict[str, Any]], analysis: list[dict[str, Any]],
                   links: Mapping[str, Mapping[str, Any]], enabled: tuple[str, ...]) -> list[dict[str, Any]]:
    """程序与分析两路可疑环节并成一张表，每条带归属轴（π）。同一环节两路都标时合并理由。"""
    merged: dict[str, dict[str, Any]] = {}
    out: list[dict[str, Any]] = []
    for item in program:
        link = links[item["link_id"]]
        entry = {"link_id": item["link_id"], "link_type": link["link_type"], "origin": ["program"],
                 "why": [item["why"]], "source_refs": [], "input_refs": [], "output_refs": []}
        merged[item["link_id"]] = entry
        out.append(entry)
    for item in analysis:
        if item["link_id"] and item["link_id"] in merged:
            entry = merged[item["link_id"]]
            entry["origin"].append("analysis")
            entry["why"].append(item["why"])
            entry["source_refs"] = list(dict.fromkeys(entry["source_refs"] + item["source_refs"]))
            continue
        link_type = links[item["link_id"]]["link_type"] if item["link_id"] else item["new_link_type"]
        entry = {"link_id": item["link_id"] or f"new:{len(out)}", "link_type": link_type,
                 "origin": ["analysis"], "why": [item["why"]], "source_refs": item["source_refs"],
                 "input_refs": item["input_refs"], "output_refs": item["output_refs"], "off_map": not item["link_id"]}
        if item["link_id"]:
            merged[item["link_id"]] = entry
        out.append(entry)
    for entry in out:
        entry["axes"] = [a for a in (enabled if entry["link_type"] == UNCLASSIFIED else TYPE_AXES[entry["link_type"]])
                         if a in enabled]
    return out


def axis_selections(links: list[Mapping[str, Any]], suspects: list[Mapping[str, Any]],
                    gaps: list[str], enabled: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    """每轴视图：本轴的可疑环节（出处原文 + 两端）在前，本轴其余环节的两端在后，最后是缺口。"""
    by_id = {link["link_id"]: link for link in links}
    slots = {}
    for axis in enabled:
        types = AXIS_LINK_TYPES[axis]
        mine = [s for s in suspects if axis in s["axes"]]
        refs: list[str] = []
        for item in mine:
            ends = link_ends(by_id[item["link_id"]]) if item["link_id"] in by_id else []
            refs.extend(item["source_refs"] + item["input_refs"] + item["output_refs"] + ends)
        for link in links:
            if link["link_type"] in types:
                refs.extend(link_ends(link))
        slots[axis] = {"refs": list(dict.fromkeys(refs + gaps)),
                       "why": [f"{s['link_id']}：{'；'.join(s['why'])}" for s in mine]}
    return slots


def run(inputs: Mapping[str, Any], axis: ScenarioAxis, runtime: Any) -> RunOutcome:
    from .transcript_axes import run_analysis, transcript_snapshot

    if transcript_snapshot(inputs["trace"], inputs.get("business_trace")):
        return run_analysis(inputs, axis, runtime)
    dossier = build_dossier(inputs["trace"], inputs.get("business_trace"))
    if not dossier["records"]:
        # 没有过程记录就不整理：六轴随之 blocked，不对着空案卷判。原因交给人补采集。
        return RunOutcome(output={}, failed=True, usage={"llm_calls": 0},
                          failure_reason=f"{FAILURE_MATERIAL} 业务 Trace 缺失或采集失败，没有可整理的过程记录："
                                         f"{json.dumps(dossier['coverage'], ensure_ascii=False)[:300]}")
    enabled = tuple(axis_id for axis_id in (getattr(runtime, "enabled_axes", ()) or PROCESS_AXES) if axis_id in PROCESS_AXES)
    enable = (enabled or PROCESS_AXES)
    catalog = build_catalog(dossier)
    catalog_text = render_catalog(catalog)
    ids = catalog_ids(catalog)
    table = build_links(dossier)
    links = {link["link_id"]: link for link in table["links"]}
    flagged = program_suspects(table["links"])
    from ..registry import AXIS_TYPES  # noqa: F401  导入即注册全部轴类型，PROCESS_SPECS 才有内容
    from .process_common import PROCESS_SPECS
    downstream = [{"axis": axis_id, "link_types": list(AXIS_LINK_TYPES[axis_id]),
                   "question": PROCESS_SPECS[axis_id].question,
                   "excludes": PROCESS_SPECS[axis_id].excludes,
                   "requires": PROCESS_SPECS[axis_id].requires}
                  for axis_id in enable if axis_id in PROCESS_SPECS]
    index = EvidenceIndex(dossier)
    index_only = {gap["id"] for gap in dossier["gaps"]}
    client = axis_llm(runtime.spec, role="judge", tools=build_dossier_tools(index),
                      tool_call_limit=TOOL_CALL_LIMIT)
    output_spec = StructuredOutputSpec.from_dataclass(
        Structure, description="记录行动路线与值得下游核对的可疑环节；原文已由程序完整保存，禁止重写证据。")
    prompt = "\n\n".join([
        "## 案卷目录\n" + catalog_text,
        "## 环节表（程序从 Agno 结构枚举）\n" + json.dumps(table, ensure_ascii=False),
        "## 程序已标出的可疑环节（program_suspects）\n" + json.dumps(flagged, ensure_ascii=False),
        "## 启用的下游轴与需求\n" + json.dumps(downstream, ensure_ascii=False),
        f"## 预算\n单个轴视图最多 {VIEW_BUDGET_CHARS} 字；一次 collect 取回总量上限 {MAX_COLLECT_CHARS} 字。",
        "## 取证工具\n" + TOOL_GUIDE,
    ])
    repaired: list[str] = []
    dropped: list[str] = []
    payload: Any = None
    for attempt in range(2):
        runtime.ensure_time_left("trace_analysis")
        raw: Any = None
        try:
            raw = client.complete_json(_SYSTEM, prompt, trace_id=runtime.trace_id,
                                      stage="llm_probe_trace_analysis", reasoning_effort="medium",
                                      output_spec=output_spec)
            raise_for_error_payload(raw)
            if isinstance(raw, Mapping):
                raw = {k: v for k, v in raw.items() if k not in {"raw_model_response", "metrics", "_tool_call_log"}}
            _validate(raw, set(links))
            # 机械核验：引用了没取回正文的编号就把这一轮打回去，别等闸门静默剔除。
            missing = _refs_without_receipt(raw, index.read_ids, index_only)
            if missing:
                raise ValueError(f"以下编号没有正文读取回执：{missing[:6]}（共 {len(missing)} 条）——"
                                 "先用 dossier_collect 把它们取回正文再引用，或从 route/suspects 里删掉")
            payload = raw
            dropped.extend(_refs_not_in_manifest(payload, ids))
            break
        except ValueError as exc:
            if not attempt:
                prompt += "\n结构或引用格式错误，请重新输出：" + str(exc)
                continue
            # 第二次仍不合规（含被结构化协议直接阻断）：能用的部分就地修复；
            # 一点可用结构都没有就是分析失败，整条阻断，不让六轴对着空结构判。
            payload, notes, lost = _salvage(raw, ids, set(links))
            if not payload["route"] and not payload["suspects"]:
                return RunOutcome(output={}, failed=True, usage={**client.usage(), "tool_calls": index.calls},
                                  failure_reason=f"{FAILURE_AXIS} 分析轴两次输出均不可用：{str(exc)[:300]}")
            dropped.extend(lost)
            repaired.extend([f"输出不可用：{str(exc)[:200]}"] + notes)
    structure = _normalize_structure(payload)
    audit = enforce_receipts(structure, ids, index.read_ids, index_only=index_only,
                             shape_only=index.shape_only_ids)
    # 回执跟着结构一起下去：下游轴视图只渲染整理阶段真读过的片段（同一条记录的粒度）
    audit["reads"] = index.read_receipts
    notes = list(structure.get("coverage_note") and [str(structure["coverage_note"])] or [])
    if repaired:
        structure["repaired"] = repaired
        notes.append(f"结构输出由程序修复：{'；'.join(repaired[:6])}")
    if audit["shape_only"]:
        notes.append(f"以下编号只读过结构图、没读过正文，已从引用中剔除（要引用必须先下钻读正文）："
                     f"{audit['shape_only'][:8]}（共 {len(audit['shape_only'])} 条）")
    if audit["unread"]:
        notes.append(f"以下编号没有读取回执，已从引用中剔除：{audit['unread'][:8]}"
                     f"（共 {len(audit['unread'])} 条）")
    if audit["unknown"] or dropped:
        notes.append(f"以下编号不在清单里，已剔除：{sorted(set(audit['unknown']) | set(dropped))[:8]}")
    if audit["suspects_without_ends"]:
        notes.append(f"这些表外可疑环节的两端都被剔除，已丢弃：{audit['suspects_without_ends'][:4]}")
    suspects = merge_suspects(flagged, structure["suspects"], links, enable)
    structure["suspects"] = suspects
    unclassified = [s["link_id"] for s in suspects if s["link_type"] == UNCLASSIFIED]
    if unclassified:
        notes.append(f"以下表外环节归不进六类，交各轴与用户复核：{unclassified}")
    selections = axis_selections(table["links"], suspects, sorted(index_only), enable)
    # 回执必须每次都跟着结构下去（不能只在有异常时写）：轴视图靠它决定能渲染哪几段正文，
    # 丢了回执会让整理员读过的整页正文在轴上又变成「未读到」（实测：干净那次把 40921 字的整页读成了缺证）。
    structure["evidence_audit"] = {**audit, "not_in_manifest": sorted(set(dropped))}
    structure["coverage_note"] = "；".join(notes)[:4000]
    # Completeness describes assembly, not whether the evidence proves process correctness.
    verdict = "partial" if any(c["status"] == "failed" for c in dossier["coverage"]) else "complete"
    origins = [o for s in suspects for o in s["origin"]]
    off_map = sum(1 for s in suspects if s.get("off_map"))
    return RunOutcome(output={"verdict": verdict, "dossier": dossier, "coverage": dossier["coverage"],
                              "structure": structure, "suspects": suspects, "selections": selections,
                              "catalog_chars": len(catalog_text)},
        summary=AxisSummary(
            f"案卷整理 {verdict}：{len(dossier['records'])} 条记录、{len(dossier['model_calls'])} 次模型调用、"
            f"{len(table['links'])} 个环节；可疑环节 {len(suspects)} 个（程序 {origins.count('program')}、"
            f"分析 {origins.count('analysis')}，其中表外 {off_map}）；取回 {len(index.read_ids)} 个编号"
            "；原始证据限制见 gaps",
            [],
        ),
        usage={**client.usage(), "tool_calls": index.calls, "read_ids": len(index.read_ids),
               "dossier_chars": len(json.dumps(dossier, ensure_ascii=False)),
               "catalog_chars": len(catalog_text), "suspects": len(suspects)})


def _axis_type() -> Any:
    from ..types import AxisType, ExecutionLimits, Field, Input, Verdict
    return AxisType(type_id="trace_analysis", title="过程案卷", summary="先完整装入原文，再列出值得各轴核对的可疑环节，不下评测结论",
        verdict_scope="axis", verdict_enum=(Verdict("complete", "所有可获得记录已装入案卷；不代表证据足够"),
        Verdict("partial", "部分轮次采集失败，案卷明确缺口")),
        depend_on=(), trigger_when=None,
        inputs=(Input("trace", source="sample.trace"), Input("business_trace", source="sample.business_trace", required=False)),
        output_fields=("verdict", "dossier", "coverage", "structure", "suspects", "selections", "catalog_chars"),
        scenario_fields=(Field("description", required=True, expand="prompt_load"),),
        limits=ExecutionLimits(llm_calls=8, tool_calls=TOOL_CALL_LIMIT, seconds=7200), run=run, verdict_path="verdict",
        requires_business_trace=True, role="analysis", implementation_files=(
            "impl/projects/llm_probe/eval_axes/adapters/trace_analysis.py", "impl/projects/llm_probe/business_trace/dossier.py",
            "impl/projects/llm_probe/business_trace/tools.py", "impl/projects/llm_probe/business_trace/reader.py",
            "impl/projects/llm_probe/business_trace/links.py",
            "impl/projects/llm_probe/business_trace/providers/agno_reader.py",
            "impl/projects/llm_probe/eval_axes/adapters/transcript_axes.py",
            "impl/projects/llm_probe/business_trace/providers/llmtracing_transcript.py"))


AXIS_TYPE = _axis_type()
