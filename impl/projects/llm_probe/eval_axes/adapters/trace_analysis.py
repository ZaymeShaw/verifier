"""Build the complete source dossier, then list the suspect links (W1 §1: S → Λ*).

The program enumerates link instances from Agno structure and marks those whose facts depart
from identity. The analyst reads the index, pulls bodies on demand, and adds semantic suspects
and off-map links, each with the source text it relied on. Every number it cites must have a read
receipt. It never writes or summarizes evidence, and never decides whether a link behaved correctly.
Each process axis then gets its own link types: suspects first, then the ends of every other link.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping

from impl.core.tool_loop import LoopContext
from impl.projects.llm_probe.business_trace.dossier import build_dossier
from impl.projects.llm_probe.business_trace.links import (
    AXIS_LINK_TYPES, LINK_TYPES, TYPE_AXES, link_ends)
from ..llm import axis_llm
from ..types import FAILURE_AXIS, FAILURE_MATERIAL, AxisRequestFailed, AxisSummary, RunOutcome, ScenarioAxis

# 分析轴按问题定位取证；并行工具共享一轮 LLM 预算。
PROCESS_AXES = ("intent_understanding", "planning_routing", "tool_execution",
                "context_memory", "knowledge_data", "model_capability")
LLM_CALL_LIMIT = 8
ANALYSIS_SECONDS = 7200
# 地图外环节找不到六类之一时的归类：交给用户，所有启用轴都能看到。
UNCLASSIFIED = "unclassified"
_EXISTING_SUSPECT_KEYS = {"link_id", "why", "source_refs"}
_NEW_SUSPECT_KEYS = {"link_type", "input_refs", "output_refs", "why", "source_refs"}


_SYSTEM = """你是业务执行案卷整理员。案卷完整保存在程序里，你拿到的是目录：每条编号的类别、在哪一轮、多大、以及一行程序生成的语义摘要（名字/状态/大小/宿主引用/正文开头）。
你还拿到程序从 Agno 结构枚举的环节表：每个环节有类型（intent_understanding 表达、planning_routing 编排、tool_execution 执行、model_capability 模型、context_memory 传递；knowledge_data 数据源读 tool_execution 的返回）、输入端与输出端编号和机器事实，以及程序按事实已标出的可疑环节（program_suspects）。
正文不在目录里，按两步工作，不要边逛边拿：
第一步，看完目录、环节表和每个下游轴的 requires，判断要读哪些编号，用 dossier_collect **一次把要的编号全取回来**（ids 是数组，可带几十条）。
第二步，看完取回的正文再补取，定稿 route 与两类发现；只有超大的节点才用 dossier_read 带 path 下钻，确需整段时 full=true。每轮尽量把互不依赖的取证调用一起发出，collect 的 ids 可带多条，以减少 LLM 往返和正文重复发送。同一回复的多个工具调用合计一轮；不要重复读取本会话已有的正文，及时提交并为验收修正预留轮次。
**读到结构图不算读过**：结构图只让你知道里面有什么、多大。
只理解结构，不评判表现、不猜根因：按当前轮和历史轮区分行动路线；解释各步正在做什么。
特别检查函数步骤的完整输出和状态：直连后端可能没有工具 span，识别其中已有记录的后端调用、参数、返回及其所在案卷编号。
route 每项 action/purpose 只能解释行动和用途，evidence_refs/input_refs/output_refs 只写案卷编号，指向你确实读过的原文。不能生成、改写或摘要任何证据正文。不要凭历史 EMPTY 声称本轮无数据，不把 token 数吻合当作请求完整。
时间未知就说明未知；不能靠排序猜因果。原始请求未保存时，明确说明持久化消息只是重建。
发现分成两个列表，偏召回：宁可多列一个值得下游核对的环节，不要漏。程序已标出的不必重复。
1. existing_link_suspects：原环节表中值得核查的步骤。每项只填 link_id、why、source_refs；link_id 从环节表复制，类型和输入输出由程序从该表取得，不重复填写。
2. new_link_suspects：运行证据中发现、但原环节表漏列的可疑步骤，如函数内部真实发生的后端调用。每项填 link_type、input_refs、output_refs、why、source_refs；不填 link_id，程序在提交通过后分配编号。link_type 填六类之一（intent_understanding/planning_routing/tool_execution/knowledge_data/model_capability/context_memory），确实无法归类填 unclassified。至少一端有真实证据；未记录的一端用空列表，不编造端点。
两个列表都必须提交。哪类没有发现，就将该列表写成 []；不要放入空对象或空字符串占位。没有新发现不代表已有环节没有可疑点。
这里的“新”是原表漏记的已发生步骤，不是想象系统应该增加的步骤；“应该发生却未发生”由下游期望核对处理。
why 一句话写为什么值得核对，只写观察，不写结论（不写"模型错了""工具故障"）。两类记录的 source_refs 均不能为空，写据此起疑的已读原文编号。
一个事件可以让多个环节都可疑，分别列出；不要替下游判断谁对谁错。
每条被引用的编号都必须是你取回并看过正文的；没看过就不要引用。gaps 的 id 例外：它的理由已写在目录里。目录摘要、结构图、检索片段都不算看过；提交时会检查引用和结构；未通过就在当前会话修正，保留已读材料和候选结果，不从头重读。程序不会自动删除引用或发现来替你通过校验。先取回再引用，不要先引用再补取。引用要精确到你读的那一段（读的是 a/b 就别引 a）。遇到超过单条上限的大节点（如整页工具回填、系统提示词）：先用 collect 取回（超限会返回结构图）再下钻；确实需要整段而切不开时，带 full=true 申请完整读取。
【证据与关联】读了消息 A，其中 model_call_ref/span_ref 指向 B，只表示 A 关联 B，不表示你读过 B。若 A 的正文已能支撑陈述，只引用 A，不要顺手把 B 加入证据。关联关系留在原记录和环节表里，无需重复抄入证据字段。只有陈述依赖 B 中的信息时才读取 B 的相关正文，再引用实际读过的位置。link_id 是被调查的环节，不是证据；它的 source_refs 仍须指向读过的原文。被拒后先判断已有证据是否足够：足够就修正多余引用；不足就补读或收窄陈述，不要机械删编号而保留无依据的断言。
coverage_note 只解释结构可还原程度。不要给 sound/problematic 等评测结论。
只输出 schema 中的 JSON。"""


def _validate(payload: Any, link_ids: set[str]) -> None:
    if not isinstance(payload, dict) or set(payload) != {
        "route", "coverage_note", "existing_link_suspects", "new_link_suspects"
    }:
        raise ValueError("结构输出必须恰好含 route/coverage_note/existing_link_suspects/new_link_suspects")
    if not isinstance(payload["route"], list) or not isinstance(payload["coverage_note"], str):
        raise ValueError("结构输出字段类型错误")
    for name in ("existing_link_suspects", "new_link_suspects"):
        if not isinstance(payload[name], list):
            raise ValueError(f"{name} 必须是列表；没有发现时填 []")
    route_keys = {"action", "purpose", "evidence_refs", "input_refs", "output_refs"}
    for number, item in enumerate(payload["route"]):
        if not isinstance(item, dict):
            raise ValueError(f"route[{number}] 必须是对象，实际为 {type(item).__name__}")
        if set(item) != route_keys:
            raise ValueError(
                f"route[{number}] 字段名错误：缺少 {sorted(route_keys - set(item))!r}，"
                f"多出 {sorted(set(item) - route_keys)!r}；"
                f"字段名必须恰好是 {sorted(route_keys)!r}。"
                "字段名不包含字面引号：JSON里的键是 action，不是 \"action\"（带引号字符的另一个键）。"
                "只修改错误的字段名，保留原陈述及证据，不要重做取证。")
        if not all(isinstance(item[k], str) for k in ("action", "purpose")):
            raise ValueError("action/purpose 必须是字符串")
        for key in ("evidence_refs", "input_refs", "output_refs"):
            refs = item[key]
            if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
                raise ValueError(f"{key} 必须是字符串列表")
    for number, item in enumerate(payload["existing_link_suspects"]):
        label = f"existing_link_suspects[{number}]"
        _check_suspect_fields(item, _EXISTING_SUSPECT_KEYS, label)
        if not isinstance(item["link_id"], str) or not item["link_id"].strip():
            raise ValueError(f"{label}.link_id 必须是非空的已有环节编号")
        if item["link_id"] not in link_ids:
            raise ValueError(f"{label}.link_id 不在环节表里：{item['link_id']}")
    for number, item in enumerate(payload["new_link_suspects"]):
        label = f"new_link_suspects[{number}]"
        _check_suspect_fields(item, _NEW_SUSPECT_KEYS, label)
        if not isinstance(item["link_type"], str) or item["link_type"] not in (*LINK_TYPES, UNCLASSIFIED):
            raise ValueError(f"{label}.link_type 必须是 {[*LINK_TYPES, UNCLASSIFIED]} 之一")
        if not (item["input_refs"] or item["output_refs"]):
            raise ValueError(f"{label} 必须写出输入端或输出端编号")


def _check_suspect_fields(item: Any, keys: set[str], label: str) -> None:
    if not isinstance(item, dict) or set(item) != keys:
        raise ValueError(f"{label} 必须恰好含 {sorted(keys)}")
    if not isinstance(item["why"], str) or not item["why"].strip():
        raise ValueError(f"{label}.why 必须是非空字符串")
    for key in sorted(keys & {"input_refs", "output_refs", "source_refs"}):
        if not isinstance(item[key], list) or any(not isinstance(ref, str) or not ref.strip() for ref in item[key]):
            raise ValueError(f"{label}.{key} 必须是非空编号组成的列表")
    if not item["source_refs"]:
        raise ValueError(f"{label}.source_refs 必须提供发现依据")


def _suspect_refs(item: Mapping[str, Any]) -> list[str]:
    return [ref for key in ("source_refs", "input_refs", "output_refs")
            if isinstance(item.get(key), list) for ref in item[key] if isinstance(ref, str)]


def _normalize_structure(payload: Mapping[str, Any]) -> dict[str, Any]:
    # Called only after validation; do not drop malformed findings or fill missing fields.
    return {"route": [dict(item) for item in payload["route"]],
            "coverage_note": payload["coverage_note"],
            "existing_link_suspects": [dict(item) for item in payload["existing_link_suspects"]],
            "new_link_suspects": [dict(item) for item in payload["new_link_suspects"]]}


def merge_suspects(program: list[dict[str, Any]], existing: list[dict[str, Any]],
                   discovered: list[dict[str, Any]], links: Mapping[str, Mapping[str, Any]],
                   enabled: tuple[str, ...]) -> list[dict[str, Any]]:
    """将程序发现与两类模型发现物化为下游环节记录；不解析旧提交格式。"""
    merged: dict[str, dict[str, Any]] = {}
    out: list[dict[str, Any]] = []
    for item in program:
        link = links[item["link_id"]]
        entry = {"link_id": item["link_id"], "link_type": link["link_type"], "origin": ["program"],
                 "why": [item["why"]], "source_refs": [],
                 "input_refs": [end["ref"] for end in link["input"]],
                 "output_refs": [end["ref"] for end in link["output"]], "off_map": False}
        merged[item["link_id"]] = entry
        out.append(entry)
    for item in existing:
        if item["link_id"] in merged:
            entry = merged[item["link_id"]]
            if "analysis" not in entry["origin"]:
                entry["origin"].append("analysis")
            entry["why"].append(item["why"])
            entry["source_refs"] = list(dict.fromkeys(entry["source_refs"] + item["source_refs"]))
            continue
        link = links[item["link_id"]]
        entry = {"link_id": item["link_id"], "link_type": link["link_type"],
                 "origin": ["analysis"], "why": [item["why"]], "source_refs": list(item["source_refs"]),
                 "input_refs": [end["ref"] for end in link["input"]],
                 "output_refs": [end["ref"] for end in link["output"]], "off_map": False}
        merged[item["link_id"]] = entry
        out.append(entry)
    for item in discovered:
        out.append({"link_id": f"new:{len(out)}", "link_type": item["link_type"],
                    "origin": ["analysis"], "why": [item["why"]], "source_refs": list(item["source_refs"]),
                    "input_refs": list(item["input_refs"]), "output_refs": list(item["output_refs"]), "off_map": True})
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


def _turn_no(text: str) -> int | None:
    found = [int(n) for n in re.findall(r"turn(\d+)", text)]
    return max(found) if found else None


def _link_turn(link: Mapping[str, Any], owners: Mapping[str, set[int]], turns: list[int]) -> int:
    """环节属于哪一轮：跨轮环节按较晚一轮；只引用共享正文的表外环节按正文最早出现的一轮；单轮 case 即第 1 轮。"""
    refs = [end["ref"] for end in (link.get("input") or []) + (link.get("output") or [])]
    found = [_turn_no(str(link.get("turn") or "")), *(_turn_no(ref) for ref in refs)]
    found += [min(owners[ref]) for ref in refs if owners.get(ref)]
    found = [t for t in found if t]
    if found:
        return max(found)
    if len(turns) == 1:
        return turns[0]
    raise ValueError(f"环节算不出属于哪一轮：{link['link_id']}")


def axis_batches(axis_id: str, dossier: Mapping[str, Any], structure: Mapping[str, Any],
                 selection: Mapping[str, Any]) -> list[dict[str, Any]]:
    """本轴环节按所属轮次排好再按大小切批（spec/alg/process-axes.md §2.3）；一批可含几轮，批次记下含哪几轮 turns。"""
    from impl.projects.llm_probe.business_trace.materials import prepare_axis_materials
    from .process_common import _axis_links

    records = dossier.get("records") or []
    turns = sorted({_turn_no(r.get("id", "")) for r in records} - {None}) or [1]
    suspects = list(structure.get("suspects") or [])
    links = _axis_links(axis_id, dossier, structure)
    if not links:
        none = [{"link_id": f"{axis_id}:none", "link_type": "/".join(AXIS_LINK_TYPES[axis_id]), "turn": "",
                 "input": [], "output": [], "facts": {}, "basis": "程序未列出本轴类型的环节"}]
        return [{**b, "turns": [f"t{turns[-1]}"]} for b in
                prepare_axis_materials(dossier, none, suspects, extra_refs=list(selection.get("refs") or []))]
    owners: dict[str, set[int]] = {}
    for record in records:
        turn = _turn_no(record.get("id", ""))
        for token in set(re.findall(r"content#\d+", json.dumps(record.get("fields") or {}, ensure_ascii=False))):
            if turn:
                owners.setdefault(token, set()).add(turn)
    turn_of = {link["link_id"]: _link_turn(link, owners, turns) for link in links}
    ordered = sorted(links, key=lambda link: turn_of[link["link_id"]])
    return [{**b, "turns": [f"t{t}" for t in sorted({turn_of[link['link_id']] for link in b["links"]})]}
            for b in prepare_axis_materials(dossier, ordered, suspects)]


def prepare_selections(dossier: Mapping[str, Any], structure: Mapping[str, Any],
                       selections: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Analysis's deterministic handoff: complete endpoints, independent of suspect recall.

    Reading receipts still constrain the analyst's claims. They do not authorize
    truncating material the downstream judge needs to verify a processing link.
    """
    for axis_id, selection in selections.items():
        selection["materials"] = axis_batches(axis_id, dossier, structure, selection)
    return selections


class _AnalysisClient:
    """在每次模型请求边界检查轴预算；端点重试仍由现有客户端负责。"""

    def __init__(self, client: Any, runtime: Any) -> None:
        self.client, self.runtime = client, runtime

    def complete_step(self, *args: Any, **kwargs: Any) -> Any:
        self.runtime.ensure_time_left("trace_analysis")
        try:
            result = self.client.complete_step(*args, **kwargs)
        except RuntimeError as exc:
            # complete_step reports endpoint/request failure by exception, unlike
            # complete_json's error payload. Keep the runner's environment category.
            raise AxisRequestFailed("llm_request_failed", str(exc)) from exc
        self.runtime.ensure_time_left("trace_analysis")
        return result


def run(inputs: Mapping[str, Any], axis: ScenarioAxis, runtime: Any) -> RunOutcome:
    from .transcript_axes import run_analysis, transcript_snapshot

    if transcript_snapshot(inputs["trace"], inputs.get("business_trace")):
        return run_analysis(inputs, axis, runtime)
    from impl.projects.llm_probe.process_loop.analysis import Analysis

    dossier = build_dossier(inputs["trace"], inputs.get("business_trace"))
    if not dossier["records"]:
        return RunOutcome(output={}, failed=True, usage={"llm_calls": 0},
                          failure_reason=f"{FAILURE_MATERIAL} 业务 Trace 缺失或采集失败，没有可整理的过程记录："
                                         f"{json.dumps(dossier['coverage'], ensure_ascii=False)[:300]}")
    enabled = tuple(axis_id for axis_id in (getattr(runtime, "enabled_axes", ()) or PROCESS_AXES)
                    if axis_id in PROCESS_AXES) or PROCESS_AXES
    client = axis_llm(runtime.spec, role="judge")
    client.reasoning_effort = "medium"
    steps = _AnalysisClient(client, runtime)
    analysis = Analysis(dossier, steps, enabled)
    result = analysis.loop.run(analysis.prompt, LoopContext(runtime.trace_id))
    usage = {**client.usage(), "llm_calls": result.llm_calls, "tool_calls": len(result.calls),
             "limits": {"llm_calls": LLM_CALL_LIMIT, "tool_calls": None, "seconds": ANALYSIS_SECONDS},
             "read_ids": len(analysis.index.read_ids),
             "dossier_chars": len(json.dumps(dossier, ensure_ascii=False)),
             "catalog_chars": len(analysis.catalog_text)}
    if result.status != "complete":
        problems = [c.denied or c.error or (c.result or {}).get("error", "")
                    for c in result.calls if c.tool == "submit_structure"
                    and c.denied != result.reason
                    and (c.denied or c.error or isinstance(c.result, dict))]
        last_problem = next((p for p in reversed(problems) if p), "")
        return RunOutcome(output={}, failed=True, usage=usage,
                          failure_reason=f"{FAILURE_AXIS} 案卷整理未通过验收：{result.reason}；{last_problem}")
    output = {**analysis.output, "dossier": dossier}
    output.pop("usage", None)
    suspects = output["suspects"]
    origins = [origin for item in suspects for origin in item["origin"]]
    off_map = sum(1 for item in suspects if item.get("off_map"))
    return RunOutcome(output=output,
        summary=AxisSummary(
            f"案卷整理 {output['verdict']}：{len(dossier['records'])} 条记录、{len(dossier['model_calls'])} 次模型调用、"
            f"{len(analysis.links)} 个环节；可疑环节 {len(suspects)} 个（程序 {origins.count('program')}、"
            f"分析 {origins.count('analysis')}，其中表外 {off_map}）；取回 {len(analysis.index.read_ids)} 个编号"
            "；原始证据限制见 gaps", []),
        usage={**usage, "suspects": len(suspects)})


def _axis_type() -> Any:
    from ..types import AxisType, ExecutionLimits, Field, Input, Verdict
    return AxisType(type_id="trace_analysis", title="过程案卷", summary="先完整装入原文，再列出值得各轴核对的可疑环节，不下评测结论",
        verdict_scope="axis", verdict_enum=(Verdict("complete", "所有可获得记录已装入案卷；不代表证据足够"),
        Verdict("partial", "部分轮次采集失败，案卷明确缺口")),
        depend_on=(), trigger_when=None,
        inputs=(Input("trace", source="sample.trace"), Input("business_trace", source="sample.business_trace", required=False)),
        output_fields=("verdict", "dossier", "coverage", "structure", "suspects", "selections", "catalog_chars"),
        scenario_fields=(Field("description", required=True, expand="prompt_load"),),
        limits=ExecutionLimits(llm_calls=LLM_CALL_LIMIT, seconds=ANALYSIS_SECONDS), run=run, verdict_path="verdict",
        requires_business_trace=True, role="analysis", implementation_files=(
            "impl/projects/llm_probe/eval_axes/adapters/trace_analysis.py", "impl/projects/llm_probe/business_trace/dossier.py",
            "impl/projects/llm_probe/business_trace/materials.py",
            "impl/projects/llm_probe/business_trace/tools.py", "impl/projects/llm_probe/business_trace/reader.py",
            "impl/projects/llm_probe/business_trace/links.py",
            "impl/projects/llm_probe/process_loop/analysis.py", "impl/projects/llm_probe/process_loop/tools.py",
            "impl/core/tool_loop/__init__.py", "impl/core/tool_loop/runtime.py", "impl/core/tool_loop/hooks.py",
            "impl/core/tool_loop/types.py", "impl/core/tool_loop/outputs.py",
            "impl/projects/llm_probe/business_trace/providers/agno_reader.py",
            "impl/projects/llm_probe/business_trace/providers/langfuse.py",
            "impl/projects/llm_probe/business_trace/providers/langfuse_reader.py",
            "impl/projects/llm_probe/eval_axes/adapters/transcript_axes.py",
            "impl/projects/llm_probe/business_trace/providers/llmtracing_transcript.py"))


AXIS_TYPE = _axis_type()
