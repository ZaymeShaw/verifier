from __future__ import annotations

import importlib
import json
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional

from . import stop_reasons
from .capability_carrier import carrier_text
from .judge_protocol import execution_failure_markers
from .schema import AttributeResult, CheckReport, FallbackDecision, FrontendViewModel, JudgeResult, RunTrace, normalize_attribute_result, normalize_check_report, normalize_frontend_view, normalize_judge_result, normalize_run_trace, to_dict, trace_conversation_summary, trace_conversation_transcript, trace_extracted_output, trace_output_source, trace_turn_records
from .schema.accessors import trace_input as get_trace_input
from .schema.table import CasePoolTable, ConversationTurn, TraceTableRow
from .summary import summary_from_attribution, summary_from_fulfillment


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        user_intent = value.get("user_intent")
        if isinstance(user_intent, dict) and user_intent.get("goal"):
            return str(user_intent.get("goal"))
        for item in value.values():
            if isinstance(item, (str, int, float, bool)) and str(item):
                return str(item)
    return _short_value(value)


def display_input_for_project(project_id: str, input_payload: Any) -> str:
    if not isinstance(input_payload, dict):
        return _first_scalar(input_payload)
    for field in _required_input_fields(project_id):
        value = input_payload.get(field)
        if isinstance(value, (str, int, float, bool)) and str(value).strip():
            return str(value)
    return _first_scalar(input_payload)


def _display_input(trace: RunTrace, input_payload: Any) -> str:
    return display_input_for_project(trace.project_id, input_payload)


def _required_input_fields(project_id: str) -> list[str]:
    if not project_id:
        return []
    try:
        live_schema = importlib.import_module(f"impl.projects.{project_id}.live_schema")
    except ModuleNotFoundError:
        return []
    fields = getattr(live_schema, "REQUIRED_INPUT_FIELDS", [])
    return [str(field) for field in fields if isinstance(field, str)]


def _short_value(value: Any, limit: int = 160) -> str:
    if value is None or value == "":
        return ""
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _scenario(trace: RunTrace, case_context: Dict[str, Any], input_payload: Any) -> str:
    if case_context.get("scenario"):
        return str(case_context.get("scenario"))
    if trace.scenario:
        return str(trace.scenario)
    if isinstance(input_payload, dict):
        if input_payload.get("scenario"):
            return str(input_payload.get("scenario"))
        metadata = _as_dict(input_payload.get("metadata"))
        if metadata.get("scenario"):
            return str(metadata.get("scenario"))
    return ""


def _reference(trace: RunTrace, view: Optional[FrontendViewModel], judge: Optional[JudgeResult], case_context: Dict[str, Any], input_payload: Any) -> Any:
    reference_panel = view.reference_panel if view else {}
    if reference_panel.get("reference") not in (None, {}, [], ""):
        return reference_panel.get("reference")
    if trace.reference_contract not in (None, {}, [], ""):
        return trace.reference_contract
    if case_context.get("reference") not in (None, {}, [], ""):
        return case_context.get("reference")
    if isinstance(input_payload, dict):
        if input_payload.get("reference") not in (None, {}, [], ""):
            return input_payload.get("reference")
        if input_payload.get("golden_answer") or input_payload.get("gold_answer"):
            return {"actual_answer": input_payload.get("golden_answer") or input_payload.get("gold_answer")}
    return judge.expected if judge else None


def _output(trace: RunTrace, view: Optional[FrontendViewModel], judge: Optional[JudgeResult], case_context: Dict[str, Any]) -> Any:
    run_trace_summary = view.run_trace_summary if view else {}
    if run_trace_summary.get("extracted_output") not in (None, {}, [], ""):
        return run_trace_summary.get("extracted_output")
    output = trace_extracted_output(trace)
    if output not in (None, {}, [], ""):
        return output
    if case_context.get("output") not in (None, {}, [], ""):
        return case_context.get("output")
    return judge.actual if judge else None


def _fulfillment_status(judge: Optional[JudgeResult], judge_summary: Dict[str, Any], status: str) -> str:
    overall = judge.overall_fulfillment if judge else {}
    return str(judge_summary.get("fulfillment_status") or overall.get("status") or status or "")


def _conversation_detail(trace: RunTrace) -> Optional[List[ConversationTurn]]:
    records = trace_turn_records(trace)
    if records:
        detail: List[ConversationTurn] = []
        for index, record in enumerate(records, start=1):
            request = record.get("request") if isinstance(record, dict) else None
            output = record.get("extracted_output") if isinstance(record, dict) else None
            output_data = output if isinstance(output, dict) else {}
            detail.append(
                ConversationTurn(
                    turn_index=int(record.get("turn_index") or index),
                    role="turn",
                    content=_first_scalar(request),
                    stage=str(output_data.get("stage") or ""),
                    extracted_summary=_short_value(output),
                    call_status=str(record.get("call_status") or ""),
                    runtime_ms=int(record.get("runtime_ms") or 0),
                    error=str(record.get("error") or ""),
                )
            )
        return detail
    turns = trace_conversation_transcript(trace)
    if not isinstance(turns, list) or not turns:
        return None
    detail: List[ConversationTurn] = []
    for index, turn in enumerate(turns, start=1):
        if not isinstance(turn, dict):
            detail.append(ConversationTurn(turn_index=index, role="unknown", content=_short_value(turn), extracted_summary=""))
            continue
        content = turn.get("content") or turn.get("input") or turn.get("user_input") or ""
        content_text = _first_scalar(content) if isinstance(content, dict) else str(content or "")
        extracted = turn.get("extracted_summary") or turn.get("stage") or ""
        detail.append(
            ConversationTurn(
                turn_index=int(turn.get("turn_index") or turn.get("turn") or index),
                role=str(turn.get("role") or "unknown"),
                content=content_text,
                stage=str(turn.get("stage") or ""),
                extracted_summary=str(extracted),
            )
        )
    return detail


def _conversation_summary(trace: RunTrace) -> Dict[str, Any]:
    return trace_conversation_summary(trace)


def _status(trace: RunTrace, judge: Optional[JudgeResult], judge_summary: Dict[str, Any], case_context: Dict[str, Any]) -> str:
    if judge_summary.get("status"):
        return str(judge_summary.get("status"))
    if judge and judge.overall_fulfillment and isinstance(judge.overall_fulfillment, dict) and judge.overall_fulfillment.get("status"):
        return str(judge.overall_fulfillment.get("status"))
    return str(trace.status or ("error" if trace.error or case_context.get("error") else ""))


def eval_axes_summary(report: Any, project_id: str) -> List[Dict[str, Any]]:
    """扩展评估轴（试验）报告 → 表格列：每轴一条 {axis_id, title, status, verdict, text, items}。

    与 carrier_text 之于"裁决"列同一角色：只搬运运行器已经算好的 summary，不重新判断。
    报告整体失败（配置无效、钩子异常）折成一条 status=failed 的伪轴，让表格能看见。
    """
    if not isinstance(report, dict):
        return []
    if report.get("error") and not report.get("results"):
        return [{
            "axis_id": "",
            "title": "扩展评估轴",
            "display": "",
            "status": "failed",
            "verdict": None,
            "text": str(report.get("error")),
            "items": [],
        }]
    analysis = next((entry.get('output') or {} for entry in report.get('results', [])
                     if entry.get('type_id') == 'trace_analysis'), {})
    dossier = analysis.get('dossier') or {}
    records = {r['id']: r for key in ('records', 'sources', 'gaps') for r in dossier.get(key, [])}
    records.update(dossier.get('contents', {}))
    expected = next((entry.get('output') or {} for entry in report.get('results', []) if entry.get('type_id') == 'expectations'), {})
    sources = {r['id']: r for r in expected.get('sources', [])}
    records.update({'expectation:' + e['expectation_id']: {**e, 'sources': [sources[r] for r in e['source_refs']]} for e in expected.get('expectations', [])})
    rows: List[Dict[str, Any]] = []
    main = report.get("main_verdict")
    has_main = isinstance(main, dict) and bool(main.get("verdict"))
    for item in report.get("results") or []:
        if not isinstance(item, dict):
            continue
        # llm_probe_loop 的主轴结论本身是一个轴（main_verdict）：已有结论时由下面的组成行展示，这里不再重复一行
        if has_main and item.get("type_id") == "main_verdict":
            continue
        summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
        usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
        type_id = str(item.get("type_id") or item.get("axis_id") or "")
        status = str(item.get("status") or "")
        items = [dict(entry) for entry in (summary.get("items") or []) if isinstance(entry, dict)]
        output = item.get('output') or {}
        assessment = output.get('assessment') or {}
        issues = output.get('issues', [])
        # issue 带哪几种引用由项目的过程轴输出决定（llm_probe 三种都有；llm_probe_loop 只有 output_refs，引文在 quotes 里）
        cited = {ref for issue in issues for key in ('source_refs', 'input_refs', 'output_refs') for ref in issue.get(key, ())}
        render_value = importlib.import_module(f"impl.projects.{project_id}.business_trace.dossier").render_value
        evidence = {ref: render_value(dossier, records[ref]) for ref in cited if ref in records}
        kind = importlib.import_module(f"impl.projects.{project_id}.eval_axes.registry").AXIS_TYPES.get(type_id)
        rows.append({
            "role": kind.role if kind else "evaluation",
            "composition": assessment.get('composition'),
            "issues": issues if 'issues' in output else None,
            "evidence_records": evidence,
            "execution_trace_ref": item.get('execution_trace_ref', ''),
            "axis_id": str(item.get("axis_id") or ""),
            "type_id": type_id,
            "title": str(item.get("title") or type_id),
            # 明细里默认展开 / 收起（llm_probe_loop 轴定义的 display）；没带的按展开
            "display": str(item.get("display") or ""),
            "status": status,
            "verdict": item.get("verdict"),
            "text": str(summary.get("text") or item.get("error") or ""),
            "items": items,
            "tokens": eval_axis_tokens(type_id, status, item.get("verdict"), items),
            # 实际命中的模型（axe-v4 D12）：对照时能看出这条是不是备用模型判的
            "llm_model": str(usage.get("llm_model") or ""),
            "llm_calls": int(usage.get("llm_calls") or 0),
            "tool_calls": int(usage.get("tool_calls") or 0),
            "elapsed_ms": int(usage.get("elapsed_ms") or 0),
            "timed_out": bool(usage.get("timed_out")),
        })
    if has_main:
        rows.insert(0, _main_verdict_row(main))
    return rows


def _main_verdict_row(main: Dict[str, Any]) -> Dict[str, Any]:
    """主轴最终结论（M 函数已算好）折成表格一行：结论令牌 + 组成逐格（demand/main_axis.md §4.3）。"""
    composition = main.get("composition") if isinstance(main.get("composition"), dict) else {}
    items = [{"key": str(entry.get("expectation_id") or ""),
              "value": str(entry.get("status") or "") + (f"·{entry['placement']}" if entry.get("placement") else ""),
              "reason": "；".join(x for x in ("待定" if entry.get("blocking", False) is None else "blocking" if entry.get("blocking") else "非 blocking",
                                             "依据事实 " + "、".join(entry.get("claim_refs") or []) if entry.get("claim_refs") else "") if x)}
             for entry in composition.get("items") or [] if isinstance(entry, dict)]
    items += [{"key": str(claim_id), "value": "挡下结论的事实", "reason": ""} for claim_id in composition.get("blocked_by_claims") or []]
    flags = ["能不能做没区分" if composition.get("capability_undetermined") else "",
             "事实属实未核" if composition.get("claims_checked") is False else ""]
    verdict = str(main["verdict"])
    return {"role": "evaluation", "composition": None, "issues": None, "evidence_records": {}, "execution_trace_ref": "",
            "axis_id": "", "type_id": "main_verdict", "title": "主轴结论", "display": "", "status": "succeeded", "verdict": verdict,
            "text": "；".join(x for x in (str(main.get("basis") or ""), *flags) if x), "items": items,
            "tokens": [f"main_verdict:{verdict}"], "llm_model": "", "llm_calls": 0, "tool_calls": 0, "elapsed_ms": 0,
            "timed_out": False}


def eval_axis_tokens(type_id: str, status: str, verdict: Any, items: List[Dict[str, Any]]) -> List[str]:
    """一条轴的结论压成可筛选令牌 `轴id:值`，导出到 Excel 后用"包含 truthfulness:refuted"就能筛。

    轴级 verdict 一个令牌；item 级按出现过的值各一个令牌并带个数（refuted×1）；没跑成用状态当值（failed/blocked）；
    未启用不出令牌——它不是结论。轴 id 用 type_id 而不是中文标题：与预设配置一致，不随翻译漂移。
    """
    if not type_id or status == "disabled":
        return []
    if status != "succeeded":
        return [f"{type_id}:{status}"]
    if verdict not in (None, ""):
        return [f"{type_id}:{verdict}"]
    counts: Dict[str, int] = {}
    for entry in items:
        value = str(entry.get("value") or "").strip()
        if value:
            counts[value] = counts.get(value, 0) + 1
    if not counts:
        return [f"{type_id}:empty"]
    return [f"{type_id}:{value}×{count}" for value, count in counts.items()]


def _root_cause(attribute: Optional[AttributeResult]) -> str:
    if not attribute:
        return ""
    if attribute.summary:
        return str(attribute.summary.get("summary_text") or "")
    conclusions = [finding.conclusion for finding in attribute.findings if finding.conclusion]
    return "\n".join([*conclusions, attribute.unresolved_reason] if attribute.unresolved_reason else conclusions)


def _execution_failure_flags(
    judge: Optional[JudgeResult],
    trace: RunTrace,
    case_context: Dict[str, Any],
) -> List[str]:
    if judge is not None:
        return sorted(execution_failure_markers(judge))
    if trace.error or case_context.get("error") or str(trace.status or "") == "error":
        return ["batch_case_failed"]
    return []


def _judge_summary(trace: RunTrace, judge: Optional[JudgeResult], case_context: Dict[str, Any]) -> Dict[str, Any]:
    flags = _execution_failure_flags(judge, trace, case_context)
    if not judge:
        execution_error = trace.error or str(case_context.get("error") or "")
        if not execution_error:
            return {}
        return {
            "status": execution_error,
            "fulfillment_status": "",
            "score": None,
            "reason": execution_error,
            "reason_source": "execution_error",
            "reason_stage": "execution",
            "is_formal_attribution": False,
            "assessment_count": 0,
            "blocking_count": 0,
            "primary_failure_dimensions": [],
            "quality_flags": flags,
        }
    if judge.summary:
        payload = {
            "status": (judge.overall_fulfillment or {}).get("status") or trace.status or "",
            "fulfillment_status": judge.summary.get("fulfillment_status") or "",
            "score": judge.summary.get("score"),
            "reason": judge.summary.get("reason") or "",
            "reason_source": judge.summary.get("reason_source") or "",
            "reason_stage": "judge",
            "is_formal_attribution": judge.summary.get("is_formal_attribution", False),
            "assessment_count": judge.summary.get("assessment_count", 0),
            "blocking_count": judge.summary.get("blocking_count", 0),
            "primary_failure_dimensions": judge.summary.get("primary_failure_dimensions") or [],
            "quality_flags": flags,
        }
        return payload
    summary = summary_from_fulfillment(to_dict(judge))
    return {
        "status": (judge.overall_fulfillment or {}).get("status") or trace.status or "",
        "fulfillment_status": summary.get("fulfillment_status") or "",
        "score": summary.get("score"),
        "reason": summary.get("reason") or "",
        "reason_source": summary.get("reason_source") or "",
        "reason_stage": "judge",
        "is_formal_attribution": summary.get("is_formal_attribution", False),
        "assessment_count": summary.get("assessment_count", 0),
        "blocking_count": summary.get("blocking_count", 0),
        "primary_failure_dimensions": summary.get("primary_failure_dimensions") or [],
        "quality_flags": flags,
    }


def _attribution_summary(attribute: Optional[AttributeResult]) -> Dict[str, Any]:
    if not attribute:
        return {}
    if attribute.summary:
        return dict(attribute.summary)
    return summary_from_attribution(to_dict(attribute))


def _fallbacks(*items: Any) -> List[FallbackDecision]:
    fallbacks: List[FallbackDecision] = []
    for item in items:
        fallbacks.extend(list(getattr(item, "fallbacks", []) or []))
    return fallbacks


def _fallback_summary(fallbacks: List[FallbackDecision]) -> Dict[str, Any]:
    by_stage = Counter(item.source_stage or "unknown" for item in fallbacks)
    return {
        "count": len(fallbacks),
        "needs_human_review": any(item.needs_human_review for item in fallbacks),
        "quality_flags": sorted({flag for item in fallbacks for flag in (item.quality_flags or [])}),
        "by_stage": dict(by_stage),
        "reasons": [item.reason for item in fallbacks if item.reason],
    }


def _check_summary(check: Optional[CheckReport]) -> Dict[str, Any]:
    if not check:
        return {}
    return {
        "passed": check.passed,
        "issue_count": len(check.issues or []) + len(check.protocol_gaps or []) + len(check.consistency_gaps or []),
    }


def build_trace_table_row(
    trace: RunTrace,
    judge: Optional[JudgeResult],
    attribute: Optional[AttributeResult],
    view: Optional[FrontendViewModel],
    check: Optional[CheckReport],
    case_context: Optional[Dict[str, Any]] = None,
) -> TraceTableRow:
    case_context = case_context or {}
    judge_summary = _judge_summary(trace, judge, case_context)
    if not judge_summary:
        judge_summary = summary_from_fulfillment(to_dict(judge) if judge else {})
    else:
        judge_summary = dict(judge_summary)
    attribution_summary = _attribution_summary(attribute)
    if not attribution_summary:
        attribution_summary = summary_from_attribution(to_dict(attribute) if attribute else {})
    else:
        attribution_summary = dict(attribution_summary)
    input_payload = get_trace_input(trace) if get_trace_input(trace) not in (None, {}, "") else case_context.get("input") or case_context.get("case_input") or ""
    status = _status(trace, judge, judge_summary, case_context)
    fulfillment_status = _fulfillment_status(judge, judge_summary, status)
    fallbacks = _fallbacks(trace, judge, attribute, check)
    fallback_summary = _fallback_summary(fallbacks)
    check_summary = _check_summary(check)
    quality_flags = list(dict.fromkeys(
        list(judge_summary.get("quality_flags") or [])
        + list(attribution_summary.get("quality_flags") or [])
        + list(fallback_summary.get("quality_flags") or [])
    ))
    conversation_detail = _conversation_detail(trace)
    divergence_stage = ""
    issue_count = len(check.issues or []) + len(check.protocol_gaps or []) + len(check.consistency_gaps or []) if check else 0
    placement = carrier_text(case_context.get("capability_carrier"))

    return TraceTableRow(
        id=_row_id(trace, case_context),
        input=_display_input(trace, input_payload),
        scenario=_scenario(trace, case_context, input_payload),
        output_summary=_short_value(_output(trace, view, judge, case_context)),
        reference_summary=_short_value(_reference(trace, view, judge, case_context, input_payload)),
        status=status,
        execution_status=str(trace.status or ""),
        execution_error=str(trace.error or case_context.get("error") or ""),
        interaction_controller_status=str(trace.interaction_controller_status or "not_run"),
        interaction_controller_error=str(trace.interaction_controller_error or ""),
        execution_mode=str(case_context.get("execution_mode") or trace.execution_mode or ""),
        output_source=str(case_context.get("output_source") or trace_output_source(trace) or ""),
        score=judge_summary.get("score"),
        fulfillment_status=fulfillment_status,
        carrier_placement=placement,
        eval_axes_summary=eval_axes_summary(case_context.get("eval_axes"), str(trace.project_id or "")),
        stage_timings={k: int(v) for k, v in (case_context.get("stage_timings") or {}).items() if isinstance(v, (int, float))},
        judge_summary=judge_summary,
        attribution_summary=attribution_summary,
        check_summary=check_summary,
        fallback_summary=fallback_summary,
        needs_human_review=bool(fallback_summary.get("needs_human_review")),
        quality_flags=quality_flags,
        check_passed=check.passed if check else None,
        issue_count=issue_count,
        fallback_count=len(fallbacks),
        divergence_stage=divergence_stage,
        root_cause_summary=_short_value(_root_cause(attribute), 900),
        created_at=str(trace.created_at or ""),
        stop_reason=str(trace.stop_reason or ""),
        stop_attribution=stop_reasons.attribution(trace.stop_reason),
        driver_health=stop_reasons.driver_health(
            trace.stop_reason,
            trace.interaction_controller_status,
            trace.interaction_controller_error,
        ).to_dict(),
        interaction_mode=str(trace.interaction_mode or ("interactive_intent" if conversation_detail else "single_turn")),
        conversation_summary=_conversation_summary(trace),
        conversation_detail=conversation_detail,
        trace_id=str(trace.trace_id or case_context.get("trace_id") or ""),
    )


def _row_id(trace: RunTrace, case_context: Dict[str, Any]) -> str:
    if case_context.get("id"):
        return str(case_context.get("id"))
    if trace.case_id:
        return str(trace.case_id)
    return str(trace.trace_id or "")


def _trace_from_run(run: Dict[str, Any]) -> RunTrace:
    trace = normalize_run_trace(run.get("trace"))
    if trace is not None:
        return trace
    return RunTrace(trace_id=str(run.get("trace_id") or ""), project_id=str(run.get("project_id") or ""), input={}, normalized_request={})


def build_trace_table_row_from_run(run: Dict[str, Any]) -> TraceTableRow:
    existing_row = run.get("table_row")
    if isinstance(existing_row, TraceTableRow):
        return existing_row
    trace = _trace_from_run(run)
    judge = normalize_judge_result(run.get("judge"))
    attribute = normalize_attribute_result(run.get("attribute"))
    view = normalize_frontend_view(run.get("frontend_view"))
    check = normalize_check_report(run.get("check"))
    case_context = {key: run.get(key) for key in ("id", "scenario", "execution_mode", "output_source", "reference", "output", "capability_carrier", "eval_axes", "stage_timings") if run.get(key) is not None}
    return build_trace_table_row(trace, judge, attribute, view, check, case_context=case_context)


def build_case_pool_table_from_runs(project_id: str, runs: Iterable[Dict[str, Any]]) -> CasePoolTable:
    rows = [build_trace_table_row_from_run(run) for run in runs]
    return CasePoolTable(project_id=project_id, rows=rows, total=len(rows), summary={})


def build_case_pool_table(project_id: str, runs: Iterable[Dict[str, Any]]) -> CasePoolTable:
    return build_case_pool_table_from_runs(project_id, runs)
