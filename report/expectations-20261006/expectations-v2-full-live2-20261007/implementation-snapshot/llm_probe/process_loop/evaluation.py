"""Agno 六轴父 ToolLoop：共用单位格式与校验，原文块预交付，运行证据按需读取。"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from impl.core.tool_loop import (
    Abort, Allow, BudgetStop, Call, DependsOn, Done, Failed, History, Hook, LoopContext, PreDecision,
    RequireDone, StopVerdict, ToolLoop, StepClient, after, is_accepted, until_accepted)
from impl.projects.llm_probe.business_trace.dossier import build_catalog, render_catalog
from impl.projects.llm_probe.business_trace.links import LIMITS
from impl.projects.llm_probe.business_trace.design_rules import dossier_blocks
from impl.projects.llm_probe.business_trace.tools import MAX_COLLECT_CHARS, TOOL_GUIDE, EvidenceIndex
from impl.projects.llm_probe.eval_axes.adapters.process_common import (
    _absent_obligation, _axis_links, _outcome, annotate, pair_up, project_obligations)
from impl.projects.llm_probe.eval_axes.adapters.process_output import (
    OUTPUT, UNIT_SYSTEM, UNIT_CONSUMER, build_units, validate_submission)
from impl.projects.llm_probe.eval_axes.adapters.process_protocol import issues_for, validate_issue_references
from impl.projects.llm_probe.eval_axes.adapters.trace_analysis import PROCESS_AXES
from impl.tools.protocol import VerifiableTool

from .analysis import Analysis, ReceiptGate
from .expectation_projection import required_units, criteria_for, validate_dossier_expectations, validate_projection
from .tools import dossier_tools

ANALYSIS_TOOL = "trace_analysis"
EVAL_PREFIX = "eval_"
# 1 次整理 + 每轴约 1~2 次取件、1 次提交、偶尔 1 次被拒重交（实测每轴 pending 0~12 对）。
TOOL_CALLS = 40

SYSTEM = UNIT_SYSTEM + UNIT_CONSUMER + """
【本次 ToolLoop 执行方式】
先调用 trace_analysis 整理案卷，各轴 briefing 给 units、criteria、original_blocks、links 与 obligations。
original_blocks 已完整交付；其余 evidence_refs/reference_catalog 只是索引，用 dossier_collect/dossier_read 补齐正文。
每轴用 eval_<axis> 提交 reason/scope_note/units/problems，不能自造行使、端点或判准编号。
pass/fail 需要读齐该单位实际输入输出；缺必要端点只能说明具体缺证，不能用目录或规则块冒充运行正文。
取证返回后的下一批才能引用正文。同一批工具调用之间看不到彼此结果。独立取证可并列发出。
input_invalid 必须先取得已定位上游问题的 accepted 回执，再在依赖轴引用该 problem_id；没有回执不得猜 ID。
本次每份 briefing.axis 指定职责；有 units 的启用轴全部 accepted 后结束；没有 units 的轴已由程序判断。
被拒后依据回执修正，不删除真实问题来通过检查。
"""

EVAL_PARAMETERS = OUTPUT.json_schema()
for key, description in {'reason': '本轴结论理由', 'scope_note': '已检查范围与不可见边界',
                         'units': '逐单位判准核对与原文块标注', 'problems': '独立问题及判准引用'}.items():
    EVAL_PARAMETERS['properties'][key]['description'] = description

@dataclass
class AxisCase:
    """一轴的判定材料：与 run_process_axis 开头同一算法。"""

    axis_id: str
    obligations: dict[str, Any]
    links: dict[str, dict[str, Any]]
    decided: dict[tuple[str, str], dict[str, Any]]
    pending: list[tuple[str, str]]
    selection: Mapping[str, Any]
    criteria: dict[tuple[str, str], list[str]]
    units: dict[str, Any]
    short_criteria: dict[str, str]
    blocks: dict[str, Any]

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
    by_ob, by_link = {ob.obligation_id: ob for ob in obligations}, {link["link_id"]: link for link in links}
    criteria = criteria_for(pending, by_link, by_ob)
    units, short_criteria, blocks = build_units(pending, criteria, by_link, dossier_blocks(dossier, list(by_link.values()), axis_id))
    return AxisCase(axis_id, by_ob, by_link, decided, pending, (analysis["selections"] or {}).get(axis_id) or {},
                    criteria, units, short_criteria, blocks)


def briefing(case: AxisCase) -> dict[str, Any]:
    """单位/判准/完整设计原文块；运行证据正文仍须读取。"""
    from impl.projects.llm_probe.eval_axes.adapters.process_common import PROCESS_SPECS

    spec = PROCESS_SPECS[case.axis_id]
    pending: dict[str, list[dict[str, Any]]] = {}
    for ob_id, link_id in case.pending:
        pending.setdefault(ob_id, []).append({"link_id": link_id, "criteria": case.criteria[(ob_id, link_id)]})
    why = case.selection.get("why") or []
    return {
        "axis": case.axis_id, "tool": case.tool if case.pending else None,
        "question": spec.question, "excludes": spec.excludes,
        "obligations": [{"obligation_id": ob.obligation_id, "link_type": ob.link_type, "situation": ob.situation,
                         "duty": ob.duty, "source": ob.source}
                        for ob in case.obligations.values() if ob.obligation_id in pending],
        "units": case.units, "criteria": case.short_criteria, "original_blocks": case.blocks,
        "program_results": [{k: r[k] for k in ("obligation_id", "link_id", "outcome", "observed")}
                            for r in case.decided.values()],
        "links": list(case.links.values()),
        "suspects": [why] if isinstance(why, str) else list(why),
        "evidence_refs": list(case.selection.get("refs") or []),
    }


def result_refs(payload: Mapping[str, Any]) -> list[str]:
    """只收集模型可写的运行证据引用；规则引用由共享校验核对原文块。"""
    refs = []
    for item in payload.get('units', []) if isinstance(payload.get('units'), list) else []:
        necessity = item.get('necessity') if isinstance(item, Mapping) else None
        if isinstance(necessity, Mapping) and isinstance(necessity.get('evidence'), list):
            refs.extend(r for r in necessity['evidence'] if isinstance(r, str))
    for problem in payload.get('problems', []) if isinstance(payload.get('problems'), list) else []:
        if isinstance(problem, Mapping) and isinstance(problem.get('evidence'), list):
            refs.extend(r for r in problem['evidence'] if isinstance(r, str))
    return refs


def validate_read_endpoints(results, links, readable):
    """ToolLoop 的派生端点也须读过；不能过滤未读端后凭剩下一端判通过。"""
    for row in results:
        link = links.get(row.get('matched_link_id') or row['link_id'], {})
        if row['outcome'] in {'pass', 'fail'}:
            ends = {e['ref'] for side in ('input', 'output') for e in link.get(side, [])}
            unread = ends - readable
            if unread:
                raise ValueError(f"{row['link_id']}: 必要端点没有此前批次完整正文回执：{sorted(unread)}")
            if not link.get('input') or not link.get('output'):
                raise ValueError(f"{row['link_id']}: 必要输入/输出端缺失，不能判 pass/fail；须明确缺证")
        if row['outcome'] == 'not_applicable' and not any(row['evidence'].values()):
            raise ValueError(f"{row['link_id']}: 未发生须有此前批次已读的正面证据")


class EvaluationReceipts(ReceiptGate):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.issues = []

    def post_batch(self, history, calls):
        super().post_batch(history, calls)
        self.issues = [p for c in history.calls if c.ok and is_accepted(c) and isinstance(c.result, Mapping)
                       for p in c.result.get('issues', [])]
        return ()


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
                 entry: Mapping[str, Any] | None = None,
                 enabled: tuple[str, ...] = PROCESS_AXES) -> None:
        self.expectations, self.projection = copy.deepcopy(expectations), copy.deepcopy(projection)
        self.expectations_sha256 = validate_projection(self.expectations, self.projection)
        self.submitted = {}
        self.dossier = dossier
        self.trace_id = trace_id
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
                             description=f"提交 {axis_id} 轴的评测：reason/scope_note/units/problems。合规返回 accepted=true；"
                                         "否则 accepted=false 并给出错误，改了再提交。",
                             parameters=EVAL_PARAMETERS, execute_fn=self._make_submit(axis_id))
              for axis_id in enabled],
        ]
        self.receipts = receipts = EvaluationReceipts(
            self.index, {EVAL_PREFIX + axis_id for axis_id in enabled}, result_refs, allowed=self.gap_ids)
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
                    "axes": [{**briefing(case), **self._criteria_material(case),
                              "expectation_units": required_units(case.axis_id, self.expectations, self.projection)}
                             for case in self.cases.values()]}
        return analyze

    def _criteria_material(self, case: AxisCase) -> dict[str, Any]:
        cited = {ref.removeprefix("expectation:") for refs in case.criteria.values() for ref in refs
                 if ref.startswith("expectation:")}
        expectations = [e for e in self.expectations["expectations"] if e["expectation_id"] in cited]
        source_ids = {r for e in expectations for r in e["source_refs"]}
        return {"expectations": expectations,
                "expectation_sources": [s for s in self.expectations["sources"] if s["id"] in source_ids]}

    def _make_submit(self, axis_id: str) -> Callable[..., Any]:
        def submit(**payload: Any) -> dict[str, Any]:
            if not self.cases[axis_id].pending:
                return {"accepted": False, "error": f"{axis_id} 没有 pending：全部义务已由程序判定，不用提交"}
            try:
                case = self.cases[axis_id]
                results = validate_submission(payload, case.units, case.short_criteria, case.links,
                    self.receipts.backed, axis_id=axis_id, obligations=case.obligations,
                    expectations=self.expectations, required=required_units(axis_id, self.expectations, self.projection),
                    blocks=case.blocks, recorded_issues=self.receipts.issues)
                validate_read_endpoints(results, case.links, self.receipts.backed)
                validate_dossier_expectations(results, case.obligations, self.expectations, case.links, self.dossier)
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
            unverified = annotate(llm, case.obligations, case.links, readable, note, program_evidence=True)
            judged = {(r["obligation_id"], r["link_id"]): r for r in llm}
            judged.update(case.decided)
            ordered = [judged[(ob_id, link_id)] for link_id in case.links for ob_id in case.obligations
                       if (ob_id, link_id) in judged]
            for r in ordered:
                r.setdefault("flags", [])
            outcome = _outcome(ordered, case.obligations, reason, note, self.analysis.output["coverage"], {}, axis_id=case.axis_id)
            why = case.selection.get("why") or []
            outcome.output["selection"] = {"refs": list(case.selection.get("refs") or []),
                                           "why": [why] if isinstance(why, str) else list(why)}
            outcome.output["unverified_refs"] = sorted(unverified)
            outcome.output["view"] = {"kind": "dossier", "execution": "tool_loop",
                                      "expectations_sha256": self.expectations_sha256}
            if 'design_sha256' in self.projection:
                outcome.output["view"]["design_sha256"] = self.projection['design_sha256']
            out.append({"type_id": case.axis_id, "status": "succeeded",
                        "verdict": outcome.output["assessment"]["verdict"],
                        "output": outcome.output, "summary": outcome.summary.as_dict()})
        validate_issue_references({item["type_id"]: item["output"] for item in out})
        return out


def scenario_entry(project_id: str, capability_ref: str) -> Mapping[str, Any] | None:
    """场景条目里的 process_obligations；轴的判定口径只来自协议与定格期望。"""
    from impl.core.capability_store import load_capability_map

    entry = load_capability_map(project_id).get(capability_ref)
    return entry if isinstance(entry, Mapping) else None
