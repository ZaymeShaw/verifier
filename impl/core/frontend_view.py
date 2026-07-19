from __future__ import annotations

from typing import Any, Dict, Optional

from .schema import AttributeResult, CheckReport, ClusterSummary, FrontendViewModel, JudgeResult, ProjectSpec, RunTrace, _non_empty_reference, to_dict, trace_extracted_output, trace_normalized_request, trace_raw_response
from .table_view import build_trace_table_row
from .summary import summary_from_fulfillment
from .show_schema import build_show_projection


def _trace_reference(trace: Optional[RunTrace]) -> Any:
    if not trace:
        return None
    if _non_empty_reference(trace.reference_contract):
        return trace.reference_contract
    input_data = trace.input or {}
    if _non_empty_reference(input_data.get("reference")):
        return input_data.get("reference")
    request = trace_normalized_request(trace)
    if _non_empty_reference(request.get("reference")):
        return request.get("reference")
    return None


def _reference_panel(trace: Optional[RunTrace], judge: Optional[JudgeResult]) -> dict:
    actual = judge.actual if judge else trace_extracted_output(trace)
    provided = _trace_reference(trace)
    generated = judge.expected if judge and provided is None else None
    reference = provided if provided is not None else generated
    return {
        "reference": reference,
        "source": "input" if provided is not None else ("judge_generated" if generated is not None else "missing"),
        "actual": actual,
    }


def _frontend_standard(spec: ProjectSpec) -> dict:
    standard = spec.frontend_extensions.get("implementation_standard") if spec.frontend_extensions else None
    if not isinstance(standard, dict):
        return {}
    result = {}
    for key in ("frontend_view", "batch_persistence"):
        value = standard.get(key)
        if value:
            result[key] = value
    return result


def _display_contract(reference_panel: dict, trace: Optional[RunTrace]) -> dict:
    output_source = "trace.extracted_output" if trace and trace_extracted_output(trace) else "judge.actual"
    return {
        "output_source": output_source,
        "reference_source": reference_panel.get("source") or "missing",
        "formatting": ["json formatting", "truncation", "output/reference alignment"],
    }


def _item_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _fulfillment_panel(judge: Optional[JudgeResult]) -> dict:
    if not judge:
        return {}
    expectations = list(judge.business_expectations or [])
    assessments = list(judge.fulfillment_assessments or [])
    assessments_by_id = {_item_value(item, "expectation_id", ""): item for item in assessments}
    matrix = []
    for expectation in expectations:
        expectation_id = _item_value(expectation, "expectation_id", "")
        assessment = assessments_by_id.get(expectation_id, {})
        matrix.append(
            {
                "expectation_id": expectation_id,
                "downstream_consumer": _item_value(expectation, "downstream_consumer", ""),
                "expected_outcome": _item_value(expectation, "expected_outcome", ""),
                "required_capabilities": list(_item_value(expectation, "required_capabilities", []) or []),
                "status": _item_value(assessment, "status", "not_evaluable"),
                "score": _item_value(assessment, "score"),
                "blocking": bool(_item_value(expectation, "blocking", False)),
                "downstream_impact": _item_value(assessment, "downstream_impact", ""),
            }
        )
    return {
        "overall_fulfillment": to_dict(judge.overall_fulfillment or {}),
        "matrix": to_dict(matrix),
    }


def _judge_panel(judge: Optional[JudgeResult]) -> dict:
    if not judge:
        return {}
    panel = to_dict(judge)
    gaps = {"wrong": list(judge.wrong or []), "missing": list(judge.missing or []), "extra": list(judge.extra or [])}
    assessments_by_id = {
        _item_value(item, "expectation_id", ""): item
        for item in judge.fulfillment_assessments or []
    }
    blocking = [
        assessments_by_id.get(_item_value(expectation, "expectation_id", ""), {})
        for expectation in judge.business_expectations or []
        if _item_value(expectation, "blocking", False)
        and _item_value(assessments_by_id.get(_item_value(expectation, "expectation_id", ""), {}), "status", "") != "fulfilled"
    ]
    summary = summary_from_fulfillment(to_dict(judge))
    panel.update(
        {
            "display_status": (judge.overall_fulfillment or {}).get("status") if isinstance(judge.overall_fulfillment, dict) else "",
            "display_reason": summary["reason"],
            "wrong_missing_extra": to_dict(gaps),
            "blocked_expectations": to_dict(blocking),
        }
    )
    return panel


def _attribute_panel(attribute: Optional[AttributeResult]) -> dict:
    if not attribute:
        return {}
    panel = to_dict(attribute)
    panel.update(
        {
            "display_root_cause": attribute.root_cause_hypothesis,
            "attribution_count": len(attribute.expectation_attributions or []),
        }
    )
    return panel


def _expectation_attribution_panel(attribute: Optional[AttributeResult]) -> dict:
    if not attribute:
        return {}
    attributions = list(attribute.expectation_attributions or [])
    return {
        "attributions": to_dict(attributions),
    }


def _verifiable_tool_panel(spec: ProjectSpec) -> dict:
    try:
        from .project_loader import load_project_tools
        catalog = []
        for vt in load_project_tools(spec).verifiable_tools():
            catalog.append({
                "tool_id": vt.tool_id,
                "description": vt.description,
                "applicable_scenario": vt.applicable_scenario,
                "parameters": vt.parameters or {},
                "has_execute_fn": vt.execute_fn is not None,
            })
        return {"available": bool(catalog), "catalog": catalog}
    except Exception as exc:
        return {"available": False, "catalog": [], "reason": f"failed to load verifiable tools: {exc}"}


def project_frontend_extensions(spec: ProjectSpec, trace: RunTrace) -> Dict[str, Any]:
    configured = dict(spec.frontend_extensions or {})
    configured.pop("implementation_standard", None)
    return {
        "schema_protocol_extensions": trace.project_fields,
        **configured,
    }


def build_frontend_view(
    spec: ProjectSpec,
    trace: Optional[RunTrace] = None,
    judge: Optional[JudgeResult] = None,
    attribute: Optional[AttributeResult] = None,
    cluster: Optional[ClusterSummary] = None,
    check: Optional[CheckReport] = None,
    project_extensions: Optional[dict] = None,
) -> FrontendViewModel:
    reference_panel = _reference_panel(trace, judge)
    extensions = dict(project_extensions or {})
    standard = _frontend_standard(spec)
    if standard:
        extensions["frontend_standard"] = standard
    extensions["display_contract"] = _display_contract(reference_panel, trace)
    extensions["verifiable_tools"] = _verifiable_tool_panel(spec)
    if trace:
        try:
            extensions["trace_show"] = build_show_projection(trace)
        except Exception as exc:
            extensions["trace_show"] = {"available": False, "reason": str(exc)}
    table_row = build_trace_table_row(trace, judge, attribute, None, check) if trace else None
    return FrontendViewModel(
        project_info={"project_id": spec.project_id, "name": spec.name, "description": spec.description},
        run_trace_summary=to_dict(trace) if trace else {},
        raw_sections={"raw_response": trace_raw_response(trace) if trace else None},
        reference_panel=to_dict(reference_panel),
        judge_panel=_judge_panel(judge),
        attribute_panel=_attribute_panel(attribute),
        fulfillment_panel=_fulfillment_panel(judge),
        expectation_attribution_panel=_expectation_attribution_panel(attribute),
        cluster_panel=to_dict(cluster) if cluster else {},
        check_panel=to_dict(check) if check else {},
        table_row=table_row,
        project_extensions=extensions,
        tool_call_log=[],
    )
