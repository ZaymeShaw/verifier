from __future__ import annotations

from impl.tools import ToolContext, ToolResult


class QACaseContractTool:
    tool_id = "QA.case_contract"
    tool_type = "project_contract"

    def run(self, context: ToolContext) -> ToolResult:
        trace = context.trace
        request = trace.normalized_request if trace else {}
        sample_input = request.get("input") if isinstance(request, dict) and isinstance(request.get("input"), dict) else {}
        reference = request.get("reference") if isinstance(request, dict) and isinstance(request.get("reference"), dict) else {}
        outputs = {
            "question_present": bool(sample_input.get("question")),
            "context_count": len(sample_input.get("contexts") or []),
            "reference_keys": sorted(reference.keys()),
            "scope": "qa_semantic_answer_evaluation",
        }
        missing = []
        if not outputs["question_present"]:
            missing.append({"field": "input.question", "reason": "QA case needs a current question"})
        return ToolResult(
            tool_id=self.tool_id,
            tool_type=self.tool_type,
            status="succeeded" if not missing else "failed",
            outputs=outputs,
            evidence=[{"qa_case_contract": outputs}] if not missing else [],
            missing_evidence=missing,
            boundary_limits=[{"scope": outputs["scope"], "external_service_required": False}],
        )
