from __future__ import annotations

from typing import Any, Dict, List

from impl.core.adapter import ProjectAdapter


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
