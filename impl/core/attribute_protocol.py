from __future__ import annotations

from impl.core.runtime_query_tools import extract_runtime_values
from impl.core.schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace, normalize_attribute_result, trace_execution_trace, trace_extracted_output

from .attribute import attribute_failure as core_attribute_failure


def run_project_attribute_protocol(
    spec: ProjectSpec,
    adapter,
    trace: RunTrace,
    judge_result: JudgeResult,
    project_attribute_context: dict | None = None,
) -> AttributeResult:
    """Run the shared attribute protocol with project-owned context/hooks.

    spec/info-volume.md：项目层 attribute.py 负责决定项目上下文、tool/probe/normalize；
    core 只提供最小 AttributeResult 协议和 Agno/tool bridge。这个 helper 避免各项目
    attribute.py 复制同一段 protocol wiring，同时不把项目策略放回 core.attribute。
    """
    base_context = adapter.build_attribute_context(trace, judge_result)
    extra_context = dict(project_attribute_context or {})
    project_attribute_context = dict(base_context or {})
    project_attribute_context.update(extra_context)
    actual = judge_result.actual or trace_extracted_output(trace) or {}
    expected = judge_result.expected or trace.reference_contract or {}
    runtime_context = {
        "expected": expected,
        "actual": actual,
        "reference": trace.reference_contract or {},
        "trace_id": trace.trace_id,
        "project_id": trace.project_id,
    }
    runtime_values = extract_runtime_values(trace_execution_trace(trace), actual)
    project_attribute_context["runtime_checks"] = adapter.get_runtime_checks(runtime_values, runtime_context)
    result = core_attribute_failure(spec, trace, judge_result, project_attribute_context=project_attribute_context)
    result = adapter.apply_attribution_probes(trace, judge_result, result)
    return normalize_attribute_result(adapter.normalize_attribute_result(trace, judge_result, result)) or result
