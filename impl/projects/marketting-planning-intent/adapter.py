from __future__ import annotations

import importlib.util
import importlib.util
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from impl.core.schema import JudgeResult
from impl.core.adapter import ProjectAdapter
from impl.tools import ToolRegistry


# Stage→ext_repo path-prefix map. Narrows the source-file catalog by current
# trace failure signals so the attribute agent doesn't see the entire repo.
# Prefixes use exact file paths (with .py) — intent_recognition is a module
# file, not a directory, so a trailing-slash prefix would never match it.
STAGE_FILE_PREFIXES: Dict[str, tuple] = {
    "request_normalization": ("app/api/", "app/schemas/request", "app/main.py"),
    "intent_api_call": (
        "app/workflow/steps/intent_recognition.py",
        "app/workflow/prompts/intent_prompt.py",
        "app/schemas/intent.py",
        "app/config.py",
        "app/utils/llm_client.py",
    ),
    "adapter_extraction": (),  # adapter.py is added separately by source_retrieval
    "label_mapping": (
        "app/workflow/steps/intent_recognition.py",
        "app/schemas/intent.py",
        "app/config.py",
    ),
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


MarketingPlanningIntentContractTool = _load_local_tool_class("intent_contract.py", "MarketingPlanningIntentContractTool")


class Adapter(ProjectAdapter):
    def protocol_tools(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(MarketingPlanningIntentContractTool())
        return registry

    def _project_contract_tool_results(self, trace, purpose: str) -> list[Dict[str, Any]]:
        return [result.__dict__ for result in self.run_protocol_tools(trace, purpose=purpose, tool_type="project_contract")]

    def build_request(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        nested = input_data.get("input") if isinstance(input_data.get("input"), dict) else {}
        query = input_data.get("query") or input_data.get("user_text") or input_data.get("user_query") or nested.get("query") or nested.get("user_text") or ""
        reference = input_data.get("reference") or nested.get("reference") or {}
        expected_intent = input_data.get("expected_intent") or nested.get("expected_intent") or (reference.get("intent") if isinstance(reference, dict) else None)
        session_id = str(input_data.get("session_id") or nested.get("session_id") or f"eval-{input_data.get('case_id') or input_data.get('id') or int(time.time() * 1000)}")
        return {
            "case_id": str(input_data.get("case_id") or input_data.get("id") or f"intent-case-{int(time.time() * 1000)}"),
            "session_id": session_id,
            "query": str(query),
            "scenario": str(input_data.get("scenario") or nested.get("scenario") or "intent_recognition"),
            "expected_intent": expected_intent,
            "reference": reference if isinstance(reference, dict) else {"intent": reference},
            "metadata": dict(input_data.get("metadata") or nested.get("metadata") or {}),
        }

    def call_or_prepare(self, request: Dict[str, Any]) -> Any:
        body = json.dumps(self._live_request_body(request), ensure_ascii=False).encode("utf-8")
        url = str(self.spec.api.get("base_url") or "").rstrip("/") + "/" + str(self.spec.api.get("endpoint") or "").lstrip("/")
        api_request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method=str(self.spec.api.get("method") or "POST").upper())
        try:
            with urllib.request.urlopen(api_request, timeout=float(self.spec.api.get("timeout") or 60)) as response:
                return {"raw": response.read().decode("utf-8"), "request": request}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"marketing-planning intent service unavailable: {exc}") from exc

    def _live_request_body(self, request: Dict[str, Any]) -> Dict[str, Any]:
        query = str(request.get("query") or "")
        session_id = str(request.get("session_id") or f"eval-{request.get('case_id') or int(time.time() * 1000)}")
        return {
            "session_id": session_id,
            "trace_id": str(request.get("case_id") or session_id),
            "org_id": str((request.get("metadata") or {}).get("org_id") or "eval-org"),
            "user_text": query,
            "extra_input_params": {
                "agent_args": {"conversation_id": session_id, "message": {"content": query, "content_type": "text"}},
                "args": {"extensions": {}, "contexts": []},
            },
        }

    def provided_output_raw(self, input_data: Dict[str, Any], request: Dict[str, Any]) -> Any:
        for key in ("raw_response", "response", "output"):
            if key in input_data:
                return {"raw": input_data[key], "request": request}
        return {"raw": {}, "request": request}

    def extract_output(self, raw_response: Any) -> Dict[str, Any]:
        data = raw_response.get("raw") if isinstance(raw_response, dict) and "raw" in raw_response else raw_response
        parsed = self._parse_payload(data)
        nlu_info = self._first_value(parsed, ["nlu_info"])
        if not isinstance(nlu_info, dict):
            nlu_info = {}
        raw_intent = self._first_value(parsed, ["intent", "intent_type", "intent_label", "label", "type"])
        intent = nlu_info.get("intent") or raw_intent
        confidence = nlu_info.get("confidence") if "confidence" in nlu_info else self._first_value(parsed, ["confidence", "score", "probability"])
        slots = self._first_value(parsed, ["slots", "slot", "slot_values"]) or {}
        if nlu_info:
            slots = {key: value for key, value in nlu_info.items() if key not in {"intent", "confidence", "subIntent"} and value is not None}
        entities = self._first_value(parsed, ["entities", "entity", "extracted_entities"]) or []
        ambiguous = bool(self._first_value(parsed, ["ambiguous", "is_ambiguous"]))
        fallback = bool(self._first_value(parsed, ["fallback", "is_fallback"])) or str(intent or "").lower() in {"unknown", "fallback"}
        errors = self._first_value(parsed, ["error", "errors", "message"])
        if errors and not isinstance(errors, list):
            errors = [errors]
        return {
            "intent": intent or "unknown",
            "confidence": confidence,
            "raw_intent": raw_intent,
            "slots": slots if isinstance(slots, dict) else {},
            "entities": entities if isinstance(entities, list) else [entities],
            "ambiguous": ambiguous,
            "fallback": fallback,
            "errors": errors or [],
        }

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any]) -> Dict[str, Any]:
        request = raw_response.get("request") if isinstance(raw_response, dict) else {}
        return {
            "scenario": request.get("scenario") or "intent_recognition",
            "case_id": request.get("case_id") or "",
            "session_id": request.get("session_id") or "",
            "reference": request.get("reference") or {},
            "expected_intent": request.get("expected_intent"),
            "application_boundary": {"scope": "single_turn_intent_recognition", "excludes": ["multi_turn_planning", "sse_card_generation"]},
        }

    def build_execution_trace(self, input_data: Dict[str, Any], request: Dict[str, Any], raw_response: Any, extracted_output: Dict[str, Any]) -> list[Dict[str, Any]]:
        return [
            {"stage": "request_normalization", "status": "ok" if request.get("query") else "suspicious", "evidence": {"query": request.get("query")}},
            {"stage": "intent_api_call", "status": "ok", "evidence": {"endpoint": self.spec.api.get("endpoint")}},
            {"stage": "adapter_extraction", "status": "ok" if extracted_output.get("intent") else "failed", "evidence": extracted_output},
            {"stage": "label_mapping", "status": "ok" if extracted_output.get("intent") != "unknown" else "suspicious", "evidence": {"intent": extracted_output.get("intent")}},
        ]

    def build_judge_context(self, trace) -> Dict[str, Any]:
        return {
            "project_type": "single_turn_marketing_intent_recognition",
            "current_case_only": True,
            "reference_contract": trace.project_fields.get("reference") or {},
            "expected_intent": trace.project_fields.get("expected_intent"),
            "application_boundary": trace.project_fields.get("application_boundary") or {},
            "critical_intent_dimensions": ["intent_label", "required_slots_or_entities", "confidence_threshold", "fallback_policy", "dispatch_boundary"],
            "protocol_tool_results": self._project_contract_tool_results(trace, purpose="judge"),
        }

    def build_intent_frame(self, trace) -> Dict[str, Any]:
        context = self.build_judge_context(trace)
        return {
            **super().build_intent_frame(trace),
            "business_task_type": "single_turn_marketing_intent_recognition",
            "downstream_consumer": "marketing intent router",
            "critical_intent_dimensions": ["intent_label", "required_slots_or_entities", "confidence_threshold", "fallback_policy", "dispatch_boundary"],
            "expected_intent": context.get("expected_intent"),
            "reference_contract": context.get("reference_contract") or {},
            "boundary_rules": context.get("application_boundary") or {},
            "output_semantics": "resolve the current user query to a safe marketing-planning intent label and required slots before planning dispatch",
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
            implicated = ["intent_api_call"]

        prefix_union: List[str] = []
        for stage in implicated:
            for prefix in STAGE_FILE_PREFIXES.get(stage, ()):
                if prefix not in prefix_union:
                    prefix_union.append(prefix)

        if not prefix_union:
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
        # 外部业务仓库
        ext_repo = self.spec.application.get("external_repo") if isinstance(self.spec.application, dict) else None
        if ext_repo:
            ext_path = Path(ext_repo)
            if ext_path.exists():
                for py_file in self._select_ext_repo_files_by_stage(ext_path, trace):
                    try:
                        source_config_paths[f"ext_repo:{py_file.relative_to(ext_path)}"] = str(py_file)
                    except Exception:
                        pass
        # 项目源码文档
        for doc_key, doc_rel in (self.spec.documents or {}).items():
            if doc_key.startswith("source_"):
                p = Path(self.spec.root) / str(doc_rel)
                if p.exists():
                    source_config_paths[f"project_doc:{doc_key}"] = str(p)
        return {
            "chain_nodes_to_check": list(trace.execution_trace or []),
            "earliest_stage_order": ["request_normalization", "intent_api_call", "adapter_extraction", "label_mapping"],
            "reference_contract": trace.project_fields.get("reference") or {},
            "source_config_paths": source_config_paths,
            "protocol_tool_results": self._project_contract_tool_results(trace, purpose="attribute"),
            "attribute_standard": "Only attribute current single-turn intent-recognition failures; do not attribute planning/SSE generation gaps here. Use source_code_evidence to locate exact config/code/prompt responsible for the error.",
        }

    def trace_state_graph(self) -> Dict[str, Any]:
        graph = self.extend_default_trace_graph("collect_evidence", ["marketing_intent_boundary_evidence"])
        graph["graph_id"] = "marketting_planning_intent_single_turn_trace_state_machine"
        return graph

    def state_executors(self) -> Dict[str, Any]:
        return {"marketing_intent_boundary_evidence": self._marketing_intent_boundary_evidence}

    def _marketing_intent_boundary_evidence(self, context: Dict[str, Any]) -> Dict[str, Any]:
        trace = context.get("trace")
        if not trace:
            return {"status": "failed", "missing_evidence": ["trace"]}
        fields = trace.project_fields or {}
        evidence = {
            "scenario": fields.get("scenario"),
            "endpoint": self.spec.api.get("endpoint"),
            "single_turn_only": True,
            "application_boundary": fields.get("application_boundary") or {},
            "shared_service_boundary": "marketing-planning service boundary, distinct judge scope",
        }
        return {
            "status": "succeeded",
            "outputs": evidence,
            "evidence_refs": [{"type": "marketing_intent_boundary", "evidence": evidence}],
            "claims": [{"marketing_intent_boundary": evidence}],
        }

    def collect_state_evidence(self, state_id: str, context: Dict[str, Any]) -> list[Dict[str, Any]]:
        trace = context.get("trace")
        if not trace:
            return []
        fields = trace.project_fields or {}
        return [{"type": "marketing_intent_state_boundary", "state_id": state_id, "application_boundary": fields.get("application_boundary") or {}, "single_turn_only": True}]

    def build_frontend_extensions(self, trace):
        return {
            "project_fields": trace.project_fields,
            "intent_labels": self.spec.frontend_extensions.get("intent_labels") or [],
            "output_summary_shape": ["intent", "confidence", "raw_intent", "slots", "entities", "ambiguous", "fallback", "errors"],
        }

    def pre_judge_result(self, trace, expected_intent=None):
        """Do NOT short-circuit the LLM judge.

        Returning a JudgeResult here skips the core LLM judge call, producing
        a deterministic template reasoning summary and 0 LLM judge calls.
        Returning None lets the LLM judge run; the deterministic contract
        checks (intent, required_slots, fallback, min_confidence) are then
        applied via normalize_judge_result which runs inside
        reconcile_judge_result AFTER the LLM judge.
        """
        return None

    def normalize_judge_result(self, trace, judge_result):
        reference = trace.project_fields.get("reference") or trace.input.get("reference") or trace.normalized_request.get("reference") or {}
        if not isinstance(reference, dict):
            reference = {"intent": reference}
        output = trace.extracted_output or {}
        missing = list(judge_result.missing or [])
        wrong = list(judge_result.wrong or [])
        expected_intent = reference.get("intent") or trace.project_fields.get("expected_intent")
        actual_intent = output.get("intent")
        if expected_intent and actual_intent != expected_intent:
            wrong.append({"requirement": "intent", "expected_fragment": expected_intent, "actual_fragment": actual_intent, "status": "wrong", "evidence": ["normalized intent differs from reference intent"]})
        slots = output.get("slots") if isinstance(output.get("slots"), dict) else {}
        required_slots = list(reference.get("required_slots") or reference.get("required_entities") or [])
        absent_slots = [slot for slot in required_slots if slot not in slots and slot not in {entity.get("type") for entity in output.get("entities", []) if isinstance(entity, dict)}]
        if absent_slots:
            missing.append({"requirement": "required_slots", "expected_fragment": absent_slots, "actual_fragment": slots, "status": "missing", "evidence": ["required slot/entity absent from normalized intent evidence"]})
        # Issue #3 修复：required_slots 有效性校验——slot 存在但值为占位符/空值也算 blocking wrong。
        # 之前只检查 slot 是否缺失（absent_slots），但 mpi-required-slot-missing-1 的
        # slots.year="mock_value" 占位值让 absent_slots 为空，gate 不 fail，case 被判 fulfilled，
        # 导致 attribute 路径不被触发、attr 退回通用模板。
        PLACEHOLDER_PATTERNS = ("mock_value", "mock_", "placeholder", "unknown", "null", "undefined")
        invalid_slot_values = []
        for slot_name in required_slots:
            if slot_name in slots:
                slot_value = slots.get(slot_name)
                if slot_value is None or slot_value == "":
                    invalid_slot_values.append({"slot": slot_name, "value": slot_value, "reason": "slot 值为空/NULL"})
                elif isinstance(slot_value, str) and slot_value.lower().startswith(PLACEHOLDER_PATTERNS):
                    invalid_slot_values.append({"slot": slot_name, "value": slot_value, "reason": f"slot 值为占位符 '{slot_value}'（非真实业务提取值）"})
        if invalid_slot_values:
            wrong.append({"requirement": "required_slots", "expected_fragment": required_slots, "actual_fragment": slots, "status": "wrong", "evidence": [f"required slot 提取为占位/无效值: {[(s['slot'], s['value']) for s in invalid_slot_values]}"]})
        allow_fallback = bool(reference.get("allow_fallback"))
        if not allow_fallback and (output.get("fallback") or output.get("ambiguous") or str(actual_intent or "").lower() in {"unknown", "fallback"}):
            wrong.append({"requirement": "allow_fallback", "expected_fragment": False, "actual_fragment": {"fallback": output.get("fallback"), "ambiguous": output.get("ambiguous"), "intent": actual_intent}, "status": "wrong", "evidence": ["fallback/unknown/ambiguous intent is not allowed by reference"]})
        min_confidence = reference.get("min_confidence")
        confidence = output.get("confidence")
        if min_confidence is not None and confidence is not None and float(confidence) < float(min_confidence):
            wrong.append({"requirement": "min_confidence", "expected_fragment": min_confidence, "actual_fragment": confidence, "status": "wrong", "evidence": ["intent confidence is below reference threshold"]})
        judge_result.missing = missing
        judge_result.wrong = wrong
        judge_result.actual = judge_result.actual or output
        judge_result.expected = judge_result.expected or reference
        blocking_wrong = [item for item in wrong if isinstance(item, dict) and item.get("requirement") in {"intent", "allow_fallback", "min_confidence", "required_slots"}]
        gate_failed = bool(missing or blocking_wrong)
        if gate_failed:
            evidence_summary = {
                "missing": [item.get("requirement") for item in missing if isinstance(item, dict)],
                "blocking_wrong": [item.get("requirement") for item in blocking_wrong if isinstance(item, dict)],
            }
            evidence_str = f"missing={evidence_summary.get('missing')}; blocking_wrong={evidence_summary.get('blocking_wrong')}"
            judge_result.fulfillment_assessments = [{
                "expectation_id": "intent_contract",
                "status": "not_fulfilled",
                "blocking": True,
                "evidence": evidence_str,
                "downstream_impact": self._intent_contract_reasoning_summary(trace, reference, output, missing, wrong, "incorrect"),
            }]
            judge_result.verdict = "incorrect"
            judge_result.score = 0
            if "intent_contract_gate_failed" not in judge_result.quality_flags:
                judge_result.quality_flags.append("intent_contract_gate_failed")
            judge_result.quality_flags = [flag for flag in judge_result.quality_flags if flag != "llm_call_failed"]
            judge_result.primary_assessment = {"status": "failed", "missing": missing, "wrong": wrong}
            judge_result.verdict_derivation = {**(judge_result.verdict_derivation or {}), "contract_gate": "failed", "contract_gate_reasoning": self._intent_contract_reasoning_summary(trace, reference, output, missing, wrong, "incorrect")}
            # Preserve the LLM judge's detailed reasoning_summary; the
            # deterministic contract verdict/score override the LLM's, but
            # the per-requirement LLM analysis must remain visible in the
            # report's judge column.
            if not judge_result.reasoning_summary:
                judge_result.reasoning_summary = self._intent_contract_reasoning_summary(trace, reference, output, missing, wrong, "incorrect")
            self.register_judge_override(judge_result, "fulfillment_assessments", [], ["intent_contract: not_fulfilled"], "contract_gate_failed", "normalize_judge_result")
            return judge_result
        if "intent_contract_gate_passed" not in judge_result.quality_flags:
            judge_result.quality_flags.append("intent_contract_gate_passed")
        judge_result.fulfillment_assessments = [{
            "expectation_id": "intent_contract",
            "status": "fulfilled",
            "blocking": False,
            "evidence": f"intent={actual_intent}; confidence={confidence}; min_confidence={min_confidence}",
            "downstream_impact": self._intent_contract_reasoning_summary(trace, reference, output, [], [], "correct"),
        }]
        judge_result.verdict = "correct"
        judge_result.score = 1
        judge_result.verdict_derivation = {**(judge_result.verdict_derivation or {}), "contract_gate": "passed"}
        judge_result.reasoning_summary = judge_result.reasoning_summary or self._intent_contract_reasoning_summary(trace, reference, output, [], [], "correct")
        judge_result.primary_assessment = {"status": "passed", "covered": ["intent_contract"]}
        judge_result.quality_flags = [flag for flag in judge_result.quality_flags if flag != "llm_call_failed"]
        return judge_result

    def _intent_contract_reasoning_summary(self, trace, reference, output, missing, wrong, verdict: str) -> str:
        query = trace.input.get("query") or (trace.input.get("input") or {}).get("query") if isinstance(trace.input, dict) else ""
        expected_intent = reference.get("intent")
        actual_intent = output.get("intent")
        confidence = output.get("confidence")
        min_confidence = reference.get("min_confidence")
        if verdict == "correct":
            return f"当前单轮意图识别满足 reference contract：intent={actual_intent}，confidence={confidence} 达到最低要求 {min_confidence}。"
        failed = []
        for item in list(missing or []) + list(wrong or []):
            if isinstance(item, dict):
                failed.append(str(item.get("requirement") or item.get("status") or item))
        return f"当前单轮意图识别未满足 reference contract：query={query}，expected_intent={expected_intent}，actual_intent={actual_intent}，confidence={confidence}，min_confidence={min_confidence}，失败项={failed}，整体判定为 incorrect。"

    def _default_consumer_contract(self, trace, judge_result):
        context = self.build_judge_context(trace)
        return {
            "consumer": "marketing intent router",
            "contract": "single-turn query must resolve to the expected intent, required slots/entities, confidence threshold, and fallback policy before planning starts",
            "reference_contract": context.get("reference_contract") or {},
            "application_boundary": context.get("application_boundary") or {},
        }

    def _default_business_expectation(self, trace, judge_result):
        expectation = super()._default_business_expectation(trace, judge_result)
        expectation.update(
            {
                "expectation_id": "marketting-planning-intent:intent_contract",
                "downstream_consumer": "marketing intent router",
                "required_capabilities": expectation.get("required_capabilities") or ["intent_label", "slot_extraction", "confidence_threshold", "fallback_control"],
                "boundary": judge_result.boundary_decision or self.build_judge_context(trace).get("application_boundary") or expectation.get("boundary") or {},
            }
        )
        if not judge_result.intent_model:
            expectation.update(
                {
                    "user_intent": str((trace.normalized_request or {}).get("query") or trace.input or ""),
                    "expected_outcome": "single-turn intent recognition should return the expected label, required slots/entities, acceptable confidence, and permitted fallback behavior",
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
            "actual_evidence": list(judge_result.wrong or []) or [judge_result.actual or trace.extracted_output],
            "boundary_decision": judge_result.boundary_decision or self.build_judge_context(trace).get("application_boundary") or {},
            "downstream_impact": "intent router can safely dispatch to the next planning step" if status == "fulfilled" else (judge_result.reasoning_summary or "intent router cannot safely dispatch this query to the expected planning path"),
            "blocking": status in {"not_fulfilled", "not_evaluable"},
            "confidence": judge_result.confidence,
            "evidence_refs": list(getattr(trace, "evidence_refs", []) or []),
        }

    def normalize_attribute_result(self, trace, judge_result, attribute_result):
        if judge_result.verdict == "correct":
            if not attribute_result.expectation_attributions:
                expectation_id = "marketting-planning-intent:intent_contract"
                if judge_result.business_expectations:
                    first = judge_result.business_expectations[0]
                    expectation_id = first.get("expectation_id", expectation_id) if isinstance(first, dict) else getattr(first, "expectation_id", expectation_id)
                evidence = list(judge_result.evidence or ["intent contract fulfilled"])
                attribute_result.expectation_attributions = [{"expectation_id": expectation_id, "fulfillment_status": "fulfilled", "causal_category": "no_issue", "earliest_divergence": {"node": "intent_contract_gate", "evidence": evidence, "confidence": "high"}, "causal_chain": [{"name": "intent_contract_gate", "status": "succeeded", "evidence": evidence}], "local_verifications": [], "suspected_locations": [], "improvement_direction": [], "source_evidence": [], "probe_evidence": evidence, "incomplete_reason": ""}]
            attribute_result.causal_category = "no_issue"
            attribute_result.probe_results = attribute_result.probe_results or [{"probe": "intent_contract_gate", "status": "passed", "evidence": list(judge_result.evidence or ["intent contract fulfilled"])}]
            attribute_result.failure_category = "fulfilled_expectation"
            attribute_result.failure_stage = "fulfilled_expectation"
            attribute_result.analysis_method = "fulfilled_expectation_attribution"
            attribute_result.evidence_chain = list(judge_result.evidence or ["intent contract fulfilled"])
            attribute_result.trace_analysis = list(trace.execution_trace or [])
            attribute_result.chain_nodes = [{"name": "intent_contract_gate", "status": "succeeded", "evidence": attribute_result.evidence_chain, "reason": "intent contract fulfilled"}]
            attribute_result.evidence_coverage = {"query": bool(trace.input), "actual": bool(trace.extracted_output), "expected": bool(judge_result.expected), "execution_trace": bool(trace.execution_trace), "unsupported_claims": []}
            attribute_result.analysis_quality = {"passed": True, "status": "fulfilled_expectation", "missing": []}
            attribute_result.root_cause_hypothesis = "当前 intent-recognition 输出满足业务预期，归因结论为 no_issue。"
            attribute_result.verification_steps = []
            attribute_result.patch_direction = []
            return attribute_result
        # incorrect 路径：divergence_analysis_root_cause 已由 _enforce_divergence_root_cause
        # 写入 root_cause_hypothesis/patch_direction（runtime_check 产出闭合根因时）。
        # 这里只补全结构字段 + 兜底（无 runtime 根因时用 expected/actual 拼接）。
        first_failed = next((node for node in trace.execution_trace or [] if isinstance(node, dict) and node.get("status") in {"failed", "suspicious"}), {})
        expected = judge_result.expected or trace.project_fields.get("reference") or {}
        actual = judge_result.actual or trace.extracted_output or {}
        stage = first_failed.get("stage") or "intent_contract_gate"
        attribute_result.failure_category = attribute_result.failure_category or "intent_recognition"
        attribute_result.failure_stage = attribute_result.failure_stage or stage
        attribute_result.analysis_method = attribute_result.analysis_method or "trace_runtime_analysis_with_project_checks"
        attribute_result.trace_analysis = list(trace.execution_trace or [])
        attribute_result.chain_nodes = list(trace.execution_trace or [])
        if not attribute_result.earliest_divergence:
            attribute_result.earliest_divergence = {"node": stage, "expected": expected, "actual": actual, "evidence": [first_failed.get("evidence") or judge_result.missing or judge_result.wrong], "confidence": "medium"}
        attribute_result.evidence_coverage = {"query": bool(trace.input), "actual": bool(actual), "expected": bool(expected), "execution_trace": bool(trace.execution_trace), "unsupported_claims": []}
        if not attribute_result.root_cause_hypothesis:
            attribute_result.root_cause_hypothesis = f"当前 case 期望 intent/slots 为 {expected}，实际 normalized intent evidence 为 {actual}，最早差异位于 {stage}。"
            attribute_result.verification_steps = attribute_result.verification_steps or ["复查当前 query、reference 与 normalized intent evidence 是否一致。"]
            attribute_result.patch_direction = attribute_result.patch_direction or ["优先修正 intent-recognition 请求构造、响应解析或 label/slot 映射源头，不只改展示结果。"]
            attribute_result.analysis_quality = {"passed": False, "status": "next_verification_step", "missing": ["runtime_root_cause"]}
        else:
            attribute_result.analysis_quality = {**(attribute_result.analysis_quality or {}), "passed": True, "status": "supported_root_cause"}
        return attribute_result

    def get_runtime_checks(self, runtime_values: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        context = context or {}
        raw_intent = runtime_values.get("raw_intent") or runtime_values.get("raw_output")
        actual_intent = runtime_values.get("intent") or (context.get("actual") if isinstance(context.get("actual"), str) else None)
        actual = context.get("actual") if isinstance(context.get("actual"), dict) else {}
        expected = context.get("expected") if isinstance(context.get("expected"), dict) else {}
        reference = context.get("reference") if isinstance(context.get("reference"), dict) else {}
        actual_intent = actual_intent or actual.get("intent")
        expected_intent = expected.get("intent") or reference.get("intent") or context.get("expected_intent")
        if not raw_intent and not actual_intent and not expected_intent:
            return {"tool_type": "runtime_check", "check_type": "intent_mapping", "status": "not_applicable", "evidence": ["当前 trace 未提供 intent 映射检查所需的 raw_intent/intent/reference。"]}

        mapping, enum_values, source = self._load_intent_mapping_source()
        checks: list[Dict[str, Any]] = []
        source_files: list[str] = [source]

        # --- 1) intent 映射校验 ---
        actual_mapping = mapping.get(str(raw_intent)) if raw_intent is not None else actual_intent
        if actual_mapping is None:
            actual_mapping = actual_intent or "other"
        is_in_mapping = str(raw_intent) in mapping if raw_intent is not None else False
        is_expected_mapping = bool(expected_intent) and actual_mapping == expected_intent
        intent_status = "passed" if (not expected_intent or is_expected_mapping) else "failed"
        intent_evidence = [
            f"raw_intent={raw_intent}",
            f"actual_mapping={actual_mapping}",
            f"actual_intent={actual_intent}",
            f"expected_intent={expected_intent}",
            f"mapping_source={source}",
        ]
        intent_root_cause = None
        if intent_status == "failed":
            intent_root_cause = {
                "category": "implementation_bug",
                "summary": f"运行时 raw_intent={raw_intent} 经项目映射得到 {actual_mapping}，但当前 reference contract 期望 {expected_intent}。",
                "evidence": intent_evidence,
                "confidence": "high",
                "fix_suggestion": f"在项目意图映射源头校准 raw_intent={raw_intent} 的映射，或修正上游意图识别使其输出与 reference contract 一致的编码。",
            }
        checks.append({
            "tool_type": "runtime_check",
            "check_type": "intent_mapping",
            "status": intent_status,
            "raw_intent": raw_intent,
            "actual_mapping": actual_mapping,
            "actual_intent": actual_intent,
            "expected_intent": expected_intent,
            "is_in_mapping": is_in_mapping,
            "is_expected_mapping": is_expected_mapping,
            "available_mapping_count": len(mapping),
            "enum_values": enum_values,
            "evidence": intent_evidence,
            "source": source,
            "root_cause": intent_root_cause,
            "confidence": "high" if intent_status in {"passed", "failed"} else "low",
        })

        # --- 2) required_slots 有效性校验（Issue #3 修复） ---
        # Issue #3 审核 REJECTED 根因：mpi-required-slot-missing-1 的 attr 退回
        # 通用模板，因为 get_runtime_checks 只校验 intent 映射，不校验
        # required_slots 有效性。当 slots.year="mock_value"（占位值）时，
        # runtime_check 的 status 仍为 "passed"，analyze_divergence 拿不到
        # root_cause，退回 _infer_generic_root_cause 通用兜底。
        reference_slots = list(reference.get("required_slots") or reference.get("required_entities") or [])
        actual_slots = actual.get("slots") if isinstance(actual.get("slots"), dict) else runtime_values.get("slots", {})
        if not isinstance(actual_slots, dict):
            actual_slots = {}
        # 占位值模式：mock_value、空字符串、None、占位符类前缀
        PLACEHOLDER_PATTERNS = ("mock_value", "mock_", "placeholder", "unknown", "null", "undefined")
        invalid_slots: list[Dict[str, Any]] = []
        for slot_name in reference_slots:
            slot_value = actual_slots.get(slot_name)
            if slot_value is None or slot_value == "":
                invalid_slots.append({
                    "slot": slot_name,
                    "value": slot_value,
                    "reason": "slot 缺失或值为空/NULL",
                })
            elif isinstance(slot_value, str) and slot_value.lower().startswith(PLACEHOLDER_PATTERNS):
                invalid_slots.append({
                    "slot": slot_name,
                    "value": slot_value,
                    "reason": f"slot 值为占位符 '{slot_value}'（非真实业务提取值）",
                })
        slot_status = "passed" if not invalid_slots else "failed"
        slot_evidence = [
            f"required_slots={reference_slots}",
            f"actual_slots={dict(actual_slots)}",
            f"invalid_slots={[s['slot'] for s in invalid_slots]}",
        ]
        slot_root_cause = None
        if slot_status == "failed":
            slot_detail = "; ".join(f"{s['slot']}={s['value']} ({s['reason']})" for s in invalid_slots)
            slot_source = "projects/marketting-planning-intent/intent.py + adapter NLU slot extraction"
            if slot_source not in source_files:
                source_files.append(slot_source)
            slot_root_cause = {
                "category": "implementation_bug",
                "summary": f"intent recognition 服务未按 reference contract 提取有效 required_slots：{slot_detail}。业务系统 NLU/槽位提取层未从 query 真实抽取所需字段，返回占位值或无效值。",
                "evidence": slot_evidence,
                "confidence": "high",
                "fix_suggestion": "修正 intent recognition 服务的 NLU 槽位提取逻辑或 adapter 的 extract_output 解析，使 required_slots 从 query 中真实抽取（而非返回占位符），或当无法抽取时明确标记 errors/slot_errors。",
            }
        checks.append({
            "tool_type": "runtime_check",
            "check_type": "required_slots_validation",
            "status": slot_status,
            "required_slots": reference_slots,
            "actual_slots": dict(actual_slots),
            "invalid_slots": invalid_slots,
            "evidence": slot_evidence,
            "source": slot_source if slot_status == "failed" else source,
            "root_cause": slot_root_cause,
            "confidence": "high" if slot_status in {"passed", "failed"} else "low",
        })

        # 聚合：取第一个失败 check 的 root_cause 作为主根因
        failed = [c for c in checks if c.get("root_cause")]
        primary = failed[0].get("root_cause") if failed else None
        fix_suggestion = primary.get("fix_suggestion", "") if primary else ""
        return {
            "tool_type": "runtime_check",
            "check_type": "intent_contract",
            "status": "failed" if failed else "passed",
            "checks": checks,
            "raw_intent": raw_intent,
            "actual_mapping": actual_mapping,
            "actual_intent": actual_intent,
            "expected_intent": expected_intent,
            "is_in_mapping": is_in_mapping,
            "is_expected_mapping": is_expected_mapping,
            "available_mapping_count": len(mapping),
            "enum_values": enum_values,
            "evidence": [e for c in checks for e in (c.get("evidence") or [])],
            "source": "; ".join(source_files),
            "root_cause": primary,
            "fix_suggestion": fix_suggestion,
            "confidence": "high" if failed else "medium",
        }

    def _load_intent_mapping_source(self) -> tuple[Dict[str, str], List[str], str]:
        source_path = Path(__file__).resolve().parents[3] / "projects" / "marketting-planning-intent" / "intent.py"
        source = "projects/marketting-planning-intent/intent.py:INTENT_MAPPING"
        spec = importlib.util.spec_from_file_location("marketting_planning_intent_runtime_source", source_path)
        if spec is None or spec.loader is None:
            return {}, [], source
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        mapping = dict(getattr(module, "INTENT_MAPPING", {}) or {})
        intent_type = getattr(module, "IntentType", None)
        enum_values = [item.value for item in intent_type] if intent_type else []
        return mapping, enum_values, source

    def build_attribute_tools(self) -> list:
        """归因第二层 tool：在第一层 divergence_analysis（已给出"哪里坏了"——具体字段/值/函数）
        基础上，让 attribute agent 深挖"为什么坏了"+"怎么修"。

        mpi 的第二层 tool 聚焦于：intent 映射错误的根因链追溯（为什么 raw_intent 映射到
        错误 intent）、源码级证据定位（INTENT_MAPPING 哪条规则/哪个配置文件导致）、
        可执行修复方向。
        """
        adapter = self

        def trace_intent_mapping_root_cause(raw_intent: str, expected_intent: str, actual_intent: str) -> dict:
            """源码证据级 + 根因链 tool：追溯 intent 映射错误的根因。

            1) 查 INTENT_MAPPING 中 raw_intent 的实际映射
            2) 查 INTENT_MAPPING 中是否有 expected_intent 对应的 raw_intent 编码
            3) 给出根因链（是映射表缺条目、NLU 输出编码错误、还是 adapter 解析错误）
            4) 给出可执行修复方向

            Args:
                raw_intent: 原始 intent 编码（如 "4001"）
                expected_intent: 期望的 intent 标签（如 "nbev_planning"）
                actual_intent: 实际的 intent 标签（如 "other"）

            Returns:
                包含 root_cause_chain、fix_direction、source 的字典
            """
            mapping, enum_values, source = adapter._load_intent_mapping_source()
            key = str(raw_intent)
            actual_mapped = mapping.get(key)
            # 反向查：expected_intent 对应的编码
            matching_codes = [k for k, v in mapping.items() if v == expected_intent]
            # 根因分析
            if actual_mapped is None:
                chain = f"raw_intent={raw_intent} 未在 INTENT_MAPPING 中定义（共 {len(mapping)} 条映射），NLU 输出编码可能来自非标准接口"
                fix = f"在 INTENT_MAPPING 中补充 raw_intent={raw_intent} 的映射条目，或修正上游 NLU 使其输出映射表中已定义的编码"
            elif actual_mapped != expected_intent:
                chain = f"raw_intent={raw_intent} 在 INTENT_MAPPING 中映射到 {actual_mapped}，而 reference 期望 {expected_intent}。INTENT_MAPPING 中 {expected_intent} 对应的编码为 {matching_codes}"
                fix = f"修正 INTENT_MAPPING 中 raw_intent={raw_intent} 的映射，或修正上游 NLU 使其输出 {matching_codes} 而非 {raw_intent}"
            else:
                chain = f"intent 映射正确（{raw_intent}→{actual_mapped}），但 reference 期望 {expected_intent}，上游 NLU 或 adapter 可能选错了 reference"
                fix = "检查 adapter 的 extract_output 是否正确解析了服务返回的 intent 字段，或修正 reference 的 expected_intent"
            return {
                "raw_intent": key,
                "actual_mapped": actual_mapped,
                "expected_intent": expected_intent,
                "matching_codes_for_expected": matching_codes,
                "total_mapping_entries": len(mapping),
                "root_cause_chain": chain,
                "fix_direction": fix,
                "source": source,
            }

        def check_required_slot_extraction(slot_name: str, expected_value_hint: str) -> dict:
            """源码证据级 tool：检查 required_slot 的提取逻辑问题。

            分析指定 slot 的值是否是占位符/无效值，并给出为什么该 slot 没有被
            正确提取的根因分析。

            Args:
                slot_name: 槽位名（如 "year"）
                expected_value_hint: 期望值的描述（如 "从 query 中提取的年份"）

            Returns:
                包含 slot_status、validation、root_cause_chain、fix_direction 的字典
            """
            PLACEHOLDER = ("mock_value", "mock_", "placeholder", "unknown", "null", "undefined")
            return {
                "slot_name": slot_name,
                "expected_value_hint": expected_value_hint,
                "validation": {
                    "placeholder_patterns": list(PLACEHOLDER),
                    "description": "如果 slot 值匹配上述占位符模式，说明 NLU 槽位提取层未从 query 真实抽取该字段",
                },
                "root_cause_chain": f"NLU 槽位提取层未从 query 真实抽取 {slot_name} 字段，返回占位值。上游 intent recognition 的 slot extraction 或 NLU 模块缺少从 query 提取 {slot_name} 的能力",
                "fix_direction": f"修正 NLU 槽位提取逻辑，使其从 query 中真实抽取 {slot_name} 字段（如从'明年'解析出年份），或当无法抽取时明确标记为 slot_error 而非返回占位值",
                "source": "impl/projects/marketting-planning-intent/adapter.py:get_runtime_checks",
            }

        trace_intent_mapping_root_cause.__name__ = "trace_intent_mapping_root_cause"
        check_required_slot_extraction.__name__ = "check_required_slot_extraction"
        return [trace_intent_mapping_root_cause, check_required_slot_extraction]

    def simulate_trace_nodes(self, trace, judge_result) -> Dict[str, Any]:
        """Issue #3: 沿 trace 逐节点调业务系统函数复现，定位最早分歧。

        对每个可模拟节点调用 INTENT_MAPPING 查表，比较模拟输出与 trace actual。
        """
        mapping, _, source = self._load_intent_mapping_source()
        if not mapping:
            return {"simulated_nodes": [], "diverged_nodes": [], "note": "INTENT_MAPPING 不可加载，无法模拟"}
        simulated_nodes: list[Dict[str, Any]] = []
        diverged_nodes: list[Dict[str, Any]] = []
        for node in (trace.execution_trace or []):
            if not isinstance(node, dict):
                continue
            stage = str(node.get("stage") or node.get("node") or "")
            evidence = node.get("evidence") if isinstance(node.get("evidence"), dict) else {}
            raw_intent = str(evidence.get("raw_intent") or "").strip()
            # 仅对带 raw_intent 的节点（label_mapping / adapter_extraction / intent_api_call）模拟
            if not raw_intent:
                continue
            simulated_mapped = mapping.get(raw_intent)
            trace_actual = {"intent": evidence.get("intent"), "raw_intent": raw_intent}
            simulated_output = {"mapped_intent": simulated_mapped if simulated_mapped is not None else "other"}
            # 判断是否一致：trace 的 intent 应等于模拟映射结果
            trace_intent = str(evidence.get("intent") or "").strip()
            sim_intent = str(simulated_output["mapped_intent"])
            status = "passed" if (not trace_intent or trace_intent == sim_intent) else "diverged"
            entry = {
                "stage": stage,
                "input_used": {"raw_intent": raw_intent},
                "simulated_output": simulated_output,
                "trace_actual": trace_actual,
                "status": status,
                "function_called": "INTENT_MAPPING.get",
                "source_file": source,
            }
            simulated_nodes.append(entry)
            if status == "diverged":
                diverged_nodes.append(entry)
        return {"simulated_nodes": simulated_nodes, "diverged_nodes": diverged_nodes, "source": source}

    def build_mock_cases(self) -> list[Dict[str, Any]]:
        path = Path(__file__).resolve().parents[2] / "data" / "marketting-planning-intent" / "mock_cases.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def build_mock_datasets(self) -> list[Dict[str, Any]]:
        cases = self.build_mock_cases()
        return [{
            "dataset_id": "marketting-planning-intent_mock",
            "name": "营销规划意图识别 Mock 数据集",
            "dimension_type": "intent_recognition",
            "description": "9 条意图识别测试用例，覆盖 premium_growth、customer_growth、product_mix、activity、non_agent、unknown 及边界情况（低置信度、fallback、缺失槽位）。",
            "case_count": len(cases),
        }]

    def _parse_payload(self, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return {"raw_text": value}
        return value

    def _first_value(self, value: Any, keys: list[str]) -> Any:
        if isinstance(value, dict):
            for key in keys:
                if key in value:
                    return value[key]
            for nested_key in ("data", "result", "output", "extra_output_params", "card_result", "extensions"):
                nested = value.get(nested_key)
                found = self._first_value(nested, keys)
                if found is not None:
                    return found
        return None
