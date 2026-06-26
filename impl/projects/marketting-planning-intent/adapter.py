from __future__ import annotations

import importlib.util
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from impl.core.adapter import ProjectAdapter


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


class Adapter(ProjectAdapter):
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
        blocking_wrong = [item for item in wrong if isinstance(item, dict) and item.get("requirement") in {"intent", "allow_fallback", "min_confidence"}]
        gate_failed = bool(missing or blocking_wrong)
        if gate_failed:
            evidence_summary = {
                "missing": [item.get("requirement") for item in missing if isinstance(item, dict)],
                "blocking_wrong": [item.get("requirement") for item in blocking_wrong if isinstance(item, dict)],
            }
            evidence_str = f"missing={evidence_summary.get('missing')}; blocking_wrong={evidence_summary.get('blocking_wrong')}"
            judge_result.fulfillment_assessments.append({
                "expectation_id": "intent_contract",
                "status": "not_fulfilled",
                "blocking": True,
                "evidence": evidence_str,
                "downstream_impact": self._intent_contract_reasoning_summary(trace, reference, output, missing, wrong, "incorrect"),
            })
            if "intent_contract_gate_failed" not in judge_result.quality_flags:
                judge_result.quality_flags.append("intent_contract_gate_failed")
            judge_result.primary_assessment = {"status": "failed", "missing": missing, "wrong": wrong}
            judge_result.verdict_derivation = {**(judge_result.verdict_derivation or {}), "contract_gate": "failed"}
            judge_result.reasoning_summary = self._intent_contract_reasoning_summary(trace, reference, output, missing, wrong, "incorrect")
            self.register_judge_override(judge_result, "fulfillment_assessments", [], ["intent_contract: not_fulfilled"], "contract_gate_failed", "normalize_judge_result")
            return judge_result
        if "intent_contract_gate_passed" not in judge_result.quality_flags:
            judge_result.quality_flags.append("intent_contract_gate_passed")
        judge_result.fulfillment_assessments.append({
            "expectation_id": "intent_contract",
            "status": "fulfilled",
            "blocking": True,
            "evidence": f"intent={actual_intent}; confidence={confidence}; min_confidence={min_confidence}",
            "downstream_impact": self._intent_contract_reasoning_summary(trace, reference, output, [], [], "correct"),
        })
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
        first_failed = next((node for node in trace.execution_trace or [] if isinstance(node, dict) and node.get("status") in {"failed", "suspicious"}), {})
        expected = judge_result.expected or trace.project_fields.get("reference") or {}
        actual = judge_result.actual or trace.extracted_output or {}
        stage = first_failed.get("stage") or "intent_contract_gate"
        existing_incomplete = str(attribute_result.incomplete_reason or "")
        missing_quality = list((attribute_result.analysis_quality or {}).get("missing") or []) if isinstance(attribute_result.analysis_quality, dict) else []
        quality_passed = not existing_incomplete
        quality_missing = missing_quality if existing_incomplete else []
        if existing_incomplete and "intent_recognition_internal_evidence" not in quality_missing:
            quality_missing.append("intent_recognition_internal_evidence")
        attribute_result.failure_category = "intent_recognition"
        attribute_result.failure_stage = stage
        attribute_result.analysis_method = "current_case_intent_contract_trace"
        attribute_result.evidence_chain = [
            {"query": trace.input.get("query") or trace.input.get("user_text")},
            {"expected": expected},
            {"actual": actual},
            {"missing": judge_result.missing, "wrong": judge_result.wrong},
        ]
        attribute_result.trace_analysis = list(trace.execution_trace or [])
        attribute_result.chain_nodes = list(trace.execution_trace or [])
        attribute_result.earliest_divergence = {"node": stage, "expected": expected, "actual": actual, "evidence": [first_failed.get("evidence") or judge_result.missing or judge_result.wrong], "confidence": "medium"}
        attribute_result.evidence_coverage = {"query": bool(trace.input), "actual": bool(actual), "expected": bool(expected), "execution_trace": bool(trace.execution_trace), "unsupported_claims": []}
        attribute_result.analysis_quality = {"passed": quality_passed, "status": "supported_root_cause" if quality_passed else "next_verification_step", "missing": quality_missing}
        attribute_result.incomplete_reason = existing_incomplete
        attribute_result.root_cause_hypothesis = f"当前 case 期望 intent/slots 为 {expected}，实际 normalized intent evidence 为 {actual}，最早差异位于 {stage}。"
        attribute_result.verification_steps = ["复查当前 query、reference 与 normalized intent evidence 是否一致。"]
        attribute_result.patch_direction = ["优先修正 intent-recognition 请求构造、响应解析或 label/slot 映射源头，不只改展示结果。"]
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
        actual_mapping = mapping.get(str(raw_intent)) if raw_intent is not None else actual_intent
        if actual_mapping is None:
            actual_mapping = actual_intent or "other"
        is_in_mapping = str(raw_intent) in mapping if raw_intent is not None else False
        is_expected_mapping = bool(expected_intent) and actual_mapping == expected_intent
        status = "passed" if (not expected_intent or is_expected_mapping) else "failed"
        evidence = [
            f"raw_intent={raw_intent}",
            f"actual_mapping={actual_mapping}",
            f"actual_intent={actual_intent}",
            f"expected_intent={expected_intent}",
            f"mapping_source={source}",
        ]
        root_cause = None
        fix_suggestion = ""
        if status == "failed":
            root_cause = {
                "category": "implementation_bug",
                "summary": f"运行时 raw_intent={raw_intent} 经项目映射得到 {actual_mapping}，但当前 reference contract 期望 {expected_intent}。",
                "evidence": evidence,
                "confidence": "high",
                "fix_suggestion": f"在项目意图映射源头校准 raw_intent={raw_intent} 的映射，或修正上游意图识别使其输出与 reference contract 一致的编码。",
            }
            fix_suggestion = root_cause["fix_suggestion"]
        return {
            "tool_type": "runtime_check",
            "check_type": "intent_mapping",
            "status": status,
            "raw_intent": raw_intent,
            "actual_mapping": actual_mapping,
            "actual_intent": actual_intent,
            "expected_intent": expected_intent,
            "is_in_mapping": is_in_mapping,
            "is_expected_mapping": is_expected_mapping,
            "available_mapping_count": len(mapping),
            "enum_values": enum_values,
            "evidence": evidence,
            "source": source,
            "root_cause": root_cause,
            "fix_suggestion": fix_suggestion,
            "confidence": "high" if status in {"passed", "failed"} else "low",
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
