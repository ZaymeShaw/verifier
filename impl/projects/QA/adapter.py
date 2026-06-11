from __future__ import annotations

from typing import Any, Dict, List

from impl.core.adapter import ProjectAdapter
from impl.core.schema import AttributeResult, JudgeResult


class Adapter(ProjectAdapter):
    metadata_fields = {"category", "model_name", "latency_ms", "token_usage", "cost", "row_index", "source_dataset"}

    def build_request(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        sample = self._normalize_sample(input_data)
        return {
            "input": sample["input"],
            "reference": sample["reference"],
            "metadata": sample["metadata"],
            "scenario": sample["scenario"],
            "data_quality_flags": sample["data_quality_flags"],
            "output": sample["output"],
        }

    def call_or_prepare(self, request: Dict[str, Any]) -> Any:
        return request.get("output") or {"actual_answer": ""}

    def mock_response(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return self.call_or_prepare(request)

    def extract_output(self, raw_response: Any) -> Dict[str, Any]:
        if isinstance(raw_response, dict):
            return {"actual_answer": str(raw_response.get("actual_answer") or raw_response.get("answer") or raw_response.get("text") or "")}
        return {"actual_answer": str(raw_response or "")}

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any]) -> Dict[str, Any]:
        request = raw_response.get("_normalized_request") if isinstance(raw_response, dict) else None
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

    def build_execution_trace(self, input_data: Dict[str, Any], request: Dict[str, Any], raw_response: Any, extracted_output: Dict[str, Any]) -> list[Dict[str, Any]]:
        return [
            {"stage": "qa.sample.normalize", "status": "ok" if request.get("scenario") != "invalid_sample" else "suspicious", "evidence": {"scenario": request.get("scenario"), "flags": request.get("data_quality_flags")}},
            {"stage": "qa.output.read", "status": "ok" if extracted_output.get("actual_answer") else "suspicious", "evidence": "evaluated output read from uploaded sample"},
            {"stage": "adapter.extract_output", "status": "ok", "evidence": {"actual_answer_present": bool(extracted_output.get("actual_answer"))}},
        ]

    def to_run_trace(self, input_data: Dict[str, Any], request: Dict[str, Any], raw_response: Any):
        if isinstance(raw_response, dict):
            raw_response = {**raw_response, "_normalized_request": request}
        return super().to_run_trace(input_data, request, raw_response)

    def build_frontend_extensions(self, trace):
        return {
            "project_fields": trace.project_fields,
            "scenarios": self.spec.frontend_extensions.get("scenarios") or [],
            "score_dimensions": self.spec.frontend_extensions.get("score_dimensions") or [],
            "error_taxonomy": self.spec.frontend_extensions.get("error_taxonomy") or [],
        }

    def normalize_judge_result(self, trace, judge_result):
        scenario = str(trace.project_fields.get("scenario") or (trace.normalized_request or {}).get("scenario") or "")
        if scenario == "qa_weak_quality" and judge_result.verdict in {"correct", "incorrect"}:
            return self._weak_quality_probe(trace, judge_result)
        if judge_result.verdict in {"correct", "incorrect", "uncertain"} and "llm_call_failed" not in (judge_result.quality_flags or []):
            return judge_result
        fallback = self._fallback_judge(trace, judge_result)
        if not fallback:
            return judge_result
        flags = ["qa_local_evidence_probe", "semantic_judge_unavailable"]
        if "llm_call_failed" in (judge_result.quality_flags or []):
            flags.insert(0, "llm_call_failed")
        fallback.quality_flags = flags
        fallback.raw_model_output = judge_result.raw_model_output
        return fallback

    def normalize_attribute_result(self, trace, judge_result, attribute_result):
        if judge_result.judge_method == "qa_weak_quality_probe":
            reason = "qa_weak_quality 没有 reference 或 contexts，当前只能记录质量估计证据，不能做正式失败归因。"
            return self._blocked_attribute_result(trace, judge_result, attribute_result, reason, "qa_weak_quality_probe", ["reference_or_context", "semantic_judge"], "QA weak-quality 样本不能被当作可判定正确/错误的语义评测样本。")
        if judge_result.judge_method == "qa_local_evidence_probe" or any(flag in (judge_result.quality_flags or []) for flag in ["semantic_judge_unavailable", "llm_call_failed"]):
            reason = "QA 本地证据探针只能记录样本和输出是否存在；缺少可用语义 judge 时不能产出正式失败归因。"
            return self._blocked_attribute_result(trace, judge_result, attribute_result, reason, "qa_local_evidence_probe", ["semantic_judge"], "QA 正式归因必须建立在可解释的 semantic judge 结果和当前样本证据链上。")
        if attribute_result.analysis_quality.get("passed") is True and attribute_result.suspected_locations and not attribute_result.local_verifications and not attribute_result.evidence_coverage.get("code_or_config"):
            reason = "疑似位置缺少代码/配置或本地验证证据，不能作为正式归因。"
            return self._blocked_attribute_result(trace, judge_result, attribute_result, reason, "qa_unverified_suspected_location", ["code_or_config", "local_verification"], "QA 归因不能只凭疑似位置通过质量门，必须有当前 case 的代码/配置或本地验证证据。")
        return attribute_result

    def _blocked_attribute_result(self, trace, judge_result, attribute_result, reason, method, missing, standard):
        scenario = str(trace.project_fields.get("scenario") or (trace.normalized_request or {}).get("scenario") or "")
        evidence = list(judge_result.evidence or [judge_result.reasoning_summary or reason])
        return AttributeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            case_id=str(trace.input.get("case_id") or ""),
            failure_category="needs_human_review",
            failure_stage=method,
            analysis_method=method,
            evidence_chain=evidence,
            trace_analysis=list(trace.execution_trace or []),
            chain_nodes=[{"name": method, "status": "not_verified", "evidence": evidence, "reason": reason}],
            local_verifications=[],
            earliest_divergence={},
            evidence_coverage={"query": bool((trace.normalized_request.get("input") or {}).get("question")), "actual": bool((trace.extracted_output or {}).get("actual_answer")), "expected": bool(judge_result.expected), "execution_trace": bool(trace.execution_trace), "project_docs": True, "code_or_config": False, "unsupported_claims": []},
            analysis_quality={"passed": False, "missing": list(missing), "standard": standard},
            incomplete_reason=reason,
            suspected_locations=[],
            root_cause_hypothesis="当前证据不足以定位 QA 业务根因，需要语义 judge 或人工复核补足证据。",
            verification_steps=["确认 semantic judge 可用后重新运行 QA judge 和 attribute。", "检查样本是否提供 output.actual_answer 以及 reference.golden_answer 或 input.contexts。"],
            patch_direction=["补齐样本协议或恢复语义 judge；不要基于本地探针结果直接修改业务代码。"],
            business_impact="该样本不能进入正式准确率归因聚簇，只能作为待复核问题保留。",
            primary_error_type="needs_human_review",
            error_types=["needs_human_review"],
            severity="unknown",
            needs_human_review=True,
            scenario=scenario,
            quality_flags=list(judge_result.quality_flags or []),
            raw_model_output=attribute_result.raw_model_output,
        )

    def _weak_quality_probe(self, trace, judge_result):
        actual = trace.extracted_output or {}
        request = trace.normalized_request or {}
        data_quality_flags = list(request.get("data_quality_flags") or trace.project_fields.get("data_quality_flags") or [])
        if "estimated_quality_only" not in data_quality_flags:
            data_quality_flags.append("estimated_quality_only")
        reason = "qa_weak_quality 没有 reference 或 contexts，只能作为质量估计样本，不能产出正式语义正确/错误判定。"
        flags = list(judge_result.quality_flags or [])
        for flag in ["estimated_quality_only", "qa_weak_quality_not_semantic_judge"]:
            if flag not in flags:
                flags.append(flag)
        judge_result.verdict = "uncertain"
        judge_result.score = None
        judge_result.confidence = min(float(judge_result.confidence or 0.2), 0.4)
        judge_result.judge_basis = "qa_weak_quality_probe"
        judge_result.judge_method = "qa_weak_quality_probe"
        judge_result.actual = judge_result.actual or actual
        judge_result.expected = judge_result.expected or self._generate_reference(request, str(actual.get("actual_answer") or ""), [], "qa_weak_quality")
        judge_result.condition_assessments = [{"requirement": "qa_weak_quality", "expected_fragment": judge_result.expected, "actual_fragment": judge_result.actual, "status": "not_verified", "evidence": [f"data_quality_flags={data_quality_flags}"]}]
        judge_result.verdict_derivation = {**(judge_result.verdict_derivation or {}), "blocking_gaps": [reason], "why_verdict": reason}
        judge_result.primary_assessment = {"boundary_id": "qa_weak_quality", "score": None, "covered": [], "missing": [reason], "wrong": [], "reasoning": reason}
        judge_result.missing = []
        judge_result.wrong = []
        judge_result.extra = []
        judge_result.score_details = []
        judge_result.needs_human_review = True
        judge_result.quality_flags = flags
        judge_result.reasoning_summary = reason
        return judge_result

    def _fallback_judge(self, trace, judge_result):
        actual = trace.extracted_output or {}
        actual_text = str(actual.get("actual_answer") or "").strip()
        request = trace.normalized_request or {}
        reference = request.get("reference") or trace.project_fields.get("reference") or {}
        golden_text = str(reference.get("golden_answer") or "").strip()
        contexts = list((request.get("input") or {}).get("contexts") or [])
        scenario = str(trace.project_fields.get("scenario") or request.get("scenario") or "")
        if scenario not in {"qa_gold_answer", "qa_context_faithfulness", "qa_weak_quality", "invalid_sample"}:
            return None

        data_quality_flags = list(request.get("data_quality_flags") or trace.project_fields.get("data_quality_flags") or [])
        expected_reference = reference or self._expected_reference_from_judge(judge_result.expected) or self._generate_reference(request, actual_text, contexts, scenario)
        reference_source = "case_reference" if reference else "judge_generated"
        evidence = [
            f"scenario={scenario or 'unknown'}",
            f"actual_answer_present={bool(actual_text)}",
            f"golden_answer_present={bool(golden_text)}",
            f"contexts_present={bool(contexts)}",
            f"data_quality_flags={data_quality_flags}",
        ]
        blocking_gaps = ["LLM semantic judge unavailable; local QA probe cannot determine answer correctness."]
        if data_quality_flags:
            blocking_gaps.extend(data_quality_flags)
        reason = "QA 本地 fallback 只记录样本证据完整性；语义正确性必须由 LLM judge 或人工复核判定。"
        return JudgeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            verdict="uncertain",
            score=None,
            confidence=0.2,
            expected=expected_reference,
            actual=actual,
            reconstructed_intent=str((request.get("input") or {}).get("question") or ""),
            judge_basis="qa_local_evidence_probe",
            judge_method="qa_local_evidence_probe",
            intent_decomposition=[{"requirement": str((request.get("input") or {}).get("question") or scenario), "evidence_source": "current query|reference|project_doc", "within_boundary": scenario != "invalid_sample"}],
            condition_assessments=[{"requirement": scenario or "qa_fallback", "expected_fragment": expected_reference, "actual_fragment": actual, "status": "not_verified", "evidence": evidence}],
            semantic_equivalence_checks=[],
            reference_generation_basis={"source": reference_source, "alignment_to_actual_shape": "QA keeps semantic fields: output.actual_answer is evaluated output and reference.golden_answer is the gold answer.", "evidence": evidence},
            verdict_derivation={"primary_boundary": scenario or "qa_fallback", "assessment_summary": reason, "blocking_gaps": blocking_gaps, "why_verdict": reason},
            boundary_decision={"within_evaluable_scope": scenario != "invalid_sample", "reasoning": reason},
            evaluation_boundary={"primary_boundary_id": scenario or "qa_fallback", "primary_boundary_name": "QA semantic evaluation", "judge_question": "当前 QA 输出是否满足样本参考或场景要求", "verdict_basis": "semantic judge unavailable; local probe is not a correctness judge", "boundary_sources": "impl/projects/QA/evaluation.md", "conflict_policy": "do not infer correct/incorrect from text overlap or answer length"},
            primary_assessment={"boundary_id": scenario or "qa_fallback", "score": None, "covered": [], "missing": blocking_gaps, "wrong": [], "reasoning": reason},
            missing=[],
            wrong=[],
            extra=[],
            evidence=evidence,
            reasoning_summary=reason,
            score_details=[],
            needs_human_review=True,
            scenario=scenario,
            quality_flags=["qa_local_evidence_probe", "semantic_judge_unavailable"],
            raw_model_output=judge_result.raw_model_output,
        )

    def _expected_reference_from_judge(self, expected: Any) -> Dict[str, str]:
        if isinstance(expected, dict):
            value = expected.get("golden_answer") or expected.get("gold_answer") or expected.get("actual_answer") or expected.get("answer") or expected.get("text")
            if value:
                return {"golden_answer": str(value)}
        if isinstance(expected, str) and expected.strip():
            return {"golden_answer": expected.strip()}
        return {}

    def _generate_reference(self, request: Dict[str, Any], actual_text: str, contexts: List[Any], scenario: str) -> Dict[str, str]:
        question = str((request.get("input") or {}).get("question") or "").strip()
        if scenario == "qa_context_faithfulness" and contexts:
            context_text = " ".join(str(ctx).strip() for ctx in contexts if str(ctx).strip())
            if context_text:
                return {"golden_answer": context_text}
        if question:
            return {"golden_answer": f"需要围绕问题“{question}”生成可核验的参考答案；当前样本未提供 golden_answer，不能把 actual_answer 直接当作参考答案。"}
        return {}

    def _text_overlap_ratio(self, actual: str, expected: str) -> float:
        expected_chars = {char for char in expected if not char.isspace() and char not in "，。！？；：,.!?;:"}
        actual_chars = {char for char in actual if not char.isspace() and char not in "，。！？；：,.!?;:"}
        if not expected_chars:
            return 0.0
        return len(expected_chars & actual_chars) / len(expected_chars)

    def build_mock_cases(self) -> list[Dict[str, Any]]:
        return [
            {
                "id": "qa-gold-1",
                "input": {
                    "question": "什么是犹豫期？",
                    "actual_answer": "犹豫期是投保人收到保险合同后，在规定天数内可申请解除合同并通常退还已交保费的期限。",
                    "golden_answer": "犹豫期是投保人收到保险合同后，在规定天数内可申请解除合同并通常退还已交保费的期限。",
                },
                "metadata": {
                    "category": "insurance_qa",
                },
                "source": "mock_agent_seed",
                "status": "pending",
                "scenario": "qa_gold_answer",
            },
            {
                "id": "qa-gold-partial-1",
                "input": {
                    "question": "等待期内因疾病出险是否赔付？",
                    "actual_answer": "等待期内疾病出险一般不赔。",
                    "golden_answer": "等待期内因疾病发生保险事故通常不承担保险责任，合同另有约定或意外事故除外。",
                    "category": "insurance_qa",
                    "model_name": "sample_answer_v1",
                },
                "source": "mock_agent_seed",
                "status": "pending",
                "scenario": "qa_gold_answer",
            },
            {
                "id": "qa-flat-1",
                "question": "重疾险和医疗险有什么区别？",
                "actual_answer": "重疾险通常按约定疾病一次性给付保险金，医疗险按实际医疗费用报销。",
                "golden_answer": "重疾险达到合同约定疾病状态后给付保险金，医疗险主要补偿实际发生且符合约定的医疗费用。",
                "metadata": {
                    "category": "flat_uploaded_dataset",
                },
                "source": "mock_agent_seed",
                "status": "pending",
            },
            {
                "id": "qa-rag-1",
                "input": {
                    "question": "材料中产品等待期多久？",
                    "contexts": ["产品条款写明：疾病责任等待期为90天，意外责任无等待期。"],
                    "actual_answer": "疾病责任等待期是90天，意外责任没有等待期。",
                },
                "source": "mock_agent_seed",
                "status": "pending",
                "scenario": "qa_context_faithfulness",
            },
            {
                "id": "qa-rag-unsupported-1",
                "input": {
                    "question": "材料中免赔额是多少？",
                    "contexts": ["保障责任包含住院医疗、特殊门诊和住院前后门急诊，未提及免赔额。"],
                    "actual_answer": "免赔额是1万元。",
                },
                "metadata": {
                    "category": "context_faithfulness",
                },
                "source": "mock_agent_seed",
                "status": "pending",
                "scenario": "qa_context_faithfulness",
            },
            {
                "id": "qa-weak-1",
                "input": {
                    "question": "怎么规划家庭保障？",
                    "answer": "建议先覆盖家庭主要收入来源的寿险、重疾和医疗风险，再根据预算补充教育金或养老规划。",
                },
                "source": "mock_agent_seed",
                "status": "pending",
                "scenario": "qa_weak_quality",
            },
            {
                "id": "qa-missing-output-1",
                "input": {
                    "question": "投保前为什么要健康告知？",
                    "gold_answer": "健康告知用于让保险公司评估被保险人的健康风险，决定是否承保、加费、除外或延期。",
                },
                "metadata": {
                    "category": "data_quality",
                },
                "source": "mock_agent_seed",
                "status": "pending",
                "scenario": "qa_gold_answer",
            },
        ]

    def build_mock_datasets(self) -> list[Dict[str, Any]]:
        cases = self.build_mock_cases()
        return [{"dataset_id": "qa_mixed_scenarios_seed", "name": "QA 混合场景样例", "dimension_type": "qa_scenario", "description": "覆盖 golden/context/weak、flat 上传字段、缺失 reference 生成和数据质量场景。", "case_count": len(cases), "cases": cases}]

    def _normalize_sample(self, data: Dict[str, Any]) -> Dict[str, Any]:
        input_part = dict(data.get("input") or {}) if isinstance(data.get("input"), dict) else {}
        output_part = dict(data.get("output") or {}) if isinstance(data.get("output"), dict) else {}
        reference_part = dict(data.get("reference") or {}) if isinstance(data.get("reference"), dict) else {}
        metadata = dict(data.get("metadata") or {}) if isinstance(data.get("metadata"), dict) else {}

        question = data.get("question") or input_part.get("question") or input_part.get("user_input") or ""
        contexts = data.get("contexts") if "contexts" in data else input_part.get("contexts", [])
        actual_answer = data.get("actual_answer") or data.get("answer") or output_part.get("actual_answer") or output_part.get("answer") or input_part.get("actual_answer") or input_part.get("answer") or ""
        golden_answer = data.get("golden_answer") or data.get("gold_answer") or reference_part.get("golden_answer") or reference_part.get("gold_answer") or input_part.get("golden_answer") or input_part.get("gold_answer") or ""

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
            "reference": {"golden_answer": str(golden_answer)} if golden_answer else {},
            "metadata": metadata,
            "scenario": str(data.get("scenario") or self._infer_scenario(question, actual_answer, golden_answer, contexts)),
            "data_quality_flags": [],
        }
        sample["data_quality_flags"] = self._quality_flags(sample)
        return sample

    def _normalize_contexts(self, contexts: Any) -> List[Any]:
        if contexts is None or contexts == "":
            return []
        if isinstance(contexts, list):
            return contexts
        return [contexts]

    def _infer_scenario(self, question: Any, actual_answer: Any, golden_answer: Any, contexts: List[Any]) -> str:
        if golden_answer:
            return "qa_gold_answer"
        if contexts:
            return "qa_context_faithfulness"
        if question and actual_answer:
            return "qa_weak_quality"
        return "invalid_sample"

    def _quality_flags(self, sample: Dict[str, Any]) -> List[str]:
        flags = []
        if not sample["input"].get("question"):
            flags.append("missing_question")
        if not sample["output"].get("actual_answer"):
            flags.append("missing_actual_answer")
        scenario = sample.get("scenario")
        if scenario == "qa_gold_answer" and not sample.get("reference", {}).get("golden_answer"):
            flags.append("missing_golden_answer")
        if scenario == "qa_context_faithfulness" and not sample["input"].get("contexts"):
            flags.append("missing_contexts")
        if scenario == "qa_weak_quality":
            flags.append("estimated_quality_only")
        return flags
