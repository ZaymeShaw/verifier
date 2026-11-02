"""实例 A：案卷整理（trace_analysis）作为子 ToolLoop（spec/adapter/tool-loop-plan-20260922.md §5）。

与 eval_axes/adapters/trace_analysis.py 同一套判定材料（目录、环节表、程序可疑环节、下游需求、_validate、
merge_suspects、axis_selections 均只读复用），机制换成 ToolLoop：
- 最终 JSON → submit_structure tool：execute 里跑 _validate，合规 accepted，否则 rejected + 错误，模型在同一会话里改；
- _refs_without_receipt 事后打回 → ReceiptGate（pre_tool）：引用必须在此前批次有正文回执，提交前就拒；
- TOOL_CALL_LIMIT + attempt 循环 → BudgetStop(tool_calls=12) + RequireDone([submit_structure])；
- _salvage / enforce_receipts 删除：loop failed 即整理失败，不产出部分结构。
"""
from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Sequence

from impl.core.tool_loop import (
    Allow, BudgetStop, Call, Deny, History, Hook, PreDecision, RequireDone, ToolLoop, StepClient, is_accepted)
from impl.projects.llm_probe.business_trace.dossier import build_catalog, render_catalog
from impl.projects.llm_probe.business_trace.links import (
    AXIS_LINK_TYPES, LINK_TYPES, build_links, program_suspects)
from impl.projects.llm_probe.business_trace.tools import MAX_COLLECT_CHARS, TOOL_GUIDE, EvidenceIndex
from impl.projects.llm_probe.eval_axes.adapters import trace_analysis as base
from impl.projects.llm_probe.eval_axes.adapters.trace_analysis import (
    PROCESS_AXES, TOOL_CALL_LIMIT, UNCLASSIFIED, _normalize_structure, _suspect_refs, _validate,
    axis_selections, merge_suspects)
from impl.tools.protocol import VerifiableTool

from .tools import dossier_tools, derive_prompt

SUBMIT = "submit_structure"

SYSTEM = derive_prompt(base._SYSTEM, {
    "引用里出现没取回正文的编号会被打回重做一次，仍不改就自动剔除。":
        "submit_structure 引用了没取回正文的编号会被拒绝并列出这些编号；同一批里的取回对同批的提交不可见，先取回、下一批再提交。",
    "只输出 schema 中的 JSON。":
        f"定稿后调用 {SUBMIT} 提交 route/coverage_note/suspects；被拒就按原因改了再提交，直到被接受。不要在回复文本里输出 JSON。",
})

_ROUTE_ITEM = {"type": "object", "properties": {
    "action": {"type": "string", "description": "这一步在做什么"},
    "purpose": {"type": "string", "description": "这一步的用途"},
    "evidence_refs": {"type": "array", "items": {"type": "string"}, "description": "读过正文的案卷编号"},
    "input_refs": {"type": "array", "items": {"type": "string"}, "description": "输入端编号"},
    "output_refs": {"type": "array", "items": {"type": "string"}, "description": "输出端编号"},
}, "required": ["action", "purpose", "evidence_refs", "input_refs", "output_refs"]}

_SUSPECT_ITEM = {"type": "object", "properties": {
    "link_id": {"type": "string", "description": "环节表里的 link_id；表外环节留空"},
    "new_link_type": {"type": "string", "description": f"表外环节的类型：{'/'.join(LINK_TYPES)} 或 {UNCLASSIFIED}；表内留空"},
    "input_refs": {"type": "array", "items": {"type": "string"}, "description": "表外环节的输入端编号；表内留空"},
    "output_refs": {"type": "array", "items": {"type": "string"}, "description": "表外环节的输出端编号；表内留空"},
    "why": {"type": "string", "description": "为什么值得核对，只写观察"},
    "source_refs": {"type": "array", "items": {"type": "string"}, "description": "据此起疑的原文编号，必须读过"},
}, "required": ["link_id", "new_link_type", "input_refs", "output_refs", "why", "source_refs"]}

SUBMIT_PARAMETERS = {"type": "object", "properties": {
    "route": {"type": "array", "items": _ROUTE_ITEM, "description": "按轮次的行动路线"},
    "coverage_note": {"type": "string", "description": "结构可还原程度"},
    "suspects": {"type": "array", "items": _SUSPECT_ITEM, "description": "值得下游核对的可疑环节"},
}, "required": ["route", "coverage_note", "suspects"]}


def payload_refs(payload: Mapping[str, Any]) -> list[str]:
    """提交里引用的全部编号。在 _validate 之前调用，形状不对的部分跳过（形状错误由 submit 自己报）。"""
    refs: list[str] = []
    for item in payload.get("route") or []:
        if isinstance(item, Mapping):
            for key in ("evidence_refs", "input_refs", "output_refs"):
                refs.extend(ref for ref in (item.get(key) or []) if isinstance(ref, str))
    for item in payload.get("suspects") or []:
        if isinstance(item, Mapping):
            refs.extend(_suspect_refs(item))
    return refs


class ReceiptGate(Hook):
    """guarded 这些提交类 tool 里引用的编号，必须在此前批次有正文回执（或是 allowed 里的缺口编号）。

    回执由 EvidenceIndex 在执行时实时写入；这里在每批结束时拍快照，pre_tool 只认快照，
    与 History「同批互不可见」同一口径。
    """

    def __init__(self, index: EvidenceIndex, guarded: set[str], refs: Callable[[Mapping[str, Any]], list[str]],
                 allowed: set[str] = frozenset(), special: Callable[[str], bool] = lambda ref: False) -> None:
        self.index = index
        self.guarded = set(guarded)
        self.refs = refs
        self.allowed = set(allowed)
        self.special = special
        self.backed: set[str] = set(allowed)
        self.shape_only: set[str] = set()

    def post_batch(self, history: History, calls: Sequence[Call]) -> Sequence[str]:
        self.backed = self.allowed | self.index.read_ids
        self.shape_only = self.index.shape_only_ids - self.backed
        return ()

    def pre_tool(self, history: History, call: Call) -> PreDecision:
        if call.tool not in self.guarded:
            return Allow()
        cited = [ref for ref in dict.fromkeys(self.refs(call.args)) if not self.special(ref)]
        unknown = [ref for ref in cited if not self.index.knows(ref)]
        looked = [ref for ref in cited if ref in self.shape_only]
        unread = [ref for ref in cited if ref not in self.backed and ref not in unknown and ref not in looked]
        problems = []
        if unknown:
            problems.append(f"不在案卷清单里的编号：{unknown[:8]}（共 {len(unknown)} 条），从引用里删掉")
        if looked:
            problems.append(f"只读到结构图、没读到正文的编号：{looked[:8]}（共 {len(looked)} 条），"
                            "下钻读正文（dossier_read 带 path 或 full=true）后再引用，或删掉")
        if unread:
            problems.append(f"此前批次没有正文读取回执的编号：{unread[:8]}（共 {len(unread)} 条），"
                            "先用 dossier_collect 取回正文、下一批再提交，或从引用里删掉")
        return Deny(f"{call.tool} 被拒：" + "；".join(problems)) if problems else Allow()


class Analysis:
    """一次案卷整理。loop 成功时 output 是与 trace_analysis 轴同形的结构（不含 dossier）。"""

    def __init__(self, dossier: Mapping[str, Any], client: StepClient,
                 enabled: tuple[str, ...] = PROCESS_AXES) -> None:
        from impl.projects.llm_probe.eval_axes.registry import AXIS_TYPES  # noqa: F401  导入即注册，PROCESS_SPECS 才有内容
        from impl.projects.llm_probe.eval_axes.adapters.process_common import PROCESS_SPECS

        self.dossier = dossier
        self.enabled = enabled
        self.catalog_text = render_catalog(build_catalog(dossier))
        self.table = build_links(dossier)
        self.links = {link["link_id"]: link for link in self.table["links"]}
        self.flagged = program_suspects(self.table["links"])
        self.gap_ids = {str(gap["id"]) for gap in dossier.get("gaps") or []}
        self.index = EvidenceIndex(dossier)
        downstream = [{"axis": axis_id, "link_types": list(AXIS_LINK_TYPES[axis_id]),
                       "question": PROCESS_SPECS[axis_id].question, "excludes": PROCESS_SPECS[axis_id].excludes,
                       "requires": PROCESS_SPECS[axis_id].requires}
                      for axis_id in enabled if axis_id in PROCESS_SPECS]
        self.prompt = "\n\n".join([
            "## 案卷目录\n" + self.catalog_text,
            "## 环节表（程序从 Agno 结构枚举）\n" + json.dumps(self.table, ensure_ascii=False),
            "## 程序已标出的可疑环节（program_suspects）\n" + json.dumps(self.flagged, ensure_ascii=False),
            "## 启用的下游轴与需求\n" + json.dumps(downstream, ensure_ascii=False),
            f"## 预算\n工具调用共 {TOOL_CALL_LIMIT} 次（含 {SUBMIT}，被拒的也算）；"
            f"一次 collect 取回总量上限 {MAX_COLLECT_CHARS} 字。",
            "## 取证工具\n" + TOOL_GUIDE,
        ])
        self.output: dict[str, Any] | None = None
        submit = VerifiableTool(
            tool_id=SUBMIT,
            description="提交整理结果（route/coverage_note/suspects）。合规返回 accepted=true；否则 accepted=false 并给出错误，改了再提交。",
            parameters=SUBMIT_PARAMETERS,
            execute_fn=self._submit,
        )
        receipts = ReceiptGate(self.index, {SUBMIT}, payload_refs, allowed=self.gap_ids)
        self.loop = ToolLoop(
            "trace_analysis", SYSTEM, [*dossier_tools(self.index), submit], client,
            completion_hook=RequireDone([SUBMIT]),
            hooks={"pre_tool": [receipts], "post_batch": [receipts]},
            end=self._end,
            budget=BudgetStop(tool_calls=TOOL_CALL_LIMIT),
        )

    def _submit(self, **payload: Any) -> dict[str, Any]:
        try:
            _validate(payload, set(self.links))
        except ValueError as exc:
            return {"accepted": False, "error": str(exc)}
        return {"accepted": True}

    def _end(self, history: History) -> dict[str, Any]:
        accepted = [call for call in history.of(SUBMIT) if call.ok and is_accepted(call)]
        structure = _normalize_structure(accepted[-1].args)
        suspects = merge_suspects(self.flagged, structure["suspects"], self.links, self.enabled)
        structure["suspects"] = suspects
        structure["evidence_audit"] = {"reads": self.index.read_receipts,
                                       "shape_only": sorted(self.index.shape_only_ids - self.index.read_ids)}
        verdict = "partial" if any(c["status"] == "failed" for c in self.dossier["coverage"]) else "complete"
        self.output = {
            "verdict": verdict, "coverage": self.dossier["coverage"], "structure": structure, "suspects": suspects,
            "selections": axis_selections(self.table["links"], suspects, sorted(self.gap_ids), self.enabled),
            "catalog_chars": len(self.catalog_text),
            "usage": {"tool_calls": len(history.calls), "read_ids": len(self.index.read_ids),
                      "suspects": len(suspects)},
        }
        return {"status": "accepted"}

    def as_tool(self) -> VerifiableTool:
        """父 loop 看到的形态：无参数；子 loop 的输入是程序备好的案卷材料，不经父模型转述。"""
        return self.loop.as_tool(
            "整理本案案卷：读目录与环节表、取回正文、列出值得各轴核对的可疑环节。每个案例只调用一次；各轴 eval_* 的提交要等它返回。",
            {"type": "object", "properties": {}, "required": []},
            render=lambda args: self.prompt,
        )
