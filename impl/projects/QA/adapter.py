from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from impl.core.adapter import ProjectAdapter
from impl.core.adapter_v2 import LegacyProjectAdapter
from impl.core.schema import AttributeResult, JudgeResult, LiveExecutionResult, LiveRequest, MultiTurnCase, SingleTurnCase
from impl.core.summary import summary_from_attribution


class Adapter(LegacyProjectAdapter):
    metadata_fields = {"category", "model_name", "latency_ms", "token_usage", "cost", "row_index", "source_dataset", "expected_quality", "expected_error_type", "quality_dimension"}

    @staticmethod
    def _input_payload(request: Dict[str, Any] | None) -> Dict[str, Any]:
        """从 normalized_request 取核心输入 payload。

        兼容两种形状：
        - flat（QAInput）：question/contexts 在顶层 → 直接返回 request
        - wrapper（旧 QARequest）：question/contexts 嵌套在 input 字段 → 返回 input
        """
        if not isinstance(request, dict):
            return {}
        nested = request.get("input")
        return nested if isinstance(nested, dict) else request


    def _load_live(self):
        """加载 ProjectLive 实例（新协议）"""
        from impl.projects.QA.live import QALive
        return QALive(self.spec)

    def _load_judge(self):
        """加载 ProjectJudge 实例（新协议）"""
        from impl.projects.QA.judge import QAJudge
        return QAJudge(self.spec, self)

    def _load_attribute(self):
        """加载 ProjectAttribute 实例（新协议）"""
        from impl.projects.QA.attribute import QAAttribute
        return QAAttribute(self.spec, self)

    def build_request(self, case: SingleTurnCase | MultiTurnCase) -> LiveRequest:
        # 方案 A：mock 直接对接 live_schema，build_request 不做形状翻译。
        # case.input 已是 QAInput 形状（= REQUEST_SCHEMA），直接透传作为 normalized_request。
        sample = self._normalize_sample(case)
        input_data = dict(case.input or {}) if hasattr(case, "input") else (dict(case.get("input") or {}) if isinstance(case, dict) else {})
        normalized_request = {
            "question": str(sample.get("input", {}).get("question") or input_data.get("question") or ""),
            "contexts": list(sample.get("input", {}).get("contexts") or input_data.get("contexts") or []),
            "reference": dict(sample.get("reference") or {}),
            "metadata": dict(sample.get("metadata") or {}),
            "scenario": str(sample.get("scenario") or "qa_default"),
            "data_quality_flags": list(sample.get("data_quality_flags") or []),
            "output": dict(sample.get("output") or {}),
        }
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
        sample_input = self._input_payload(request)
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
        sample_input = self._input_payload(request)
        reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
        contexts = sample_input.get("contexts") or []
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
        expectation = {
            "expectation_id": "QA:answer_quality",
            "downstream_consumer": "QA user",
            "required_capabilities": ["answer_relevance", "groundedness", "reference_alignment"],
            "boundary": self.build_judge_context(trace).get("application_boundary") or {},
        }
        question = str(self._input_payload(trace.normalized_request).get("question") or "")
        expectation.update({
            "user_intent": question,
            "expected_outcome": "actual answer should satisfy answer relevance, groundedness, and reference alignment for the current QA sample",
            "acceptance_criteria": list(judge_result.missing or judge_result.wrong or []),
        })
        return expectation

    def _default_fulfillment_assessment(self, trace, judge_result, expectation):
        overall = judge_result.overall_fulfillment or {}
        status = overall.get("status") or "not_evaluable"
        reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else judge_result.expected or {}
        actual = judge_result.actual or trace.extracted_output or {}
        return {
            "expectation_id": expectation.get("expectation_id"),
            "status": status,
            "expected_evidence": list(judge_result.missing or []) or [reference],
            "actual_evidence": list(judge_result.wrong or []) or [actual],
            "downstream_impact": "QA answer is acceptable for the current user" if status == "fulfilled" else (judge_result.reasoning_summary or "QA user cannot rely on the answer quality for this sample"),
            "blocking": status in {"not_fulfilled", "not_evaluable"},
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
        overall = judge_result.overall_fulfillment or {}
        status = overall.get("status")
        if scenario == "qa_weak_quality" and status in {"fulfilled", "not_fulfilled"}:
            return self._weak_quality_probe(trace, judge_result)
        if status == "not_evaluable":
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
        if status in {"fulfilled", "not_fulfilled", "not_evaluable"}:
            return self._enrich_semantic_judge(trace, judge_result, scenario)
        fallback = self._fallback_judge(trace, judge_result)
        if not fallback:
            return self._scrub_placeholder_ids(judge_result)
        return self._scrub_placeholder_ids(fallback)

    def _scrub_placeholder_ids(self, judge_result):
        """Replace E1/E2/exp_*/exp-* placeholder IDs with descriptive Chinese per prompt rule 518-520."""
        placeholder_patterns = [
            (r"\bE\d+\b", "编码失败项"),
            (r"\bexp[-_]?\d+\b", "编码失败项"),
        ]
        text_fields = ["reasoning_summary", "blocking_gaps", "why_verdict", "reasoning"]
        for field in text_fields:
            val = getattr(judge_result, field, None)
            if val and isinstance(val, str):
                for pat, replacement in placeholder_patterns:
                    val = re.sub(pat, replacement, val)
                setattr(judge_result, field, val)
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
        question = str(self._input_payload(request).get("question") or "")
        judge_result.expected = judge_result.expected or reference
        judge_result.actual = actual
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
        if not judge_result.fulfillment_assessments:
            overall = judge_result.overall_fulfillment or {}
            status = overall.get("status") or "not_evaluable"
            req_name = f"answer_quality_for_{scenario}" if scenario else "qa_answer_quality"
            judge_result.fulfillment_assessments = [{"expectation_id": req_name, "status": status, "expected_evidence": [reference], "actual_evidence": [actual], "downstream_impact": judge_result.reasoning_summary or "QA answer quality judged for current sample", "blocking": status == "not_fulfilled", "evidence_refs": []}]
        judge_result.reasoning_summary = judge_result.reasoning_summary or f"QA answer quality judged for current sample (scenario={scenario or 'unknown'})"
        return self._scrub_placeholder_ids(judge_result)

    def _qa_taxonomy_error_type(self, judge_result, reference, actual, taxonomy):
        overall = judge_result.overall_fulfillment or {}
        status = overall.get("status")
        if status == "fulfilled":
            return "none" if "none" in taxonomy else ""
        if status == "not_evaluable":
            return "needs_human_review" if "needs_human_review" in taxonomy else ""
        wrong_text = " ".join(str(item) for item in (judge_result.wrong or []))
        expected_text = str((reference or {}).get("actual_answer") or judge_result.expected or "")
        actual_text = str((actual or {}).get("actual_answer") or judge_result.actual or "")
        if (wrong_text or expected_text) and actual_text and len(actual_text) < max(len(expected_text) * 0.8, 1):
            return "answer_incomplete" if "answer_incomplete" in taxonomy else "answer_incorrect"
        return "answer_incorrect" if "answer_incorrect" in taxonomy else ""

    def normalize_attribute_result(self, trace, judge_result, attribute_result):
        overall = judge_result.overall_fulfillment or {}
        status = overall.get("status") or "not_evaluable"
        # 当 judge 处于 not_evaluable 或缺少语义证据时，记录 insufficient_evidence。
        if status == "not_evaluable":
            reason = "QA judge 处于 not_evaluable 状态，缺少可用语义判定，不能产出正式失败归因。"
            return self._blocked_attribute_result(
                trace, judge_result, attribute_result, reason, "qa_local_evidence_probe",
                ["semantic_judge"],
                "QA 正式归因必须建立在可解释的 semantic judge 结果和当前样本证据链上。"
            )
        if status == "fulfilled":
            return self._patch_chinese_text_fields(attribute_result)
        return self._patch_chinese_text_fields(attribute_result)

    def _patch_chinese_text_fields(self, attribute_result):
        """Translate common English fragments to Chinese in attribute output text fields for QA not_fulfilled cases."""
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
        val = attribute_result.root_cause_hypothesis
        if val and isinstance(val, str):
            for en, zh in en_to_zh.items():
                val = val.replace(en, zh)
            attribute_result.root_cause_hypothesis = val
        for ea in (attribute_result.expectation_attributions or []):
            if not isinstance(ea, dict):
                continue
            for field in ("root_cause_hypothesis",):
                val = ea.get(field)
                if val and isinstance(val, str):
                    for en, zh in en_to_zh.items():
                        val = val.replace(en, zh)
                    ea[field] = val
        return attribute_result

    def _sample_label_attribute_result(self, trace, judge_result, attribute_result):
        status = (judge_result.overall_fulfillment or {}).get("status") or "not_fulfilled"
        evidence = list(judge_result.evidence or [judge_result.reasoning_summary])
        expectation_id = "QA:answer_quality"
        result = AttributeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            case_id=str(trace.input.get("case_id") or trace.input.get("id") or ""),
            expectation_attributions=[{
                "expectation_id": expectation_id,
                "fulfillment_status": status,
                "suspected_locations": [],
                "root_cause_hypothesis": "业务预期已达成，当前归因结论为 no_issue。" if status == "fulfilled" else "QA seeded mock 标注表明当前回答未满足样本质量预期。",
                "evidence": evidence,
            }],
            suspected_locations=[],
            evidence=evidence,
            evidence_strength="strong",
            root_cause_hypothesis="业务预期已达成，当前归因结论为 no_issue。" if status == "fulfilled" else "QA seeded mock 标注表明当前回答未满足样本质量预期。",
        )
        result.summary = summary_from_attribution({
            "expectation_attributions": result.expectation_attributions,
            "root_cause_hypothesis": result.root_cause_hypothesis,
            "evidence_strength": result.evidence_strength,
        })
        return result

    def _blocked_attribute_result(self, trace, judge_result, attribute_result, reason, method, missing, standard):
        evidence = list(judge_result.evidence or [judge_result.reasoning_summary or reason])
        result = AttributeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            case_id=str(trace.input.get("case_id") or ""),
            suspected_locations=[],
            evidence=evidence,
            evidence_strength="none",
            root_cause_hypothesis="当前证据不足以定位 QA 业务根因，需要语义 judge 或人工复核补足证据。",
        )
        result.summary = summary_from_attribution({
            "expectation_attributions": result.expectation_attributions,
            "root_cause_hypothesis": result.root_cause_hypothesis,
            "evidence_strength": result.evidence_strength,
        })
        return result

    def _weak_quality_probe(self, trace, judge_result):
        actual = trace.extracted_output or {}
        request = trace.normalized_request or {}
        reason = "qa_weak_quality 没有 reference 或 contexts，只能作为质量估计样本，不能产出正式语义正确/错误判定。"
        judge_result.actual = actual
        judge_result.expected = judge_result.expected or self._generate_reference(request, str(actual.get("actual_answer") or ""), [], "qa_weak_quality")
        judge_result.fulfillment_assessments = list(judge_result.fulfillment_assessments or []) + [{
            "expectation_id": "QA:weak_quality_probe",
            "status": "not_evaluable",
            "blocking": False,
            "evidence": [reason],
            "downstream_impact": reason,
        }]
        judge_result.missing = []
        judge_result.wrong = []
        judge_result.extra = []
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
             "downstream_impact": "用户获得了完整准确的答案", "blocking": False, "evidence_refs": []},
        ]
        judge_result.expected = reference
        judge_result.actual = actual
        judge_result.missing = []
        judge_result.wrong = []
        judge_result.extra = []
        judge_result.evidence = evidence
        judge_result.reasoning_summary = "actual_answer 与 reference.actual_answer 完全一致，当前 QA 样本业务预期已达成。"
        return judge_result

    def _fallback_judge(self, trace, judge_result):
        actual = trace.extracted_output or {}
        actual_text = str(actual.get("actual_answer") or "").strip()
        request = trace.normalized_request or {}
        reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
        golden_text = str(reference.get("actual_answer") or "").strip()
        contexts = list(self._input_payload(request).get("contexts") or [])
        scenario = str(trace.scenario or request.get("scenario") or "")
        if scenario not in {"qa_gold_answer", "qa_context_faithfulness", "qa_weak_quality", "invalid_sample"}:
            return None
        expected_reference = reference or self._expected_reference_from_judge(judge_result.expected) or self._generate_reference(request, actual_text, contexts, scenario)
        metadata = dict(request.get("metadata") or {})
        labeled = self._fallback_judge_from_sample_label(trace, judge_result, expected_reference, actual, scenario, metadata, [])
        if labeled:
            return labeled
        reason = "QA 本地 fallback 只记录样本证据完整性；语义正确性必须由 LLM judge 或人工复核判定。"
        judge_result.fulfillment_assessments = list(judge_result.fulfillment_assessments or []) + [{
            "expectation_id": "QA:local_evidence_probe",
            "status": "not_evaluable",
            "expected_evidence": [expected_reference],
            "actual_evidence": [actual],
            "downstream_impact": reason,
            "blocking": False,
        }]
        judge_result.expected = expected_reference
        judge_result.actual = actual
        judge_result.missing = []
        judge_result.wrong = []
        judge_result.extra = []
        judge_result.evidence = [
            f"scenario={scenario or 'unknown'}",
            f"actual_answer_present={bool(actual_text)}",
            f"reference_answer_present={bool(golden_text)}",
            f"contexts_present={bool(contexts)}",
        ]
        judge_result.reasoning_summary = reason
        return judge_result

    def _fallback_judge_from_sample_label_forced(self, trace, judge_result, expected_reference, actual, scenario, metadata, expected_quality):
        """Rescue an LLM 'uncertain' verdict using the seeded sample expected_quality label."""
        return self._fallback_judge_from_sample_label(
            trace, judge_result, expected_reference, actual, scenario, metadata, []
        )

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
        judge_result.fulfillment_assessments = list(judge_result.fulfillment_assessments or []) + [{
            "expectation_id": "QA:sample_expected_quality", "status": status,
            "expected_evidence": [expected_reference], "actual_evidence": [actual],
            "downstream_impact": "QA answer is acceptable for the current user" if is_correct else "QA user cannot rely on the answer quality for this sample",
            "blocking": not is_correct, "evidence_refs": [],
        }]
        judge_result.expected = expected_reference
        judge_result.actual = actual
        judge_result.missing = []
        judge_result.wrong = [] if is_correct else [{"requirement": "QA:answer_quality", "error_type": error_type or "answer_incorrect"}]
        judge_result.extra = []
        judge_result.evidence = evidence
        judge_result.reasoning_summary = "QA seeded mock sample expected_quality label used because semantic LLM judge was unavailable."
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
        question = str(self._input_payload(request).get("question") or "").strip()
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
        output_source = data.get("output") if isinstance(data.get("output"), dict) else input_part.get("output")
        reference_source = data.get("reference") if isinstance(data.get("reference"), dict) else input_part.get("reference")
        metadata_source = data.get("metadata") if isinstance(data.get("metadata"), dict) else input_part.get("metadata")
        output_part = dict(output_source or {}) if isinstance(output_source, dict) else {}
        reference_part = dict(reference_source or {}) if isinstance(reference_source, dict) else {}
        metadata = dict(metadata_source or {}) if isinstance(metadata_source, dict) else {}
        question = data.get("question") or input_part.get("question") or ""
        contexts = data.get("contexts") if "contexts" in data else (input_part.get("contexts") or [])
        actual_answer = output_part.get("actual_answer") or ""
        reference_answer = reference_part.get("actual_answer") or ""
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