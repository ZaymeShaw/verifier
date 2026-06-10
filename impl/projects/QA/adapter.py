from __future__ import annotations

from typing import Any, Dict, List

from impl.core.adapter import ProjectAdapter
from impl.core.schema import JudgeResult


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
        if "llm_call_failed" not in (judge_result.quality_flags or []):
            return judge_result
        result = self._fallback_judge(trace, judge_result)
        return result or judge_result

    def _fallback_judge(self, trace, judge_result):
        actual = trace.extracted_output or {}
        actual_text = str(actual.get("actual_answer") or "").strip()
        request = trace.normalized_request or {}
        reference = request.get("reference") or trace.project_fields.get("reference") or {}
        golden_text = str(reference.get("golden_answer") or "").strip()
        contexts = list((request.get("input") or {}).get("contexts") or [])
        scenario = str(trace.project_fields.get("scenario") or request.get("scenario") or "")
        if scenario == "qa_gold_answer" and golden_text:
            score, verdict, missing = self._compare_answer(actual_text, golden_text)
            reason = "LLM judge 不可用，已使用 QA golden answer 的确定性覆盖率兜底。"
            evidence = [f"actual_answer={actual_text}", f"golden_answer={golden_text}"]
        elif scenario == "qa_context_faithfulness" and contexts:
            score = 1.0 if actual_text and any(self._text_overlap_ratio(actual_text, str(ctx)) >= 0.35 for ctx in contexts) else 0.5 if actual_text else 0.0
            verdict = "correct" if score >= 0.75 else "incorrect" if score < 0.5 else "uncertain"
            missing = [] if score >= 0.5 else ["answer lacks support from provided contexts"]
            reason = "LLM judge 不可用，已使用 QA context faithfulness 的文本重叠兜底。"
            evidence = [f"actual_answer={actual_text}", f"contexts={contexts}"]
        elif scenario == "qa_weak_quality":
            score = 0.75 if len(actual_text) >= 20 else 0.4 if actual_text else 0.0
            verdict = "correct" if score >= 0.7 else "incorrect" if score < 0.5 else "uncertain"
            missing = [] if score >= 0.7 else ["answer is too short or empty for weak-quality usefulness estimate"]
            reason = "LLM judge 不可用，已使用 QA weak-quality 的基础可用性兜底；该场景只作为质量估计。"
            evidence = [f"actual_answer={actual_text}"]
        else:
            return None
        return JudgeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            verdict=verdict,
            score=score,
            confidence=0.55,
            expected=reference or None,
            actual=actual,
            reconstructed_intent=str((request.get("input") or {}).get("question") or ""),
            judge_basis="qa_deterministic_fallback_after_llm_failure",
            boundary_decision={"within_evaluable_scope": scenario != "invalid_sample", "reasoning": reason},
            evaluation_boundary={"primary_boundary_id": scenario or "qa_fallback", "primary_boundary_name": "QA fallback evaluation", "judge_question": "当前 QA 输出是否满足样本参考或场景要求", "verdict_basis": reason, "boundary_sources": "impl/projects/QA/evaluation.md", "conflict_policy": "fallback is conservative when evidence is insufficient"},
            primary_assessment={"boundary_id": scenario or "qa_fallback", "score": score, "covered": [] if missing else ["basic scenario requirement covered"], "missing": missing, "wrong": [], "reasoning": reason},
            missing=missing,
            wrong=[],
            extra=[],
            evidence=evidence,
            reasoning_summary=reason,
            score_details=[{"name": "fallback_score", "score": score, "weight": 1, "reason": reason}],
            needs_human_review=verdict == "uncertain",
            scenario=scenario,
            quality_flags=["llm_call_failed", "deterministic_fallback"],
            raw_model_output=judge_result.raw_model_output,
        )

    def _compare_answer(self, actual: str, golden: str):
        if not actual:
            return 0.0, "incorrect", ["actual_answer is empty"]
        ratio = self._text_overlap_ratio(actual, golden)
        if actual == golden or ratio >= 0.72:
            return 1.0, "correct", []
        if ratio >= 0.45:
            return 0.65, "uncertain", ["golden answer is only partially covered"]
        return 0.3, "incorrect", ["golden answer is mostly missing"]

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
                    "actual_answer": "犹豫期通常是投保人收到合同后的一段可无条件退保期限。",
                    "golden_answer": "犹豫期是投保人收到保险合同后，在规定天数内可申请解除合同并通常退还已交保费的期限。",
                    "category": "insurance_qa",
                },
                "source": "mock_agent_seed",
                "status": "pending",
                "scenario": "qa_gold_answer",
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
                "id": "qa-weak-1",
                "input": {
                    "question": "怎么规划家庭保障？",
                    "actual_answer": "建议先覆盖家庭主要收入来源的寿险、重疾和医疗风险，再根据预算补充教育金或养老规划。",
                },
                "source": "mock_agent_seed",
                "status": "pending",
                "scenario": "qa_weak_quality",
            },
        ]

    def build_mock_datasets(self) -> list[Dict[str, Any]]:
        cases = self.build_mock_cases()
        return [{"dataset_id": "qa_mixed_scenarios_seed", "name": "QA 混合场景样例", "dimension_type": "qa_scenario", "description": "覆盖 golden/context/weak 三类 QA scenario。", "case_count": len(cases), "cases": cases}]

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
