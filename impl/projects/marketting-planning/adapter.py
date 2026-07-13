from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from impl.core.adapter import ProjectAdapter
from impl.core.adapter_v2 import LegacyProjectAdapter
from impl.core.schema import ExecutionTraceEvent, LiveExecutionResult, LiveMultiTurnState, LiveRequest, MultiTurnCase, SingleTurnCase, TraceExecutionContext
from .judge import application_boundary_from_trace, build_judge_context, build_intent_frame, default_business_expectation, default_consumer_contract, default_fulfillment_assessment, normalize_judge_result_for_project
from .attribute import build_attribute_context, get_runtime_checks, attribution_probes, apply_attribution_probes, normalize_attribute_result_for_project


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


class Adapter(LegacyProjectAdapter):
    stages = {"intent", "clarification", "planning", "non_agent", "fallback", "unknown"}

    def _load_live(self):
        import importlib.util
        from pathlib import Path
        path = Path(self.spec.root) / "live.py"
        module_spec = importlib.util.spec_from_file_location(f"impl_project_{self.spec.project_id}_live", path)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        return module.MarketingPlanningLive(self.spec, self)

    def _load_judge(self):
        import importlib.util
        from pathlib import Path
        path = Path(self.spec.root) / "judge.py"
        module_spec = importlib.util.spec_from_file_location(f"impl_project_{self.spec.project_id}_judge", path)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        return module.MarketingPlanningJudge(self.spec, self)

    def _load_attribute(self):
        import importlib.util
        from pathlib import Path
        path = Path(self.spec.root) / "attribute.py"
        module_spec = importlib.util.spec_from_file_location(f"impl_project_{self.spec.project_id}_attribute", path)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        return module.MarketingPlanningAttribute(self.spec, self)

    def build_request(self, case: SingleTurnCase | MultiTurnCase) -> LiveRequest:
        input_data = dict(case.input or {})
        turns = self._normalize_turns(input_data.get("turns"))
        query = self._extract_query(input_data, turns)
        if not turns and query:
            turns = [{"role": "user", "content": str(query)}]
        elif turns and not query:
            query = self._last_user_content(turns)
        case_id = str(case.id or input_data.get("case_id") or input_data.get("id") or f"marketing-case-{int(time.time() * 1000)}")
        shared_session = self._bool(input_data.get("shared_session"))
        declared_session = input_data.get("session_id")
        session_id = str(declared_session) if shared_session and declared_session else f"eval-{case_id}"
        scenario = str(input_data.get("scenario") or case.scenario or self._infer_scenario(input_data, turns))
        boundary = self._normalize_boundary(input_data.get("boundary") or {})
        case_reference = case.reference if isinstance(case.reference, dict) else {}
        reference = self._normalize_reference(input_data.get("reference") or case_reference or {}, input_data, scenario)
        first_user_turn = next((turn.get("content") for turn in turns if turn.get("role") == "user" and turn.get("content")), "")
        current_turn = self._current_turn(turns, query)
        normalized_request = {
            "case_id": case_id,
            "session_id": session_id,
            "shared_session": shared_session,
            "user_intent": str(input_data.get("user_intent") or query or first_user_turn or scenario),
            "query": str(query or current_turn.get("content") or ""),
            "turns": turns,
            "current_turn": current_turn,
            "scenario": scenario,
            "expected_stage": input_data.get("expected_stage") or reference.get("expected_stage"),
            "expected_path_types": self._list(input_data.get("expected_path_types") or reference.get("required_path_types")),
            "expected_cards": self._list(input_data.get("expected_cards") or reference.get("required_cards")),
            "metadata": dict(input_data.get("metadata") or {}),
            "boundary": boundary,
            "reference": reference,
        }
        return LiveRequest(
            project_id=self.spec.project_id,
            raw_input=input_data,
            case_id=case_id,
            turns=turns,
            normalized_request=normalized_request,
            # execution_mode 由 pipeline.live_run 在 provided/live 分支统一覆盖，
            # 项目层不参与 ready 判定，build_request 只管构造 normalized_request。
            execution_mode="live_service",
            session_id=session_id,
        )

    def trace_state_graph(self) -> Dict[str, Any]:
        graph = self.extend_default_trace_graph("collect_evidence", ["marketing_planning_boundary_evidence"])
        graph["limits"] = {**(graph.get("limits") or {}), "max_steps": 28, "max_retries_per_state": 1}
        return graph

    def trace_state_graph(self) -> Dict[str, Any]:
        graph = self.extend_default_trace_graph("collect_evidence", ["marketing_planning_boundary_evidence"])
        graph["limits"] = {**(graph.get("limits") or {}), "max_steps": 28, "max_retries_per_state": 1}
        return graph

    def state_executors(self) -> Dict[str, Any]:
        return {"marketing_planning_boundary_evidence": self._marketing_planning_boundary_evidence}

    def _marketing_planning_boundary_evidence(self, context: TraceExecutionContext) -> Dict[str, Any]:
        trace = context.get("trace")
        if not trace:
            return {"status": "failed", "missing_evidence": ["trace"]}
        scenario = trace.scenario or (trace.normalized_request or {}).get("scenario") or ""
        application_boundary = application_boundary_from_trace(trace)
        evidence = {
            "scenario": scenario,
            "session_id": trace.session_id,
            "shared_session": bool((trace.normalized_request or {}).get("shared_session")),
            "application_boundary": application_boundary,
            "expected_stage": trace.reference_contract.get("expected_stage"),
            "expected_path_types": self._list(trace.reference_contract.get("required_path_types")),
            "external_repo_mutation": "not_performed_by_adapter",
        }
        return {
            "status": "succeeded",
            "outputs": evidence,
            "evidence_refs": [{"type": "marketing_planning_boundary", "evidence": evidence}],
            "claims": [{"marketing_planning_boundary": evidence}],
        }

    def collect_state_evidence(self, state_id: str, context: TraceExecutionContext) -> list[Dict[str, Any]]:
        trace = context.get("trace")
        if not trace:
            return []
        scenario = trace.scenario or (trace.normalized_request or {}).get("scenario") or ""
        return [{"type": "marketing_planning_state_boundary", "state_id": state_id, "application_boundary": application_boundary_from_trace(trace), "scenario": scenario, "shared_service_boundary": "local configured service only"}]

    def attribution_probes(self, trace, judge_result):
        target_probe = self._target_value_unit_probe(trace, judge_result)
        return [target_probe] if target_probe else []

    def normalize_attribute_result(self, trace, judge_result, attribute_result):
        overall = judge_result.overall_fulfillment or {}
        if overall.get("status") == "fulfilled":
            if not attribute_result.expectation_attributions:
                expectation_id = "marketting-planning:planning_output_contract"
                if judge_result.business_expectations:
                    first = judge_result.business_expectations[0]
                    expectation_id = first.get("expectation_id", expectation_id) if isinstance(first, dict) else getattr(first, "expectation_id", expectation_id)
                evidence = list(judge_result.evidence or ["planning output contract fulfilled"])
                attribute_result.expectation_attributions = [{"expectation_id": expectation_id, "fulfillment_status": "fulfilled", "suspected_locations": [], "root_cause_hypothesis": "当前 planning 输出满足业务预期，归因结论为 no_issue。", "evidence": evidence}]
            attribute_result.suspected_locations = []
            attribute_result.root_cause_hypothesis = "当前 planning 输出满足业务预期，归因结论为 no_issue。"
            return attribute_result
        target_probe = self._target_value_unit_probe(trace, judge_result)
        if target_probe:
            attribute_result.suspected_locations = [{
                "location": "request_normalization",
                "evidence": list(target_probe.get("evidence") or []),
                "findings": target_probe,
            }]
            attribute_result.evidence = list(target_probe.get("evidence") or [])
            attribute_result.evidence_strength = "strong"
            attribute_result.root_cause_hypothesis = f"当前 query 含目标值 {target_probe.get('source_amount')}，按项目内部单位应为 {target_probe.get('expected_target_nbev_wan')} 万，实际链路使用 {target_probe.get('actual_target_nbev_wan')} 万，最早差异位于请求归一化/目标值单位转换。"
            return attribute_result
        return attribute_result

    def _target_value_unit_probe(self, trace, judge_result) -> Dict[str, Any]:
        evidence_text = self._target_value_error_evidence(judge_result)
        if not evidence_text:
            return {}
        trace_input = trace.input or {}
        normalized_request = trace.normalized_request or {}
        turns = normalized_request.get("turns") if isinstance(normalized_request.get("turns"), list) else []
        query = str(
            normalized_request.get("query")
            or (turns[-1].get("content") if turns and isinstance(turns[-1], dict) else "")
            or normalized_request.get("user_intent")
            or trace_input.get("query")
            or ""
        )
        amount_match = re.search(r"(\d+(?:\.\d+)?)\s*亿", query)
        if not amount_match:
            return {}
        expected = int(float(amount_match.group(1)) * 10000)
        actual = self._find_target_nbev_wan(judge_result.actual)
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
        evidence_text = json.dumps(to_dict([judge_result.expected, judge_result.wrong, judge_result.actual, judge_result.fulfillment_assessments]), ensure_ascii=False)
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
            "schema_protocol_extensions": trace.project_fields,
            "scenarios": self.spec.frontend_extensions.get("scenarios") or [],
            "stages": self.spec.frontend_extensions.get("stages") or [],
            "path_types": self.spec.frontend_extensions.get("path_types") or [],
            "output_summary_shape": ["stage", "event_summary", "card_summary", "session_summary", "fallback", "errors"],
        }

    # build_mock_cases / build_mock_datasets 已移除：
    # pipeline.mock_cases / mock_datasets 全线走 mock_agent（LLM 生成），不再读 seed JSON。
    # 详见 impl/core/mock_agent.py 与 impl/core/pipeline.py。

    def build_interactive_turn(self, case: Dict[str, Any], previous_turns: List[Dict[str, Any]]) -> Dict[str, Any]:
        # 优先委托 mock_agent.next_turn（LLM 扮演用户），不可用时回退硬编码规则。
        mock_agent_turn = self._mock_agent_next_turn(case, previous_turns)
        if mock_agent_turn is not None:
            return mock_agent_turn
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

    def _mock_agent_next_turn(self, case: Dict[str, Any], previous_turns: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        # 懒加载 MockAgent：无 live_schema 或 LLM 不可用时返回 None，回退硬编码。
        try:
            from impl.core.mock_agent import MockAgent, load_live_schema
            if load_live_schema(self.spec.project_id) is None:
                return None
            if not getattr(self, "_mock_agent_instance", None):
                self._mock_agent_instance = MockAgent(self.spec)
            live_feedback = {}
            if previous_turns:
                last = previous_turns[-1] if isinstance(previous_turns[-1], dict) else {}
                live_feedback = {"missing_fields": self._list(last.get("missing_fields")), "stage": last.get("stage")}
            return self._mock_agent_instance.next_turn(case, previous_turns, live_feedback)
        except Exception:
            return None

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
        session_id = f"interactive-{case.case_id}"
        start = time.time()
        raw_responses: List[Any] = []

        for _ in range(max_turns):
            next_turn = self.build_interactive_turn(source_case, turn_traces)
            transcript.append({"role": "user", "content": str(next_turn.get("query") or "")})
            request_input = {
                "case_id": case.case_id,
                "session_id": session_id,
                "shared_session": True,
                "query": next_turn.get("query"),
                "turns": transcript,
                "scenario": source_case.get("scenario") or "interactive_intent",
                "reference": source_case.get("reference") or {},
            }
            request = self.build_request(SingleTurnCase(id=case.case_id, input=request_input))
            from impl.core.live import load_project_live
            project_live = load_project_live(self.spec, self)
            if len(turn_traces) < len(turn_outputs):
                raw = project_live.deliver_provided(SingleTurnCase(id=case.case_id, input={"output": turn_outputs[len(turn_traces)]}), request)
            else:
                candidate = project_live.deliver_real(request)
                raw = candidate.raw_response if isinstance(candidate, LiveExecutionResult) else candidate
            raw_responses.append(raw)
            extracted_result = project_live.extract_output(raw, request)
            turns = extracted_result.get("turns") if isinstance(extracted_result, dict) else None
            extracted = turns[-1] if isinstance(turns, list) and turns and isinstance(turns[-1], dict) else extracted_result
            turn_trace = self._interactive_turn_trace(len(turn_traces) + 1, next_turn, extracted, turn_expectations)
            turn_traces.append(turn_trace)
            transcript.append({"role": "assistant", "content": self._interactive_assistant_content(extracted), "stage": extracted.get("stage") or "unknown", "extracted_summary": turn_trace.get("error_summary") or turn_trace.get("judge_verdict") or ""})
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
        final_output = {
            "stage": final_stage,
            "conversation_summary": conversation_summary,
            "turn_results": turn_traces,
            "final_turn": turn_traces[-1] if turn_traces else {},
        }
        live_result = LiveExecutionResult(
            project_id=self.spec.project_id,
            case_id=case.case_id,
            session_id=session_id,
            raw_input=source_case,
            normalized_request={"case_id": case.case_id, "interaction_mode": "interactive_intent", "max_turns": max_turns, "policy": policy, "user_intent": source_case.get("user_intent") or source_case.get("input", {}).get("user_intent") or {}},
            call_status="succeeded",
            raw_response={"turn_responses": raw_responses},
            runtime_ms=int((time.time() - start) * 1000),
            extracted_output=final_output,
            output_source="interactive_adapter",
            execution_trace=[
                ExecutionTraceEvent(stage="interactive_turn", status=turn.get("judge_verdict"), evidence={"turn_index": turn.get("turn_index"), "stage": turn.get("stage"), "missing_fields": turn.get("missing_fields")})
                for turn in turn_traces
            ],
            project_fields={},
            interaction_mode="interactive_intent",
            multi_turn_state=LiveMultiTurnState(session_id=session_id, turn_index=len(turn_traces), transcript=transcript, accumulated_fields=final_output, missing_fields=self._list((turn_traces[-1] if turn_traces else {}).get("missing_fields")), stop_reason=stop_reason),
        )
        trace = self.to_run_trace(live_result)
        trace.trace_id = f"interactive-{case.case_id}"
        trace.execution_mode = "interactive_intent"
        trace.output_source = "interactive_adapter"
        trace.status = "ok" if final_verdict == "correct" else "error"
        trace.stop_reason = stop_reason
        trace.conversation_summary = conversation_summary
        trace.multi_turn_input = {"user_intent": source_case.get("user_intent") or source_case.get("input", {}).get("user_intent") or {}, "policy": policy, "conversation_summary": conversation_summary}
        judge = {
            "trace_id": trace.trace_id,
            "project_id": self.spec.project_id,
            "reasoning_summary": f"interactive_intent final_stage={final_stage}, stop_reason={stop_reason}",
        }
        attribute = {
            "trace_id": trace.trace_id,
            "project_id": self.spec.project_id,
            "case_id": case.case_id,
            "root_cause_hypothesis": "" if final_verdict == "correct" else "系统回复未满足当前 interactive_intent 的 turn_expectations 或未在 max_turns 内完成。",
        }
        return {"case_id": case.case_id, "execution_mode": "interactive_intent", "output_source": live_result.output_source, "trace": trace, "judge": judge, "attribute": attribute}

    def _interactive_assistant_content(self, output: Dict[str, Any]) -> str:
        stage = output.get("stage") or "unknown"
        missing_fields = self._list((output.get("session_summary") or {}).get("missing_fields"))
        cards = [card.get("path_type") for card in output.get("card_summary") or [] if card.get("path_type")]
        parts = [f"stage={stage}"]
        if missing_fields:
            parts.append("missing=" + ",".join(str(item) for item in missing_fields))
        if cards:
            parts.append("cards=" + ",".join(str(item) for item in cards))
        return " · ".join(parts)

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

    # build_mock_datasets 已移除：pipeline.mock_datasets 全线走 mock_agent。

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

    def _extract_query(self, input_data: Dict[str, Any], turns: List[Dict[str, Any]]) -> str:
        for value in (
            input_data.get("query"),
            self._last_user_content(turns),
        ):
            if isinstance(value, dict):
                value = value.get("content") or value.get("query") or value.get("text")
            if value is not None and str(value).strip():
                return str(value)
        return ""

    def _last_user_content(self, turns: List[Dict[str, Any]]) -> str:
        for turn in reversed(turns):
            if turn.get("role") == "user" and turn.get("content"):
                return str(turn.get("content"))
        return ""

    def _current_turn(self, turns: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
        if turns:
            for turn in reversed(turns):
                if turn.get("role") == "user" and turn.get("content"):
                    return turn
            return turns[-1]
        return {"role": "user", "content": str(query)} if query else {}

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

    def _bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None or value == "":
            return False
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y", "on"}:
                return True
            if normalized in {"false", "0", "no", "n", "off"}:
                return False
        return False

    def _list(self, value: Any) -> List[Any]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return value
        return [value]

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
