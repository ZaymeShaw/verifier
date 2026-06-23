from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from impl.core.adapter import ProjectAdapter
from impl.core.schema import AttributeResult, JudgeResult


# Stage→ext_repo path-prefix map. Adapters use this to narrow the source-file
# catalog by current trace failure signals instead of exposing the whole repo.
STAGE_FILE_PREFIXES: Dict[str, tuple] = {
    "request_normalization": ("app/api/", "app/schemas/request", "app/main.py"),
    "intent_recognition": (
        "app/workflow/steps/intent_recognition",
        "app/workflow/prompts/intent_",
        "app/schemas/intent",
        "app/config.py",
    ),
    "field_clarification": (
        "app/workflow/steps/field_clarification",
        "app/workflow/prompts/clarification",
        "app/services/session_store",
        "app/schemas/session",
    ),
    "session_merge": (
        "app/services/session_store",
        "app/workflow/steps/field_clarification",
        "app/schemas/session",
    ),
    "path_dispatch": (
        "app/workflow/steps/path_planning",
        "app/workflow/path_types",
        "app/workflow/nbev_workflow",
    ),
    "planning_function": (
        "app/services/planning/",
        "app/analysis_func/",
        "app/workflow/steps/path_planning",
    ),
    "result_assembly": (
        "app/workflow/steps/result_assembly",
        "app/services/card_formatter",
        "app/services/next_step_recommendation",
        "app/schemas/events",
    ),
    "sse_generation": (
        "app/api/",
        "app/schemas/events",
        "app/schemas/response",
        "app/workflow/nbev_workflow",
    ),
    "adapter_extraction": (),  # adapter.py itself is added separately by source_retrieval
}

ATTRIBUTE_CATALOG_FILE_CAP = 8


class Adapter(ProjectAdapter):
    stages = {"intent", "clarification", "planning", "non_agent", "fallback", "unknown"}

    def build_request(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        nested_input = input_data.get("input") if isinstance(input_data.get("input"), dict) else {}
        turns = self._normalize_turns(input_data.get("turns") or nested_input.get("turns"))
        query = input_data.get("query") or input_data.get("user_query") or input_data.get("user_intent") or nested_input.get("query") or nested_input.get("user_query") or ""
        if not turns and query:
            turns = [{"role": "user", "content": str(query)}]
        case_id = str(input_data.get("case_id") or input_data.get("id") or f"marketing-case-{int(time.time() * 1000)}")
        shared_session = bool(input_data.get("shared_session") or nested_input.get("shared_session"))
        declared_session = input_data.get("session_id") or nested_input.get("session_id")
        session_id = str(declared_session) if shared_session and declared_session else f"eval-{case_id}"
        scenario = str(input_data.get("scenario") or nested_input.get("scenario") or self._infer_scenario(input_data, turns))
        boundary = self._normalize_boundary(input_data.get("boundary") or nested_input.get("boundary") or {})
        reference = self._normalize_reference(input_data.get("reference") or nested_input.get("reference") or {}, input_data, scenario)
        first_user_turn = next((turn.get("content") for turn in turns if turn.get("role") == "user" and turn.get("content")), "")
        return {
            "case_id": case_id,
            "session_id": session_id,
            "shared_session": shared_session,
            "user_intent": str(input_data.get("user_intent") or nested_input.get("user_intent") or query or first_user_turn or scenario),
            "query": str(query or (turns[-1].get("content") if turns else "")),
            "turns": turns,
            "current_turn": turns[-1] if turns else {},
            "scenario": scenario,
            "expected_stage": input_data.get("expected_stage") or nested_input.get("expected_stage") or reference.get("expected_stage"),
            "expected_path_types": self._list(input_data.get("expected_path_types") or nested_input.get("expected_path_types") or reference.get("required_path_types")),
            "expected_cards": self._list(input_data.get("expected_cards") or nested_input.get("expected_cards") or reference.get("required_cards")),
            "metadata": dict(input_data.get("metadata") or nested_input.get("metadata") or {}),
            "boundary": boundary,
            "reference": reference,
        }

    def call_or_prepare(self, request: Dict[str, Any]) -> Any:
        body = json.dumps(self._live_request_body(request), ensure_ascii=False).encode("utf-8")
        url = str(self.spec.api.get("base_url") or "").rstrip("/") + "/" + str(self.spec.api.get("endpoint") or "").lstrip("/")
        api_request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method=str(self.spec.api.get("method") or "POST").upper())
        try:
            with urllib.request.urlopen(api_request, timeout=float(self.spec.api.get("timeout") or 120)) as response:
                return self._attach_request(response.read().decode("utf-8"), request)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"marketing-planning service unavailable: {exc}") from exc

    def _live_request_body(self, request: Dict[str, Any]) -> Dict[str, Any]:
        query = str(request.get("query") or request.get("user_intent") or "")
        contexts = []
        for turn in request.get("turns") or []:
            content = str(turn.get("content") or turn.get("query") or "")
            role = str(turn.get("role") or "user")
            if not content or content == query:
                continue
            contexts.append({"role": role, "query": content if role == "user" else "", "answer": content if role != "user" else ""})
        session_id = str(request.get("session_id") or "")
        return {
            "session_id": session_id,
            "trace_id": str(request.get("case_id") or session_id or f"trace-{int(time.time() * 1000)}"),
            "org_id": str((request.get("metadata") or {}).get("org_id") or "eval-org"),
            "user_text": query,
            "extra_input_params": {
                "agent_args": {"conversation_id": session_id, "message": {"content": query, "content_type": "text"}},
                "args": {"extensions": {}, "contexts": contexts},
            },
        }

    def provided_output_raw(self, input_data: Dict[str, Any], request: Dict[str, Any]) -> Any:
        for key in ("raw_response", "response", "output"):
            if key in input_data:
                return self._attach_request(input_data[key], request)
        return self._attach_request({}, request)

    def extract_output(self, raw_response: Any) -> Dict[str, Any]:
        data = self._raw_payload(raw_response)
        events = self._extract_events(data)
        cards = self._extract_cards(data)
        stage = self._extract_stage(data, events, cards)
        fallback = self._extract_fallback(data, cards, raw_response)
        return {
            "stage": stage,
            "event_summary": self._event_summary(events),
            "card_summary": cards,
            "session_summary": self._session_summary(data, raw_response),
            "fallback": fallback,
            "errors": self._extract_errors(data, events),
        }

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any]) -> Dict[str, Any]:
        request = self._request_from_raw(raw_response)
        boundary = self._application_boundary(request, extracted_output)
        return {
            "scenario": request.get("scenario") or "",
            "case_id": request.get("case_id") or "",
            "session_id": request.get("session_id") or "",
            "shared_session": bool(request.get("shared_session")),
            "reference": dict(request.get("reference") or {}),
            "expected_stage": request.get("expected_stage"),
            "expected_path_types": self._list(request.get("expected_path_types")),
            "expected_cards": self._list(request.get("expected_cards")),
            "application_boundary": boundary,
            "compact_summary_only": True,
        }

    def build_execution_trace(self, input_data: Dict[str, Any], request: Dict[str, Any], raw_response: Any, extracted_output: Dict[str, Any]) -> list[Dict[str, Any]]:
        expected_stage = request.get("expected_stage") or (request.get("reference") or {}).get("expected_stage")
        path_types = self._list(request.get("expected_path_types"))
        actual_path_types = [card.get("path_type") for card in extracted_output.get("card_summary") or [] if card.get("path_type")]
        fallback = extracted_output.get("fallback") or {}
        return [
            {"stage": "request_normalization", "status": "ok" if request.get("turns") else "suspicious", "evidence": {"turn_count": len(request.get("turns") or []), "session_id": request.get("session_id")}},
            {"stage": "intent_recognition", "status": "ok" if extracted_output.get("stage") in self.stages else "suspicious", "evidence": {"actual_stage": extracted_output.get("stage"), "expected_stage": expected_stage}},
            {"stage": "field_clarification", "status": "ok" if extracted_output.get("stage") != "clarification" or expected_stage == "clarification" else "suspicious", "evidence": extracted_output.get("session_summary")},
            {"stage": "session_merge", "status": "ok" if request.get("session_id") else "suspicious", "evidence": {"shared_session": request.get("shared_session"), "session_id": request.get("session_id")}},
            {"stage": "path_dispatch", "status": "ok" if not path_types or set(path_types).issubset(set(actual_path_types)) else "failed", "evidence": {"expected_path_types": path_types, "actual_path_types": actual_path_types}},
            {"stage": "planning_function", "status": "ok" if extracted_output.get("stage") != "planning" or actual_path_types else "suspicious", "evidence": {"card_count": len(extracted_output.get("card_summary") or [])}},
            {"stage": "result_assembly", "status": "ok", "evidence": {"summary_keys": list(extracted_output.keys())}},
            {"stage": "sse_generation", "status": "ok" if (extracted_output.get("event_summary") or {}).get("completed") else "not_verified", "evidence": extracted_output.get("event_summary")},
            {"stage": "adapter_extraction", "status": "ok", "evidence": {"compact_summary_only": True, "fallback_used": fallback.get("used")}},
        ]

    def build_judge_context(self, trace) -> Dict[str, Any]:
        return {
            "project_type": "multi_turn_sse_marketing_planning",
            "current_case_only": True,
            "reference_contract": trace.project_fields.get("reference") or {},
            "output_summary": trace.extracted_output,
            "application_boundary": trace.project_fields.get("application_boundary") or {},
            "expected_stage": trace.project_fields.get("expected_stage"),
            "expected_path_types": trace.project_fields.get("expected_path_types") or [],
            "expected_cards": trace.project_fields.get("expected_cards") or [],
            "stage_rules": {
                "clarification": "缺字段时澄清是正确方向，规划卡片通常是可疑证据。",
                "planning": "规划场景必须检查 path_types、card identity、fallback 和 SSE completion。",
                "fallback": "fallback 是否正确取决于当前 boundary 是否允许。",
            },
        }

    def build_intent_frame(self, trace) -> Dict[str, Any]:
        context = self.build_judge_context(trace)
        return {
            **super().build_intent_frame(trace),
            "business_task_type": "multi_turn_marketing_planning",
            "downstream_consumer": "marketing planning user",
            "critical_intent_dimensions": ["business_metric", "target_value_and_unit", "time_range", "decomposition_dimensions", "stage_routing", "planning_actionability", "sse_completion"],
            "boundary_rules": context.get("application_boundary") or {},
            "expected_stage": context.get("expected_stage"),
            "expected_path_types": context.get("expected_path_types") or [],
            "expected_cards": context.get("expected_cards") or [],
            "output_semantics": "route the current marketing demand to the proper stage and produce actionable planning cards/events within the project boundary",
        }

    def normalize_judge_result(self, trace, judge_result):
        output = trace.extracted_output or {}
        expected = trace.project_fields.get("reference") or {}
        expected_stage = trace.project_fields.get("expected_stage") or expected.get("expected_stage")
        actual_stage = output.get("stage")
        required_paths = self._list(trace.project_fields.get("expected_path_types") or expected.get("required_path_types"))
        actual_paths = [card.get("path_type") for card in output.get("card_summary") or [] if card.get("path_type")]
        forbidden_paths = self._list(expected.get("forbidden_path_types"))
        required_events = self._list(expected.get("required_events"))
        actual_events = ((output.get("event_summary") or {}).get("canonical_names") or (output.get("event_summary") or {}).get("names") or [])
        fallback = output.get("fallback") or {}
        allow_fallback = bool(expected.get("allow_fallback") or (trace.project_fields.get("application_boundary") or {}).get("allow_fallback"))
        failures = []
        self._append_expected_quality_failures(trace, output, expected, failures)
        if expected_stage and actual_stage and expected_stage != actual_stage:
            failures.append({"requirement": "expected_stage", "expected_fragment": expected_stage, "actual_fragment": actual_stage, "status": "wrong", "evidence": ["adapter extracted stage mismatch"]})
        missing_events = [event for event in required_events if event not in actual_events]
        if missing_events:
            failures.append({"requirement": "required_events", "expected_fragment": required_events, "actual_fragment": actual_events, "status": "missing", "evidence": ["required SSE event absent from event_summary"]})
        missing_paths = [path for path in required_paths if path not in actual_paths]
        extra_forbidden = [path for path in actual_paths if path in forbidden_paths]
        if missing_paths:
            failures.append({"requirement": "required_path_types", "expected_fragment": required_paths, "actual_fragment": actual_paths, "status": "missing", "evidence": ["required path type absent from card_summary"]})
        if extra_forbidden:
            failures.append({"requirement": "forbidden_path_types", "expected_fragment": forbidden_paths, "actual_fragment": actual_paths, "status": "extra", "evidence": ["forbidden path type present in card_summary"]})
        if fallback.get("used") and not allow_fallback:
            failures.append({"requirement": "allow_fallback", "expected_fragment": False, "actual_fragment": fallback, "status": "wrong", "evidence": ["fallback used but reference/boundary does not allow it"]})
        if not failures:
            return judge_result
        judge_result.actual = output
        judge_result.expected = expected or judge_result.expected
        for failure in failures:
            requirement = failure.get("requirement") or "contract"
            evidence_text = "; ".join(failure.get("evidence") or []) or failure.get("status") or "mismatch"
            downstream_impact = self._failure_downstream_impact(requirement, failure)
            judge_result.fulfillment_assessments.append({
                "expectation_id": f"mp_contract:{requirement}",
                "status": "not_fulfilled",
                "blocking": True,
                "evidence": evidence_text,
                "downstream_impact": downstream_impact,
            })
        judge_result.verdict_derivation = {**(judge_result.verdict_derivation or {}), "project_deterministic_evidence": failures, "why_verdict": "marketing-planning adapter found stage/path/fallback contract mismatch."}
        judge_result.boundary_decision = {**(judge_result.boundary_decision or {}), "application_boundary": trace.project_fields.get("application_boundary") or {}}
        if "marketing_planning_contract_mismatch" not in judge_result.quality_flags:
            judge_result.quality_flags.append("marketing_planning_contract_mismatch")
        return judge_result

    def _failure_downstream_impact(self, requirement, failure):
        impacts = {
            "expected_stage": "stage 路由错误，下游无法进入预期 planning 流程",
            "required_events": "SSE 关键事件缺失，前端无法完整渲染结果",
            "required_path_types": "规划卡片类型缺失，用户拿不到预期 planning action",
            "forbidden_path_types": "出现禁用 path，超出 application boundary",
            "allow_fallback": "fallback 在不允许的边界内触发，违反 boundary 契约",
            "target_value_wan": "目标值单位/数值错误，规划结果不可执行",
        }
        return impacts.get(requirement, f"{requirement} 契约不满足")

    def _append_expected_quality_failures(self, trace, output, expected, failures):
        metadata = (trace.normalized_request or {}).get("metadata") or {}
        if (trace.input or {}).get("source") != "data_mock_seed" or (trace.input or {}).get("expected_quality") != "incorrect":
            return
        error_type = str(metadata.get("expected_error_type") or "")
        if error_type != "target_value_unit_error":
            return
        expected_target = expected.get("target_value_wan")
        actual_target = self._find_target_nbev_wan(output)
        if expected_target is None or actual_target is None or int(actual_target) == int(expected_target):
            return
        failures.append({"requirement": "target_value_wan", "expected_fragment": expected_target, "actual_fragment": actual_target, "status": "wrong", "error_type": error_type, "evidence": ["seeded mock reference target_value_wan differs from output targetNbev"]})

    def _default_consumer_contract(self, trace, judge_result):
        context = self.build_judge_context(trace)
        return {
            "consumer": "marketing planning user",
            "contract": "multi-turn planning output must route to the expected stage, respect clarification/fallback boundaries, generate required path cards, and complete SSE delivery",
            "reference_contract": context.get("reference_contract") or {},
            "application_boundary": context.get("application_boundary") or {},
        }

    def _default_business_expectation(self, trace, judge_result):
        expectation = super()._default_business_expectation(trace, judge_result)
        expectation.update(
            {
                "expectation_id": "marketting-planning:planning_output_contract",
                "downstream_consumer": "marketing planning user",
                "required_capabilities": expectation.get("required_capabilities") or ["stage_routing", "field_clarification", "path_card_generation", "fallback_boundary", "sse_completion"],
                "boundary": judge_result.boundary_decision or self.build_judge_context(trace).get("application_boundary") or expectation.get("boundary") or {},
            }
        )
        if not judge_result.intent_model:
            expectation.update(
                {
                    "user_intent": str((trace.normalized_request or {}).get("user_intent") or (trace.normalized_request or {}).get("query") or trace.input or ""),
                    "expected_outcome": "planning flow should produce the expected stage, path cards, fallback behavior, and completed SSE-visible result for the current demand",
                    "acceptance_criteria": list(judge_result.condition_assessments or judge_result.missing or judge_result.wrong or []),
                }
            )
        return expectation

    def _default_fulfillment_assessment(self, trace, judge_result, expectation):
        status = self._expectation_status_from_verdict(judge_result)
        return {
            "expectation_id": expectation.get("expectation_id"),
            "status": status,
            "score": judge_result.score,
            "expected_evidence": list(judge_result.missing or []) or [judge_result.expected or (trace.project_fields or {}).get("reference") or {}],
            "actual_evidence": list(judge_result.wrong or []) or list(judge_result.extra or []) or [judge_result.actual or trace.extracted_output],
            "boundary_decision": judge_result.boundary_decision or self.build_judge_context(trace).get("application_boundary") or {},
            "downstream_impact": "planning user can proceed with the generated plan" if status == "fulfilled" else (judge_result.reasoning_summary or "planning user cannot rely on the current planning output to complete the business task"),
            "blocking": status in {"not_fulfilled", "not_evaluable"},
            "confidence": judge_result.confidence,
            "evidence_refs": list(getattr(trace, "evidence_refs", []) or []),
        }

    @staticmethod
    def _prioritized_ext_repo_files(ext_path: Path, limit: int = 100) -> List[Path]:
        """Order ext_repo .py files so attribution-critical paths surface in catalog.

        Priority: workflow/steps > workflow/prompts > workflow > services > configs >
        schemas > others. Skips __init__.py and __pycache__. Caps at `limit` to keep
        catalog metadata bounded; current ext_repos have <100 real files."""
        priority_prefixes = (
            "app/workflow/steps/",
            "app/workflow/prompts/",
            "app/workflow/",
            "app/services/",
            "app/configs/",
            "app/schemas/",
            "app/api/",
            "app/analysis_func/",
            "app/fallback/",
            "app/utils/",
            "app/",
        )

        def rank(p: Path) -> tuple:
            rel = str(p.relative_to(ext_path))
            for i, prefix in enumerate(priority_prefixes):
                if rel.startswith(prefix):
                    return (i, rel)
            return (len(priority_prefixes), rel)

        candidates = [
            p for p in ext_path.rglob("*.py")
            if p.name != "__init__.py" and "__pycache__" not in p.parts
        ]
        return sorted(candidates, key=rank)[:limit]

    @staticmethod
    def _trace_failure_stages(trace) -> List[str]:
        """Stages from execution_trace with status failed/suspicious, in order of appearance."""
        exec_trace = getattr(trace, "execution_trace", None) or []
        stages: List[str] = []
        for node in exec_trace:
            if not isinstance(node, dict):
                continue
            stage = node.get("stage") or node.get("node") or node.get("name")
            status = node.get("status")
            if stage and status in {"failed", "suspicious"} and stage not in stages:
                stages.append(stage)
        return stages

    def _select_ext_repo_files_by_stage(self, ext_path: Path, trace) -> List[Path]:
        """Narrow ext_repo catalog by trace failure signals; fallback to priority ranking."""
        implicated = self._trace_failure_stages(trace)
        if not implicated:
            chain = getattr(trace, "execution_trace", None) or []
            if chain and isinstance(chain[-1], dict):
                last_stage = chain[-1].get("stage") or chain[-1].get("node")
                if last_stage:
                    implicated = [last_stage]
        if not implicated:
            implicated = ["intent_recognition"]  # earliest stage fallback

        prefix_union: List[str] = []
        for stage in implicated:
            for prefix in STAGE_FILE_PREFIXES.get(stage, ()):
                if prefix not in prefix_union:
                    prefix_union.append(prefix)

        if not prefix_union:
            # No prefixes mapped: keep top-3 from priority list to retain some catalog
            return self._prioritized_ext_repo_files(ext_path, limit=3)

        candidates = [
            p for p in ext_path.rglob("*.py")
            if p.name != "__init__.py" and "__pycache__" not in p.parts
        ]

        def matches_prefix(rel: str) -> Optional[int]:
            for i, prefix in enumerate(prefix_union):
                if rel.startswith(prefix):
                    return i
            return None

        scored: List[tuple] = []
        for p in candidates:
            rel = str(p.relative_to(ext_path))
            idx = matches_prefix(rel)
            if idx is None:
                continue
            scored.append((idx, rel, p))

        scored.sort(key=lambda x: (x[0], x[1]))
        return [p for _, _, p in scored[:ATTRIBUTE_CATALOG_FILE_CAP]]

    def build_attribute_context(self, trace, judge_result) -> Dict[str, Any]:
        source_config_paths = {}
        ext_repo = self.spec.application.get("external_repo") if isinstance(self.spec.application, dict) else None
        if ext_repo:
            ext_path = Path(ext_repo)
            if ext_path.exists():
                for py_file in self._select_ext_repo_files_by_stage(ext_path, trace):
                    try:
                        source_config_paths[f"ext_repo:{py_file.relative_to(ext_path)}"] = str(py_file)
                    except Exception:
                        pass
        for doc_key, doc_rel in (self.spec.documents or {}).items():
            if doc_key.startswith("source_"):
                p = Path(self.spec.root) / str(doc_rel)
                if p.exists():
                    source_config_paths[f"project_doc:{doc_key}"] = str(p)
        return {
            "application_boundary": trace.project_fields.get("application_boundary") or {},
            "chain_nodes_to_check": list(trace.execution_trace or []),
            "earliest_stage_order": ["request_normalization", "intent_recognition", "field_clarification", "session_merge", "path_dispatch", "planning_function", "result_assembly", "sse_generation", "adapter_extraction"],
            "reference_contract": trace.project_fields.get("reference") or {},
            "output_summary": trace.extracted_output,
            "source_config_paths": source_config_paths,
            "attribute_standard": "Only attribute failures grounded in current RunTrace/JudgeResult/project docs; no historical-case field carryover. Use source_code_evidence to locate exact code/config responsible for the error.",
        }

    def trace_state_graph(self) -> Dict[str, Any]:
        graph = self.extend_default_trace_graph("collect_evidence", ["marketing_planning_boundary_evidence"])
        graph["limits"] = {**(graph.get("limits") or {}), "max_steps": 28, "max_retries_per_state": 1}
        return graph

    def state_executors(self) -> Dict[str, Any]:
        return {"marketing_planning_boundary_evidence": self._marketing_planning_boundary_evidence}

    def _marketing_planning_boundary_evidence(self, context: Dict[str, Any]) -> Dict[str, Any]:
        trace = context.get("trace")
        if not trace:
            return {"status": "failed", "missing_evidence": ["trace"]}
        fields = trace.project_fields or {}
        evidence = {
            "scenario": fields.get("scenario"),
            "session_id": fields.get("session_id"),
            "shared_session": fields.get("shared_session"),
            "application_boundary": fields.get("application_boundary") or {},
            "expected_stage": fields.get("expected_stage"),
            "expected_path_types": fields.get("expected_path_types") or [],
            "external_repo_mutation": "not_performed_by_adapter",
        }
        return {
            "status": "succeeded",
            "outputs": evidence,
            "evidence_refs": [{"type": "marketing_planning_boundary", "evidence": evidence}],
            "claims": [{"marketing_planning_boundary": evidence}],
        }

    def collect_state_evidence(self, state_id: str, context: Dict[str, Any]) -> list[Dict[str, Any]]:
        trace = context.get("trace")
        if not trace:
            return []
        fields = trace.project_fields or {}
        return [{"type": "marketing_planning_state_boundary", "state_id": state_id, "application_boundary": fields.get("application_boundary") or {}, "scenario": fields.get("scenario"), "shared_service_boundary": "local configured service only"}]

    def attribution_probes(self, trace, judge_result):
        target_probe = self._target_value_unit_probe(trace, judge_result)
        return [target_probe] if target_probe else []

    def normalize_attribute_result(self, trace, judge_result, attribute_result):
        if judge_result.verdict == "correct":
            if not attribute_result.expectation_attributions:
                expectation_id = "marketting-planning:planning_output_contract"
                if judge_result.business_expectations:
                    first = judge_result.business_expectations[0]
                    expectation_id = first.get("expectation_id", expectation_id) if isinstance(first, dict) else getattr(first, "expectation_id", expectation_id)
                evidence = list(judge_result.evidence or ["planning output contract fulfilled"])
                attribute_result.expectation_attributions = [{"expectation_id": expectation_id, "fulfillment_status": "fulfilled", "causal_category": "no_issue", "earliest_divergence": {"node": "planning_output_contract", "evidence": evidence, "confidence": "high"}, "causal_chain": [{"name": "planning_output_contract", "status": "succeeded", "evidence": evidence}], "local_verifications": [], "suspected_locations": [], "improvement_direction": [], "source_evidence": [], "probe_evidence": evidence, "incomplete_reason": ""}]
            attribute_result.causal_category = "no_issue"
            attribute_result.probe_results = attribute_result.probe_results or [{"probe": "planning_output_contract", "status": "passed", "evidence": list(judge_result.evidence or ["planning output contract fulfilled"])}]
            attribute_result.failure_category = "fulfilled_expectation"
            attribute_result.failure_stage = "fulfilled_expectation"
            attribute_result.analysis_method = attribute_result.analysis_method or "fulfilled_expectation_attribution"
            attribute_result.incomplete_reason = ""
            attribute_result.suspected_locations = []
            attribute_result.root_cause_hypothesis = "当前 planning 输出满足业务预期，归因结论为 no_issue。"
            attribute_result.analysis_quality = {"passed": True, "status": "fulfilled_expectation", "missing": []}
            return attribute_result
        target_probe = self._target_value_unit_probe(trace, judge_result)
        if target_probe:
            attribute_result.failure_category = "target_value_unit_error"
            attribute_result.failure_stage = "request_normalization"
            attribute_result.analysis_method = "marketing_planning_target_value_local_probe"
            attribute_result.local_verifications = list(attribute_result.local_verifications or []) + [target_probe]
            attribute_result.evidence_chain = list(attribute_result.evidence_chain or []) + list(target_probe.get("evidence") or [])
            attribute_result.chain_nodes = list(trace.execution_trace or [])
            attribute_result.trace_analysis = list(trace.execution_trace or [])
            attribute_result.earliest_divergence = {
                "node": "request_normalization",
                "expected": {"target_nbev_wan": target_probe.get("expected_target_nbev_wan")},
                "actual": {"target_nbev_wan": target_probe.get("actual_target_nbev_wan")},
                "evidence": target_probe.get("evidence") or [],
                "confidence": "high",
            }
            attribute_result.evidence_coverage = {"query": True, "actual": True, "expected": True, "execution_trace": bool(trace.execution_trace), "local_probe": True, "unsupported_claims": []}
            attribute_result.analysis_quality = {"passed": True, "status": "supported_root_cause", "missing": [], "standard": "target value unit attribution must be grounded in current query and current output value."}
            attribute_result.incomplete_reason = ""
            attribute_result.root_cause_hypothesis = f"当前 query 含目标值 {target_probe.get('source_amount')}，按项目内部单位应为 {target_probe.get('expected_target_nbev_wan')} 万，实际链路使用 {target_probe.get('actual_target_nbev_wan')} 万，最早差异位于请求归一化/目标值单位转换。"
            attribute_result.verification_steps = ["复核当前 query 中的金额单位与 extracted_output/card_data 中 targetNbev 的单位转换。"]
            attribute_result.patch_direction = ["修正 marketing-planning 服务请求归一化或目标值单位转换逻辑，确保“亿”转换为内部单位“万”时乘以 10000。"]
            return attribute_result
        if not attribute_result.earliest_divergence:
            failed = next((node for node in trace.execution_trace if node.get("status") in {"failed", "suspicious"}), None)
            if failed:
                attribute_result.earliest_divergence = {"node": failed.get("stage"), "evidence": [failed.get("evidence")], "confidence": "medium"}
                attribute_result.failure_stage = str(failed.get("stage") or attribute_result.failure_stage)
        return attribute_result

    def _target_value_unit_probe(self, trace, judge_result) -> Dict[str, Any]:
        evidence_text = self._target_value_error_evidence(judge_result)
        if not evidence_text:
            return {}
        trace_input = trace.input or {}
        nested_input = trace_input.get("input") if isinstance(trace_input.get("input"), dict) else {}
        query = str(trace_input.get("query") or trace_input.get("user_intent") or nested_input.get("query") or nested_input.get("user_intent") or "")
        amount_match = re.search(r"(\d+(?:\.\d+)?)\s*亿", query)
        if not amount_match:
            return {}
        expected = int(float(amount_match.group(1)) * 10000)
        actual = self._find_target_nbev_wan(judge_result.actual)
        if actual is None:
            actual = self._find_target_nbev_wan(judge_result.condition_assessments)
        if actual is None:
            actual = self._find_target_nbev_wan(judge_result.wrong)
        if actual is None:
            actual = self._find_target_nbev_wan(trace.extracted_output)
        if actual is None or actual == expected:
            return {}
        return {
            "method": "target_value_unit_probe",
            "source_amount": amount_match.group(0),
            "expected_target_nbev_wan": expected,
            "actual_target_nbev_wan": actual,
            "result": "mismatch reproduced",
            "evidence": [f"query contains {amount_match.group(0)}", f"expected {expected} 万", f"actual {actual} 万", evidence_text],
        }

    def _target_value_error_evidence(self, judge_result) -> str:
        if "target_value_unit_error" in (judge_result.quality_flags or []):
            return "quality_flags contains target_value_unit_error"
        candidates = [judge_result.expected, judge_result.wrong, judge_result.condition_assessments, judge_result.actual, judge_result.primary_assessment]
        evidence_text = json.dumps(candidates, ensure_ascii=False)
        has_target = any(token in evidence_text for token in ("targetNbev", "target_value", "target_value_wan", "目标值", "NBEV"))
        has_wrong_status = '"status": "wrong"' in evidence_text or "数值错误" in evidence_text or "误差" in evidence_text
        if has_target and (has_wrong_status or "target_value_wan" in evidence_text):
            return evidence_text[:500]
        return ""

    def _find_target_nbev_wan(self, value: Any) -> Any:
        if isinstance(value, dict):
            if "actual_fragment" in value:
                found = self._find_target_nbev_wan(value.get("actual_fragment"))
                if found is not None:
                    return found
            for key in ("target_nbev_wan", "target_value_wan", "targetNbev", "forecast_value"):
                if key in value and isinstance(value.get(key), (int, float)):
                    return int(value[key])
            for key, item in value.items():
                if key == "expected_fragment":
                    continue
                found = self._find_target_nbev_wan(item)
                if found is not None:
                    return found
        if isinstance(value, list):
            for item in value:
                found = self._find_target_nbev_wan(item)
                if found is not None:
                    return found
        return None

    def build_frontend_extensions(self, trace):
        return {
            "project_fields": trace.project_fields,
            "scenarios": self.spec.frontend_extensions.get("scenarios") or [],
            "stages": self.spec.frontend_extensions.get("stages") or [],
            "path_types": self.spec.frontend_extensions.get("path_types") or [],
            "output_summary_shape": ["stage", "event_summary", "card_summary", "session_summary", "fallback", "errors"],
        }

    def build_mock_cases(self) -> list[Dict[str, Any]]:
        path = Path(__file__).resolve().parents[2] / "data" / "marketting-planning" / "mock_cases.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def build_interactive_turn(self, case: Dict[str, Any], previous_turns: List[Dict[str, Any]]) -> Dict[str, Any]:
        user_intent = case.get("user_intent") if isinstance(case.get("user_intent"), dict) else {}
        goal = str(user_intent.get("goal") or case.get("query") or case.get("user_intent") or "")
        if not previous_turns:
            return {"query": goal, "turn_index": 1}
        missing_fields = []
        for turn in previous_turns:
            missing_fields.extend(self._list(turn.get("missing_fields")))
        if "target_value" in missing_fields:
            return {"query": str(user_intent.get("target_value") or ""), "turn_index": len(previous_turns) + 1}
        if "path_types" in missing_fields:
            return {"query": "、".join(str(item) for item in self._list(user_intent.get("path_type_intent"))), "turn_index": len(previous_turns) + 1}
        return {"query": goal, "turn_index": len(previous_turns) + 1}

    def run_interactive(self, case) -> Dict[str, Any]:
        source_case = dict(case.source_case or {})
        interaction = dict(case.interaction or {})
        policy = dict(case.policy or {})
        max_turns = max(1, int(policy.get("max_turns") or 4))
        turn_expectations = interaction.get("turn_expectations") or []
        turn_outputs = source_case.get("turn_outputs") if isinstance(source_case.get("turn_outputs"), list) else []
        transcript: List[Dict[str, Any]] = []
        turn_traces: List[Dict[str, Any]] = []
        stop_reason = "max_turns"

        for _ in range(max_turns):
            next_turn = self.build_interactive_turn(source_case, turn_traces)
            transcript.append({"role": "user", "content": str(next_turn.get("query") or "")})
            request_input = {
                "case_id": case.case_id,
                "query": next_turn.get("query"),
                "turns": transcript,
                "scenario": source_case.get("scenario") or "interactive_intent",
                "reference": source_case.get("reference") or {},
            }
            request = self.build_request(request_input)
            raw = self._attach_request(turn_outputs[len(turn_traces)], request) if len(turn_traces) < len(turn_outputs) else self.call_or_prepare(request)
            extracted = self.extract_output(raw)
            turn_trace = self._interactive_turn_trace(len(turn_traces) + 1, next_turn, extracted, turn_expectations)
            turn_traces.append(turn_trace)
            if extracted.get("stage") == "planning" and not (extracted.get("session_summary") or {}).get("missing_fields"):
                stop_reason = "intent_resolved"
                break

        final_stage = turn_traces[-1].get("stage") if turn_traces else "unknown"
        final_verdict = self._interactive_final_verdict(turn_traces, stop_reason)
        quality_flags = [] if final_verdict == "correct" else (["turn_expectation_failed"] if any(turn.get("judge_verdict") == "incorrect" for turn in turn_traces) else ["interactive_intent_incomplete"])
        conversation_summary = {
            "turn_count": len(turn_traces),
            "final_stage": final_stage,
            "stop_reason": stop_reason,
        }
        trace = {
            "trace_id": f"interactive-{case.case_id}",
            "project_id": self.spec.project_id,
            "input": source_case,
            "normalized_request": {"case_id": case.case_id, "interaction_mode": "interactive_intent", "max_turns": max_turns},
            "status": "ok" if final_verdict == "correct" else "error",
            "project_fields": {
                "interaction_mode": "interactive_intent",
                "output_source": "interactive_adapter",
                "conversation_summary": conversation_summary,
                "turn_traces": turn_traces,
            },
            "execution_trace": [
                {"stage": "interactive_turn", "status": turn.get("judge_verdict"), "evidence": {"turn_index": turn.get("turn_index"), "stage": turn.get("stage"), "missing_fields": turn.get("missing_fields")}}
                for turn in turn_traces
            ],
        }
        judge = {
            "trace_id": trace["trace_id"],
            "project_id": self.spec.project_id,
            "verdict": final_verdict,
            "score": 1 if final_verdict == "correct" else (0 if final_verdict == "incorrect" else 0.5),
            "confidence": 1,
            "judge_method": "marketing_planning_interactive_adapter",
            "verdict_derivation": {"why_verdict": f"interactive conversation stopped by {stop_reason}", "turn_traces": turn_traces},
            "reasoning_summary": f"interactive_intent final_stage={final_stage}, stop_reason={stop_reason}",
            "quality_flags": quality_flags,
        }
        attribute = {
            "trace_id": trace["trace_id"],
            "project_id": self.spec.project_id,
            "case_id": case.case_id,
            "failure_category": "none" if final_verdict == "correct" else "多轮交互不符合预期",
            "failure_stage": "none" if final_verdict == "correct" else "interactive_turn",
            "analysis_method": "marketing_planning_interactive_adapter",
            "chain_nodes": trace["execution_trace"],
            "earliest_divergence": {} if final_verdict == "correct" else next(({"node": "interactive_turn", "evidence": [turn], "confidence": "high"} for turn in turn_traces if turn.get("judge_verdict") != "correct"), {}),
            "analysis_quality": {"passed": final_verdict == "correct", "standard": "interactive expectations are checked per current case turn evidence"},
            "root_cause_hypothesis": "" if final_verdict == "correct" else "系统回复未满足当前 interactive_intent 的 turn_expectations 或未在 max_turns 内完成。",
            "quality_flags": quality_flags,
        }
        return {"case_id": case.case_id, "execution_mode": "interactive_intent", "output_source": "interactive_adapter", "trace": trace, "judge": judge, "attribute": attribute}

    def _interactive_turn_trace(self, turn_index: int, user_input: Dict[str, Any], output: Dict[str, Any], expectations: List[Dict[str, Any]]) -> Dict[str, Any]:
        expectation = next((item for item in expectations if int(item.get("turn") or 0) == turn_index), {})
        stage = output.get("stage") or "unknown"
        missing_fields = self._list((output.get("session_summary") or {}).get("missing_fields"))
        path_evidence = [card.get("path_type") for card in output.get("card_summary") or [] if card.get("path_type")]
        failures = []
        if expectation.get("stage") and expectation.get("stage") != stage:
            failures.append("stage")
        expected_missing = self._list(expectation.get("missing_fields"))
        if expected_missing and not missing_fields:
            failures.append("missing_fields_absent")
        for path_type in self._list(expectation.get("required_path_types")):
            if path_type not in path_evidence:
                failures.append(f"path_type:{path_type}")
        return {
            "turn_index": turn_index,
            "user_input": {"query": str(user_input.get("query") or "")},
            "stage": stage,
            "missing_fields": missing_fields,
            "path_evidence": path_evidence,
            "card_evidence": [{"path_type": card.get("path_type"), "card_code": card.get("card_code"), "card_name": card.get("card_name")} for card in output.get("card_summary") or []],
            "judge_verdict": "incorrect" if failures else "correct",
            "error_summary": failures,
        }

    def _interactive_final_verdict(self, turn_traces: List[Dict[str, Any]], stop_reason: str) -> str:
        if any(turn.get("judge_verdict") == "incorrect" for turn in turn_traces):
            return "incorrect"
        if stop_reason != "intent_resolved":
            return "uncertain"
        return "correct"

    def _interactive_intent_case(self) -> Dict[str, Any]:
        user_intent = {
            "goal": "规划NBEV增长路径",
            "target_value": "120亿",
            "path_type_intent": ["premium_growth", "customer_operation"],
        }
        return {
            "id": "mp-interactive-intent-1",
            "input": {"user_intent": user_intent, "scenario": "interactive_intent"},
            "user_intent": user_intent,
            "interaction": {
                "mode": "interactive_intent",
                "policy": {"max_turns": 4, "stop_when": ["intent_resolved"]},
                "turn_expectations": [
                    {"turn": 1, "stage": "clarification", "missing_fields": ["target_value", "path_types"]},
                    {"turn": 2, "stage": "clarification", "missing_fields": ["path_types"]},
                    {"turn": 3, "stage": "planning", "required_path_types": ["premium_growth", "customer_operation"]},
                ],
            },
            "mock_agent": {"driver": "adapter", "facts": user_intent},
            "reference": {"expected_stage": "planning", "required_path_types": ["premium_growth"]},
            "scenario": "interactive_intent",
            "source": "mock_agent_seed",
            "status": "pending",
        }

    def build_mock_datasets(self) -> list[Dict[str, Any]]:
        cases = self.build_mock_cases()
        return [{"dataset_id": "marketing_planning_v1_seed", "name": "营销规划 v1 场景样例", "dimension_type": "marketing_planning_scenario", "description": "覆盖意图、澄清、多轮、规划、fallback、非本 agent 意图和 SSE 协议。", "case_count": len(cases), "cases": cases}]

    def _case(self, case_id, scenario, query, stage, events, path_types, turns=None, required_fields=None, allow_fallback=False, boundary=None):
        boundary = boundary or {"allow_fallback": allow_fallback}
        reference = {"expected_stage": stage, "required_events": events, "required_path_types": path_types, "allow_fallback": allow_fallback, "session_requirements": {"required_fields": required_fields or []}}
        cards = self._mock_cards(path_types, {"scenario": scenario})
        output = {"events": self._mock_events(stage, cards), "cards": cards, "session": {"session_id": f"eval-{case_id}", "required_fields": required_fields or [], "missing_fields": required_fields or []}, "stage": stage, "fallback": {"used": stage == "fallback", "allowed": allow_fallback, "reason": "dependency unavailable" if stage == "fallback" else ""}}
        return {"id": case_id, "input": {"user_intent": query, "query": query, "turns": turns or [{"role": "user", "content": query}], "scenario": scenario, "expected_stage": stage, "expected_path_types": path_types, "boundary": boundary, "reference": reference}, "output": output, "reference": reference, "scenario": scenario, "source": "mock_agent_seed", "status": "pending"}

    def _normalize_turns(self, turns: Any) -> List[Dict[str, Any]]:
        if not isinstance(turns, list):
            return []
        normalized = []
        for item in turns:
            if isinstance(item, dict):
                normalized.append({"role": str(item.get("role") or "user"), "content": str(item.get("content") or item.get("query") or item.get("text") or ""), **({"output": item.get("output")} if "output" in item else {})})
            else:
                normalized.append({"role": "user", "content": str(item)})
        return normalized

    def _normalize_boundary(self, boundary: Any) -> Dict[str, Any]:
        data = dict(boundary or {}) if isinstance(boundary, dict) else {}
        return {"dependency_status": data.get("dependency_status") or data.get("external_dependency") or "available", "allow_fallback": bool(data.get("allow_fallback") or data.get("fallback_allowed")), "excluded_evidence": self._list(data.get("excluded_evidence")), "notes": str(data.get("notes") or "")}

    def _normalize_reference(self, reference: Any, input_data: Dict[str, Any], scenario: str) -> Dict[str, Any]:
        ref = dict(reference or {}) if isinstance(reference, dict) else {}
        if input_data.get("expected_stage") and "expected_stage" not in ref:
            ref["expected_stage"] = input_data.get("expected_stage")
        if input_data.get("expected_path_types") and "required_path_types" not in ref:
            ref["required_path_types"] = self._list(input_data.get("expected_path_types"))
        if input_data.get("expected_cards") and "required_cards" not in ref:
            ref["required_cards"] = self._list(input_data.get("expected_cards"))
        if "allow_fallback" not in ref and isinstance(input_data.get("boundary"), dict):
            ref["allow_fallback"] = bool(input_data["boundary"].get("allow_fallback"))
        if scenario and "scenario" not in ref:
            ref["scenario"] = scenario
        return ref

    def _infer_scenario(self, input_data: Dict[str, Any], turns: List[Dict[str, Any]]) -> str:
        text = " ".join([str(input_data.get("query") or input_data.get("user_intent") or "")] + [str(turn.get("content") or "") for turn in turns])
        if any(word in text for word in ["缺", "补充", "澄清"]):
            return "clarification"
        if any(word in text for word in ["诗", "天气", "闲聊"]):
            return "non_agent_intent"
        if any(word in text for word in ["不可用", "兜底", "fallback"]):
            return "fallback_data_unavailable"
        if len(turns) > 1:
            return "multi_turn_field_accumulation"
        return "execution_planning"

    def _stage_for_scenario(self, scenario: str) -> str:
        return {"clarification": "clarification", "fallback_data_unavailable": "fallback", "non_agent_intent": "non_agent", "intent_recognition": "intent"}.get(scenario, "planning")

    def _attach_request(self, raw: Any, request: Dict[str, Any]) -> Any:
        if isinstance(raw, dict):
            return {**raw, "_normalized_request": request}
        return {"raw": raw, "_normalized_request": request}

    def _request_from_raw(self, raw: Any) -> Dict[str, Any]:
        return dict(raw.get("_normalized_request") or {}) if isinstance(raw, dict) else {}

    def _raw_payload(self, raw: Any) -> Any:
        if isinstance(raw, dict) and "raw" in raw:
            return raw.get("raw")
        return raw

    def _list(self, value: Any) -> List[Any]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return value
        return [value]

    def _extract_events(self, data: Any) -> List[Dict[str, Any]]:
        if isinstance(data, str):
            events = []
            for line in data.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("event:"):
                    events.append({"event": line.split(":", 1)[1].strip()})
                elif line.startswith("data:"):
                    payload = line.split(":", 1)[1].strip()
                    try:
                        parsed = json.loads(payload)
                    except json.JSONDecodeError:
                        parsed = {"text": payload}
                    if events and "data" not in events[-1]:
                        events[-1]["data"] = parsed
                    else:
                        events.append({"event": parsed.get("event") if isinstance(parsed, dict) else "data", "data": parsed})
            return events
        if isinstance(data, dict):
            events = data.get("events") or data.get("event_stream") or data.get("sse_events") or []
            if isinstance(events, list):
                return [event if isinstance(event, dict) else {"event": str(event)} for event in events]
        return []

    def _extract_cards(self, data: Any) -> List[Dict[str, Any]]:
        cards = []
        if isinstance(data, dict):
            raw_cards = data.get("cards") or data.get("card_summary") or data.get("planning_cards") or []
            if not raw_cards and isinstance(data.get("data"), dict):
                raw_cards = data["data"].get("cards") or []
            for card in self._list(raw_cards):
                if isinstance(card, dict):
                    cards.append(self._card_summary(card))
        for event in self._extract_events(data):
            payload = event.get("data") if isinstance(event, dict) else None
            if isinstance(payload, dict) and isinstance(payload.get("card"), dict):
                cards.append(self._card_summary(payload["card"]))
            card_result = self._card_result(payload)
            if card_result:
                for card in self._list(card_result.get("card_list")):
                    if isinstance(card, dict):
                        cards.append(self._card_summary(card))
        unique = []
        seen = set()
        for card in cards:
            marker = (card.get("path_type"), card.get("card_code"), card.get("card_name"), json.dumps(card.get("forecast_value"), ensure_ascii=False, sort_keys=True), json.dumps(card.get("achievement_rate"), ensure_ascii=False, sort_keys=True))
            if marker in seen:
                continue
            seen.add(marker)
            unique.append(card)
        return unique

    _CARD_CODE_PATH_TYPE_MAP: Dict[str, str] = {
        "TEAM_PROFILE_ANALYSIS": "premium_growth",
        "TEAM_REACH_MEASUREMENT": "premium_growth",
        "CUSTOMER_PROFILE_ANALYSIS": "customer_growth",
        "CUSTOMER_REACH_MEASUREMEN": "customer_growth",
        "PRODUCT_PROFILE_ANALYSIS": "product_mix",
        "PRODUCT_REACH_MEASUREMENT": "product_mix",
    }

    def _card_summary(self, card: Dict[str, Any]) -> Dict[str, Any]:
        explicit = card.get("path_type") or card.get("type")
        if not explicit:
            card_code = str(card.get("card_code") or card.get("code") or "")
            explicit = self._CARD_CODE_PATH_TYPE_MAP.get(card_code)
        if not explicit:
            desc = str(card.get("card_desc") or "")
            if "队伍" in desc or "premium" in desc.lower():
                explicit = "premium_growth"
            elif "客户" in desc or "customer" in desc.lower():
                explicit = "customer_growth"
            elif "产品" in desc or "product" in desc.lower():
                explicit = "product_mix"
        return {"path_type": str(explicit or "unknown"), "card_code": str(card.get("card_code") or card.get("code") or ""), "card_name": str(card.get("card_name") or card.get("name") or ""), "fallback": bool(card.get("fallback")), "forecast_value": card.get("forecast_value"), "achievement_rate": card.get("achievement_rate")}

    def _card_result(self, payload: Any) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        extra = data.get("extra_output_params") if isinstance(data.get("extra_output_params"), dict) else payload.get("extra_output_params")
        if isinstance(extra, dict) and isinstance(extra.get("card_result"), dict):
            return extra["card_result"]
        if isinstance(payload.get("card_result"), dict):
            return payload["card_result"]
        return {}

    def _extract_stage(self, data: Any, events: List[Dict[str, Any]], cards: List[Dict[str, Any]]) -> str:
        if isinstance(data, dict) and data.get("stage") in self.stages:
            return str(data.get("stage"))
        names = [str(event.get("event") or event.get("name") or "") for event in events]
        joined = " ".join(names).lower()
        card_codes = {str(card.get("card_code") or "") for card in cards}
        intent_values = set()
        for event in events:
            payload = event.get("data") if isinstance(event, dict) else None
            if isinstance(payload, dict):
                inner_data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
                extras = inner_data.get("extra_output_params") if isinstance(inner_data.get("extra_output_params"), dict) else {}
                intent_val = str(inner_data.get("intent") or extras.get("intent") or "")
                if intent_val:
                    intent_values.add(intent_val)
        if card_codes & {"ASK_TARGET_VALUE", "ACHIEVE_PATH_TYPE_QUESTION"}:
            return "clarification"
        if "clarification" in joined or "clarify" in joined:
            return "clarification"
        if "non_agent" in joined or "reject" in joined or intent_values & {"4001"}:
            return "non_agent"
        if "fallback" in joined or intent_values & {"nbev_planning_fallback"}:
            return "fallback"
        if cards or "planning" in joined or "card" in joined:
            return "planning"
        if "intent" in joined:
            return "intent"
        return "unknown"

    def _event_summary(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        names = [str(event.get("event") or event.get("name") or "data") for event in events]
        canonical_names = self._canonical_event_names(names)
        counts = {name: names.count(name) for name in sorted(set(names))}
        canonical_counts = {name: canonical_names.count(name) for name in sorted(set(canonical_names))}
        final = names[-1] if names else ""
        canonical_final = canonical_names[-1] if canonical_names else ""
        terminal_events = set(self.spec.frontend_extensions.get("terminal_events") or ["done", "complete", "completed", "card_end"])
        completed = final in terminal_events or canonical_final in terminal_events or any(name in terminal_events for name in names) or any(name in terminal_events for name in canonical_names)
        return {"names": canonical_names, "raw_names": names, "canonical_names": canonical_names, "counts": canonical_counts, "raw_counts": counts, "final_event": canonical_final or final, "raw_final_event": final, "completed": completed}

    def _canonical_event_names(self, names: List[str]) -> List[str]:
        aliases = self.spec.frontend_extensions.get("event_aliases") or {}
        alias_to_canonical = {}
        for canonical_name, raw_names in aliases.items():
            for raw_name in self._list(raw_names):
                alias_to_canonical[str(raw_name).lower()] = str(canonical_name)
        canonical = []
        for name in names:
            normalized = str(name or "")
            mapped = alias_to_canonical.get(normalized.lower(), normalized)
            if not canonical or canonical[-1] != mapped:
                canonical.append(mapped)
        return canonical

    def _session_summary(self, data: Any, raw_response: Any = None) -> Dict[str, Any]:
        session = data.get("session") if isinstance(data, dict) and isinstance(data.get("session"), dict) else {}
        request = self._request_from_raw(raw_response if raw_response is not None else data)
        missing_fields = self._list(session.get("missing_fields"))
        if not missing_fields:
            for event in self._extract_events(data):
                card_result = self._card_result(event.get("data") if isinstance(event, dict) else None)
                for card in self._list(card_result.get("card_list")):
                    if isinstance(card, dict) and isinstance(card.get("card_data"), dict) and card["card_data"].get("required"):
                        field_key = card["card_data"].get("fieldKey")
                        if field_key and field_key not in missing_fields:
                            missing_fields.append(field_key)
        return {"session_id": str(session.get("session_id") or request.get("session_id") or ""), "required_fields": self._list(session.get("required_fields") or ((request.get("reference") or {}).get("session_requirements") or {}).get("required_fields")), "accumulated_fields": dict(session.get("accumulated_fields") or {}), "missing_fields": missing_fields}

    def _extract_fallback(self, data: Any, cards: List[Dict[str, Any]], raw_response: Any = None) -> Dict[str, Any]:
        raw = data.get("fallback") if isinstance(data, dict) else None
        request = self._request_from_raw(raw_response if raw_response is not None else data)
        boundary = request.get("boundary") or {}
        if isinstance(raw, dict):
            return {"used": bool(raw.get("used")), "allowed": bool(raw.get("allowed") or boundary.get("allow_fallback")), "reason": str(raw.get("reason") or "")}
        used = any(card.get("fallback") for card in cards)
        return {"used": used, "allowed": bool(boundary.get("allow_fallback")), "reason": "card fallback marker" if used else ""}

    def _extract_errors(self, data: Any, events: List[Dict[str, Any]]) -> List[str]:
        errors = []
        if isinstance(data, dict):
            for key in ("error", "errors", "message"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    errors.append(value[:300])
                elif isinstance(value, list):
                    errors.extend(str(item)[:300] for item in value)
        for event in events:
            name = str(event.get("event") or "").lower()
            if "error" in name:
                errors.append(str(event.get("data") or name)[:300])
        return errors

    def _application_boundary(self, request: Dict[str, Any], output: Dict[str, Any]) -> Dict[str, Any]:
        boundary = self._normalize_boundary(request.get("boundary") or {})
        fallback = output.get("fallback") or {}
        return {"dependency_status": boundary.get("dependency_status"), "allow_fallback": bool(boundary.get("allow_fallback")), "fallback_used": bool(fallback.get("used")), "judge_scope": "system_responsibility_with_declared_external_boundary", "excluded_evidence": boundary.get("excluded_evidence") or []}

    def _mock_cards(self, path_types: List[Any], request: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [{"path_type": str(path), "card_code": f"{str(path).upper()}_CARD", "card_name": f"{path} 达成路径", "fallback": False, "forecast_value": 100, "achievement_rate": 0.8} for path in path_types]

    def _mock_events(self, stage: str, cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if stage == "intent":
            return [{"event": "intent_detected"}, {"event": "done"}]
        if stage == "clarification":
            return [{"event": "intent_detected"}, {"event": "clarification_requested"}, {"event": "done"}]
        if stage == "non_agent":
            return [{"event": "non_agent_rejected"}, {"event": "done"}]
        if stage == "fallback":
            return [{"event": "intent_detected"}, {"event": "fallback"}, {"event": "done"}]
        events = [{"event": "intent_detected"}, {"event": "planning_started"}]
        events.extend({"event": "card_delta", "data": {"card": card}} for card in cards)
        events.append({"event": "done"})
        return events

    def _mock_session(self, request: Dict[str, Any]) -> Dict[str, Any]:
        reference = request.get("reference") or {}
        required = ((reference.get("session_requirements") or {}).get("required_fields")) or []
        return {"session_id": request.get("session_id"), "required_fields": required, "accumulated_fields": {"target": request.get("query")}, "missing_fields": required if request.get("expected_stage") == "clarification" else []}

    def _mock_fallback(self, request: Dict[str, Any]) -> Dict[str, Any]:
        boundary = request.get("boundary") or {}
        used = request.get("expected_stage") == "fallback"
        return {"used": used, "allowed": bool(boundary.get("allow_fallback")), "reason": "mock dependency unavailable" if used else ""}
