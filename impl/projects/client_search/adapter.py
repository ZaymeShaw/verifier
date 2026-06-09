from __future__ import annotations

import threading
import time
from typing import Any, Dict

from impl.core.adapter import ProjectAdapter
from impl.core.schema import JudgeResult, RunTrace


_SERVICE_LOCK = threading.Lock()


class Adapter(ProjectAdapter):
    equivalent_condition_forms = {
        "pCategorys": {
            ("MATCH", "疾病保险"): ("CONTAINS", ("疾病保险",)),
        }
    }

    field_patterns = {
        "clientAge": {
            "field": "clientAge",
            "operator": "RANGE/GTE/LTE/MATCH",
            "value_type": "number",
            "definition": "客户年龄字段，用于年龄精确值或边界条件筛选。",
            "examples": ["45岁女性保费10万以上", "大于50岁的客户"],
        },
        "clientSex": {
            "field": "clientSex",
            "operator": "MATCH",
            "value_type": "enum",
            "enums": ["男", "女"],
            "definition": "客户性别字段。",
            "examples": ["45岁女性保费10万以上"],
        },
        "annPremSegNum": {
            "field": "annPremSegNum",
            "operator": "GTE/LTE/RANGE/MATCH",
            "value_type": "number",
            "definition": "年缴保费金额字段，中文金额单位需要换算成数值。",
            "examples": ["45岁女性保费10万以上", "年缴保费一万以上的客户"],
        },
        "polNoInfo.payamountdue": {
            "field": "polNoInfo.payamountdue",
            "operator": "MATCH",
            "value_type": "enum",
            "enums": ["是", "否"],
            "definition": "生存金未领取金额是否大于0；是表示存在未领取生存金。",
            "examples": ["有未领生存金的", "有生存金未领取的客户"],
        },
        "pCategorys": {
            "field": "pCategorys",
            "operator": "CONTAINS/NOT_CONTAINS",
            "value_type": "list",
            "definition": "险种大类字段，用于年金险、两全险、重疾险等保险类别筛选。",
            "examples": ["买了年金险或两全险的客户", "只有重疾险的客户"],
        },
    }

    def build_request(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        nested_input = input_data.get("input") if isinstance(input_data.get("input"), dict) else {}
        query = input_data.get("query") or input_data.get("user_text") or nested_input.get("query") or nested_input.get("user_text") or ""
        extra = dict(input_data.get("extra_input_params") or nested_input.get("extra_input_params") or {})
        return {
            "user_text": query,
            "user_id": input_data.get("user_id") or "eval-user",
            "trace_id": input_data.get("trace_id") or f"general-eval-{int(time.time() * 1000)}",
            "session_id": input_data.get("session_id") or "general-eval-session",
            "source": input_data.get("source") or "askbob",
            "extra_input_params": extra,
        }

    def call_or_prepare(self, request: Dict[str, Any]) -> Any:
        with _SERVICE_LOCK:
            return super().call_or_prepare(request)

    def provided_output_raw(self, input_data: Dict[str, Any], request: Dict[str, Any]) -> Any:
        if "raw_response" in input_data:
            return input_data["raw_response"]
        if "response" in input_data:
            return input_data["response"]
        output = input_data.get("output") or {}
        if not isinstance(output, dict):
            return output
        if "data" in output:
            return output
        conditions = output.get("conditions") or output.get("structured_output") or []
        logic = output.get("query_logic") or output.get("logic") or "AND"
        query = request.get("user_text") or output.get("source_query") or ""
        return {
            "code": output.get("status_code", 0),
            "message": output.get("summary") or "provided client_search output",
            "data": {
                "query": query,
                "robot_text": output.get("user_visible_text") or output.get("summary") or "provided output",
                "extra_output_params": {
                    "query_logic": logic,
                    "conditions": conditions,
                    "matched_level": output.get("matched_level"),
                    "intent_summary": output.get("summary") or "provided output",
                    "matched_patterns": output.get("matched_patterns") or [],
                    "rewritten_query": output.get("source_query") or query,
                },
            },
        }

    def _response_query(self, raw_response: Dict[str, Any], extra: Dict[str, Any]) -> str:
        data = raw_response.get("data") or {}
        return extra.get("rewritten_query") or extra.get("query") or data.get("query") or ""

    def _empty_result_reason(self, query: str, extra: Dict[str, Any]) -> str:
        if extra.get("conditions"):
            return ""
        if not query:
            return "empty_query"
        return "service_returned_no_conditions"

    def extract_output(self, raw_response: Any) -> Dict[str, Any]:
        if not isinstance(raw_response, dict):
            return {"raw_text": str(raw_response)}
        extra = (((raw_response.get("data") or {}).get("extra_output_params")) or {})
        query = self._response_query(raw_response, extra)
        empty_reason = self._empty_result_reason(query, extra)
        return {
            "summary": extra.get("intent_summary") or raw_response.get("message") or raw_response.get("msg") or "",
            "structured_output": extra.get("conditions") or [],
            "logic": extra.get("query_logic"),
            "status_code": raw_response.get("code"),
            "user_visible_text": ((raw_response.get("data") or {}).get("robot_text")),
            "empty_result_reason": empty_reason,
            "is_empty_result": bool(empty_reason),
            "source_query": query,
        }

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(raw_response, dict):
            return {}
        extra = (((raw_response.get("data") or {}).get("extra_output_params")) or {})
        return {
            "query_logic": extra.get("query_logic"),
            "conditions": extra.get("conditions"),
            "matched_level": extra.get("matched_level"),
            "intent_summary": extra.get("intent_summary"),
            "matched_patterns": extra.get("matched_patterns"),
            "rewritten_query": extra.get("rewritten_query"),
            "source_query": extracted_output.get("source_query"),
            "empty_result_reason": extracted_output.get("empty_result_reason"),
            "is_empty_result": extracted_output.get("is_empty_result"),
        }

    def build_execution_trace(self, input_data: Dict[str, Any], request: Dict[str, Any], raw_response: Any, extracted_output: Dict[str, Any]) -> list[Dict[str, Any]]:
        extra = (((raw_response.get("data") or {}).get("extra_output_params")) or {}) if isinstance(raw_response, dict) else {}
        return [
            {"stage": "adapter.build_request", "status": "ok", "evidence": {"user_text": request.get("user_text"), "source": request.get("source")}},
            {"stage": "client_search.api", "status": "ok" if isinstance(raw_response, dict) and raw_response.get("code") == 0 else "suspicious", "evidence": {"code": raw_response.get("code") if isinstance(raw_response, dict) else None}},
            {"stage": "client_search.routing", "status": "ok" if extra.get("matched_level") is not None else "not_verified", "evidence": {"matched_level": extra.get("matched_level"), "matched_patterns": extra.get("matched_patterns")}},
            {"stage": "adapter.extract_output", "status": "suspicious" if extracted_output.get("is_empty_result") else "ok", "evidence": {"logic": extracted_output.get("logic"), "condition_count": len(extracted_output.get("structured_output") or []), "empty_result_reason": extracted_output.get("empty_result_reason")}},
        ]

    def _hashable_value(self, value: Any) -> Any:
        if isinstance(value, list):
            return tuple(self._hashable_value(item) for item in value)
        if isinstance(value, dict):
            return tuple(sorted((key, self._hashable_value(item)) for key, item in value.items()))
        return value

    def _jsonable_value(self, value: Any) -> Any:
        if isinstance(value, tuple):
            if all(isinstance(item, tuple) and len(item) == 2 for item in value):
                return {key: self._jsonable_value(item) for key, item in value}
            return [self._jsonable_value(item) for item in value]
        return value

    def _canonical_condition(self, condition: Any) -> Any:
        if not isinstance(condition, dict):
            return condition
        field = condition.get("field")
        operator = condition.get("operator")
        value = condition.get("value")
        normalized_value = self._hashable_value(value)
        equivalent = self.equivalent_condition_forms.get(field, {}).get((operator, normalized_value))
        if equivalent:
            operator, normalized_value = equivalent
        normalized_value = self._jsonable_value(normalized_value)
        return {"field": field, "operator": operator, "value": normalized_value}

    def _canonical_conditions(self, value: Any) -> list[Any]:
        if isinstance(value, dict):
            conditions = value.get("conditions") or value.get("structured_output") or []
        else:
            conditions = value if isinstance(value, list) else []
        return [self._canonical_condition(condition) for condition in conditions]

    def normalize_judge_result(self, trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
        if judge_result.verdict == "correct":
            return judge_result
        expected = self._canonical_conditions(judge_result.expected)
        actual = self._canonical_conditions(judge_result.actual or trace.extracted_output)
        if not expected or expected != actual:
            return judge_result
        judge_result.verdict = "correct"
        judge_result.score = 1
        judge_result.confidence = max(float(judge_result.confidence or 0), 0.9)
        judge_result.probability = max(float(judge_result.probability or 0), 0.9)
        judge_result.actual = {"query_logic": trace.extracted_output.get("logic") or "AND", "conditions": actual}
        judge_result.expected = {"query_logic": "AND", "conditions": expected}
        judge_result.wrong = []
        judge_result.missing = []
        judge_result.extra = []
        judge_result.reasoning_summary = "按项目后处理等价规则归一后，actual 与 expected 条件语义一致。"
        judge_result.judge_basis = "project_equivalent_condition_normalization"
        judge_result.quality_flags = [flag for flag in judge_result.quality_flags if flag not in {"operator_mismatch", "llm_call_failed"}]
        return judge_result

    def build_mock_cases(self) -> list[Dict[str, Any]]:
        queries = [
            "45岁女性保费10万以上",
            "有生存金未领取的客户",
            "年缴保费一万以上的客户",
            "45岁以上女性客户",
            "买了年金险或两全险的客户",
            "大于50岁的客户",
            "只有重疾险的客户",
            "上有老下有小的客户",
        ]
        return [
            {
                "id": f"client-search-seed-{index + 1}",
                "input": {"query": query},
                "expected_intent": "",
                "source": "mock_agent_seed",
                "status": "pending",
            }
            for index, query in enumerate(queries)
        ]

    def build_mock_datasets(self) -> list[Dict[str, Any]]:
        dimensions = [
            {
                "dataset_id": "client_search_demographic_100",
                "name": "客户基础画像筛选",
                "dimension_type": "demographic_profile",
                "description": "年龄、性别、婚姻、学历等客户基础画像查询。",
                "templates": [
                    "{age}岁{sex}性客户",
                    "{age}岁以上{sex}性客户",
                    "{age_min}到{age_max}岁的客户",
                    "{marriage}客户",
                    "{education}以上学历客户",
                    "{age}岁{marriage}{sex}性客户",
                ],
                "values": {
                    "age": [25, 30, 35, 40, 45, 50, 55, 60],
                    "age_min": [20, 30, 40, 50],
                    "age_max": [35, 45, 55, 65],
                    "sex": ["男", "女"],
                    "marriage": ["已婚", "未婚", "离异"],
                    "education": ["大专", "本科", "硕士"],
                },
            },
            {
                "dataset_id": "client_search_premium_policy_100",
                "name": "保费与保单状态筛选",
                "dimension_type": "premium_policy",
                "description": "年缴保费、保单状态、到期、缴费等保单经营查询。",
                "templates": [
                    "年缴保费超过{premium}的客户",
                    "保费{premium}以上的{sex}性客户",
                    "{status}保单客户",
                    "保单{expire_window}到期的客户",
                    "{age}岁以上年缴保费{premium}以上客户",
                    "{pay_status}的客户",
                ],
                "values": {
                    "premium": ["一万", "三万", "五万", "十万", "二十万"],
                    "sex": ["男", "女"],
                    "status": ["有效", "失效", "满期", "退保"],
                    "expire_window": ["今年", "明年", "三个月内", "半年内"],
                    "age": [30, 40, 50, 60],
                    "pay_status": ["续期未缴费", "保费已缴清", "有欠缴保费"],
                },
            },
            {
                "dataset_id": "client_search_product_coverage_100",
                "name": "险种与保障配置筛选",
                "dimension_type": "product_coverage",
                "description": "持有/未持有险种、保障类别、保额等产品配置查询。",
                "templates": [
                    "买了{product}的客户",
                    "没有配置{product}的客户",
                    "只买了{product}的客户",
                    "买了{product_a}或{product_b}的客户",
                    "{age}岁以上未配置{product}的客户",
                    "{product}保额{coverage}以上的客户",
                ],
                "values": {
                    "product": ["重疾险", "医疗险", "意外险", "年金险", "两全险", "终身寿险", "定期寿险"],
                    "product_a": ["年金险", "重疾险", "医疗险"],
                    "product_b": ["两全险", "意外险", "终身寿险"],
                    "age": [30, 40, 50, 60],
                    "coverage": ["10万", "30万", "50万", "100万"],
                },
            },
            {
                "dataset_id": "client_search_family_lifecycle_100",
                "name": "家庭结构与生命周期筛选",
                "dimension_type": "family_lifecycle",
                "description": "子女、父母、配偶、上有老下有小、教育金等家庭场景查询。",
                "templates": [
                    "有{child}的客户",
                    "子女{child_age}岁以上的客户",
                    "父母{parent_age}岁以上的客户",
                    "上有老下有小的客户",
                    "{sex}性且有子女的客户",
                    "{age}岁左右关注子女教育的客户",
                ],
                "values": {
                    "child": ["儿子", "女儿", "未成年子女", "两个孩子"],
                    "child_age": [3, 6, 10, 15, 18],
                    "parent_age": [55, 60, 65, 70, 75],
                    "sex": ["男", "女"],
                    "age": [30, 35, 40, 45],
                },
            },
            {
                "dataset_id": "client_search_value_service_100",
                "name": "客户价值与服务机会筛选",
                "dimension_type": "value_service_opportunity",
                "description": "VIP、客户价值、客户温度、生存金未领取、服务触达机会等经营动作查询。",
                "templates": [
                    "{vip}客户",
                    "客户价值{value_level}的客户",
                    "客户温度{temperature}的客户",
                    "有生存金未领取的客户",
                    "{age}岁以上{vip}客户",
                    "客户价值{value_level}且持有{product}的客户",
                ],
                "values": {
                    "vip": ["寿险VIP", "高净值", "钻石级", "铂金级"],
                    "value_level": ["高", "中", "低", "A类", "B类"],
                    "temperature": ["高", "中", "低", "活跃", "沉默"],
                    "age": [35, 45, 55, 65],
                    "product": ["重疾险", "年金险", "医疗险", "终身寿险"],
                },
            },
        ]
        return [self._build_dataset(item) for item in dimensions]

    def _build_dataset(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        cases = []
        templates = spec["templates"]
        values = spec["values"]
        keys = list(values)
        for index in range(100):
            template = templates[index % len(templates)]
            params = {key: values[key][(index + offset) % len(values[key])] for offset, key in enumerate(keys)}
            query = template.format(**params)
            cases.append({
                "id": f"{spec['dataset_id']}-{index + 1:03d}",
                "input": {"query": query},
                "expected_intent": "",
                "source": "mock_dataset_agent",
                "status": "pending",
                "dimension_type": spec["dimension_type"],
                "dataset_id": spec["dataset_id"],
            })
        return {**{key: spec[key] for key in ["dataset_id", "name", "dimension_type", "description"]}, "case_count": len(cases), "cases": cases}

    def mock_response(self, request: Dict[str, Any]) -> Dict[str, Any]:
        query = request.get("user_text") or ""
        examples = {
            "45岁女性保费10万以上": [
                {"field": "clientAge", "operator": "RANGE", "value": {"min": 45, "max": 45}},
                {"field": "clientSex", "operator": "MATCH", "value": "女"},
                {"field": "annPremSegNum", "operator": "GTE", "value": 100000},
            ],
            "有生存金未领取的客户": [
                {"field": "polNoInfo.payamountdue", "operator": "MATCH", "value": "是"},
            ],
            "年缴保费一万以上的客户": [
                {"field": "annPremSegNum", "operator": "GTE", "value": 10000},
            ],
            "45岁以上女性客户": [
                {"field": "clientAge", "operator": "GTE", "value": 45},
                {"field": "clientSex", "operator": "MATCH", "value": "女"},
            ],
            "买了年金险或两全险的客户": [
                {"field": "polNoInfo.plancodeinfo.plantypedesc", "operator": "CONTAINS", "value": ["年金", "两全险"]},
            ],
            "大于50岁的客户": [
                {"field": "clientAge", "operator": "GTE", "value": 51},
            ],
            "只有重疾险的客户": [
                {"field": "pCategorys", "operator": "CONTAINS", "value": ["疾病保险"]},
                {"field": "pCategorys", "operator": "NOT_CONTAINS", "value": ["定期寿险", "护理保险", "两全保险", "年金保险", "医疗保险", "意外伤害保险", "终身寿险"]},
            ],
            "上有老下有小的客户": [
                {"field": "familyInfo.familyrelation", "operator": "CONTAINS", "value": ["父母", "(外)祖父母"]},
                {"field": "familyInfo.familyrelation", "operator": "MATCH", "value": "子女"},
            ],
        }
        conditions = examples.get(query, [])
        matched_patterns = [self.field_patterns[item["field"]] for item in conditions if item.get("field") in self.field_patterns]
        return {
            "code": 0,
            "message": "mock client_search response",
            "data": {
                "robot_text": "mock response; real client_search service was not called",
                "extra_output_params": {
                    "query_logic": "AND",
                    "conditions": conditions,
                    "matched_level": 0,
                    "intent_summary": f"mock intent for: {query}",
                    "matched_patterns": matched_patterns,
                    "rewritten_query": query,
                },
            },
        }
