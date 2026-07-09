"""spec/info-volume.md：通用层 adapter 基类。

通用层只保留：
- live 投递协议（build_request / call_or_prepare / extract_output）
- ready gate（has_provided_output）
- 默认 execution_trace / to_run_trace / build_frontend_extensions
- ToolOrchestrator/VerifiableTool 默认实现（返回空）

项目层职责：
- 在 impl/projects/<project>/adapter.py 中 override 需要 project-specific 行为的方法
- 提供 build_attribute_context / build_judge_context / get_verifiable_tools / get_runtime_checks
- 项目特有的 judge/attribute 后处理（normalize_judge_result / normalize_attribute_result）
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional

from .schema import AttributeResult, EvidenceRef, ExecutionTraceEvent, JudgeResult, LiveExecutionResult, LiveRequest, MultiTurnCase, ProbeResult, ProjectSpec, RunTrace, SingleTurnCase, TraceExecutionContext, judge_expected_actual_gaps, trace_execution_trace, trace_extracted_output, trace_input, trace_normalized_request, trace_project_fields
from .interaction_protocol import resolve_ready, ready_from_spec
from impl.tools import ToolRegistry


def _assessment_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _derive_overall_fulfillment(assessments: list[Any]) -> Dict[str, Any]:
    statuses = [str(_assessment_value(item, "status") or "").strip().lower() for item in assessments]
    from .judge import _derive_overall_status
    return {
        "status": _derive_overall_status(statuses),
        "assessment_count": len(assessments),
        "blocking_expectations": [
            _assessment_value(item, "expectation_id")
            for item in assessments
            if _assessment_value(item, "status") != "fulfilled" and _assessment_value(item, "blocking", False)
        ],
    }


class ProjectAdapter(ABC):
    def __init__(self, spec: ProjectSpec):
        self.spec = spec

    @abstractmethod
    def build_request(self, case: SingleTurnCase | MultiTurnCase) -> LiveRequest:
        raise NotImplementedError

    def call_or_prepare(self, request: LiveRequest) -> LiveExecutionResult:
        from .http_client import call_project_api
        start = time.time()
        try:
            raw_response = call_project_api(self.spec, request.normalized_request)
            call_status = "succeeded"
            call_error = None
        except Exception as exc:
            raw_response = None
            call_status = "failed"
            call_error = str(exc)
        extracted_output = self.extract_output(raw_response) if call_status == "succeeded" else {}
        return LiveExecutionResult(
            project_id=self.spec.project_id,
            case_id=request.case_id,
            session_id=request.session_id,
            raw_input=request.raw_input,
            normalized_request=request.normalized_request,
            call_status=call_status,
            raw_response=raw_response,
            call_error=call_error,
            runtime_ms=int((time.time() - start) * 1000),
            extracted_output=extracted_output,
            output_source=request.execution_mode,
            execution_trace=self.build_execution_trace(request.raw_input, request.normalized_request, raw_response, extracted_output),
            project_fields=self.project_fields(raw_response, extracted_output),
            application_boundary=self.application_boundary(raw_response, extracted_output),
        )

    def has_provided_output(self, case: SingleTurnCase | MultiTurnCase, request: LiveRequest | None) -> bool:
        return resolve_ready(self.spec, case).output

    def provided_output_raw(self, case: SingleTurnCase | MultiTurnCase, request: LiveRequest | None) -> Any:
        output = getattr(case, "output", None)
        if isinstance(output, dict) and output:
            return output
        input_data = dict(case.input or {})
        for key in ("raw_response", "response", "output"):
            if key in input_data:
                return input_data[key]
        return {}

    def extract_output(self, raw_response: Any) -> Dict[str, Any]:
        raise NotImplementedError("project live extraction must be implemented in impl/projects/<project>/live.py or a legacy adapter")

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def application_boundary(self, raw_response: Any, extracted_output: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def build_frontend_extensions(self, trace: RunTrace) -> Dict[str, Any]:
        return {"schema_protocol_extensions": trace_project_fields(trace)}

    def trace_state_graph(self) -> Dict[str, Any]:
        return {}

    def extend_default_trace_graph(self, collect_executor_id: str, extra_collect_executor_ids: list[str]) -> Dict[str, Any]:
        from copy import deepcopy
        from .state_machine import DEFAULT_TRACE_GRAPH
        graph = deepcopy(DEFAULT_TRACE_GRAPH)
        graph["graph_id"] = f"{self.spec.project_id}_trace_state_machine"
        refs = [{"executor_id": collect_executor_id, "executor_type": "deterministic", "role": "generic_evidence_collector"}]
        refs.extend({"executor_id": executor_id, "executor_type": "adapter_hook", "role": executor_id} for executor_id in extra_collect_executor_ids)
        graph["states"]["collect_evidence"] = {
            **graph["states"].get("collect_evidence", {}),
            "executor_refs": refs,
            "merge_policy": "sequential_accumulation",
        }
        return graph

    def state_executors(self) -> Dict[str, Callable[[TraceExecutionContext], Dict[str, Any]]]:
        return {}

    def collect_state_evidence(self, state_id: str, context: TraceExecutionContext) -> list[EvidenceRef]:
        return []

    def run_state_probe(self, probe_id: str, context: TraceExecutionContext) -> ProbeResult:
        return ProbeResult(probe_id=probe_id, status="skipped", stage="adapter.run_state_probe")

    def normalize_state_result(self, state_id: str, context: TraceExecutionContext, result: Dict[str, Any]) -> Dict[str, Any]:
        return result

    def build_execution_trace(self, input_data: Dict[str, Any], request: Dict[str, Any], raw_response: Any, extracted_output: Dict[str, Any]) -> list[ExecutionTraceEvent]:
        return [
            ExecutionTraceEvent(stage="adapter.build_request", status="ok", evidence="normalized request built"),
            ExecutionTraceEvent(stage="project.call", status="ok", evidence="raw response captured"),
            ExecutionTraceEvent(stage="adapter.extract_output", status="ok", evidence="generic extracted_output built"),
        ]

    def to_run_trace(self, result: LiveExecutionResult) -> RunTrace:
        project_fields = dict(result.project_fields or {})
        raw_input = result.raw_input if isinstance(result.raw_input, dict) else {}
        normalized_request = result.normalized_request if isinstance(result.normalized_request, dict) else {}
        reference_contract = raw_input.get("reference") if isinstance(raw_input.get("reference"), dict) else normalized_request.get("reference") if isinstance(normalized_request.get("reference"), dict) else {}
        scenario = str(raw_input.get("scenario") or normalized_request.get("scenario") or "")
        multi_turn_state = getattr(result, "multi_turn_state", None)
        return RunTrace(
            trace_id=result.trace_id if hasattr(result, "trace_id") else f"{result.project_id}:{result.case_id}:{int(time.time()*1000)}",
            project_id=result.project_id,
            case_id=result.case_id,
            input=raw_input,
            normalized_request=normalized_request,
            raw_response=result.raw_response,
            extracted_output=result.extracted_output or {},
            live_result=result,
            execution_mode=result.output_source or "live_service",
            output_source=result.output_source or "live_service",
            scenario=scenario,
            reference_contract=dict(reference_contract or {}),
            application_boundary=dict(result.application_boundary or {}),
            project_fields=project_fields,
            runtime_logs=[],
            evidence_refs=[],
            execution_trace=list(result.execution_trace or []),
            status="ok" if result.call_status == "succeeded" else "error",
            error=result.call_error or "",
            interaction_mode=getattr(result, "interaction_mode", "single_turn") or "single_turn",
            multi_turn_input=None,
            fallbacks=list(getattr(result, "fallbacks", []) or []),
            ready=[],
        )

    # === 以下方法保留为空/默认，项目层在 impl/projects/<project>/adapter.py 中按需 override ===

    def get_runtime_checks(self, runtime_values: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return {}

    def build_attribute_tools(self) -> list:
        return []

    def protocol_tools(self) -> ToolRegistry:
        return ToolRegistry()

    def run_protocol_tools(self, trace: RunTrace, purpose: str, tool_type: str | None = None, inputs: Dict[str, Any] | None = None) -> list:
        return []

    def pre_judge_result(self, trace: RunTrace, expected_intent: Optional[str] = None) -> Optional[JudgeResult]:
        return None

    def build_judge_context(self, trace: RunTrace) -> Dict[str, Any]:
        return {}

    def build_intent_frame(self, trace: RunTrace) -> Dict[str, Any]:
        request_candidates = []
        for source_name, source_value in (("normalized_request", trace_normalized_request(trace)), ("input", trace_input(trace))):
            if isinstance(source_value, dict):
                for key in ("query", "user_intent", "question", "input"):
                    value = source_value.get(key)
                    if value:
                        request_candidates.append({"source": f"{source_name}.{key}", "value": value})
            elif source_value:
                request_candidates.append({"source": source_name, "value": source_value})
        context = self.build_judge_context(trace)
        live_boundary = trace.live_result.application_boundary if trace.live_result else {}
        return {
            "project_id": self.spec.project_id,
            "downstream_consumer": context.get("project_type") or self.spec.project_id,
            "request_candidates": request_candidates,
            "boundary_hints": context.get("application_boundary") or live_boundary or {},
            "output_semantics": "current trace output should let the user or downstream system continue the project task",
        }

    def get_verifiable_tools(self) -> list:
        return []

    def build_attribute_context(self, trace: RunTrace, judge_result: JudgeResult) -> Dict[str, Any]:
        return {}

    def attribution_probes(self, trace: RunTrace, judge_result: JudgeResult) -> list[Dict[str, Any]]:
        return []

    def apply_attribution_probes(self, trace: RunTrace, judge_result: JudgeResult, attribute_result: AttributeResult) -> AttributeResult:
        return attribute_result

    def normalize_attribute_result(self, trace: RunTrace, judge_result: JudgeResult, attribute_result: AttributeResult) -> AttributeResult:
        return attribute_result

    def normalize_judge_result(self, trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
        return judge_result

    def reconcile_judge_result(self, trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
        return judge_result

    def build_mock_cases(self) -> list[Dict[str, Any]]:
        return []

    def build_mock_datasets(self) -> list[Dict[str, Any]]:
        return []


def ensure_jsonable(value: Any) -> Any:
    import json
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return str(value)