from __future__ import annotations

import importlib.util
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from impl.core.adapter import ProjectAdapter
from impl.tools import ToolRegistry
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


def _load_local_tool_class(module_file: str, class_name: str):
    module_path = Path(__file__).resolve().parent / "tools" / module_file
    module_name = f"{__name__}_{module_file.replace('.py', '')}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load project tool: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, class_name)


MarketingPlanningContractTool = _load_local_tool_class("planning_contract.py", "MarketingPlanningContractTool")


class Adapter(ProjectAdapter):
    stages = {"intent", "clarification", "planning", "non_agent", "fallback", "unknown"}

    def protocol_tools(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(MarketingPlanningContractTool())
        return registry

    def _project_contract_tool_results(self, trace, purpose: str) -> list[Dict[str, Any]]:
        return [result.__dict__ for result in self.run_protocol_tools(trace, purpose=purpose, tool_type="project_contract")]

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
            "protocol_tool_results": self._project_contract_tool_results(trace, purpose="judge"),
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

    def pre_judge_result(self, trace, expected_intent=None):
        """Do NOT short-circuit the LLM judge.

        Returning a JudgeResult here skips the core LLM judge call (see
        pipeline.judge), producing a deterministic template reasoning summary
        and 0 LLM judge calls. Returning None lets the LLM judge run and
        produce a detailed per-requirement analysis; the deterministic
        contract checks (stage, required_paths, forbidden_paths, events,
        fallback) are then applied via normalize_judge_result which runs
        inside reconcile_judge_result AFTER the LLM judge.
        """
        return None

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
            if not judge_result.fulfillment_assessments:
                judge_result.fulfillment_assessments = [{
                    "expectation_id": "mp_contract:planning_output_contract",
                    "status": "fulfilled",
                    "blocking": False,
                    "evidence": "planning output contract satisfied by deterministic adapter checks",
                    "downstream_impact": "planning user can proceed with the generated plan",
                }]
            judge_result.verdict = "correct"
            judge_result.score = 1
            return judge_result
        judge_result.actual = output
        judge_result.expected = expected or judge_result.expected
        judge_result.wrong = [failure for failure in failures if failure.get("status") in {"wrong", "extra"}]
        judge_result.missing = [failure for failure in failures if failure.get("status") == "missing"]
        judge_result.fulfillment_assessments = []
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
        judge_result.verdict = "incorrect"
        judge_result.score = 0
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
        if expected_target is None:
            return
        actual_target = self._find_target_nbev_wan(output)
        if actual_target is None:
            failures.append({"requirement": "target_value_wan", "expected_fragment": expected_target, "actual_fragment": "targetNbev missing from planning output", "status": "wrong", "error_type": error_type, "evidence": ["seeded mock expected target_value_unit_error but output did not expose a verifiable targetNbev"]})
            return
        if int(actual_target) == int(expected_target):
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
            "protocol_tool_results": self._project_contract_tool_results(trace, purpose="attribute"),
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
        # judge 判定为 uncertain 时，attr 不应产出确定性 implementation_bug 根因。
        # 此时表明 judge 无法确认输出是否正确，attr 应反映这种不确定性而非强行归类。
        if judge_result.verdict == "uncertain":
            reason = "judge 判定为 uncertain，当前规划输出无法被明确判定为正确或错误，归因不能给出确定性根因。"
            if "self_check_failed" in (judge_result.quality_flags or []):
                reason = "judge self-check 失败，判定为 uncertain，当前规划输出无法被确认满足或不满足契约，归因不能给出确定性根因。"
            attribute_result.causal_category = "insufficient_evidence"
            attribute_result.failure_category = "insufficient_evidence"
            attribute_result.failure_stage = "judge_uncertain"
            attribute_result.analysis_method = "judge_uncertain_blocked_attribute"
            attribute_result.evidence_chain = list(judge_result.evidence or [reason])
            attribute_result.trace_analysis = list(trace.execution_trace or [])
            attribute_result.chain_nodes = list(trace.execution_trace or [])
            attribute_result.earliest_divergence = {}
            attribute_result.evidence_coverage = {"query": bool(trace.input), "actual": bool(judge_result.actual), "expected": bool(judge_result.expected), "execution_trace": bool(trace.execution_trace), "unsupported_claims": []}
            attribute_result.analysis_quality = {"passed": False, "status": "insufficient_evidence", "missing": ["deterministic_judge_verdict"], "standard": "judge uncertain 时不能产出确定性归因，需人工复核或补充 judge 证据。"}
            attribute_result.incomplete_reason = reason
            attribute_result.suspected_locations = []
            attribute_result.root_cause_hypothesis = f"当前 judge 无法确定 planning 输出是否满足契约要求（verdict=uncertain），建议人工复核后重新判定。"
            attribute_result.verification_steps = ["复核 judge 的 self_check 和 overall_fulfillment，确认哪些维度无法评估。", "补充缺失的评估维度证据后重新运行 judge。"]
            attribute_result.patch_direction = ["在 judge 给出确定性 verdict 之前，不应基于不确定的判定修改业务代码。"]
            attribute_result.business_impact = "当前 case 无法进入正式根因聚簇，需人工复核 judge 的 uncertain 结论。"
            attribute_result.needs_human_review = True
            attribute_result.primary_error_type = "needs_human_review"
            attribute_result.error_types = ["needs_human_review"]
            return attribute_result
        if judge_result.verdict == "correct" and not self._target_value_unit_probe(trace, judge_result):
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
        contract_fallback = self._contract_fallback_attribute_result(trace, judge_result, attribute_result)
        if contract_fallback:
            return contract_fallback
        if not attribute_result.earliest_divergence:
            failed = next((node for node in trace.execution_trace if node.get("status") in {"failed", "suspicious"}), None)
            if failed:
                attribute_result.earliest_divergence = {"node": failed.get("stage"), "evidence": [failed.get("evidence")], "confidence": "medium"}
                attribute_result.failure_stage = str(failed.get("stage") or attribute_result.failure_stage)
        return attribute_result

    def _contract_fallback_attribute_result(self, trace, judge_result, attribute_result):
        text = " ".join(str(item) for item in [
            attribute_result.incomplete_reason,
            attribute_result.root_cause_hypothesis,
            attribute_result.business_impact,
            attribute_result.verification_steps,
            attribute_result.patch_direction,
        ] if item)
        stale_markers = ("source_file_catalog", "prompt 文件", "源码/配置证据", "未能获取足够", "无法完成正式归因")
        if not any(marker in text for marker in stale_markers) and not (judge_result.wrong or judge_result.missing):
            return None
        failed = next((node for node in trace.execution_trace or [] if isinstance(node, dict) and node.get("status") in {"failed", "suspicious"}), {})
        failed_requirement = next((item for item in list(judge_result.wrong or []) + list(judge_result.missing or []) if isinstance(item, dict)), {})
        requirement = failed_requirement.get("requirement") or "planning_contract"
        expected = failed_requirement.get("expected_fragment") or judge_result.expected or (trace.project_fields or {}).get("reference") or {}
        actual = failed_requirement.get("actual_fragment") or judge_result.actual or trace.extracted_output or {}
        evidence = [judge_result.reasoning_summary] if judge_result.reasoning_summary else []
        evidence.extend(str(item) for item in judge_result.evidence or [])
        if failed_requirement:
            evidence.append(json.dumps(failed_requirement, ensure_ascii=False))
        if failed:
            evidence.append(json.dumps(failed.get("evidence") or {}, ensure_ascii=False))
        if not evidence:
            return None
        stage = str(failed.get("stage") or self._stage_for_requirement(requirement))
        attribute_result.causal_category = "implementation_bug"
        attribute_result.failure_category = str(requirement)
        attribute_result.failure_stage = stage
        attribute_result.analysis_method = "marketing_planning_contract_evidence_fallback"
        attribute_result.evidence_chain = evidence
        attribute_result.trace_analysis = list(trace.execution_trace or [])
        attribute_result.chain_nodes = list(trace.execution_trace or [])
        attribute_result.local_verifications = list(attribute_result.local_verifications or []) + [{"method": "planning_contract_judge_evidence", "target": requirement, "result": "not_fulfilled", "evidence": evidence}]
        attribute_result.earliest_divergence = {"node": stage, "expected": expected, "actual": actual, "evidence": evidence, "confidence": "high"}
        attribute_result.evidence_coverage = {"query": bool(trace.input), "actual": bool(actual), "expected": bool(expected), "execution_trace": bool(trace.execution_trace), "project_contract": True, "unsupported_claims": []}
        attribute_result.analysis_quality = {"passed": True, "status": "supported_root_cause", "missing": [], "standard": "planning attribution must use current contract/judge evidence instead of stale catalog fallback."}
        attribute_result.incomplete_reason = ""
        attribute_result.root_cause_hypothesis = f"当前 planning 输出未满足 {requirement} 契约：expected={expected}，actual={actual}，最早差异位于 {stage}。"
        attribute_result.verification_steps = ["复核当前 trace.execution_trace、reference_contract 与 extracted_output 中的规划阶段/事件/卡片证据。"]
        attribute_result.patch_direction = ["修正 marketing-planning 服务中产生该规划阶段、SSE 事件或卡片字段的源头逻辑；不要只修改评测展示结果。"]
        return attribute_result

    def _stage_for_requirement(self, requirement: str) -> str:
        mapping = {
            "required_events": "sse_generation",
            "expected_stage": "intent_recognition",
            "required_path_types": "path_dispatch",
            "forbidden_path_types": "path_dispatch",
            "allow_fallback": "result_assembly",
        }
        return mapping.get(str(requirement), "planning_output_contract")

    def _infer_target_nbev_from_query(self, trace) -> Any:
        trace_input = trace.input or {}
        nested_input = trace_input.get("input") if isinstance(trace_input.get("input"), dict) else {}
        query = str(trace_input.get("query") or trace_input.get("user_intent") or nested_input.get("query") or nested_input.get("user_intent") or "")
        amount_match = re.search(r"(\d+(?:\.\d+)?)\s*亿", query)
        if amount_match:
            return int(float(amount_match.group(1)) * 10000)
        amount_match = re.search(r"(\d+(?:\.\d+)?)\s*万", query)
        if amount_match:
            return int(float(amount_match.group(1)))
        return None

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
        evidence_text = self._target_value_error_evidence(judge_result)
        if "targetNbev missing" in evidence_text or "未暴露" in evidence_text:
            return {
                "method": "target_value_unit_probe",
                "source_amount": amount_match.group(0),
                "expected_target_nbev_wan": expected,
                "actual_target_nbev_wan": "missing",
                "result": "mismatch reproduced",
                "evidence": [f"query contains {amount_match.group(0)}", f"expected {expected} 万", "actual targetNbev missing from output", evidence_text],
            }
        actual = self._find_target_nbev_wan(judge_result.actual)
        if actual is None:
            actual = self._find_target_nbev_wan(judge_result.condition_assessments)
        if actual is None:
            actual = self._find_target_nbev_wan(judge_result.wrong)
        if actual is None:
            actual = self._find_target_nbev_wan(trace.extracted_output)
        if actual is None:
            actual = self._infer_target_nbev_from_query(trace)
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

    def get_runtime_checks(self, runtime_values: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """直接引用营销规划业务系统原函数，校验 stage/path_type/fallback 是否符合预期。

        这是 Issue #3 用户诉求（"直接引用业务系统原函数"）的市场规划落地：
        不再让 attribute agent 读源码/prompt 猜测，而是从业务系统仓库直接加载
        `app/workflow/path_types.py` 的 normalize_path_types / extract_target_value_from_text
        以及 `app/configs/config_dev.json` 的 PATH_ORDER / CARD_METADATA / SSE_EVENTS，
        对当前 trace 的 actual_stage / actual_path_types / fallback / target_value
        做运行时校验，直接产出闭合根因。
        """
        context = context or {}
        checks: list[Dict[str, Any]] = []
        source_files: list[str] = []
        path_module = self._load_business_path_types_module()
        config = self._load_business_config()
        expected = context.get("expected") if isinstance(context.get("expected"), dict) else {}
        reference = context.get("reference") if isinstance(context.get("reference"), dict) else {}
        actual = context.get("actual") if isinstance(context.get("actual"), dict) else {}
        actual = actual or self._runtime_actual_from_values(runtime_values)
        wrong = list(context.get("wrong") or [])

        valid_path_types = tuple(path_module.get("VALID_PATH_TYPES", ())) if path_module else ()
        path_aliases = dict(path_module.get("PATH_TYPE_ALIASES", {})) if path_module else {}
        normalize_fn = path_module.get("normalize_path_types") if path_module else None
        extract_target_fn = path_module.get("extract_target_value_from_text") if path_module else None
        path_order = list(config.get("PATH_ORDER", [])) if config else []
        card_metadata = config.get("CARD_METADATA", {}) if config else {}
        sse_events = config.get("SSE_EVENTS", {}) if config else {}
        if valid_path_types:
            source_files.append("app/workflow/path_types.py:VALID_PATH_TYPES/normalize_path_types")
        if path_order:
            source_files.append("app/configs/config_dev.json:PATH_ORDER")
        if card_metadata:
            source_files.append("app/configs/config_dev.json:CARD_METADATA")
        if sse_events:
            source_files.append("app/configs/config_dev.json:SSE_EVENTS")

        # 适配器 path_type 英文名 → 业务系统中文名的映射
        # 基于 _CARD_CODE_PATH_TYPE_MAP 和 adapter 阶段路由约定
        EN_TO_ZH_PATH = {
            "premium_growth": "队伍",
            "customer_growth": "客户",
            "product_mix": "产品",
            "activity": "活动",
            "unknown": "未知",
        }
        ZH_TO_EN_PATH = {v: k for k, v in EN_TO_ZH_PATH.items()}

        # 1) path_type 校验：用业务系统原函数 normalize 后比对 expected/forbidden
        required_paths = self._list(reference.get("required_path_types") or expected.get("required_path_types"))
        forbidden_paths = self._list(reference.get("forbidden_path_types") or expected.get("forbidden_path_types"))
        actual_paths = [card.get("path_type") for card in (actual.get("card_summary") or []) if isinstance(card, dict) and card.get("path_type")]
        # 将 adapter 英文 path_type 映射为业务系统中文名，传给 normalize_path_types
        actual_zh = [EN_TO_ZH_PATH.get(p, p) for p in actual_paths]
        normalized_zh = []
        if normalize_fn and actual_zh:
            res = normalize_fn(actual_zh)
            normalized_zh = list(res) if isinstance(res, list) else []
        else:
            normalized_zh = list(actual_zh)
        # 映射回英文用于 comparision
        normalized_actual = [ZH_TO_EN_PATH.get(p, p) for p in normalized_zh]
        # expected/forbidden 也映射为中文传给 normalize
        required_zh = [EN_TO_ZH_PATH.get(p, p) for p in required_paths]
        normalized_required_zh = []
        if normalize_fn and required_zh:
            nr = normalize_fn(required_zh)
            normalized_required_zh = list(nr) if isinstance(nr, list) else []
        else:
            normalized_required_zh = list(required_zh)
        normalized_required = [ZH_TO_EN_PATH.get(p, p) for p in normalized_required_zh]
        forbidden_zh = [EN_TO_ZH_PATH.get(p, p) for p in forbidden_paths]
        missing_paths = [p for p in normalized_required if p not in normalized_actual]
        extra_forbidden = [p for p in normalized_actual if p in forbidden_paths]
        path_status = "passed" if not (missing_paths or extra_forbidden) else "failed"
        path_evidence = [
            f"required_path_types={required_paths}",
            f"forbidden_path_types={forbidden_paths}",
            f"actual_path_types={normalized_actual}",
            f"valid_path_types(zh)={list(valid_path_types)}",
            f"path_order={path_order}",
            f"path_aliases={path_aliases}",
            f"missing_paths={missing_paths}",
            f"extra_forbidden={extra_forbidden}",
            f"en_to_zh_mapping={EN_TO_ZH_PATH}",
        ]
        path_root_cause = None
        if path_status == "failed":
            detail = []
            if missing_paths:
                detail.append(f"缺少必要路径 {missing_paths}（业务系统 normalize_path_types 仅保留 {list(valid_path_types)}）")
            if extra_forbidden:
                detail.append(f"出现禁用路径 {extra_forbidden}（reference/forbidden_path_types 不允许）")
            path_root_cause = {
                "category": "implementation_bug",
                "summary": "营销规划服务未按业务系统 path_types 约定产出规划路径：" + "；".join(detail) + "，最早分歧位于 path_dispatch。",
                "evidence": path_evidence,
                "confidence": "high",
                "fix_suggestion": "修正 marketing-planning 服务中 path_planning/nbev_workflow 的路径派发逻辑，使其按 app/workflow/path_types.py:normalize_path_types 的有效集合与 app/configs/config_dev.json:PATH_ORDER 顺序产出 card_summary。",
            }
        checks.append({
            "tool_type": "runtime_check",
            "check_type": "path_type_validation",
            "status": path_status,
            "required_path_types": required_paths,
            "forbidden_path_types": forbidden_paths,
            "actual_path_types": normalized_actual,
            "missing_paths": missing_paths,
            "extra_forbidden": extra_forbidden,
            "valid_path_types": list(valid_path_types),
            "path_order": path_order,
            "evidence": path_evidence,
            "source": "; ".join(source_files) or "marketing-planning business system",
            "root_cause": path_root_cause,
            "confidence": "high" if path_status in {"passed", "failed"} else "low",
        })

        # 2) stage 校验：用业务系统 stages 约定比对 expected_stage
        expected_stage = reference.get("expected_stage") or expected.get("expected_stage")
        actual_stage = actual.get("stage")
        stage_status = "passed" if (not expected_stage or expected_stage == actual_stage) else "failed"
        stage_evidence = [
            f"expected_stage={expected_stage}",
            f"actual_stage={actual_stage}",
            f"adapter_stages={list(self.stages)}",
        ]
        stage_root_cause = None
        if stage_status == "failed":
            stage_root_cause = {
                "category": "implementation_bug",
                "summary": f"营销规划服务 stage 路由错误：业务系统约定 expected_stage={expected_stage}，实际 actual_stage={actual_stage}，最早分歧位于 intent_recognition/stage routing。",
                "evidence": stage_evidence,
                "confidence": "high",
                "fix_suggestion": "修正 marketing-planning 服务 app/workflow/steps 的 stage 判定/路由逻辑，使 stage 与 reference.expected_stage 一致。",
            }
        checks.append({
            "tool_type": "runtime_check",
            "check_type": "stage_routing",
            "status": stage_status,
            "expected_stage": expected_stage,
            "actual_stage": actual_stage,
            "evidence": stage_evidence,
            "source": "app/configs/config_dev.json:INTENT_MAPPING + adapter.stages",
            "root_cause": stage_root_cause,
            "confidence": "high" if stage_status in {"passed", "failed"} else "low",
        })

        # 3) target_value 单位校验：直接调用业务系统 extract_target_value_from_text
        target_evidence = []
        target_root_cause = None
        target_status = "not_applicable"
        if extract_target_fn:
            query = str((runtime_values.get("query")) or (context.get("query")) or "")
            source_amount = self._target_amount_in_query(query)
            if source_amount and reference.get("target_value_wan") is not None:
                expected_wan = int(reference.get("target_value_wan"))
                actual_target = self._find_target_nbev_wan(actual)
                parsed = extract_target_fn(query)
                target_status = "failed"
                if actual_target is None:
                    target_evidence = [f"query={query}", f"source_amount={source_amount}", f"expected={expected_wan} 万", "actual targetNbev missing from output", f"business extract_target_value_from_text -> {parsed}"]
                    target_root_cause = {
                        "category": "implementation_bug",
                        "summary": f"当前 query 含 {source_amount}，业务系统 extract_target_value_from_text 解析为 {parsed} 万，但实际链路未产出可核验 targetNbev，最早分歧位于 request_normalization/目标值单位转换。",
                        "evidence": target_evidence,
                        "confidence": "high",
                        "fix_suggestion": "修正 marketing-planning 服务请求归一化或目标值单位转换逻辑，确保“亿”转换为内部单位“万”时乘以 10000。",
                    }
                elif int(actual_target) != expected_wan:
                    target_evidence = [f"query={query}", f"source_amount={source_amount}", f"expected={expected_wan} 万", f"actual={actual_target} 万", f"business extract_target_value_from_text -> {parsed}"]
                    target_status = "failed"
                    target_root_cause = {
                        "category": "implementation_bug",
                        "summary": f"当前 query 含 {source_amount}，按业务系统单位应为 {expected_wan} 万，实际链路使用 {actual_target} 万，最早差异位于 request_normalization/目标值单位转换。",
                        "evidence": target_evidence,
                        "confidence": "high",
                        "fix_suggestion": "修正 marketing-planning 服务请求归一化或目标值单位转换逻辑，确保“亿”转换为内部单位“万”时乘以 10000。",
                    }
                else:
                    target_status = "passed"
                    target_evidence = [f"query={query}", f"expected={expected_wan} 万", f"actual={actual_target} 万"]
                checks.append({
                    "tool_type": "runtime_check",
                    "check_type": "target_value_unit",
                    "status": target_status,
                    "expected_target_nbev_wan": expected_wan,
                    "actual_target_nbev_wan": actual_target,
                    "source_amount": source_amount,
                    "business_parsed": parsed,
                    "evidence": target_evidence,
                    "source": "app/workflow/path_types.py:extract_target_value_from_text",
                    "root_cause": target_root_cause,
                    "confidence": "high" if target_status in {"passed", "failed"} else "low",
                })

        # 4) fallback / SSE 校验：用业务系统 config 的 SSE_EVENTS 集合判定 completion
        fallback = actual.get("fallback") or {}
        allow_fallback = bool(reference.get("allow_fallback") or expected.get("allow_fallback"))
        event_summary = actual.get("event_summary") or {}
        event_names = list(event_summary.get("canonical_names") or event_summary.get("names") or [])
        completed = bool(event_summary.get("completed"))
        required_events = self._list(reference.get("required_events") or expected.get("required_events"))
        missing_events = [e for e in required_events if e not in event_names]
        fallback_status = "passed" if (not fallback.get("used") or allow_fallback) else "failed"
        sse_status = "passed" if not missing_events and completed else ("failed" if missing_events else "passed")
        fb_evidence = [
            f"fallback_used={fallback.get('used')}",
            f"allow_fallback={allow_fallback}",
            f"required_events={required_events}",
            f"actual_events={event_names}",
            f"missing_events={missing_events}",
            f"completed={completed}",
            f"sse_event_catalog_count={len(sse_events)}",
        ]
        fb_root_cause = None
        if fallback_status == "failed" or sse_status == "failed":
            detail = []
            if fallback.get("used") and not allow_fallback:
                detail.append("fallback 在不允许的 boundary 内触发，违反业务系统 boundary 契约")
            if missing_events:
                detail.append(f"缺少必要 SSE 事件 {missing_events}（业务系统 SSE_EVENTS 目录已定义这些事件）")
            fb_root_cause = {
                "category": "implementation_bug",
                "summary": "营销规划服务 SSE/fallback 不符合业务系统约定：" + "；".join(detail) + "，最早分歧位于 result_assembly/sse_generation。",
                "evidence": fb_evidence,
                "confidence": "high",
                "fix_suggestion": "修正 marketing-planning 服务 result_assembly/sse_generation 与 fallback 控制逻辑，使其按 app/configs/config_dev.json:SSE_EVENTS 产出事件并遵守 boundary.allow_fallback。",
            }
        checks.append({
            "tool_type": "runtime_check",
            "check_type": "fallback_sse",
            "status": "failed" if (fallback_status == "failed" or sse_status == "failed") else "passed",
            "fallback_used": bool(fallback.get("used")),
            "allow_fallback": allow_fallback,
            "missing_events": missing_events,
            "completed": completed,
            "card_metadata_keys": list(card_metadata.keys())[:20] if isinstance(card_metadata, dict) else [],
            "evidence": fb_evidence,
            "source": "app/configs/config_dev.json:SSE_EVENTS/CARD_METADATA + adapter boundary",
            "root_cause": fb_root_cause,
            "confidence": "high",
        })

        failed = [c for c in checks if c.get("root_cause")]
        primary = failed[0].get("root_cause") if failed else None
        return {
            "tool_type": "runtime_check",
            "check_type": "marketing_planning_contract",
            "status": "failed" if failed else "passed",
            "checks": checks,
            "source": "; ".join(source_files) or "marketing-planning business system path_types.py + config_dev.json",
            "evidence": [e for c in checks for e in (c.get("evidence") or [])],
            "root_cause": primary,
            "fix_suggestion": primary.get("fix_suggestion") if primary else "",
            "confidence": "high" if failed else "medium",
            "note": "直接调用业务系统 app/workflow/path_types.py 与 app/configs/config_dev.json 校验 stage/path/fallback/target_value，不读 prompt 推测。",
        }

    def _runtime_actual_from_values(self, runtime_values: Dict[str, Any]) -> Dict[str, Any]:
        actual = {}
        for key in ("stage", "card_summary", "fallback", "event_summary"):
            if key in runtime_values:
                actual[key] = runtime_values[key]
        return actual

    def _target_amount_in_query(self, query: str) -> Optional[str]:
        match = re.search(r"(\d+(?:\.\d+)?)\s*亿", query or "")
        return match.group(0) if match else None

    def _load_business_path_types_module(self) -> Dict[str, Any]:
        """直接加载业务系统 app/workflow/path_types.py 的原函数。"""
        ext_repo = self.spec.application.get("external_repo") if isinstance(self.spec.application, dict) else None
        if not ext_repo:
            return {}
        source_path = Path(ext_repo) / "app" / "workflow" / "path_types.py"
        if not source_path.exists():
            return {}
        try:
            spec = importlib.util.spec_from_file_location("marketing_planning_runtime_path_types", source_path)
            if spec is None or spec.loader is None:
                return {}
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return {
                "VALID_PATH_TYPES": getattr(module, "VALID_PATH_TYPES", ()),
                "PATH_TYPE_ALIASES": getattr(module, "PATH_TYPE_ALIASES", {}),
                "normalize_path_types": getattr(module, "normalize_path_types", None),
                "extract_target_value_from_text": getattr(module, "extract_target_value_from_text", None),
            }
        except Exception:
            return {}

    def _load_business_config(self) -> Dict[str, Any]:
        """直接加载业务系统 app/configs/config_dev.json 的运行时配置。"""
        ext_repo = self.spec.application.get("external_repo") if isinstance(self.spec.application, dict) else None
        if not ext_repo:
            return {}
        config_path = Path(ext_repo) / "app" / "configs" / "config_dev.json"
        if not config_path.exists():
            return {}
        try:
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def build_attribute_tools(self) -> list:
        """Issue #3: 暴露项目级 runtime tool 给 attribute agent 调用（Agno 兼容函数）。

        闭包函数直接调用业务系统原函数 normalize_path_types / extract_target_value_from_text，
        让 attribute agent 通过 tool call 复现 trace 节点行为。
        """
        adapter = self

        def validate_path_types(path_types: list) -> dict:
            """用业务系统 normalize_path_types 校验路径类型是否合法并归一化。

            Args:
                path_types: 路径类型列表（英文，如 ["premium_growth", "customer_growth"]）

            Returns:
                包含 normalized、valid_path_types、source 的字典
            """
            path_module = adapter._load_business_path_types_module()
            valid = list(path_module.get("VALID_PATH_TYPES", ())) if path_module else ()
            normalize_fn = path_module.get("normalize_path_types") if path_module else None
            # adapter 英文 path → 业务系统中文名
            EN_TO_ZH = {"premium_growth": "队伍", "customer_growth": "客户", "product_mix": "产品", "activity": "活动", "unknown": "未知"}
            zh_input = [EN_TO_ZH.get(p, p) for p in path_types]
            normalized_zh = list(normalize_fn(zh_input)) if (normalize_fn and zh_input) else zh_input
            ZH_TO_EN = {v: k for k, v in EN_TO_ZH.items()}
            normalized_en = [ZH_TO_EN.get(p, p) for p in normalized_zh]
            return {
                "input_path_types": path_types,
                "normalized_path_types": normalized_en,
                "valid_path_types_zh": valid,
                "source": "app/workflow/path_types.py:normalize_path_types",
            }

        def extract_target_value(query: str) -> dict:
            """用业务系统 extract_target_value_from_text 从 query 解析目标值（万）。

            Args:
                query: 用户查询文本（如 "NBEV达成路径规划，目标值120亿"）

            Returns:
                包含 parsed_target_wan、source 的字典
            """
            path_module = adapter._load_business_path_types_module()
            extract_fn = path_module.get("extract_target_value_from_text") if path_module else None
            parsed = extract_fn(query) if extract_fn else None
            return {
                "query": query,
                "parsed_target_wan": parsed,
                "source": "app/workflow/path_types.py:extract_target_value_from_text",
            }

        validate_path_types.__name__ = "validate_path_types"
        extract_target_value.__name__ = "extract_target_value"
        return [validate_path_types, extract_target_value]

    def simulate_trace_nodes(self, trace, judge_result) -> Dict[str, Any]:
        """Issue #3: 沿 trace 逐节点调业务系统函数复现，定位最早分歧。

        对 path_dispatch 节点调 normalize_path_types，对 request_normalization 节点调
        extract_target_value_from_text，比较模拟输出与 trace actual。
        """
        path_module = self._load_business_path_types_module()
        config = self._load_business_config()
        normalize_fn = path_module.get("normalize_path_types") if path_module else None
        extract_target_fn = path_module.get("extract_target_value_from_text") if path_module else None
        valid_path_types = list(path_module.get("VALID_PATH_TYPES", ())) if path_module else ()
        EN_TO_ZH = {"premium_growth": "队伍", "customer_growth": "客户", "product_mix": "产品", "activity": "活动", "unknown": "未知"}
        ZH_TO_EN = {v: k for k, v in EN_TO_ZH.items()}
        source_path = "app/workflow/path_types.py:normalize_path_types/extract_target_value_from_text"
        simulated_nodes: list[Dict[str, Any]] = []
        diverged_nodes: list[Dict[str, Any]] = []
        for node in (trace.execution_trace or []):
            if not isinstance(node, dict):
                continue
            stage = str(node.get("stage") or node.get("node") or "")
            evidence = node.get("evidence") if isinstance(node.get("evidence"), dict) else {}
            entry = None
            if stage == "path_dispatch" and normalize_fn:
                actual_paths = evidence.get("actual_path_types") or evidence.get("actual_paths") or []
                expected_paths = evidence.get("expected_path_types") or evidence.get("expected_paths") or []
                zh_input = [EN_TO_ZH.get(p, p) for p in actual_paths]
                normalized_zh = list(normalize_fn(zh_input)) if zh_input else []
                normalized_en = [ZH_TO_EN.get(p, p) for p in normalized_zh]
                # 模拟：expected_paths 经 normalize 后应等于 normalized actual
                zh_expected = [EN_TO_ZH.get(p, p) for p in expected_paths]
                norm_expected = list(normalize_fn(zh_expected)) if zh_expected else []
                # 检查 required paths 是否都在 normalized actual 中
                missing = [p for p in (ZH_TO_EN.get(p, p) for p in norm_expected) if p not in normalized_en]
                status = "passed" if not missing else "diverged"
                entry = {
                    "stage": stage,
                    "input_used": {"actual_path_types": actual_paths, "expected_path_types": expected_paths},
                    "simulated_output": {"normalized_actual": normalized_en, "normalized_expected": [ZH_TO_EN.get(p, p) for p in norm_expected]},
                    "trace_actual": {"actual_path_types": actual_paths},
                    "status": status,
                    "function_called": "normalize_path_types",
                    "source_file": source_path,
                    "missing_paths": missing,
                }
            elif stage == "request_normalization" and extract_target_fn:
                query = str(evidence.get("query") or (trace.normalized_request or {}).get("query") or (trace.input or {}).get("query") or "")
                parsed = extract_target_fn(query) if query else None
                trace_target = evidence.get("target_value") or evidence.get("target_nbev_wan")
                status = "passed" if (trace_target is None or parsed == trace_target) else "diverged"
                entry = {
                    "stage": stage,
                    "input_used": {"query": query},
                    "simulated_output": {"parsed_target_wan": parsed},
                    "trace_actual": {"target_value": trace_target},
                    "status": status,
                    "function_called": "extract_target_value_from_text",
                    "source_file": source_path,
                }
            if entry:
                simulated_nodes.append(entry)
                if entry["status"] == "diverged":
                    diverged_nodes.append(entry)
        return {"simulated_nodes": simulated_nodes, "diverged_nodes": diverged_nodes, "source": source_path, "valid_path_types": valid_path_types}

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
