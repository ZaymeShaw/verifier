from __future__ import annotations

import json
from dataclasses import fields
from typing import Any, Dict, Optional

from impl.core.judge_protocol import ProjectJudge
from impl.core.live_transport import _redact_headers
from impl.core.schema import JudgeResult, RunTrace, normalize_judge_result, to_dict, trace_application_boundary
from impl.projects.llm_probe_loop.capability import resolve_capability
from impl.projects.llm_probe_loop.live import application_boundary_for


def _request_payload(trace: RunTrace) -> Dict[str, Any]:
    request = trace.normalized_request if isinstance(trace.normalized_request, dict) else {}
    return dict(request)


def _capability(trace: RunTrace) -> str:
    # 能力解析失败必须 fail-fast：错误消息不能被当成 user_intent 喂给 judge。
    return resolve_capability(_request_payload(trace))


def _parse_output_text(output_text: str) -> Any:
    """output_text 能 parse 成 JSON 时返回解析结果，否则 None。

    提取协议不变（output_text 仍是唯一输出字段）；这里只是给 judge 一份
    可读的结构化视图，免得它在转义字符串里找证据找不到而误判 not_evaluable。
    """
    text = str(output_text or "").strip()
    if not text or text[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


MAIN_AXIS_SOURCE = "main_axis_source"


def _main_axis_result(judge, trace: RunTrace) -> JudgeResult:
    """无 trace 且启用主轴框：跑该预设全部框，主结论取扩展轴主轴（fulfillment）的输出。

    报告挂到 trace 上，判后 pass（run_for_trace）直接拿走，不重跑。主轴或其启用了的上游（知识查证、
    真实性）没成功 → 整案执行失败，不降级照判（spec/adapter/main-axis-switch-plan-20261018.md §3.1、§5）。
    """
    from impl.projects.llm_probe_loop.eval_axes import MAIN_AXIS, build_report, main_axis_upstream
    from impl.projects.llm_probe_loop.eval_axes.common import STATUS_FAILED, STATUS_SUCCEEDED

    if hasattr(trace, "_pending_process_report"):
        delattr(trace, "_pending_process_report")
    report = build_report(judge.spec, trace)
    trace._pending_process_report = report
    if report.get("business_failure"):
        # 命中场景登记的错误码：运行失败、不出结论（demand/main_axis.md §3.6）。
        return JudgeResult(trace_id=trace.trace_id, project_id=trace.project_id, overall_fulfillment={"status": "not_evaluable"},
                           reasoning_summary="被测系统调用失败，不出结论：" + report["business_failure"],
                           # 用现有的执行失败标记：表格与汇总按"运行失败"处理、不进统计，"补跑执行失败"能挑出来重跑。
                           evidence=["evaluation_execution_failed", "business_call_failed",
                                     {"kind": MAIN_AXIS_SOURCE, "value": "eval_axes." + MAIN_AXIS}])
    by_type = {r.get("type_id"): r for r in report["results"]}
    main = by_type.get(MAIN_AXIS) or {"type_id": MAIN_AXIS, "status": "missing"}
    # 主轴本身必须成功；上游只在预设启用了且确实跑了（没被判不适用）时才要求成功。
    broken = ([main] if main.get("status") != STATUS_SUCCEEDED else []) + [
        by_type[t] for t in sorted(main_axis_upstream())
        if t in by_type and by_type[t].get("status") == STATUS_FAILED]
    if broken:
        detail = "；".join(f"{r.get('title') or r.get('type_id')}：{r.get('status')} {str(r.get('error') or '')[:300]}".strip() for r in broken)
        return JudgeResult(
            trace_id=trace.trace_id, project_id=trace.project_id,
            overall_fulfillment={"status": "not_evaluable"},
            reasoning_summary="主轴或其依赖的评估轴没有成功，整案阻断：" + detail,
            evidence=["evaluation_execution_failed", {"kind": MAIN_AXIS_SOURCE, "value": "eval_axes." + MAIN_AXIS}],
        )
    # 判官结果只收它自己的字段；兑现轴的其余输出（期望来源、是否核了事实）留在轴结果里。
    keep = {f.name for f in fields(JudgeResult)}
    output = {k: v for k, v in (main.get("output") or {}).items() if k in keep}
    result = normalize_judge_result({**output, "trace_id": trace.trace_id, "project_id": trace.project_id})
    result.evidence = [*(result.evidence or []), {"kind": MAIN_AXIS_SOURCE, "value": "eval_axes." + MAIN_AXIS}]
    return result


class ProcessJudgeExecution:
    """主结论只由 axis loop 出（spec/alg/axis_loop.md §12.2.2）：场景没开兑现就记运行失败，不退回单次判官
    ——退回去只看最终回答、不读 trace，页面上却和正常结论一样。"""

    def run(self, judge, trace, user_intent):
        from impl.projects.llm_probe_loop.eval_axes import main_axis_enabled
        if main_axis_enabled(judge.spec, trace):
            return _main_axis_result(judge, trace)
        return JudgeResult(
            trace_id=trace.trace_id, project_id=trace.project_id, overall_fulfillment={"status": "not_evaluable"},
            reasoning_summary="场景没有启用兑现（fulfillment），llm_probe_loop 不出主结论；请在场景里开兑现及其依赖的轴。",
            evidence=["evaluation_execution_failed", {"kind": MAIN_AXIS_SOURCE, "value": "eval_axes." + MAIN_AXIS}])


class LlmProbeJudge(ProjectJudge):
    def judge_execution(self):
        return ProcessJudgeExecution()

    def build_context(self, trace: RunTrace) -> dict:
        request = _request_payload(trace)
        capability = _capability(trace)
        show_schema = request.get("show_schema")
        output = trace.extracted_output if isinstance(trace.extracted_output, dict) else {}
        output_text = str(output.get("output_text") or "")
        output_text_parsed = _parse_output_text(output_text)
        system_extras = [
            "## 能力描述\n"
            "只根据能力描述判断 output_text 是否兑现了该能力。没有 gold output，不要编造参考答案。\n",
            "## not_evaluable 的边界\n"
            "not_evaluable 只在证据本身缺失时使用：output_text 为空或无法读取。\n"
            "只要 output_text 有内容且可读，就必须对照能力描述和本次输入判 fulfilled 或 not_fulfilled。\n"
            "不要因为「不知道被测系统支不支持这种查询」而判 not_evaluable——系统能力边界是判后承载性裁决（轴2）的职责，不是本判定的输入。\n"
            "## 期望派生\n"
            "期望只来自两处：能力描述声明的职责，以及本次输入字面表达的语义。\n"
            "输入里明确表达的语义必须被输出忠实保留——等值/前缀/包含、范围与边界、数量与单位、逻辑关系；"
            "语义被放大、缩小或改写即 not_fulfilled（如输入说「姓名是张三」，输出却做前缀匹配）。\n"
            "不要发明两处都没有的要求：能力描述未声明「拒绝不支持的表述」时，不得要求输出必须拒绝。\n"
            "期望在看回答之前就该定下：写用户要得到什么，不按本次回答的内容加条件。\n",
            # spec/alg/fulfilled.md §5：判的是用户要的拿到没有；如实、属实都不是结果。
            "## 办成看结果\n"
            "判的是用户要的东西有没有拿到。回答如实、态度好、说法属实，都不等于拿到：用户要结果（一个值、一段条款、一份名单）而回答没给出，判 not_fulfilled；"
            "没拿到的原因（系统做不了、信息源本来没有、外部故障）由判后承载性裁决（轴2）区分，不在这里放行或降级。用户问的本身就是能不能、有没有时，答复就是结果。\n"
            # demand/main_axis.md §4.3、spec/alg/fulfilled.md §3.1。
            "能力描述里关于拿不到时怎么做的要求（如实说明、澄清追问、不编造）只能是附带期望（blocking=false），不能替代用户要的结果，也不能让没给出结果的核心期望判 fulfilled。\n",
        ]
        if output_text_parsed is not None:
            system_extras.append(
                "## output_text_parsed\n"
                "output_text 是 JSON 字符串，user prompt 里附了解析后的 output_text_parsed。"
                "找证据以 output_text_parsed 为准，两者内容等价。\n"
            )
        if show_schema not in (None, "", {}, []):
            system_extras.append(
                "## show_schema\n"
                "下面指出输出里哪些部分重要。没提到的部分不要当成失败依据。\n"
            )
        return {
            "intent_frame": {
                "project_id": self.spec.project_id,
                "downstream_consumer": request.get("capability_ref") or "probed HTTP service",
                "output_semantics": "output_text should fulfill the capability description",
                "capability": capability,
                "show_schema": show_schema,
                "critical_intent_dimensions": ["capability_fulfillment", "show_schema_focus"],
            },
            "system_prompt_extras": system_extras,
            "user_prompt_extras": to_dict({
                "capability": capability,
                "show_schema": show_schema,
                "request": {
                    "url": request.get("url") or "",
                    "method": request.get("method"),
                    "headers": _redact_headers(request.get("headers") or {}),
                    "body": request.get("body") or {},
                    "capability_ref": request.get("capability_ref") or "",
                },
                "output_text": output_text,
                "output_text_parsed": output_text_parsed,
                "application_boundary": trace_application_boundary(trace)
                or application_boundary_for(str(request.get("response_mode") or "json")),
            }),
        }

    def build_intent_frame(self, trace: RunTrace, context: Optional[dict] = None) -> dict:
        built = context if context is not None else self.build_context(trace)
        frame = dict(built.get("intent_frame") or {})
        frame.setdefault("request_candidates", [
            {"source": "normalized_request.body", "value": (_request_payload(trace).get("body") or {})},
        ])
        return frame

    def normalize_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        judge_result = normalize_judge_result(result) or result
        actual = trace.extracted_output if isinstance(trace.extracted_output, dict) else {}
        judge_result.actual = actual if actual else (judge_result.actual or {"output_text": ""})
        if judge_result.expected is None:
            judge_result.expected = {}
        return judge_result
