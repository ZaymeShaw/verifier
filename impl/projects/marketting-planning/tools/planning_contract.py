from __future__ import annotations

from impl.tools import ToolContext, ToolResult


class MarketingPlanningContractTool:
    tool_id = "marketting-planning.planning_contract"
    tool_type = "project_contract"

    def run(self, context: ToolContext) -> ToolResult:
        trace = context.trace
        project_fields = trace.project_fields if trace else {}
        output = trace.extracted_output if trace else {}
        outputs = {
            "expected_stage": project_fields.get("expected_stage") if isinstance(project_fields, dict) else None,
            "actual_stage": output.get("stage") if isinstance(output, dict) else None,
            "expected_path_types": project_fields.get("expected_path_types") if isinstance(project_fields, dict) else [],
            "actual_path_types": [card.get("path_type") for card in output.get("card_summary") or [] if isinstance(card, dict) and card.get("path_type")] if isinstance(output, dict) else [],
            "sse_completed": bool((output.get("event_summary") or {}).get("completed")) if isinstance(output, dict) else False,
            "scope": "multi_turn_sse_marketing_planning",
        }
        missing = []
        if not outputs["actual_stage"]:
            missing.append({"field": "extracted_output.stage", "reason": "planning stage output is required"})
        if outputs["expected_stage"] and outputs["actual_stage"] != outputs["expected_stage"]:
            missing.append({
                "field": "extracted_output.stage",
                "reason": "actual stage must match the project reference stage",
                "expected": outputs["expected_stage"],
                "actual": outputs["actual_stage"],
            })
        missing_paths = [path for path in (outputs["expected_path_types"] or []) if path not in (outputs["actual_path_types"] or [])]
        if missing_paths:
            missing.append({
                "field": "extracted_output.card_summary.path_type",
                "reason": "required planning path types are missing",
                "expected": outputs["expected_path_types"],
                "actual": outputs["actual_path_types"],
            })
        return ToolResult(
            tool_id=self.tool_id,
            tool_type=self.tool_type,
            status="succeeded" if not missing else "failed",
            outputs=outputs,
            evidence=[{"planning_contract": outputs}] if not missing else [],
            missing_evidence=missing,
            boundary_limits=[{"scope": outputs["scope"], "checks": ["stage_routing", "path_types", "sse_completion"]}],
        )
