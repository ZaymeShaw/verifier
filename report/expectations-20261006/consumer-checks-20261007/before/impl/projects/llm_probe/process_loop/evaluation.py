"""实例 B：六轴过程评测作为父 ToolLoop，案卷整理（实例 A）作为它的一个 tool（spec §6）。

与 eval_axes 的 run_process_axis 同一套判定材料与规则（义务、pair_up、ProcessAssessment、check_coverage、
annotate、_outcome 均复用）。差异：
- 六轴共用一段会话（策略 a）：trace_analysis 返回每轴的紧凑 briefing（pending 对、义务、可疑理由、证据编号），
  不再给每轴预装 80k 的 dossier_view，正文由评测模型按需 dossier_collect；
- 每轴的最终 JSON → eval_<axis> tool：execute 里跑 enforce_output + _expand + check_coverage，被拒在同一会话里改；
- 引用读取回执：annotate 事后标注 → ReceiptGate 提交前拒（此前批次的正文回执、gaps、case、project:）；
- depend_on/blocked、格式重试、salvage → spec §6 的标准 hook + loop failed（见 hooks()）：
  整理失败或预算耗尽，整个 case failed，无部分结果。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from impl.core.structured_output import StructuredOutputSpec, enforce_output
from impl.core.tool_loop import (
    Abort, Allow, BudgetStop, Call, DependsOn, Done, Failed, History, Hook, LoopContext, PreDecision,
    RequireDone, StopVerdict, ToolLoop, StepClient, after, is_accepted, until_accepted)
from impl.core.materials_store import expand_material_uris
from impl.projects.llm_probe.business_trace.dossier import build_catalog, render_catalog
from impl.projects.llm_probe.business_trace.links import LIMITS
from impl.projects.llm_probe.business_trace.tools import MAX_COLLECT_CHARS, TOOL_GUIDE, EvidenceIndex
from impl.projects.llm_probe.eval_axes.adapters.process_common import (
    _SYSTEM as BASE_SYSTEM, ProcessAssessment, _absent_obligation, _axis_links, _expand,
    _outcome, _special_ref, annotate, check_coverage, pair_up, project_obligations, validate_result_evidence)
from impl.projects.llm_probe.eval_axes.adapters.process_protocol import (issues_for, validate_units, validate_issue_references)
from impl.projects.llm_probe.eval_axes.adapters.trace_analysis import PROCESS_AXES
from impl.tools.protocol import VerifiableTool

from .analysis import Analysis, ReceiptGate
from .expectation_projection import required_units, contracts_for, bind_results, validate_contract_coverage, validate_dossier_expectations, CONSUMER_PROMPT
from .tools import dossier_tools
from ..process_contract import criterion_text

ANALYSIS_TOOL = "trace_analysis"
EVAL_PREFIX = "eval_"
# 1 次整理 + 每轴约 1~2 次取件、1 次提交、偶尔 1 次被拒重交（实测每轴 pending 0~12 对）。
TOOL_CALLS = 40

SYSTEM = BASE_SYSTEM + CONSUMER_PROMPT + """
【本次执行方式】
先调用 trace_analysis 整理案卷，返回各轴 briefing：question/excludes/scenario_criterion、obligations、pending、program_results、links、suspects、evidence_refs。
初始 briefing 只有索引，没有预装正文。合并各轴需要的 evidence_refs，用 dossier_collect 批量取证；大条目按工具回执补读。
取证返回后的下一批才能引用正文。同一批工具调用之间看不到彼此结果。独立取证可并列发出。
如果某项要判 input_invalid，先提交并取得其已定位上游问题的 accepted 回执，再在依赖轴引用该 problem_id；没有回执时不得猜 ID。没有这种依赖的轴可并列提交。
引用只用此前批次取得完整正文的编号、已有 gaps 编号、case、expectation:<id> 或 obligation:<id>；关联编号不能冒充正文。
本次没有 dimension 单轴字段：每份 briefing.axis 指定其职责。每轴调用 eval_<axis>，只提交该轴 pending，不在普通回复中输出最终 JSON。
有 pending 的启用轴全部 accepted 后结束；没有 pending 的轴已由程序判断。被拒后依据回执修正，不删除真实问题来通过检查。
"""

OUTPUT_SPEC = StructuredOutputSpec.from_dataclass(
    ProcessAssessment, required_nonempty=["reason", "scope_note"],
    description="pending 中每一对（obligation_id, link_id）恰好出现一次；fail 写两端证据；insufficient_evidence 必填 missing。",
)

EVAL_PARAMETERS = OUTPUT_SPEC.json_schema()
for key, description in {"reason": "本轴判定理由", "scope_note": "检查范围", "results": "逐项结论、问题与上游引用"}.items():
    EVAL_PARAMETERS["properties"][key]["description"] = description

@dataclass
class AxisCase:
    """一轴的判定材料：与 run_process_axis 开头同一算法。"""

    axis_id: str
    obligations: dict[str, Any]
    links: dict[str, dict[str, Any]]
    decided: dict[tuple[str, str], dict[str, Any]]
    pending: list[tuple[str, str]]
    selection: Mapping[str, Any]

    @property
    def tool(self) -> str:
        return EVAL_PREFIX + self.axis_id


def axis_case(axis_id: str, dossier: Mapping[str, Any], analysis: Mapping[str, Any],
              entry: Mapping[str, Any] | None, expectations, projection) -> AxisCase:
    from impl.projects.llm_probe.eval_axes.adapters.process_common import PROCESS_SPECS

    links = _axis_links(axis_id, dossier, analysis["structure"]) + required_units(axis_id, expectations, projection)
    obligations = PROCESS_SPECS[axis_id].obligations + project_obligations(entry, axis_id)
    if not links:
        absent = _absent_obligation(axis_id)
        obligations = (absent,)
        links = [{"link_id": f"{axis_id}:none", "link_type": absent.link_type, "turn": "", "input": [], "output": [],
                  "facts": {}, "basis": "程序未列出本轴类型的环节"}]
    decided, pending = pair_up(obligations, links)
    return AxisCase(axis_id, {ob.obligation_id: ob for ob in obligations}, {link["link_id"]: link for link in links},
                    decided, pending, (analysis["selections"] or {}).get(axis_id) or {})


def briefing(case: AxisCase, criterion: str) -> dict[str, Any]:
    """父模型看到的本轴材料：不含正文，只有判什么、判哪几对、先读哪些编号。"""
    from impl.projects.llm_probe.eval_axes.adapters.process_common import PROCESS_SPECS

    spec = PROCESS_SPECS[case.axis_id]
    pending: dict[str, list[str]] = {}
    for ob_id, link_id in case.pending:
        pending.setdefault(ob_id, []).append(link_id)
    why = case.selection.get("why") or []
    return {
        "axis": case.axis_id, "tool": case.tool if case.pending else None,
        "question": spec.question, "excludes": spec.excludes, "scenario_criterion": criterion_text(criterion),
        "obligations": [{"obligation_id": ob.obligation_id, "link_type": ob.link_type, "situation": ob.situation,
                         "duty": ob.duty, "source": ob.source}
                        for ob in case.obligations.values() if ob.obligation_id in pending],
        "pending": pending,
        "program_results": [{k: r[k] for k in ("obligation_id", "link_id", "outcome", "observed")}
                            for r in case.decided.values()],
        "links": list(case.links.values()),
        "suspects": [why] if isinstance(why, str) else list(why),
        "evidence_refs": list(case.selection.get("refs") or []),
    }


def result_refs(payload: Mapping[str, Any]) -> list[str]:
    """eval 提交里引用的编号；在 enforce_output 之前调用，形状不对的部分跳过（形状错误由提交自己报）。"""
    refs: list[str] = []
    for group in payload.get("results") or []:
        if isinstance(group, Mapping):
            for problem in group.get("problems", []):
                for key in ("source_refs", "input_refs", "output_refs"):
                    refs.extend(problem.get(key, []))
            for key in ("source_refs", "input_refs", "output_refs"):
                refs.extend(ref for ref in (group.get(key) or []) if isinstance(ref, str))
    return refs


def analysis_failure(history: History) -> str:
    """trace_analysis 已执行但没被接受的原因；还没执行或已接受返回空串。被拒的调用没执行，不算。"""
    call = next((c for c in history.of(ANALYSIS_TOOL) if not c.denied), None)
    if call is None or is_accepted(call):
        return ""
    if call.error:
        return call.error
    result = call.result if isinstance(call.result, Mapping) else {}
    return str(result.get("reason") or "未返回结果")[:500]


class AnalysisFailed(Hook):
    """子 loop 失败是否算父 loop 失败由父层 hook 决定（spec §3.5）：这里算。

    整理不出结构，各轴没有待判材料，继续只会被 DependsOn 拒到预算 / max_blocked 用完；直接失败更早暴露同一个原因。
    模型还在调工具时在 pre_tool 止住（stop 问不到），模型停下时在 stop 止住。
    """

    def pre_tool(self, history: History, call: Call) -> PreDecision:
        failure = analysis_failure(history)
        return Abort(f"案卷整理失败：{failure}") if failure else Allow()

    def stop(self, history: History, blocked: int) -> StopVerdict:
        failure = analysis_failure(history)
        return Failed(f"案卷整理失败：{failure}") if failure else Done()


def hooks(cases: Callable[[], Mapping[str, AxisCase] | None], axes: Sequence[str]) -> tuple[Hook, dict[str, list[Hook]]]:
    """返回核心完成 hook 与按事件注册的辅助 hooks（spec §6）：
    - eval_* 依赖 trace_analysis 被接受；任何 tool 被接受后不再重复调用（含 trace_analysis）；
    - 整理失败 → 整案失败；
    - 做完 = trace_analysis 被接受，且有 pending 的轴都被接受（清单要等整理结果才知道）。
    pending 为空的轴提交了由 eval_* 自己打回（内容合规，不是次序）。
    """
    evals = [EVAL_PREFIX + axis_id for axis_id in axes]
    once = until_accepted()

    def required(history: History) -> list[str]:
        if not any(c.ok and is_accepted(c) for c in history.of(ANALYSIS_TOOL)):
            return [ANALYSIS_TOOL]
        return [case.tool for case in cases().values() if case.pending]

    failure = AnalysisFailed()
    return RequireDone(required), {
        'pre_tool': [failure,
                     DependsOn({tool: after(ANALYSIS_TOOL, accepted=is_accepted) for tool in evals}),
                     DependsOn({tool: once for tool in [ANALYSIS_TOOL, *evals]})],
        'stop': [failure],
    }


def _trail(call: Call) -> dict[str, Any]:
    """报告里的调用轨迹：被拒 / 出错 / 提交被打回各带原因，不必回翻 ContextRecord。"""
    result = call.result if call.ok and isinstance(call.result, Mapping) else {}
    return {"id": call.id, "batch": call.batch, "tool": call.tool, "denied": call.denied, "error": call.error,
            "accepted": result.get("accepted"), "rejected": str(result.get("error") or "")[:500]}


class Evaluation:
    """一个 case 的六轴过程评测。run() 返回报告；loop 失败时 status=failed，没有任何轴的部分结论。"""

    def __init__(self, dossier: Mapping[str, Any], client: StepClient, *, expectations, projection, trace_id: str,
                 criteria: Mapping[str, str] | None = None, entry: Mapping[str, Any] | None = None,
                 enabled: tuple[str, ...] = PROCESS_AXES) -> None:
        self.expectations, self.projection = expectations, projection
        self.submitted = {}
        self.dossier = dossier
        self.trace_id = trace_id
        self.criteria = dict(criteria or {})
        self.entry = entry
        self.enabled = enabled
        self.catalog_text = render_catalog(build_catalog(dossier))
        self.index = EvidenceIndex(dossier)
        self.gap_ids = {str(gap["id"]) for gap in dossier.get("gaps") or []}
        self.analysis = Analysis(dossier, client, enabled)
        self.cases: dict[str, AxisCase] | None = None
        inner = self.analysis.as_tool()
        tools = [
            VerifiableTool(tool_id=ANALYSIS_TOOL, description=inner.description, parameters=inner.parameters,
                           execute_fn=self._make_analyze(inner.execute_fn)),
            *dossier_tools(self.index),
            *[VerifiableTool(tool_id=EVAL_PREFIX + axis_id,
                             description=f"提交 {axis_id} 轴的评测：reason/scope_note/results。合规返回 accepted=true；"
                                         "否则 accepted=false 并给出错误，改了再提交。",
                             parameters=EVAL_PARAMETERS, execute_fn=self._make_submit(axis_id))
              for axis_id in enabled],
        ]
        receipts = ReceiptGate(self.index, {EVAL_PREFIX + axis_id for axis_id in enabled}, result_refs,
                               allowed=self.gap_ids, special=_special_ref)
        completion, lifecycle = hooks(lambda: self.cases, enabled)
        lifecycle['pre_tool'].append(receipts)
        lifecycle['post_batch'] = [receipts]
        self.loop = ToolLoop("llm_probe_process_loop", SYSTEM, tools, client,
                             completion_hook=completion, hooks=lifecycle, end=lambda history: None,
                             budget=BudgetStop(tool_calls=TOOL_CALLS))

    def _make_analyze(self, execute: Callable[..., Any]) -> Callable[..., Any]:
        def analyze(**args: Any) -> dict[str, Any]:
            result = execute(**args)
            if not (isinstance(result, Mapping) and result.get("status") == "accepted"):
                # 子 loop 失败：与各提交类 tool 同一口径（accepted=false），常用 hook 用 is_accepted 就能判
                return {**(result if isinstance(result, Mapping) else {"reason": str(result)}), "accepted": False}
            self.cases = {axis_id: axis_case(axis_id, self.dossier, self.analysis.output, self.entry, self.expectations, self.projection)
                          for axis_id in self.enabled}
            return {"status": "accepted", "accepted": True, "limits": LIMITS,
                    "axes": [{**briefing(case, self.criteria.get(case.axis_id, "")),
                              "expectations": contracts_for(case.axis_id, self.expectations, self.projection),
                              "expectation_sources": self.expectations['sources'],
                              "expectation_units": required_units(case.axis_id, self.expectations, self.projection)}
                             for case in self.cases.values()]}
        return analyze

    def _make_submit(self, axis_id: str) -> Callable[..., Any]:
        def submit(**payload: Any) -> dict[str, Any]:
            if not self.cases[axis_id].pending:
                return {"accepted": False, "error": f"{axis_id} 没有 pending：全部义务已由程序判定，不用提交"}
            try:
                enforce_output(payload, OUTPUT_SPEC, caller=axis_id)
                results = _expand(payload["results"])
                check_coverage(results, self.cases[axis_id].pending)
                bind_results(results, self.cases[axis_id].obligations, self.expectations,
                             required_units(axis_id, self.expectations, self.projection),
                             runtime_links={k: l for k, l in self.cases[axis_id].links.items() if l.get('origin') != 'expectation_deduction'})
                validate_contract_coverage(results, axis_id, self.projection)
                validate_dossier_expectations(results, self.cases[axis_id].obligations, self.expectations, self.cases[axis_id].links, self.dossier)
                validate_units(results, axis_id)
                validate_result_evidence(results, self.cases[axis_id].obligations,
                                         self.cases[axis_id].links, self.index.read_ids | self.gap_ids)
            except (ValueError, KeyError, TypeError) as exc:
                return {"accepted": False, "error": str(exc)[:1500]}
            self.submitted[axis_id] = results
            return {"accepted": True, "issues": issues_for(axis_id, results)}
        return submit

    def _user(self) -> str:
        return "\n\n".join([
            f"## 案例\n{self.trace_id}",
            "## 案卷目录\n" + self.catalog_text,
            "## 取证工具\n" + TOOL_GUIDE + f"\n一次 collect 取回总量上限 {MAX_COLLECT_CHARS} 字。",
            f"## 预算\n工具调用共 {TOOL_CALLS} 次（含 trace_analysis 与各轴提交，被拒的也算）。",
        ])

    def run(self) -> dict[str, Any]:
        started = time.monotonic()
        result = self.loop.run(self._user(), LoopContext(trace_id=self.trace_id))
        usage = {"segments": result.segments, "tool_calls": len(result.calls),
                 "analysis_tool_calls": (self.analysis.output or {}).get("usage", {}).get("tool_calls"),
                 "elapsed_ms": int((time.monotonic() - started) * 1000)}
        calls = [_trail(c) for c in result.calls]
        if result.status != "complete":
            return {"status": "failed", "reason": result.reason, "usage": usage, "calls": calls}
        return {"status": "complete", "trace_analysis": self.analysis.output, "axes": self._axes(result.calls),
                "usage": usage, "calls": calls}

    def _axes(self, calls: Sequence[Call]) -> list[dict[str, Any]]:
        readable = self.index.read_ids | self.gap_ids
        accepted = {c.tool: c.args for c in calls if c.ok and is_accepted(c)}
        out = []
        for case in self.cases.values():
            if case.pending:
                payload = accepted[case.tool]
                llm, reason, note = self.submitted[case.axis_id], payload["reason"], payload["scope_note"]
            else:
                llm, reason, note = [], "本轴全部义务由程序按机器事实判定", "程序判定：" + "、".join(case.links)
            unverified = annotate(llm, case.obligations, case.links, readable, note)
            judged = {(r["obligation_id"], r["link_id"]): r for r in llm}
            judged.update(case.decided)
            ordered = [judged[(ob_id, link_id)] for link_id in case.links for ob_id in case.obligations
                       if (ob_id, link_id) in judged]
            for r in ordered:
                r.setdefault("flags", [])
            outcome = _outcome(ordered, case.obligations, reason, note, self.analysis.output["coverage"], {}, axis_id=case.axis_id, criterion=self.criteria.get(case.axis_id, ""))
            why = case.selection.get("why") or []
            outcome.output["selection"] = {"refs": list(case.selection.get("refs") or []),
                                           "why": [why] if isinstance(why, str) else list(why)}
            outcome.output["unverified_refs"] = sorted(unverified)
            out.append({"type_id": case.axis_id, "status": "succeeded",
                        "verdict": outcome.output["assessment"]["verdict"],
                        "output": outcome.output, "summary": outcome.summary.as_dict()})
        validate_issue_references({item["type_id"]: item["output"] for item in out})
        return out


def criteria_for(project_id: str, capability_ref: str) -> tuple[dict[str, str], Mapping[str, Any] | None]:
    """场景条目给每轴的判准（与 build_report 同口径：条目里配了就用，否则用轴的 question）与 process_obligations。"""
    from impl.core.capability_store import load_capability_map
    from impl.projects.llm_probe.eval_axes.adapters.process_common import PROCESS_SPECS
    from impl.projects.llm_probe.eval_axes.validate import load_scenario_axes

    axes, _ = load_scenario_axes(project_id, capability_ref)
    configured = {axis.type_id: axis.description for axis in axes}
    criteria = {key: expand_material_uris(configured.get(key) or spec.question) for key, spec in PROCESS_SPECS.items()}
    entry = load_capability_map(project_id).get(capability_ref)
    return criteria, entry if isinstance(entry, Mapping) else None
