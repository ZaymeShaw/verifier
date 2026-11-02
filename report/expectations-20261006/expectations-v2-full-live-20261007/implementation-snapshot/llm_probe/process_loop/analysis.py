"""案卷整理的统一 ToolLoop；评测轴入口和嵌套评测共用。

submit_structure 校验结构与实际读取回执；拒绝原因在同一会话中返回。
证据与关联编号分别处理；预算耗尽则明确失败，不删除发现以产出部分结构。
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
    PROCESS_AXES, LLM_CALL_LIMIT, ANALYSIS_SECONDS, UNCLASSIFIED, _normalize_structure, _suspect_refs, _validate,
    axis_selections, merge_suspects, prepare_selections)
from impl.tools.protocol import VerifiableTool

from .tools import dossier_tools, derive_prompt

SUBMIT = "submit_structure"

SYSTEM = derive_prompt(base._SYSTEM, {
    "只输出 schema 中的 JSON。":
        f"同一批读取的正文要到下一批才可作为证据提交。定稿后调用 {SUBMIT} 提交 route/coverage_note/existing_link_suspects/new_link_suspects；被拒就按原因改了再提交，直到被接受。不要在回复文本里输出 JSON。",
})

_ROUTE_ITEM = {"type": "object", "properties": {
    "action": {"type": "string", "description": "这一步在做什么"},
    "purpose": {"type": "string", "description": "这一步的用途"},
    "evidence_refs": {"type": "array", "items": {"type": "string"}, "description": "读过正文的案卷编号"},
    "input_refs": {"type": "array", "items": {"type": "string"}, "description": "输入端编号"},
    "output_refs": {"type": "array", "items": {"type": "string"}, "description": "输出端编号"},
}, "required": ["action", "purpose", "evidence_refs", "input_refs", "output_refs"], "additionalProperties": False}

_SOURCE_REFS = {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1,
                "description": "支持该发现的已读原文编号；目录已给出理由的缺口编号也可引用。不能为空。"}
_WHY = {"type": "string", "minLength": 1, "description": "为什么值得核对，只写有证据的观察，不下评测结论"}
_EXISTING_SUSPECT_ITEM = {"type": "object", "properties": {
    "link_id": {"type": "string", "minLength": 1, "description": "从已有环节表复制编号；类型和输入输出由程序查表取得"},
    "why": _WHY,
    "source_refs": _SOURCE_REFS,
}, "required": ["link_id", "why", "source_refs"], "additionalProperties": False}

_NEW_SUSPECT_ITEM = {"type": "object", "properties": {
    "link_type": {"type": "string", "enum": [*LINK_TYPES, UNCLASSIFIED],
                  "description": "原表漏列但运行证据中实际存在的步骤类型；确实无法分类时用 unclassified。编号由程序生成。"},
    "input_refs": {"type": "array", "items": {"type": "string", "minLength": 1},
                   "description": "输入端的已读证据编号；该端未记录则 []，输入输出不能同时为空"},
    "output_refs": {"type": "array", "items": {"type": "string", "minLength": 1},
                    "description": "输出端的已读证据编号；该端未记录则 []，输入输出不能同时为空"},
    "why": _WHY,
    "source_refs": _SOURCE_REFS,
}, "required": ["link_type", "input_refs", "output_refs", "why", "source_refs"], "additionalProperties": False}

SUBMIT_PARAMETERS = {"type": "object", "properties": {
    "route": {"type": "array", "items": _ROUTE_ITEM, "description": "按轮次的行动路线"},
    "coverage_note": {"type": "string", "description": "结构可还原程度"},
    "existing_link_suspects": {"type": "array", "items": _EXISTING_SUSPECT_ITEM,
                               "description": "已有环节中值得核查的步骤；没有发现则 []，不放占位记录"},
    "new_link_suspects": {"type": "array", "items": _NEW_SUSPECT_ITEM,
                          "description": "运行证据里发现的、原表漏列的可疑步骤；没有发现则 []，不表示应该发生但未发生的步骤"},
}, "required": ["route", "coverage_note", "existing_link_suspects", "new_link_suspects"], "additionalProperties": False}


def payload_refs(payload: Mapping[str, Any]) -> list[str]:
    """提交里引用的全部编号。在 _validate 之前调用，形状不对的部分跳过（形状错误由 submit 自己报）。"""
    refs: list[str] = []
    for item in payload.get("route", []) if isinstance(payload.get("route"), list) else []:
        if isinstance(item, Mapping):
            for key in ("evidence_refs", "input_refs", "output_refs"):
                if isinstance(item.get(key), list):
                    refs.extend(ref for ref in item[key] if isinstance(ref, str))
    for name in ("existing_link_suspects", "new_link_suspects"):
        for item in payload.get(name, []) if isinstance(payload.get(name), list) else []:
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
                            "若已读证据足以支撑陈述，移除额外关联引用；否则补读（dossier_collect/dossier_read）后再提交，或收窄陈述。不要仅删引用来保留无依据的断言")
        return Deny(f"{call.tool} 被拒：" + "；".join(problems)) if problems else Allow()


class StructureCompleted(RequireDone):
    """接受整理提交后进入完整 stop/end 检查，不再请求模型生成收尾文本。"""

    def __init__(self) -> None:
        super().__init__([SUBMIT])

    def ready_to_finish(self, history: History) -> bool:
        return any(call.ok and is_accepted(call) for call in history.of(SUBMIT))


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
            f"## 预算\nLLM 调用最多 {LLM_CALL_LIMIT} 轮；每轮可同时发出多个取证工具调用，按轮次计预算。"
            f"{SUBMIT} 被拒后修正仍占下一轮，须预留轮次；最后一轮及时提交，验收通过即结束。"
            f"一次 collect 取回总量上限 {MAX_COLLECT_CHARS} 字。",
            "## 取证工具\n" + TOOL_GUIDE,
        ])
        self.output: dict[str, Any] | None = None
        submit = VerifiableTool(
            tool_id=SUBMIT,
            description="提交 route/coverage_note/existing_link_suspects/new_link_suspects；两类发现分别列出，没有发现的列表填 []。合规返回 accepted=true，否则按错误修正。",
            parameters=SUBMIT_PARAMETERS,
            execute_fn=self._submit,
        )
        receipts = ReceiptGate(self.index, {SUBMIT}, payload_refs, allowed=self.gap_ids)
        self.loop = ToolLoop(
            "trace_analysis", SYSTEM, [*dossier_tools(self.index), submit], client,
            completion_hook=StructureCompleted(),
            hooks={"pre_tool": [receipts], "post_batch": [receipts]},
            end=self._end,
            budget=BudgetStop(llm_calls=LLM_CALL_LIMIT, seconds=ANALYSIS_SECONDS),
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
        suspects = merge_suspects(self.flagged, structure.pop("existing_link_suspects"),
                                  structure.pop("new_link_suspects"), self.links, self.enabled)
        structure["suspects"] = suspects
        structure["evidence_audit"] = {"reads": self.index.read_receipts,
                                       "shape_only": sorted(self.index.shape_only_ids - self.index.read_ids),
                                       "submissions": [{"accepted": c.ok and is_accepted(c),
                                                        "reason": c.denied or c.error or (c.result or {}).get("error", "")}
                                                       for c in history.of(SUBMIT)]}
        verdict = "partial" if any(c["status"] == "failed" for c in self.dossier["coverage"]) else "complete"
        self.output = {
            "verdict": verdict, "coverage": self.dossier["coverage"], "structure": structure, "suspects": suspects,
            "selections": prepare_selections(self.dossier, structure,
                axis_selections(self.table["links"], suspects, sorted(self.gap_ids), self.enabled)),
            "catalog_chars": len(self.catalog_text),
            "usage": {"llm_calls": history.llm_calls, "tool_calls": len(history.calls), "read_ids": len(self.index.read_ids),
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
