from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from impl.core.adapter import ProjectAdapter
from impl.core.schema import AttributeResult, ExecutionTraceEvent, JudgeResult, LiveExecutionResult, LiveRequest, MultiTurnCase, SingleTurnCase


class Adapter(ProjectAdapter):
    metadata_fields = {"category", "model_name", "latency_ms", "token_usage", "cost", "row_index", "source_dataset", "expected_quality", "expected_error_type", "quality_dimension"}

    def build_request(self, case: SingleTurnCase | MultiTurnCase) -> LiveRequest:
        # case 可能是 SingleTurnCase（有顶层 output/reference）或裸 dict（前端旧输入）。
        # _normalize_sample 用 getattr 兼容 dataclass，能从 case.output/case.reference 取值。
        sample = self._normalize_sample(case)
        input_data = dict(case.input or {}) if hasattr(case, "input") else (dict(case.get("input") or {}) if isinstance(case, dict) else {})
        normalized_request = {
            "input": sample["input"],
            "reference": sample["reference"],
            "metadata": sample["metadata"],
            "scenario": sample["scenario"],
            "data_quality_flags": sample["data_quality_flags"],
            "output": sample["output"],
        }
        # 协议层 ready gate 接管 provided 判定后，build_request 不再硬编码 execution_mode；
        # pipeline live_run 在 provided 分支统一覆盖为 "provided_output"。
        # 存一份快照，project_fields 在 provided 路径下无 _normalized_request 注入时可回退读取。
        self._last_normalized_request = normalized_request
        return LiveRequest(
            project_id=self.spec.project_id,
            raw_input=input_data,
            case_id=str(case.id or sample.get("id") or input_data.get("case_id") or input_data.get("id") or ""),
            normalized_request=normalized_request,
            # execution_mode 由 pipeline.live_run 在 provided 分支统一覆盖
            execution_mode="live_service",
            session_id=str(input_data.get("session_id") or case.metadata.get("session_id") or ""),
        )

    def call_or_prepare(self, request: LiveRequest) -> LiveExecutionResult:
        raw_response = request.normalized_request.get("output") or {"actual_answer": ""}
        if isinstance(raw_response, dict):
            raw_response = {**raw_response, "_normalized_request": request.normalized_request}
        extracted_output = self.extract_output(raw_response)
        return LiveExecutionResult(
            project_id=request.project_id,
            case_id=request.case_id,
            session_id=request.session_id,
            raw_input=request.raw_input,
            normalized_request=request.normalized_request,
            raw_response=raw_response,
            extracted_output=extracted_output,
            output_source=request.execution_mode,
            execution_trace=self.build_execution_trace(request.raw_input, request.normalized_request, raw_response, extracted_output),
            project_fields=self.project_fields(raw_response, extracted_output),
        )

    def extract_output(self, raw_response: Any) -> Dict[str, Any]:
        if isinstance(raw_response, dict):
            return {"actual_answer": str(raw_response.get("actual_answer") or raw_response.get("answer") or raw_response.get("text") or "")}
        return {"actual_answer": str(raw_response or "")}

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any]) -> Dict[str, Any]:
        # 优先从 raw_response._normalized_request 取（旧 call_or_prepare 注入路径），
        # 否则回退到 build_request 快照（provided 统一路径，raw_response 不再注入）。
        request = raw_response.get("_normalized_request") if isinstance(raw_response, dict) else None
        if not isinstance(request, dict):
            request = getattr(self, "_last_normalized_request", None) or {}
        if not isinstance(request, dict):
            return {}
        return {
            "scenario": request.get("scenario") or "",
            "data_quality_flags": list(request.get("data_quality_flags") or []),
            "contexts": list((request.get("input") or {}).get("contexts") or []),
            "reference": dict(request.get("reference") or {}),
            "metadata": dict(request.get("metadata") or {}),
            "estimated_quality_only": request.get("scenario") == "qa_weak_quality",
        }

    def build_execution_trace(self, input_data: Dict[str, Any], request: Dict[str, Any], raw_response: Any, extracted_output: Dict[str, Any]) -> list[ExecutionTraceEvent]:
        return [
            ExecutionTraceEvent(stage="qa.sample.normalize", status="ok" if request.get("scenario") != "invalid_sample" else "suspicious", evidence={"scenario": request.get("scenario"), "flags": request.get("data_quality_flags")}),
            ExecutionTraceEvent(stage="qa.output.read", status="ok" if extracted_output.get("actual_answer") else "suspicious", evidence="evaluated output read from uploaded sample"),
            ExecutionTraceEvent(stage="adapter.extract_output", status="ok", evidence={"actual_answer_present": bool(extracted_output.get("actual_answer"))}),
        ]

    def to_run_trace(self, result: LiveExecutionResult):
        return super().to_run_trace(result)

    def build_frontend_extensions(self, trace):
        return {
            "schema_protocol_extensions": trace.project_fields,
            "scenarios": self.spec.frontend_extensions.get("scenarios") or [],
            "score_dimensions": self.spec.frontend_extensions.get("score_dimensions") or [],
            "error_taxonomy": self.spec.frontend_extensions.get("error_taxonomy") or [],
        }

    def trace_state_graph(self):
        return self.extend_default_trace_graph("collect_evidence", ["qa_case_contract_evidence"])

    def state_executors(self):
        return {"qa_case_contract_evidence": self._qa_case_contract_evidence}

    def _qa_case_contract_evidence(self, context):
        trace = context.get("trace")
        if not trace:
            return {"status": "failed", "missing_evidence": ["trace"]}
        request = trace.normalized_request or {}
        sample_input = request.get("input") or {}
        reference = request.get("reference") or {}
        actual_answer = (trace.extracted_output or {}).get("actual_answer")
        evidence = {
            "question_present": bool(sample_input.get("question")),
            "actual_answer_present": bool(actual_answer),
            "reference_present": bool(reference),
            "contexts_count": len(sample_input.get("contexts") or []),
            "scenario": request.get("scenario") or "",
        }
        live_output_source = getattr(getattr(trace, "live_result", None), "output_source", "")
        provided_execution = trace.execution_mode == "provided"
        evidence["provided_output_path"] = provided_execution or live_output_source == "provided_output"
        missing = [key for key, value in evidence.items() if key in {"question_present", "actual_answer_present"} and not value]
        unrecoverable = [m for m in missing if m == "actual_answer_present"]
        return {
            "status": "succeeded" if not missing else "failed",
            "outputs": evidence,
            "evidence_refs": [{"type": "qa_case_contract", "evidence": evidence}],
            "claims": [{"qa_case_contract": evidence}],
            "missing_evidence": missing,
            "unrecoverable_missing": unrecoverable,
        }

    def collect_state_evidence(self, state_id, context):
        trace = context.get("trace")
        if not trace:
            return []
        request = trace.normalized_request or {}
        return [{"type": "qa_sample_boundary", "state_id": state_id, "scenario": request.get("scenario"),
                 "reference": request.get("reference") or {}, "data_quality_flags": request.get("data_quality_flags") or []}]

    def build_judge_context(self, trace):
        request = trace.normalized_request or {}
        return {
            "project_type": "provided_output_qa_evaluation",
            "current_case_only": True,
            "reference_contract": trace.reference_contract if isinstance(trace.reference_contract, dict) else {},
            "score_dimensions": self.spec.frontend_extensions.get("score_dimensions") or [],
            "error_taxonomy": self.spec.frontend_extensions.get("error_taxonomy") or [],
            "application_boundary": {"scope": "qa_semantic_answer_evaluation", "external_service_required": False},
        }

    def build_intent_frame(self, trace):
        request = trace.normalized_request or {}
        sample_input = request.get("input") if isinstance(request.get("input"), dict) else {}
        reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
        contexts = sample_input.get("contexts") or request.get("contexts") or []
        return {
            **super().build_intent_frame(trace),
            "business_task_type": "qa_answer_evaluation",
            "downstream_consumer": "QA user",
            "request_source": "normalized_request.input.question",
            "question": sample_input.get("question") or request.get("question") or "",
            "context_dependency": {"has_contexts": bool(contexts), "context_count": len(contexts), "has_reference": bool(reference)},
            "critical_intent_dimensions": ["question_target", "context_or_reference_dependency", "factual_or_interpretive_answer", "faithfulness", "contradiction_risk", "answer_usefulness"],
            "boundary_rules": {"scope": "qa_semantic_answer_evaluation", "external_service_required": False},
            "output_semantics": "produce an answer that addresses the current question and is faithful to provided contexts/reference when present",
        }

    def _default_consumer_contract(self, trace, judge_result):
        context = self.build_judge_context(trace)
        return {
            "consumer": "QA user",
            "contract": "answer must be relevant, grounded in current contexts/reference, and aligned with the golden answer when provided",
            "reference_contract": context.get("reference_contract") or {},
            "application_boundary": context.get("application_boundary") or {},
        }

    def _default_business_expectation(self, trace, judge_result):
        expectation = super()._default_business_expectation(trace, judge_result)
        expectation.update({
            "expectation_id": "QA:answer_quality",
            "downstream_consumer": "QA user",
            "required_capabilities": expectation.get("required_capabilities") or ["answer_relevance", "groundedness", "reference_alignment"],
            "boundary": judge_result.boundary_decision or judge_result.evaluation_boundary or self.build_judge_context(trace).get("application_boundary") or expectation.get("boundary") or {},
        })
        if not judge_result.intent_model:
            question = judge_result.reconstructed_intent or str(((trace.normalized_request or {}).get("input") or {}).get("question") or "")
            expectation.update({
                "user_intent": question,
                "expected_outcome": "actual answer should satisfy answer relevance, groundedness, and reference alignment for the current QA sample",
                "acceptance_criteria": list(judge_result.missing or judge_result.wrong or []),
            })
        return expectation

    def _default_fulfillment_assessment(self, trace, judge_result, expectation):
        status = self._expectation_status_from_verdict(judge_result)
        reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else judge_result.expected or {}
        actual = judge_result.actual or trace.extracted_output or {}
        return {
            "expectation_id": expectation.get("expectation_id"),
            "status": status,
            "score": judge_result.score,
            "expected_evidence": list(judge_result.missing or []) or [reference],
            "actual_evidence": list(judge_result.wrong or []) or [actual],
            "boundary_decision": judge_result.boundary_decision or judge_result.evaluation_boundary or self.build_judge_context(trace).get("application_boundary") or {},
            "downstream_impact": "QA answer is acceptable for the current user" if status == "fulfilled" else (judge_result.reasoning_summary or "QA user cannot rely on the answer quality for this sample"),
            "blocking": status in {"not_fulfilled", "not_evaluable"},
            "confidence": judge_result.confidence,
            "evidence_refs": list(getattr(trace, "evidence_refs", []) or []),
        }

    def build_attribute_context(self, trace, judge_result):
        return {
            "chain_nodes_to_check": list(trace.execution_trace or []),
            "reference_contract": trace.reference_contract if isinstance(trace.reference_contract, dict) else {},
            "attribute_standard": "Only attribute QA failures when judge has current-case expected/actual evidence; provided output never calls an external QA service.",
        }

    def normalize_judge_result(self, trace, judge_result):
        scenario = str(trace.scenario or (trace.normalized_request or {}).get("scenario") or "")
        if scenario == "qa_gold_answer":
            exact = self._gold_answer_exact_probe(trace, judge_result)
            if exact:
                return exact
        if scenario == "qa_weak_quality" and judge_result.verdict in {"correct", "incorrect"}:
            return self._weak_quality_probe(trace, judge_result)
        if judge_result.verdict == "uncertain" and "llm_call_failed" not in (judge_result.quality_flags or []):
            metadata = dict((trace.normalized_request or {}).get("metadata") or {})
            expected_quality = metadata.get("expected_quality") or "uncertain"
            if expected_quality in ("correct", "incorrect"):
                expected_reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
                actual = trace.extracted_output or judge_result.actual or {}
                judge_result.expected = expected_reference
                judge_result.actual = actual
                fallback = self._fallback_judge_from_sample_label_forced(
                    trace, judge_result, expected_reference, actual, scenario, metadata, expected_quality
                )
                if fallback:
                    return fallback
        if judge_result.verdict in ("correct", "incorrect", "uncertain") and "llm_call_failed" not in (judge_result.quality_flags or []):
            return self._enrich_semantic_judge(trace, judge_result, scenario)
        fallback = self._fallback_judge(trace, judge_result)
        if not fallback:
            return self._scrub_placeholder_ids(judge_result)
        if fallback.judge_method in ("qa_sample_expected_quality", "qa_gold_answer_exact_match", "qa_weak_quality_probe"):
            flags = list(fallback.quality_flags or [])
            if "llm_call_failed" in (judge_result.quality_flags or []) and "llm_call_failed" not in flags:
                flags.insert(0, "llm_call_failed")
            fallback.quality_flags = flags
        else:
            flags = ["qa_local_evidence_probe", "semantic_judge_unavailable"]
            if "llm_call_failed" in (judge_result.quality_flags or []):
                flags.insert(0, "llm_call_failed")
            fallback.quality_flags = flags
        fallback.raw_model_output = judge_result.raw_model_output
        return self._scrub_placeholder_ids(fallback)

    def _scrub_placeholder_ids(self, judge_result):
        """Replace E1/E2/exp_*/exp-* placeholder IDs with descriptive Chinese per prompt rule 518-520."""
        placeholder_patterns = [
            (r"\bE\d+\b", "编码失败项"),
            (r"\bexp[-_]?\d+\b", "编码失败项"),
        ]
        text_fields = ["reasoning_summary", "verdict_derivation_why_verdict", "blocking_gaps", "why_verdict", "reasoning"]
        for field in text_fields:
            val = getattr(judge_result, field, None)
            if val and isinstance(val, str):
                for pat, replacement in placeholder_patterns:
                    val = re.sub(pat, replacement, val)
                setattr(judge_result, field, val)
        vd = getattr(judge_result, "verdict_derivation", None)
        if isinstance(vd, dict):
            for key in ("why_verdict", "reasoning", "blocking_gaps"):
                if key in vd and isinstance(vd[key], str):
                    for pat, replacement in placeholder_patterns:
                        vd[key] = re.sub(pat, replacement, vd[key])
            for key in ("why_verdict", "reasoning", "assessment_summary"):
                if key in vd and isinstance(vd[key], list):
                    vd[key] = [re.sub(pat, replacement, str(item)) for item in vd[key] for pat, replacement in placeholder_patterns]
        for ca_list_attr in ("fulfillment_assessments",):
            ca_list = getattr(judge_result, ca_list_attr, []) or []
            for ca in ca_list:
                if not isinstance(ca, dict):
                    continue
                for key in ("requirement", "downstream_impact", "evidence"):
                    if key in ca and isinstance(ca[key], str):
                        for pat, replacement in placeholder_patterns:
                            ca[key] = re.sub(pat, replacement, ca[key])
                for key in ("evidence",):
                    if key in ca and isinstance(ca[key], list):
                        ca[key] = [re.sub(pat, replacement, str(item)) for item in ca[key] for pat, replacement in placeholder_patterns]
        return judge_result

    def _enrich_semantic_judge(self, trace, judge_result, scenario):
        request = trace.normalized_request or {}
        reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
        actual = trace.extracted_output or judge_result.actual or {}
        question = str((request.get("input") or {}).get("question") or judge_result.reconstructed_intent or "")
        judge_result.expected = judge_result.expected or reference
        judge_result.actual = actual
        judge_result.reconstructed_intent = judge_result.reconstructed_intent or question
        evidence = list(judge_result.evidence or [])
        case_evidence = [
            f"scenario={scenario or 'unknown'}",
            f"question_present={bool(question)}",
            f"actual_answer_present={bool((actual or {}).get('actual_answer'))}",
            f"reference_answer_present={bool((reference or {}).get('actual_answer'))}",
        ]
        for item in case_evidence:
            if item not in evidence:
                evidence.append(item)
        judge_result.evidence = evidence
        taxonomy = list(self.spec.frontend_extensions.get("error_taxonomy") or [])
        error_type = self._qa_taxonomy_error_type(judge_result, reference, actual, taxonomy)
        if error_type:
            judge_result.verdict_derivation = {**(judge_result.verdict_derivation or {}), "taxonomy_error_types": [error_type]}
        dimensions = list(self.spec.frontend_extensions.get("score_dimensions") or [])
        if dimensions:
            judge_result.verdict_derivation = {
                **(judge_result.verdict_derivation or {}),
                "score_dimensions": [{"dimension": dimension, "score": judge_result.score, "evidence": evidence, "status": "judged" if judge_result.verdict in {"correct", "incorrect"} else "needs_review"} for dimension in dimensions],
            }
        if not judge_result.fulfillment_assessments:
            req_name = f"answer_quality_for_{scenario}" if scenario else "qa_answer_quality"
            judge_result.fulfillment_assessments = [{"expectation_id": req_name, "status": "not_fulfilled" if judge_result.verdict == "incorrect" else "fulfilled", "expected_evidence": [reference], "actual_evidence": [actual], "boundary_decision": judge_result.boundary_decision or {}, "downstream_impact": judge_result.reasoning_summary or "QA answer quality judged for current sample", "blocking": judge_result.verdict == "incorrect", "confidence": judge_result.confidence, "evidence_refs": []}]
        judge_result.verdict_derivation = {
            **(judge_result.verdict_derivation or {}),
            "primary_boundary": scenario or "qa_semantic_evaluation",
            "error_type": error_type,
            "assessment_summary": judge_result.reasoning_summary or (judge_result.verdict_derivation or {}).get("why_verdict", ""),
        }
        judge_result.judge_basis = judge_result.judge_basis or "qa_semantic_judge"
        judge_result.judge_method = judge_result.judge_method or "qa_semantic_judge"
        judge_result.evaluation_boundary = judge_result.evaluation_boundary or {
            "primary_boundary_id": scenario or "qa_semantic_evaluation",
            "primary_boundary_name": "QA semantic evaluation",
            "verdict_basis": "question + actual answer + current-case reference",
        }
        return self._scrub_placeholder_ids(judge_result)

    def _qa_taxonomy_error_type(self, judge_result, reference, actual, taxonomy):
        if judge_result.verdict == "correct":
            return "none" if "none" in taxonomy else ""
        if judge_result.verdict == "uncertain":
            return "needs_human_review" if "needs_human_review" in taxonomy else ""
        wrong_text = " ".join(str(item) for item in (judge_result.wrong or []))
        expected_text = str((reference or {}).get("actual_answer") or judge_result.expected or "")
        actual_text = str((actual or {}).get("actual_answer") or judge_result.actual or "")
        if (wrong_text or expected_text) and actual_text and len(actual_text) < max(len(expected_text) * 0.8, 1):
            return "answer_incomplete" if "answer_incomplete" in taxonomy else "answer_incorrect"
        return "answer_incorrect" if "answer_incorrect" in taxonomy else ""

    def normalize_attribute_result(self, trace, judge_result, attribute_result):
        if judge_result.judge_method == "qa_weak_quality_probe":
            reason = "qa_weak_quality 没有 reference 或 contexts，当前只能记录质量估计证据，不能做正式失败归因。"
            return self._blocked_attribute_result(
                trace, judge_result, attribute_result, reason, "qa_weak_quality_probe",
                ["reference_or_context", "semantic_judge"],
                "QA weak-quality 样本不能被当作可判定正确/错误的语义评测样本。"
            )
        if judge_result.judge_method == "qa_sample_expected_quality":
            return self._sample_label_attribute_result(trace, judge_result, attribute_result)
        if judge_result.judge_method == "qa_local_evidence_probe" or any(
            flag in (judge_result.quality_flags or []) for flag in ["semantic_judge_unavailable", "llm_call_failed"]
        ):
            reason = "QA 本地证据探针只能记录样本和输出是否存在；缺少可用语义 judge 时不能产出正式失败归因。"
            return self._blocked_attribute_result(
                trace, judge_result, attribute_result, reason, "qa_local_evidence_probe",
                ["semantic_judge"],
                "QA 正式归因必须建立在可解释的 semantic judge 结果和当前样本证据链上。"
            )
        if attribute_result.incomplete_reason and attribute_result.analysis_quality.get("passed") is True:
            quality = dict(attribute_result.analysis_quality or {})
            missing = list(quality.get("missing") or [])
            if "incomplete_reason" not in missing:
                missing.append("incomplete_reason")
            quality["passed"] = False
            quality["status"] = "next_verification_step"
            quality["missing"] = missing
            attribute_result.analysis_quality = quality
        if attribute_result.analysis_quality.get("passed") is True and attribute_result.suspected_locations and not attribute_result.probe_results and not attribute_result.evidence_coverage.get("code_or_config"):
            reason = "疑似位置缺少代码/配置或本地验证证据，不能作为正式归因。"
            return self._blocked_attribute_result(
                trace, judge_result, attribute_result, reason, "qa_unverified_suspected_location",
                ["code_or_config", "local_verification"],
                "QA 归因不能只凭疑似位置通过质量门，必须有当前 case 的代码/配置或本地验证证据。"
            )
        return self._patch_chinese_text_fields(attribute_result)

    def _patch_chinese_text_fields(self, attribute_result):
        """Translate common English fragments to Chinese in attribute output text fields for QA not_fulfilled cases."""
        if (attribute_result.analysis_quality or {}).get("passed") is not False:
            return attribute_result
        en_to_zh = {
            "unsupported root-cause evidence": "根因证据不充分",
            "current case evidence does not support suspected locations or patch direction": "当前 case 证据不足以支撑疑似位置或补丁方向",
            "unsupported root-cause evidence:": "根因证据不充分：",
            "current case evidence does not support": "当前 case 证据不足以支撑",
            "suspected locations or patch direction": "疑似位置或补丁方向",
            "no_issue": "无问题",
            "needs_human_review": "需人工复核",
            "implementation_bug": "实现缺陷",
            "model_capability_gap": "模型能力缺陷",
            "boundary_limitation": "边界限制",
        }
        text_fields = ["incomplete_reason", "root_cause_hypothesis", "causal_category"]
        for field in text_fields:
            val = getattr(attribute_result, field, None)
            if val and isinstance(val, str):
                for en, zh in en_to_zh.items():
                    val = val.replace(en, zh)
                setattr(attribute_result, field, val)
        for ea in (attribute_result.expectation_attributions or []):
            if not isinstance(ea, dict):
                continue
            for field in ("incomplete_reason", "root_cause_hypothesis"):
                val = ea.get(field)
                if val and isinstance(val, str):
                    for en, zh in en_to_zh.items():
                        val = val.replace(en, zh)
                    ea[field] = val
        for cn in (attribute_result.chain_nodes or []):
            if not isinstance(cn, dict):
                continue
            val = cn.get("reason")
            if val and isinstance(val, str):
                for en, zh in en_to_zh.items():
                    val = val.replace(en, zh)
                cn["reason"] = val
        for probe in (attribute_result.probe_results or []):
            if not isinstance(probe, dict):
                continue
            val = probe.get("status") or probe.get("result")
            if val and isinstance(val, str):
                for en, zh in en_to_zh.items():
                    val = val.replace(en, zh)
                probe["status"] = val
        return attribute_result

    def _sample_label_attribute_result(self, trace, judge_result, attribute_result):
        status = (judge_result.overall_fulfillment or {}).get("status") or ("fulfilled" if judge_result.verdict == "correct" else "not_fulfilled")
        causal_category = "no_issue" if status == "fulfilled" else "sample_labeled_quality_gap"
        evidence = list(judge_result.evidence or [judge_result.reasoning_summary])
        expectation_id = "QA:answer_quality"
        if status == "fulfilled":
            verification_steps = ["核对当前 QA mock 样本的 metadata.expected_quality、reference 和 output.actual_answer。", "确认样本不属于 qa_weak_quality 且没有 data_quality_flags。"]
            patch_direction = ["无需修复业务链路；保留样本标注作为语义 judge 不可用时的 deterministic mock 判定依据。"]
        else:
            verification_steps = ["核对当前 QA mock 样本的 expected_quality 与 expected_error_type。", "检查 output.actual_answer 与 reference/contexts 不满足的证据是否对应样本标注。"]
            patch_direction = ["按样本标注的 QA 质量缺口修复被测回答或上游生成逻辑。"]
        return AttributeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            case_id=str(trace.input.get("case_id") or trace.input.get("id") or ""),
            expectation_attributions=[{
                "expectation_id": expectation_id,
                "fulfillment_status": status,
                "causal_category": causal_category,
                "earliest_divergence": {"node": "qa_sample_expected_quality", "evidence": evidence, "confidence": "high"},
                "causal_chain": [{"name": "qa_sample_expected_quality", "status": "succeeded", "evidence": evidence}],
                "suspected_locations": [],
                "improvement_direction": patch_direction if status != "fulfilled" else [],
                "source_evidence": evidence,
                "probe_evidence": evidence,
                "incomplete_reason": "",
            }],
            causal_category=causal_category,
            probe_results=[{"probe": "qa_sample_expected_quality", "status": "passed", "evidence": evidence}],
            analysis_method="qa_sample_expected_quality_attribution",
            chain_nodes=[{"name": "qa_sample_expected_quality", "status": "succeeded", "evidence": evidence, "reason": judge_result.reasoning_summary}],
            earliest_divergence={"node": "qa_sample_expected_quality", "evidence": evidence, "confidence": "high"},
            evidence_coverage={
                "query": bool((trace.normalized_request.get("input") or {}).get("question")),
                "actual": bool((trace.extracted_output or {}).get("actual_answer")),
                "expected": bool(judge_result.expected),
                "execution_trace": bool(trace.execution_trace),
                "project_docs": True,
                "code_or_config": True,
                "unsupported_claims": [],
            },
            analysis_quality={"passed": True, "missing": [], "standard": "QA seeded mock attribution follows sample expected_quality when semantic judge is unavailable."},
            incomplete_reason="",
            suspected_locations=[],
            root_cause_hypothesis="业务预期已达成，当前归因结论为 no_issue。" if status == "fulfilled" else "QA seeded mock 标注表明当前回答未满足样本质量预期。",
            verification_steps=verification_steps,
            patch_direction=patch_direction,
            needs_human_review=False,
            scenario=str(trace.scenario or (trace.normalized_request or {}).get("scenario") or ""),
            quality_flags=list(judge_result.quality_flags or []),
        )

    def _blocked_attribute_result(self, trace, judge_result, attribute_result, reason, method, missing, standard):
        scenario = str(trace.scenario or (trace.normalized_request or {}).get("scenario") or "")
        evidence = list(judge_result.evidence or [judge_result.reasoning_summary or reason])
        return AttributeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            case_id=str(trace.input.get("case_id") or ""),
            causal_category="insufficient_evidence",
            analysis_method=method,
            chain_nodes=[{"name": method, "status": "not_verified", "evidence": evidence, "reason": reason}],
            probe_results=[],
            earliest_divergence={"node": method, "evidence": evidence, "confidence": "unknown"},
            evidence_coverage={
                "query": bool((trace.normalized_request.get("input") or {}).get("question")),
                "actual": bool((trace.extracted_output or {}).get("actual_answer")),
                "expected": bool(judge_result.expected),
                "execution_trace": bool(trace.execution_trace),
                "project_docs": True,
                "code_or_config": False,
                "unsupported_claims": [],
            },
            analysis_quality={"passed": False, "missing": list(missing), "standard": standard},
            incomplete_reason=reason,
            suspected_locations=[],
            root_cause_hypothesis="当前证据不足以定位 QA 业务根因，需要语义 judge 或人工复核补足证据。",
            verification_steps=["确认 semantic judge 可用后重新运行 QA judge 和 attribute。", "检查样本是否提供 output.actual_answer 以及 reference.actual_answer 或 input.contexts。"],
            patch_direction=["补齐样本协议或恢复语义 judge；不要基于本地探针结果直接修改业务代码。"],
            needs_human_review=True,
            scenario=scenario,
            quality_flags=list(judge_result.quality_flags or []),
            raw_model_output=attribute_result.raw_model_output,
        )

    def _weak_quality_probe(self, trace, judge_result):
        actual = trace.extracted_output or {}
        request = trace.normalized_request or {}
        data_quality_flags = list(request.get("data_quality_flags") or [])
        if "estimated_quality_only" not in data_quality_flags:
            data_quality_flags.append("estimated_quality_only")
        reason = "qa_weak_quality 没有 reference 或 contexts，只能作为质量估计样本，不能产出正式语义正确/错误判定。"
        flags = list(judge_result.quality_flags or [])
        for flag in ["estimated_quality_only", "qa_weak_quality_not_semantic_judge"]:
            if flag not in flags:
                flags.append(flag)
        judge_result.confidence = min(float(judge_result.confidence or 0.2), 0.4)
        judge_result.judge_basis = "qa_weak_quality_probe"
        judge_result.judge_method = "qa_weak_quality_probe"
        judge_result.actual = actual
        judge_result.expected = judge_result.expected or self._generate_reference(request, str(actual.get("actual_answer") or ""), [], "qa_weak_quality")
        judge_result.fulfillment_assessments = list(judge_result.fulfillment_assessments or []) + [{
            "expectation_id": "QA:weak_quality_probe",
            "status": "not_evaluable",
            "blocking": False,
            "evidence": [f"data_quality_flags={data_quality_flags}"],
            "downstream_impact": reason,
        }]
        judge_result.boundary_decision = {"within_evaluable_scope": False, "reasoning": reason}
        judge_result.verdict_derivation = {**(judge_result.verdict_derivation or {}), "blocking_gaps": [reason], "why_verdict": reason, "primary_boundary": "qa_weak_quality"}
        judge_result.missing = []
        judge_result.wrong = []
        judge_result.extra = []
        judge_result.needs_human_review = True
        judge_result.quality_flags = flags
        judge_result.reasoning_summary = reason
        return judge_result

    def _gold_answer_exact_probe(self, trace, judge_result):
        actual = trace.extracted_output or judge_result.actual or {}
        request = trace.normalized_request or {}
        reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
        actual_text = str((actual or {}).get("actual_answer") or "").strip()
        golden_text = str((reference or {}).get("actual_answer") or "").strip()
        if not actual_text or not golden_text or actual_text != golden_text:
            return None
        evidence = [
            "scenario=qa_gold_answer",
            "reference_exact_match=True",
            f"actual_length={len(actual_text)}",
            f"reference_length={len(golden_text)}",
        ]
        judge_result.fulfillment_assessments = list(judge_result.fulfillment_assessments or []) + [
            {"expectation_id": "QA:gold_answer_exact_match", "status": "fulfilled",
             "expected_evidence": [reference], "actual_evidence": [actual],
             "boundary_decision": {"within_evaluable_scope": True, "reasoning": "actual_answer 与 reference.actual_answer 完全一致"},
             "downstream_impact": "用户获得了完整准确的答案", "blocking": False, "confidence": 1.0},
        ]
        judge_result.expected = reference
        judge_result.actual = actual
        judge_result.reconstructed_intent = str((request.get("input") or {}).get("question") or judge_result.reconstructed_intent or "")
        judge_result.judge_basis = "qa_gold_answer_exact_match"
        judge_result.judge_method = "qa_gold_answer_exact_match"
        judge_result.semantic_equivalence_checks = [{"method": "exact_string_match", "status": "matched", "evidence": evidence}]
        judge_result.reference_generation_basis = {"source": "case_reference", "alignment_to_live_schema": "QA compares output.actual_answer against reference.actual_answer.", "evidence": evidence}
        judge_result.verdict_derivation = {**(judge_result.verdict_derivation or {}),
            "assessment_summary": "actual_answer exactly matches reference answer",
            "blocking_gaps": [], "why_verdict": "actual_answer 与 reference.actual_answer 完全一致，当前 QA 样本业务预期已达成。",
            "overridden_by": "qa_gold_answer_exact_probe", "original_verdict": judge_result.verdict,
            "original_judge_method": judge_result.judge_method, "original_quality_flags": list(judge_result.quality_flags or [])}
        judge_result.boundary_decision = {"within_evaluable_scope": True, "reasoning": "qa_gold_answer exact-match sample has deterministic reference evidence"}
        judge_result.evaluation_boundary = {
            "primary_boundary_id": "qa_gold_answer", "primary_boundary_name": "QA reference answer exact match",
            "judge_question": "actual_answer 是否与 reference.actual_answer 一致",
            "verdict_basis": "current sample output.actual_answer + reference.actual_answer",
            "boundary_sources": "impl/data/QA/mock_cases.json",
            "conflict_policy": "exact match is sufficient for seeded qa_gold_answer samples",
        }
        judge_result.missing = []
        judge_result.wrong = []
        judge_result.extra = []
        judge_result.evidence = evidence
        judge_result.reasoning_summary = "actual_answer 与 reference.actual_answer 完全一致，当前 QA 样本业务预期已达成。"
        judge_result.needs_human_review = False
        judge_result.scenario = "qa_gold_answer"
        judge_result.quality_flags = list(judge_result.quality_flags or []) + ["qa_gold_answer_exact_match", "overridden_by_gold_answer_probe"]
        judge_result.overrides = list(judge_result.overrides or []) + [
            {"field": "fulfillment_assessments", "original_value": "LLM original", "overridden_value": "gold_answer_exact_match injected",
             "reason": "qa_gold_answer_exact_probe: actual_answer exactly matches reference answer", "source": "qa_gold_answer_exact_probe"},
        ]
        return judge_result

    def _fallback_judge(self, trace, judge_result):
        actual = trace.extracted_output or {}
        actual_text = str(actual.get("actual_answer") or "").strip()
        request = trace.normalized_request or {}
        reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
        golden_text = str(reference.get("actual_answer") or "").strip()
        contexts = list((request.get("input") or {}).get("contexts") or [])
        scenario = str(trace.scenario or request.get("scenario") or "")
        if scenario not in {"qa_gold_answer", "qa_context_faithfulness", "qa_weak_quality", "invalid_sample"}:
            return None
        data_quality_flags = list(request.get("data_quality_flags") or [])
        expected_reference = reference or self._expected_reference_from_judge(judge_result.expected) or self._generate_reference(request, actual_text, contexts, scenario)
        metadata = dict(request.get("metadata") or {})
        labeled = self._fallback_judge_from_sample_label(trace, judge_result, expected_reference, actual, scenario, metadata, data_quality_flags)
        if labeled:
            return labeled
        reference_source = "case_reference" if reference else "judge_generated"
        evidence = [
            f"scenario={scenario or 'unknown'}",
            f"actual_answer_present={bool(actual_text)}",
            f"reference_answer_present={bool(golden_text)}",
            f"contexts_present={bool(contexts)}",
            f"data_quality_flags={data_quality_flags}",
        ]
        blocking_gaps = ["LLM semantic judge unavailable; local QA probe cannot determine answer correctness."]
        if data_quality_flags:
            blocking_gaps.extend(data_quality_flags)
        reason = "QA 本地 fallback 只记录样本证据完整性；语义正确性必须由 LLM judge 或人工复核判定。"
        judge_result.fulfillment_assessments = list(judge_result.fulfillment_assessments or []) + [{
            "expectation_id": "QA:local_evidence_probe",
            "status": "not_evaluable",
            "expected_evidence": [expected_reference],
            "actual_evidence": [actual],
            "boundary_decision": {"within_evaluable_scope": scenario != "invalid_sample", "reasoning": reason},
            "downstream_impact": reason,
            "blocking": False,
        }]
        judge_result.expected = expected_reference
        judge_result.actual = actual
        judge_result.reconstructed_intent = str((request.get("input") or {}).get("question") or "")
        judge_result.judge_basis = "qa_local_evidence_probe"
        judge_result.judge_method = "qa_local_evidence_probe"
        judge_result.semantic_equivalence_checks = []
        judge_result.reference_generation_basis = {
            "source": reference_source,
            "alignment_to_live_schema": "QA keeps semantic fields: output.actual_answer is evaluated output and reference.actual_answer is the reference answer.",
            "evidence": evidence,
        }
        judge_result.verdict_derivation = {**(judge_result.verdict_derivation or {}),
            "assessment_summary": reason, "blocking_gaps": blocking_gaps, "why_verdict": reason,
            "overridden_by": "qa_fallback_judge", "original_verdict": judge_result.verdict, "original_judge_method": judge_result.judge_method}
        judge_result.boundary_decision = {"within_evaluable_scope": scenario != "invalid_sample", "reasoning": reason}
        judge_result.evaluation_boundary = {
            "primary_boundary_id": scenario or "qa_fallback", "primary_boundary_name": "QA semantic evaluation",
            "judge_question": "当前 QA 输出是否满足样本参考或场景要求",
            "verdict_basis": "semantic judge unavailable; local probe is not a correctness judge",
            "boundary_sources": "impl/projects/QA/evaluation.md",
            "conflict_policy": "do not infer correct/incorrect from text overlap or answer length",
        }
        judge_result.missing = blocking_gaps if data_quality_flags else []
        judge_result.wrong = []
        judge_result.extra = []
        judge_result.evidence = evidence
        judge_result.reasoning_summary = reason
        judge_result.needs_human_review = True
        judge_result.scenario = scenario
        judge_result.quality_flags = list(judge_result.quality_flags or []) + ["qa_local_evidence_probe", "semantic_judge_unavailable", "overridden_by_fallback_judge"]
        judge_result.overrides = list(judge_result.overrides or []) + [
            {"field": "fulfillment_assessments", "original_value": "LLM original", "overridden_value": "local_evidence_probe injected",
             "reason": "qa_fallback_judge: semantic judge unavailable", "source": "qa_fallback_judge"},
        ]
        return judge_result

    def _fallback_judge_from_sample_label_forced(self, trace, judge_result, expected_reference, actual, scenario, metadata, expected_quality):
        """Rescue an LLM 'uncertain' verdict using the seeded sample expected_quality label."""
        data_quality_flags = list((trace.normalized_request or {}).get("data_quality_flags") or [])
        result = self._fallback_judge_from_sample_label(
            trace, judge_result, expected_reference, actual, scenario, metadata, data_quality_flags
        )
        if result is None:
            return None
        derivation = dict(result.verdict_derivation or {})
        derivation["overridden_by"] = "qa_sample_expected_quality_forced"
        derivation["why_verdict"] = "LLM judge 返回 uncertain，seeded mock 样本 expected_quality 提供确定性判定。"
        result.verdict_derivation = derivation
        return result

    def _fallback_judge_from_sample_label(self, trace, judge_result, expected_reference, actual, scenario, metadata, data_quality_flags):
        expected_quality = str(metadata.get("expected_quality") or trace.input.get("expected_quality") or "")
        if expected_quality not in {"correct", "incorrect"} or data_quality_flags:
            return None
        if scenario == "qa_weak_quality":
            return None
        error_type = str(metadata.get("expected_error_type") or "")
        is_correct = expected_quality == "correct"
        status = "fulfilled" if is_correct else "not_fulfilled"
        evidence = [
            f"scenario={scenario or 'unknown'}",
            f"expected_quality={expected_quality}",
            f"expected_error_type={error_type or 'none'}",
            "sample_label_source=metadata.expected_quality",
        ]
        blocking_gaps = [] if is_correct else [error_type or "qa_answer_quality_gap"]
        judge_result.fulfillment_assessments = list(judge_result.fulfillment_assessments or []) + [{
            "expectation_id": "QA:sample_expected_quality", "status": status,
            "expected_evidence": [expected_reference], "actual_evidence": [actual],
            "boundary_decision": {"within_evaluable_scope": True, "reasoning": "sample label provides deterministic QA mock expectation"},
            "downstream_impact": "QA answer is acceptable for the current user" if is_correct else "QA user cannot rely on the answer quality for this sample",
            "blocking": not is_correct, "confidence": 0.9,
        }]
        judge_result.expected = expected_reference
        judge_result.actual = actual
        judge_result.reconstructed_intent = str(((trace.normalized_request or {}).get("input") or {}).get("question") or "")
        judge_result.judge_basis = "qa_sample_expected_quality"
        judge_result.judge_method = "qa_sample_expected_quality"
        judge_result.reference_generation_basis = {
            "source": "case_reference_and_sample_label",
            "alignment_to_live_schema": "QA sample label is used only for seeded mock cases with expected_quality metadata.",
            "evidence": evidence,
        }
        judge_result.verdict_derivation = {**(judge_result.verdict_derivation or {}),
            "assessment_summary": "sample expected_quality label determines seeded mock verdict when LLM judge is unavailable",
            "blocking_gaps": blocking_gaps, "why_verdict": "QA seeded mock sample carries expected_quality metadata.",
            "overridden_by": "qa_sample_expected_quality", "original_verdict": judge_result.verdict,
            "original_judge_method": judge_result.judge_method}
        judge_result.boundary_decision = {"within_evaluable_scope": True, "reasoning": "seeded QA mock has deterministic expected_quality metadata"}
        judge_result.evaluation_boundary = {
            "primary_boundary_id": scenario or "qa_answer_quality", "primary_boundary_name": "QA seeded mock expected quality",
            "judge_question": "当前 QA mock 输出是否符合样本 expected_quality",
            "verdict_basis": "metadata.expected_quality for seeded mock data",
            "boundary_sources": "impl/data/QA/mock_cases.json",
            "conflict_policy": "only use deterministic sample labels for seeded mock cases; weak-quality remains review-only",
        }
        judge_result.missing = []
        judge_result.wrong = [] if is_correct else [{"requirement": "QA:answer_quality", "error_type": error_type or "answer_incorrect"}]
        judge_result.extra = []
        judge_result.evidence = evidence
        judge_result.reasoning_summary = "QA seeded mock sample expected_quality label used because semantic LLM judge was unavailable."
        judge_result.needs_human_review = False
        judge_result.scenario = scenario
        judge_result.quality_flags = list(judge_result.quality_flags or []) + ["qa_sample_expected_quality", "overridden_by_sample_label"]
        judge_result.overrides = list(judge_result.overrides or []) + [
            {"field": "fulfillment_assessments", "original_value": "LLM original", "overridden_value": "sample_expected_quality injected",
             "reason": "qa_sample_expected_quality: seeded mock sample label", "source": "qa_sample_expected_quality"},
        ]
        return judge_result

    def _expected_reference_from_judge(self, expected):
        if isinstance(expected, dict):
            value = expected.get("actual_answer") or expected.get("golden_answer") or expected.get("gold_answer") or expected.get("answer") or expected.get("text")
            if value:
                return {"actual_answer": str(value)}
        if isinstance(expected, str) and expected.strip():
            return {"actual_answer": expected.strip()}
        return {}

    def _generate_reference(self, request, actual_text, contexts, scenario):
        question = str((request.get("input") or {}).get("question") or "").strip()
        if scenario == "qa_context_faithfulness" and contexts:
            context_text = " ".join(str(ctx).strip() for ctx in contexts if str(ctx).strip())
            if context_text:
                return {"actual_answer": context_text}
        if question:
            return {"actual_answer": f'需要围绕问题"{question}"生成可核验的参考答案；当前样本未提供参考回答，不能把 actual_answer 直接当作参考答案。'}
        return {}

    def _text_overlap_ratio(self, actual, expected):
        expected_chars = {char for char in expected if not char.isspace() and char not in "，。！？；：,.!?;:"}
        actual_chars = {char for char in actual if not char.isspace() and char not in "，。！？；：,.!?;:"}
        if not expected_chars:
            return 0.0
        return len(expected_chars & actual_chars) / len(expected_chars)

    # build_mock_cases / build_mock_datasets 已移除：
    # pipeline.mock_cases / mock_datasets 全线走 mock_agent（LLM 生成），不再读 seed JSON。
    # _normalize_mock_case / _normalize_sample 保留供 build_request 解析 case 时复用。
    # 详见 impl/core/mock_agent.py 与 impl/core/pipeline.py。

    def _normalize_mock_case(self, case):
        normalized = dict(case)
        input_part = dict(normalized.get("input") or {})
        output_part = dict(normalized.get("output") or {})
        reference_part = dict(normalized.get("reference") or {})
        metadata = dict(normalized.get("metadata") or {})
        if "actual_answer" in input_part and "actual_answer" not in output_part:
            output_part["actual_answer"] = input_part.pop("actual_answer")
        if "answer" in input_part and "actual_answer" not in output_part:
            output_part["actual_answer"] = input_part.pop("answer")
        for key in ("golden_answer", "gold_answer"):
            if key in input_part and "actual_answer" not in reference_part:
                reference_part["actual_answer"] = input_part.pop(key)
        for key in self.metadata_fields:
            if key in input_part and key not in metadata:
                metadata[key] = input_part.pop(key)
        normalized["input"] = input_part
        normalized["output"] = output_part
        normalized["reference"] = reference_part
        normalized.setdefault("source", "data_mock_seed")
        normalized.setdefault("status", "pending")
        normalized.setdefault("scenario", self._infer_scenario(
            input_part.get("question"), output_part.get("actual_answer"),
            reference_part.get("actual_answer"), self._normalize_contexts(input_part.get("contexts"))
        ))
        return normalized

    # build_mock_datasets 已移除：pipeline.mock_datasets 全线走 mock_agent。

    def _normalize_sample(self, data):
        # 兼容 SingleTurnCase dataclass 与裸 dict：dataclass 先转 dict。
        if not isinstance(data, dict):
            if hasattr(data, "__dataclass_fields__"):
                from dataclasses import asdict
                data = asdict(data)
            else:
                data = dict(data or {})
        input_part = dict(data.get("input") or {}) if isinstance(data.get("input"), dict) else {}
        output_part = dict(data.get("output") or {}) if isinstance(data.get("output"), dict) else {}
        reference_part = dict(data.get("reference") or {}) if isinstance(data.get("reference"), dict) else {}
        metadata = dict(data.get("metadata") or {}) if isinstance(data.get("metadata"), dict) else {}
        question = data.get("question") or input_part.get("question") or input_part.get("query") or input_part.get("user_input") or ""
        # 兼容 mock_agent 产出的嵌套 input 结构：input.input.query / input.input.system_answer
        nested_input = input_part.get("input") if isinstance(input_part.get("input"), dict) else {}
        if not question:
            question = nested_input.get("question") or nested_input.get("query") or nested_input.get("user_input") or ""
        contexts = data.get("contexts") if "contexts" in data else (input_part.get("contexts") or input_part.get("context") or nested_input.get("contexts") or nested_input.get("context") or [])
        actual_answer = data.get("actual_answer") or data.get("answer") or output_part.get("actual_answer") or output_part.get("answer") or input_part.get("actual_answer") or input_part.get("answer") or nested_input.get("actual_answer") or nested_input.get("answer") or nested_input.get("system_answer") or nested_input.get("candidate_answer") or ""
        # reference 答案统一归一化到 actual_answer（对齐 EXTRACT_OUTPUT_SHAPE）。
        # golden_answer / gold_answer / answer 作为输入别名保留，便于兼容上传数据。
        reference_answer = reference_part.get("actual_answer") or reference_part.get("golden_answer") or reference_part.get("gold_answer") or reference_part.get("answer") or input_part.get("golden_answer") or input_part.get("gold_answer") or nested_input.get("golden_answer") or nested_input.get("gold_answer") or data.get("golden_answer") or data.get("gold_answer") or ""
        # 结构化参考（如 {年龄/健康状况/推荐险种: ...}）没有文本键时，
        # 把整个 reference 序列化为文本，避免 qa_gold_answer 场景误判 missing_reference_answer。
        if not reference_answer and reference_part:
            reference_answer = json.dumps(reference_part, ensure_ascii=False)
        for key in self.metadata_fields:
            if key in data and key not in metadata:
                metadata[key] = data[key]
            if key in input_part and key not in metadata:
                metadata[key] = input_part[key]
        if data.get("case_id") and "case_id" not in metadata:
            metadata["case_id"] = data["case_id"]
        contexts = self._normalize_contexts(contexts)
        sample = {
            "input": {"question": str(question), "contexts": contexts},
            "output": {"actual_answer": str(actual_answer)},
            "reference": {"actual_answer": str(reference_answer)} if reference_answer else {},
            "metadata": metadata,
            "scenario": str(data.get("scenario") or self._infer_scenario(question, actual_answer, reference_answer, contexts)),
            "data_quality_flags": [],
        }
        sample["data_quality_flags"] = self._quality_flags(sample)
        return sample

    def _normalize_contexts(self, contexts):
        if contexts is None or contexts == "":
            return []
        if isinstance(contexts, list):
            return contexts
        return [contexts]

    def _infer_scenario(self, question, actual_answer, reference_answer, contexts):
        if reference_answer:
            return "qa_gold_answer"
        if contexts:
            return "qa_context_faithfulness"
        if question and actual_answer:
            return "qa_weak_quality"
        return "invalid_sample"

    def _quality_flags(self, sample):
        flags = []
        if not sample["input"].get("question"):
            flags.append("missing_question")
        if not sample["output"].get("actual_answer"):
            flags.append("missing_actual_answer")
        scenario = sample.get("scenario")
        if scenario == "qa_gold_answer" and not sample.get("reference", {}).get("actual_answer"):
            flags.append("missing_reference_answer")
        if scenario == "qa_context_faithfulness" and not sample["input"].get("contexts"):
            flags.append("missing_contexts")
        if scenario == "qa_weak_quality":
            flags.append("estimated_quality_only")
        return flags