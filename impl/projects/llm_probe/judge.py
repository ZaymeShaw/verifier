from __future__ import annotations

import json
from typing import Any, Dict, Optional

from impl.core.judge_protocol import ProjectJudge
from impl.core.live_transport import _redact_headers
from impl.core.schema import JudgeResult, RunTrace, normalize_judge_result, to_dict, trace_application_boundary
from impl.projects.llm_probe.capability import resolve_capability
from impl.projects.llm_probe.live import application_boundary_for


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


class LlmProbeJudge(ProjectJudge):
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
            "not_evaluable 只在证据本身缺失时使用：output_text 为空、无法读取、或 HTTP 层失败。\n"
            "只要 output_text 有内容且可读，就必须对照能力描述和本次输入判 fulfilled 或 not_fulfilled。\n"
            "不要因为「不知道被测系统支不支持这种查询」而判 not_evaluable——系统能力边界是判后承载性裁决（轴2）的职责，不是本判定的输入。\n"
            "## 期望派生\n"
            "期望只来自两处：能力描述声明的职责，以及本次输入字面表达的语义。\n"
            "输入里明确表达的语义必须被输出忠实保留——等值/前缀/包含、范围与边界、数量与单位、逻辑关系；"
            "语义被放大、缩小或改写即 not_fulfilled（如输入说「姓名是张三」，输出却做前缀匹配）。\n"
            "不要发明两处都没有的要求：能力描述未声明「拒绝不支持的表述」时，不得要求输出必须拒绝。\n",
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
            "user_intent": capability,
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
