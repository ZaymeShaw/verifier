from __future__ import annotations

from typing import Any, Optional

from .schema import AttributeResult, CheckReport, ClusterSummary, FrontendViewModel, JudgeResult, ProjectSpec, RunTrace, to_dict


def _reference_scalar(reference: Any) -> Any:
    if isinstance(reference, dict):
        for value in reference.values():
            if isinstance(value, (str, int, float, bool)) and str(value):
                return value
        return ""
    return reference


def _first_list_value(data: Any) -> Any:
    if not isinstance(data, dict):
        return None
    for value in data.values():
        if isinstance(value, list):
            return value
    return None


def _first_list_key(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    for key, value in data.items():
        if isinstance(value, list):
            return key
    return None


def _align_reference_shape(reference: Any, actual: Any) -> Any:
    if not isinstance(actual, dict):
        return reference
    if isinstance(reference, dict):
        if "golden_answer" in reference:
            return reference
        if set(actual).intersection(reference):
            return reference
        list_key = _first_list_key(actual)
        list_value = _first_list_value(reference)
        if list_key and list_value is not None:
            shaped = {key: actual.get(key) for key in actual}
            shaped[list_key] = list_value
            for key in shaped:
                if isinstance(shaped.get(key), str) and isinstance(reference.get(key), str):
                    shaped[key] = reference.get(key)
            return shaped
    scalar = _reference_scalar(reference)
    string_keys = [key for key, value in actual.items() if isinstance(value, str)]
    if string_keys:
        return {string_keys[0]: str(scalar)}
    return reference


def _non_empty_reference(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return any(item not in (None, "", [], {}) for item in value.values())
    if isinstance(value, list):
        return bool(value)
    return value != ""


def _trace_reference(trace: Optional[RunTrace]) -> Any:
    if not trace:
        return None
    input_data = trace.input or {}
    if _non_empty_reference(input_data.get("reference")):
        return input_data.get("reference")
    if trace.project_fields and _non_empty_reference(trace.project_fields.get("reference")):
        return trace.project_fields.get("reference")
    request = trace.normalized_request or {}
    if _non_empty_reference(request.get("reference")):
        return request.get("reference")
    return None


def _reference_panel(trace: Optional[RunTrace], judge: Optional[JudgeResult]) -> dict:
    actual = judge.actual if judge else (trace.extracted_output if trace else None)
    output_shape = trace.extracted_output if trace else actual
    provided = _trace_reference(trace)
    generated = judge.expected if judge and provided is None else None
    reference = provided if provided is not None else generated
    if reference is not None:
        reference = _align_reference_shape(reference, output_shape)
    return {
        "reference": reference,
        "source": "input" if provided is not None else ("judge_generated" if generated is not None else "missing"),
        "actual": actual,
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
    return FrontendViewModel(
        project_info={"project_id": spec.project_id, "name": spec.name, "description": spec.description},
        run_trace_summary=to_dict(trace) if trace else {},
        raw_sections={"raw_response": trace.raw_response if trace else None},
        reference_panel=to_dict(_reference_panel(trace, judge)),
        judge_panel=to_dict(judge) if judge else {},
        attribute_panel=to_dict(attribute) if attribute else {},
        cluster_panel=to_dict(cluster) if cluster else {},
        check_panel=to_dict(check) if check else {},
        project_extensions=project_extensions or {},
    )
