from __future__ import annotations

from impl.tools import ToolContext, ToolResult


class MarketingPlanningIntentContractTool:
    tool_id = "marketting-planning-intent.intent_contract"
    tool_type = "project_contract"

    def run(self, context: ToolContext) -> ToolResult:
        trace = context.trace
        project_fields = trace.project_fields if trace else {}
        output = trace.extracted_output if trace else {}
        reference = project_fields.get("reference") if isinstance(project_fields, dict) else {}
        outputs = {
            "expected_intent": project_fields.get("expected_intent") if isinstance(project_fields, dict) else None,
            "actual_intent": output.get("intent") if isinstance(output, dict) else None,
            "actual_confidence": output.get("confidence") if isinstance(output, dict) else None,
            "reference_keys": sorted(reference.keys()) if isinstance(reference, dict) else [],
            "scope": "single_turn_intent_recognition",
        }
        missing = []
        if not outputs["actual_intent"]:
            missing.append({"field": "extracted_output.intent", "reason": "intent recognition output is required"})
        if outputs["expected_intent"] and outputs["actual_intent"] != outputs["expected_intent"]:
            missing.append({
                "field": "extracted_output.intent",
                "reason": "actual intent must match the project reference intent",
                "expected": outputs["expected_intent"],
                "actual": outputs["actual_intent"],
            })
        return ToolResult(
            tool_id=self.tool_id,
            tool_type=self.tool_type,
            status="succeeded" if not missing else "failed",
            outputs=outputs,
            evidence=[{"intent_contract": outputs}] if not missing else [],
            missing_evidence=missing,
            boundary_limits=[{"scope": outputs["scope"], "excludes": ["multi_turn_planning", "sse_card_generation"]}],
        )
