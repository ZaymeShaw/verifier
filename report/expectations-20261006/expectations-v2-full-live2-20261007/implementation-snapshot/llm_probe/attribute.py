from __future__ import annotations

from impl.core.attribute_protocol import ProjectAttribute
from impl.core.schema import AttributeResult, JudgeResult, RunTrace, normalize_attribute_result, to_dict


class LlmProbeAttribute(ProjectAttribute):
    def build_context(self, trace: RunTrace, judge_result: JudgeResult) -> dict:
        request = trace.normalized_request if isinstance(trace.normalized_request, dict) else {}
        actual = judge_result.actual or trace.extracted_output or {}
        return {
            "chain_nodes_to_check": list(trace.execution_trace or []),
            "reference_contract": trace.reference_contract if isinstance(trace.reference_contract, dict) else {},
            "attribute_standard": "llm_probe attribution stays skipped unless manually enabled; do not invent root causes.",
            "user_prompt_extras": to_dict({
                "capability_ref": request.get("capability_ref") or "",
                "actual_output": actual,
            }),
        }

    def normalize_result(self, trace: RunTrace, judge_result: JudgeResult, result: AttributeResult) -> AttributeResult:
        return normalize_attribute_result(result) or result
