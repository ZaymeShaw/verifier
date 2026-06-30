from __future__ import annotations

import json
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional
from urllib.parse import urljoin

from impl.core.adapter import ProjectAdapter
from impl.core.schema import AttributeResult, JudgeResult, RunTrace
from impl.projects.client_search.tools import ClientSearchConditionCompareTool, ClientSearchFieldDefinitionSearchTool
from impl.tools import ToolContext, ToolRegistry

import yaml as _yaml


_SERVICE_LOCK = threading.Lock()


class Adapter(ProjectAdapter):
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

    def _capability_manifest(self) -> dict:
        """Generate full field capability manifest from source YAML configs."""
        try:
            config_paths = self._source_config_paths()
            definitions_path = config_paths.get('source_field_definitions')
            if not definitions_path or not Path(definitions_path).exists():
                return {}
            with open(definitions_path) as f:
                data = _yaml.safe_load(f)
            intents = data.get('intents', [])
            fields = {}
            for item in intents:
                fn = item.get('field', '')
                if not fn:
                    continue
                if fn not in fields:
                    fields[fn] = {
                        'field': fn,
                        'operators': set(),
                        'value_types': set(),
                        'description': item.get('description', ''),
                        'definition': item.get('description', ''),
                        'enums': item.get('enum') or [],
                        'unit': item.get('unit') or '',
                        'notes': item.get('notes', ''),
                    }
                fields[fn]['operators'].add(item.get('operator', ''))
                fields[fn]['value_types'].add(item.get('value_type', ''))
            for f in fields.values():
                f['operators'] = sorted(f['operators'])
                f['value_types'] = sorted(f['value_types'])
            return {k: {**v, 'operators': v['operators'], 'value_types': v['value_types']} for k, v in fields.items()}
        except Exception:
            return {}

    def _value_mappings(self) -> dict:
        """Load field-specific spoken-to-standard enum value mappings from source YAML."""
        try:
            config_paths = self._source_config_paths()
            path = config_paths.get('source_value_mappings')
            if not path or not Path(path).exists():
                return {}
            with open(path) as f:
                data = _yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _enhanced_rules(self) -> dict:
        """Load L2 regex matching rules from source YAML."""
        try:
            config_paths = self._source_config_paths()
            path = config_paths.get('source_enhanced_rules')
            if not path or not Path(path).exists():
                return {}
            with open(path) as f:
                data = _yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def protocol_tools(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(ClientSearchConditionCompareTool())
        registry.register(ClientSearchFieldDefinitionSearchTool())
        return registry

    def _source_config_paths(self) -> Dict[str, str]:
        paths = {}
        root = Path(self.spec.root)
        for key, rel in (self.spec.documents or {}).items():
            if key.startswith("source_") and "config/" in str(rel):
                paths[key] = str((root / str(rel)).resolve())
        return paths

    def _external_boundary_sources(self) -> Dict[str, Any]:
        return {"config_paths": self._source_config_paths()}

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

    def to_run_trace(self, input_data: Dict[str, Any], request: Dict[str, Any], raw_response: Any):
        if isinstance(raw_response, dict):
            raw_response = {**raw_response, "_downstream_search": self._probe_downstream_search(raw_response)}
        return super().to_run_trace(input_data, request, raw_response)

    def _probe_downstream_search(self, raw_response: Dict[str, Any]) -> Dict[str, Any]:
        config = self.spec.application.get("downstream_search") if isinstance(self.spec.application, dict) else None
        if not isinstance(config, dict) or not config.get("enabled", True):
            return {"status": "not_configured"}
        extra = (((raw_response.get("data") or {}).get("extra_output_params")) or {})
        conditions = list(extra.get("conditions") or [])
        query_logic = str(extra.get("query_logic") or "AND")
        payload = {
            "header": {"agent_id": "eval-user", "page": 1, "size": 20},
            "query_logic": query_logic,
            "conditions": conditions,
        }
        if not conditions:
            return {"status": "skipped", "reason": "parse returned no conditions", "payload": payload}
        base_url = str(config.get("base_url") or "").rstrip("/") + "/"
        endpoint = str(config.get("endpoint") or "").lstrip("/")
        if not base_url.strip("/") or not endpoint:
            return {"status": "not_configured", "payload": payload}
        url = urljoin(base_url, endpoint)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        search_request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method=str(config.get("method") or "POST").upper())
        try:
            with urllib.request.urlopen(search_request, timeout=float(config.get("timeout") or 3)) as response:
                text = response.read().decode("utf-8")
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                result = {"text": text}
            return {"status": "ok", "url": url, "payload": payload, "result": result}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {"status": "unavailable", "url": url, "payload": payload, "error": str(exc)}

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
        downstream_search = raw_response.get("_downstream_search") if isinstance(raw_response.get("_downstream_search"), dict) else {}
        application_boundary = self._application_boundary(downstream_search)
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
            "downstream_search": downstream_search,
            "application_boundary": application_boundary,
            "external_boundary_sources": self._external_boundary_sources(),
        }

    def build_execution_trace(self, input_data: Dict[str, Any], request: Dict[str, Any], raw_response: Any, extracted_output: Dict[str, Any]) -> list[Dict[str, Any]]:
        extra = (((raw_response.get("data") or {}).get("extra_output_params")) or {}) if isinstance(raw_response, dict) else {}
        downstream_search = raw_response.get("_downstream_search") if isinstance(raw_response, dict) and isinstance(raw_response.get("_downstream_search"), dict) else {}
        return [
            {"stage": "adapter.build_request", "status": "ok", "evidence": {"user_text": request.get("user_text"), "source": request.get("source")}},
            {"stage": "client_search.api", "status": "ok" if isinstance(raw_response, dict) and raw_response.get("code") == 0 else "suspicious", "evidence": {"code": raw_response.get("code") if isinstance(raw_response, dict) else None}},
            {"stage": "client_search.routing", "status": "ok" if extra.get("matched_level") is not None else "not_verified", "evidence": {"matched_level": extra.get("matched_level"), "matched_patterns": extra.get("matched_patterns")}},
            {"stage": "client_search.downstream_search", "status": downstream_search.get("status") or "not_verified", "evidence": downstream_search},
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

    def _semantic_equivalence_config(self) -> Dict[str, Any]:
        extensions = self.spec.frontend_extensions or {}
        config = extensions.get("semantic_equivalence_rules")
        return config if isinstance(config, dict) else {}

    def _equivalent_condition_forms(self) -> Dict[str, Dict[Any, Any]]:
        forms: Dict[str, Dict[Any, Any]] = {}
        for item in self._semantic_equivalence_config().get("equivalent_condition_forms") or []:
            if not isinstance(item, dict):
                continue
            field = item.get("field")
            operator = item.get("operator")
            equivalent_operator = item.get("equivalent_operator")
            if not field or not operator or not equivalent_operator:
                continue
            value = self._hashable_value(item.get("value"))
            equivalent_value = self._hashable_value(item.get("equivalent_value"))
            forms.setdefault(str(field), {})[(str(operator), value)] = (str(equivalent_operator), equivalent_value)
        return forms

    def _canonical_condition(self, condition: Any) -> Any:
        if not isinstance(condition, dict):
            return condition
        field = condition.get("field")
        operator = condition.get("operator")
        value = condition.get("value")
        normalized_value = self._hashable_value(value)
        equivalent = self._equivalent_condition_forms().get(field, {}).get((operator, normalized_value))
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

    def semantic_equivalence_rules(self) -> list[Dict[str, Any]]:
        config = self._semantic_equivalence_config()
        rules = []
        rules.extend(list(config.get("equivalent_condition_forms") or []))
        rules.extend(list(config.get("operator_compatibility") or []))
        rules.extend(list(config.get("equivalent_fields") or []))
        return rules

    def _semantic_equivalence_rules(self) -> list[Dict[str, Any]]:
        return self.semantic_equivalence_rules()

    def _intent_expected_conditions(self, trace: RunTrace) -> Dict[str, Any]:
        for source in (trace.project_fields.get("intent_expected") if trace.project_fields else None, trace.normalized_request.get("intent_expected") if trace.normalized_request else None):
            if isinstance(source, dict) and source.get("conditions"):
                return source
        return {}

    def _condition_comparison(self, trace: RunTrace) -> Dict[str, Any]:
        inputs = {"expected": self._intent_expected_conditions(trace)}
        results = self.run_protocol_tools(trace, purpose="judge", tool_type="comparison", inputs=inputs)
        result = next((item for item in results if item.tool_id == "client_search.condition_compare"), None)
        if result is None:
            result = self.protocol_tools().run(
                "client_search.condition_compare",
                ToolContext(project_id=self.spec.project_id, purpose="judge", spec=self.spec, trace=trace, inputs=inputs),
            )
        return {
            "tool_id": result.tool_id,
            "tool_type": result.tool_type,
            "status": result.status,
            "outputs": result.outputs,
            "evidence": result.evidence,
            "boundary_limits": result.boundary_limits,
            "error": result.error,
        }

    def _judge_governance(self) -> Dict[str, Any]:
        return {
            "canonical_method": "current_case_llm_judge",
            "judge_role": "只判断当前 API actual output 是否语义覆盖当前 query，不做根因归因。",
            "must_ignore_as_verdict_basis": ["HTTP 200", "review_verdict", "source", "run_status", "root_cause_cluster", "attribute_result", "cluster", "history"],
            "binary_when_evidence_sufficient": True,
            "uncertain_only_when": ["LLM/API judge 调用不可用", "当前配置/枚举/字段证据不足以判断 expected-vs-actual", "application_boundary 明确排除了该需求且无法判断范围内输出"],
            "actual_output_priority": "以 API 最终 actual conditions 的下游可执行语义为准；prompt/config/后处理存在表述冲突时，先判断 actual 是否能搜出用户核心意图，再把冲突写入 evidence/check。",
            "required_comparison": ["query core intent", "field semantic carrier", "operator for field type", "value normalization", "query_logic", "missing/wrong/extra conditions"],
        }

    def _attribute_quality_gate(self) -> Dict[str, Any]:
        return {
            "run_only_for": ["incorrect", "uncertain with inspectable expected-vs-actual gap"],
            "block_when_judge_unavailable": True,
            "minimum_evidence": ["current query", "actual conditions/matched_level", "judge expected-vs-actual diff", "execution_trace or project chain nodes", "project docs/config evidence"],
            "required_outputs": ["clear root_cause_hypothesis", "evidence-backed chain_nodes", "earliest_divergence", "suspected_locations only when evidenced", "specific verification_steps", "minimal patch_direction", "business_impact", "analysis_quality"],
            "quality_standard": "必须围绕当前 query 产出明确根因、可核验证据链、疑似文件/配置位置、具体修改建议、明确修改方案和业务影响；期望条件和修改方案必须来自当前 query 或同 query 链路证据，不能引用无关历史 case 字段。",
        }

    def _default_consumer_contract(self, trace: RunTrace, judge_result: JudgeResult) -> Dict[str, Any]:
        context = self.build_judge_context(trace)
        return {
            "consumer": "downstream client search",
            "contract": "parsed field/operator/value conditions and query logic must be executable for downstream client search within the active application boundary",
            "reference_contract": context.get("field_patterns") or {},
            "application_boundary": context.get("application_boundary") or {},
        }

    def _comparison_outputs(self, trace: RunTrace) -> Dict[str, Any]:
        return (self._condition_comparison(trace).get("outputs") or {})

    def _apply_condition_comparison(self, trace: RunTrace, judge_result: JudgeResult) -> None:
        comparison = self._comparison_outputs(trace)
        if not comparison:
            return
        wrong = list(comparison.get("wrong") or [])
        missing = list(comparison.get("missing") or [])
        extra = list(comparison.get("extra") or [])
        if wrong or missing or extra:
            # Save LLM original gaps before replacing
            derivation = dict(judge_result.verdict_derivation or {})
            derivation["llm_original_gaps"] = {
                "wrong": list(judge_result.wrong or []),
                "missing": list(judge_result.missing or []),
                "extra": list(judge_result.extra or []),
            }
            judge_result.verdict_derivation = derivation
            if "condition_comparison_overrode_llm_gaps" not in (judge_result.quality_flags or []):
                judge_result.quality_flags = list(judge_result.quality_flags or []) + ["condition_comparison_overrode_llm_gaps"]
            judge_result.wrong = wrong
            judge_result.missing = missing
            judge_result.extra = extra
        judge_result.condition_assessments = [
            *[{**item, "status": "wrong"} for item in wrong if isinstance(item, dict)],
            *[{**item, "status": "missing"} for item in missing if isinstance(item, dict)],
            *[{**item, "status": "extra"} for item in extra if isinstance(item, dict)],
        ] or judge_result.condition_assessments
        expected = comparison.get("expected")
        actual = comparison.get("actual")
        if expected:
            judge_result.expected = expected
        if actual:
            judge_result.actual = actual
        basis = dict(judge_result.reference_generation_basis or {})
        basis.setdefault("source", comparison.get("expected_source") or "client_search_condition_compare")
        basis.setdefault("comparison_basis", comparison.get("comparison_basis"))
        basis.setdefault("expected_source", comparison.get("expected_source"))
        judge_result.reference_generation_basis = basis
        if comparison.get("evaluable") is False:
            derivation = dict(judge_result.verdict_derivation or {})
            derivation.setdefault("why_verdict", "client_search condition comparison has no current intent/config expected conditions; reference conditions are evidence only")
            derivation.setdefault("missing_evidence", ["current intent/config expected conditions"])
            judge_result.verdict_derivation = derivation
        elif comparison.get("expected_source_label") == "reference_fallback" and not wrong and not missing and not extra:
            # reference_fallback with no gaps → semantically equivalent, clear the uncertain path
            derivation = dict(judge_result.verdict_derivation or {})
            derivation.setdefault("why_verdict", "client_search condition comparison matched reference conditions (fallback); conditions are semantically equivalent")
            judge_result.verdict_derivation = derivation
        elif wrong or missing or extra:
            derivation = dict(judge_result.verdict_derivation or {})
            derivation.setdefault("blocking_gaps", [*(missing or []), *(wrong or []), *(extra or [])])
            derivation.setdefault("why_verdict", "client_search condition comparison found wrong/missing/extra customer-search gaps")
            judge_result.verdict_derivation = derivation

    def _default_business_expectation(self, trace: RunTrace, judge_result: JudgeResult) -> Dict[str, Any]:
        expectation = super()._default_business_expectation(trace, judge_result)
        comparison = self._comparison_outputs(trace)
        expectation.update(
            {
                "expectation_id": "client_search:search_condition_contract",
                "downstream_consumer": "downstream client search",
                "required_capabilities": expectation.get("required_capabilities") or ["field_operator_value_logic", "semantic_equivalence", "downstream_search_executability"],
                "boundary": judge_result.boundary_decision or self.build_judge_context(trace).get("application_boundary") or expectation.get("boundary") or {},
                "comparison_basis": comparison.get("comparison_basis") or "client_search wrong/missing/extra customer-search coverage",
                "expected_source": comparison.get("expected_source"),
            }
        )
        if comparison:
            expectation.update(
                {
                    "user_intent": comparison.get("target_population") or expectation.get("user_intent"),
                    "expected_outcome": "actual search conditions should cover the target customer population without wrong, missing, or extra conditions",
                    "acceptance_criteria": {
                        "expected": comparison.get("expected"),
                        "wrong": comparison.get("wrong") or [],
                        "missing": comparison.get("missing") or [],
                        "extra": comparison.get("extra") or [],
                    },
                }
            )
        elif not judge_result.intent_model:
            expectation.update(
                {
                    "user_intent": str((trace.normalized_request or {}).get("user_text") or (trace.extracted_output or {}).get("source_query") or trace.input or ""),
                    "expected_outcome": "current query should become complete, semantically correct, downstream-executable search conditions",
                    "acceptance_criteria": list(judge_result.condition_assessments or judge_result.missing or judge_result.wrong or []),
                }
            )
        return expectation

    def _default_fulfillment_assessment(self, trace: RunTrace, judge_result: JudgeResult, expectation: Dict[str, Any]) -> Dict[str, Any]:
        comparison = self._comparison_outputs(trace)
        gaps = list(comparison.get("wrong") or []) + list(comparison.get("missing") or []) + list(comparison.get("extra") or [])
        if comparison and comparison.get("evaluable") is False:
            status = "not_evaluable"
        elif comparison and comparison.get("expected_source_label") == "reference_fallback" and not gaps:
            # reference_fallback conditions matched — semantically equivalent
            status = "fulfilled"
        elif comparison:
            status = "not_fulfilled" if gaps else "fulfilled"
        else:
            status = self._expectation_status_from_verdict(judge_result)
        return {
            "expectation_id": expectation.get("expectation_id"),
            "status": status,
            "score": 0 if status == "not_fulfilled" else (1 if status == "fulfilled" else judge_result.score),
            "expected_evidence": [comparison.get("expected")] if comparison else (list(judge_result.missing or []) or [judge_result.expected or self.field_patterns]),
            "actual_evidence": [comparison.get("actual"), {"wrong_missing_extra": gaps}] if comparison else (list(judge_result.wrong or []) or [judge_result.actual or trace.extracted_output]),
            "boundary_decision": judge_result.boundary_decision or self.build_judge_context(trace).get("application_boundary") or {},
            "downstream_impact": "search conditions cover the target customer population" if status == "fulfilled" else (judge_result.reasoning_summary or "wrong/missing/extra conditions change the target customer population"),
            "blocking": status in {"not_fulfilled", "not_evaluable"},
            "confidence": judge_result.confidence,
            "evidence_refs": list(getattr(trace, "evidence_refs", []) or []),
        }

    def _field_definition_search_tool(self, trace: RunTrace):
        tool = ClientSearchFieldDefinitionSearchTool()

        def search_field_definition(field_name: str) -> str:
            """Search client_search field definition by project-local protocol tool."""
            result = self.protocol_tools().run(
                tool.tool_id,
                ToolContext(
                    project_id=self.spec.project_id,
                    purpose="judge",
                    spec=self.spec,
                    trace=trace,
                    inputs={"field_name": field_name},
                ),
            )
            return tool.format_for_llm(result, field_name)

        search_field_definition.__name__ = "search_field_definition"
        search_field_definition.__doc__ = (
            "Search for a client_search field definition, operators, value types, and examples. "
            "Use only when capability_manifest is insufficient for the current field."
        )
        return search_field_definition

    def build_judge_context(self, trace: RunTrace) -> Dict[str, Any]:
        downstream = trace.project_fields.get("downstream_search") if isinstance(trace.project_fields, dict) else {}
        application_boundary = trace.project_fields.get("application_boundary") if isinstance(trace.project_fields, dict) else None
        condition_comparison = self._condition_comparison(trace)
        return {
            "semantic_equivalence_rules": self._semantic_equivalence_rules(),
            "field_patterns": self.field_patterns,
            "application_boundary": application_boundary or self._application_boundary(downstream),
            "judge_governance": self._judge_governance(),
            "condition_comparison": condition_comparison,
            "protocol_tool_results": [condition_comparison],
            "judge_agno_tools": [self._field_definition_search_tool(trace)],
            "client_search_judge_basis": "wrong/missing/extra customer-search condition coverage within current field/config boundary",
            "boundary_usage": "application adapter has already decided whether result-set verification is in scope; judge should evaluate only within application_boundary.judge_scope.",
            "external_boundary_sources": trace.project_fields.get("external_boundary_sources") if isinstance(trace.project_fields, dict) else {},
            "capability_manifest": self._capability_manifest(),
            "value_mappings": self._value_mappings(),
            "enhanced_rules": self._enhanced_rules(),
        }

    def build_intent_frame(self, trace: RunTrace) -> Dict[str, Any]:
        context = self.build_judge_context(trace)
        return {
            **super().build_intent_frame(trace),
            "business_task_type": "natural_language_to_downstream_client_search_conditions",
            "downstream_consumer": "downstream client search",
            "critical_intent_dimensions": ["target_population", "field_semantics", "operator", "value_or_unit", "boolean_logic", "unsupported_or_out_of_boundary_request"],
            "boundary_rules": context.get("application_boundary") or {},
            "output_semantics": "produce complete, semantically correct, downstream-executable search conditions and query logic for the current user request",
            "semantic_equivalence_rules": context.get("semantic_equivalence_rules") or [],
            "field_patterns": context.get("field_patterns") or {},
            "condition_comparison": context.get("condition_comparison") or {},
            "capability_manifest": context.get("capability_manifest") or {},
            "critical_intent_dimensions_detail": {
                "target_population": "目标客户群体描述，驱动 population-sensitive field/operator/value 组合",
                "field_semantics": "请求中提到的字段及其语义定义，优先匹配 capability_manifest 中的 field/description",
                "operator": "每个字段允许的操作符，必须匹配 capability_manifest 中对应字段的 operators 列表",
                "value_or_unit": "值的单位换算与格式规范，如万=10000、岁以上用GTE+1等",
                "boolean_logic": "条件间的 AND/OR/NOT 逻辑关系",
                "unsupported_or_out_of_boundary_request": "系统不支持或超出评估边界的请求，应标记为 not_evaluable",
            },
        }

    def get_runtime_checks(self, runtime_values: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """直接引用 client_search 业务系统原函数，校验条件搜索契约。

        这是 Issue #3 用户诉求（"直接引用业务系统原函数"）的 client_search 落地：
        不再让 attribute agent 读源码/prompt 猜测，而是直接调用 adapter 的
        _capability_manifest（加载 source_field_definitions YAML）、_value_mappings、
        _enhanced_rules、_condition_comparison 等业务判定函数，
        对当前 trace 的 conditions / field definitions / query_logic 做运行时校验，直接产出闭合根因。
        """
        context = context or {}
        expected = context.get("expected") if isinstance(context.get("expected"), dict) else {}
        reference = context.get("reference") if isinstance(context.get("reference"), dict) else {}
        actual = context.get("actual") if isinstance(context.get("actual"), dict) else {}
        actual = actual or runtime_values
        wrong = list(context.get("wrong") or [])
        missing = list(context.get("missing") or [])

        # 1) 直接加载业务系统配置（field definitions / value mappings / enhanced rules）
        capability_manifest = self._capability_manifest()
        value_mappings = self._value_mappings()
        enhanced_rules = self._enhanced_rules()

        field_count = len(capability_manifest)
        value_mapping_field_count = len(value_mappings)
        enhanced_rule_count = len(enhanced_rules)

        # 2) 条件校验：比较 expected vs actual conditions
        expected_conditions = list(expected.get("conditions") or reference.get("expected_conditions") or [])
        actual_conditions = list(actual.get("conditions") or actual.get("structured_output") or runtime_values.get("structured_output") or [])
        actual_logic = actual.get("logic") or actual.get("query_logic") or runtime_values.get("query_logic") or "AND"
        expected_logic = expected.get("query_logic") or expected.get("logic") or reference.get("expected_logic") or "AND"

        # 3) 字段级校验：检查 actual conditions 中的字段是否在 capability_manifest 中
        unknown_fields = []
        field_mismatches = []
        for cond in actual_conditions:
            if not isinstance(cond, dict):
                continue
            field = cond.get("field")
            if field and field not in capability_manifest and field not in self.field_patterns:
                unknown_fields.append(field)
            elif field and field in capability_manifest:
                manifest = capability_manifest[field]
                allowed_operators = set(manifest.get("operators", []))
                actual_operator = cond.get("operator")
                if actual_operator and allowed_operators and actual_operator not in allowed_operators:
                    field_mismatches.append({
                        "field": field,
                        "operator": actual_operator,
                        "allowed_operators": sorted(allowed_operators),
                    })

        condition_status = "passed"
        gap_counts = {"wrong": len(wrong), "missing": len(missing), "extra": 0}
        gap_evidence = [
            f"expected_conditions_count={len(expected_conditions)}",
            f"actual_conditions_count={len(actual_conditions)}",
            f"expected_logic={expected_logic}",
            f"actual_logic={actual_logic}",
            f"wrong_count={len(wrong)}",
            f"missing_count={len(missing)}",
            f"unknown_fields={unknown_fields}",
            f"operator_mismatches={len(field_mismatches)}",
        ]
        if wrong or missing or unknown_fields or field_mismatches:
            condition_status = "failed"

        root_cause = None
        if condition_status == "failed":
            details = []
            gap_details = []
            # 把 wrong/missing 的具体条目嵌入 summary，让不同 case 的归因区分开来
            for item in wrong:
                if isinstance(item, dict):
                    field = item.get("expected_fragment", {}).get("field") or item.get("actual_fragment", {}).get("field") or ""
                    exp_op = item.get("expected_fragment", {}).get("operator") or ""
                    exp_val = item.get("expected_fragment", {}).get("value")
                    act_op = item.get("actual_fragment", {}).get("operator") or ""
                    act_val = item.get("actual_fragment", {}).get("value")
                    reason = item.get("reason", "")
                    if reason:
                        gap_details.append(f"{field} 字段错误：{reason}")
                    elif exp_op != act_op:
                        gap_details.append(f"{field} 操作符错误：期望 {exp_op}，实际 {act_op}")
                    elif exp_val != act_val:
                        gap_details.append(f"{field} 值错误：期望 {json.dumps(exp_val, ensure_ascii=False)}，实际 {json.dumps(act_val, ensure_ascii=False)}")
                    else:
                        gap_details.append(f"{field} 条件不匹配")
                else:
                    gap_details.append(str(item))
            for item in missing:
                if isinstance(item, dict):
                    field = item.get("expected_fragment", {}).get("field") or "unknown"
                    op = item.get("expected_fragment", {}).get("operator") or ""
                    val = item.get("expected_fragment", {}).get("value")
                    gap_details.append(f"缺失 {field} 条件（期望 {op} {json.dumps(val, ensure_ascii=False)}）")
                else:
                    gap_details.append(str(item))
            if unknown_fields:
                gap_details.append(f"未知字段 {unknown_fields}（不在 capability_manifest 中）")
            if field_mismatches:
                for fm in field_mismatches:
                    gap_details.append(f"{fm['field']} 操作符 {fm['operator']} 不在允许列表中 {fm['allowed_operators']}")
            if not gap_details:
                gap_details = [f"条件错误 {len(wrong)} 项，条件缺失 {len(missing)} 项"]
            # 构建区分不同 case 的根因 summary：按 error type 分类
            # 值错误类（如单位转换、数值错误）
            has_value_error = any("值错误" in d or "值或枚举值错误" in d for d in gap_details)
            # 操作符错误类（如 GTE 不是 GT）
            has_operator_error = any("操作符错误" in d for d in gap_details)
            # 枚举值/字段定义错误类（如寿险不是有效枚举）
            has_enum_error = any("枚举值" in d or "value_mappings" in d or "有效枚举" in d for d in gap_details)
            if has_value_error:
                prefix = "client_search 数值解析错误："
            elif has_operator_error:
                prefix = "client_search 操作符选择错误："
            elif has_enum_error:
                prefix = "client_search 枚举值/字段定义错误："
            else:
                prefix = "client_search 条件解析与业务系统字段定义/映射规则不一致："
            root_cause = {
                "category": "implementation_bug",
                "summary": prefix + "；".join(gap_details),
                "evidence": gap_evidence + gap_details,
                "confidence": "high",
                "fix_suggestion": "修正客户搜索 parser 的字段选择、值抽取、操作符或布尔逻辑生成源头，使其与 capability_manifest 的字段定义和操作符集合一致。",
            }

        checks = [
            {
                "tool_type": "runtime_check",
                "check_type": "field_definition_manifest",
                "status": "passed",
                "field_count": field_count,
                "value_mapping_field_count": value_mapping_field_count,
                "enhanced_rule_count": enhanced_rule_count,
                "sample_fields": sorted(list(capability_manifest.keys())[:10]) if capability_manifest else [],
                "evidence": [
                    f"capability_manifest_fields={field_count}",
                    f"value_mappings_fields={value_mapping_field_count}",
                    f"enhanced_rules_entries={enhanced_rule_count}",
                ],
                "source": "source_field_definitions.yaml + source_value_mappings.yaml + source_enhanced_rules.yaml",
                "confidence": "high",
            },
            {
                "tool_type": "runtime_check",
                "check_type": "condition_validation",
                "status": condition_status,
                "expected_conditions_count": len(expected_conditions),
                "actual_conditions_count": len(actual_conditions),
                "expected_logic": expected_logic,
                "actual_logic": actual_logic,
                "wrong_count": len(wrong),
                "missing_count": len(missing),
                "unknown_fields": unknown_fields,
                "operator_mismatches": field_mismatches,
                "evidence": gap_evidence,
                "source": "impl/projects/client_search/adapter.py:_capability_manifest/_value_mappings/_enhanced_rules",
                "root_cause": root_cause,
                "confidence": "high" if condition_status in {"passed", "failed"} else "low",
            },
        ]

        return {
            "tool_type": "runtime_check",
            "check_type": "client_search_condition_contract",
            "status": "failed" if condition_status == "failed" else "passed",
            "checks": checks,
            "source": "impl/projects/client_search/adapter.py:_capability_manifest/_value_mappings/_enhanced_rules",
            "evidence": [e for c in checks for e in (c.get("evidence") or [])],
            "root_cause": root_cause,
            "fix_suggestion": root_cause.get("fix_suggestion") if root_cause else "",
            "confidence": "high" if condition_status == "failed" else "medium",
            "note": "直接加载业务系统 field_definitions.yaml / value_mappings.yaml / enhanced_rules.yaml 校验条件，不读 prompt 推测。",
        }

    def build_attribute_tools(self) -> list:
        """归因第二层 tool：在第一层 divergence_analysis（已给出"哪里坏了"——具体字段/操作符/枚举值）
        基础上，让 attribute agent 深挖"为什么坏了"+"怎么修"。

        cs 的第二层 tool 聚焦于：条件解析错误的根因链追溯（为什么该字段/操作符/值错误）、
        枚举值映射偏差的源码级定位、可执行修复方向。
        """
        adapter = self

        def trace_condition_root_cause(field: str, expected_operator: str, expected_value, actual_operator: str, actual_value) -> dict:
            """源码证据级 + 根因链 tool：追溯搜索条件解析错误的根因。

            1) 查 field 的 capability_manifest 定义（允许操作符/枚举/单位）
            2) 查 value_mappings 看是否有别名映射
            3) 定位是"操作符选错""值单位转换错""枚举值无效"还是"字段不存在"
            4) 给出根因链和可执行修复方向

            Args:
                field: 字段名
                expected_operator: 期望操作符
                expected_value: 期望值
                actual_operator: 实际操作符
                actual_value: 实际值

            Returns:
                包含 failure_mode、root_cause_chain、fix_direction 的字典
            """
            manifest = adapter._capability_manifest()
            value_mappings = adapter._value_mappings()
            field_def = manifest.get(field, {})
            allowed_ops = field_def.get("operators", [])
            enums = field_def.get("enums", [])
            unit = field_def.get("unit", "")
            # 判断失败模式
            if not field_def:
                mode = "unknown_field"
                chain = f"字段 {field} 不在 capability_manifest 中（共 {len(manifest)} 字段），parser 输出了不存在的字段"
                fix = f"修正 parser 的字段映射逻辑，使 {field} 映射到 manifest 中已定义的合法字段；参考 manifest 的字段集合"
            elif actual_operator != expected_operator and expected_operator:
                mode = "operator_error"
                chain = f"字段 {field} 操作符错误：实际 {actual_operator}，期望 {expected_operator}。允许的操作符为 {allowed_ops}。parser 的操作符选择逻辑未正确表达用户语义（如'大于'应为 GT 而非 GTE）"
                fix = f"修正 parser 的操作符映射规则，使'{field}'字段的语义映射到正确的操作符 {expected_operator}"
            elif actual_value != expected_value and expected_value is not None:
                # 值错误：检查是否单位转换或枚举映射
                if isinstance(actual_value, (int, float)) and isinstance(expected_value, (int, float)):
                    ratio = expected_value / actual_value if actual_value else None
                    mode = "value_unit_error"
                    chain = f"字段 {field} 值错误：实际 {actual_value}，期望 {expected_value}（比值 {ratio}）。单位转换逻辑出错（如'万'未 ×10000、'亿'未 ×10000）"
                    fix = f"修正 parser 的数值单位转换逻辑，确保 {field} 的值按 {unit or '正确单位'} 换算"
                elif enums:
                    mode = "enum_mapping_error"
                    chain = f"字段 {field} 枚举值错误：实际 {actual_value}，期望 {expected_value}。该字段有效枚举为 {enums}。parser 未正确将口语别名映射到标准枚举"
                    fix = f"修正 value_mappings，使口语别名映射到标准枚举 {expected_value}；检查别名映射规则"
                else:
                    mode = "value_error"
                    chain = f"字段 {field} 值错误：实际 {actual_value}，期望 {expected_value}"
                    fix = f"修正 parser 的值抽取逻辑，使 {field} 抽取到正确值"
            else:
                mode = "unknown"
                chain = "条件解析错误模式未明确，需结合 trace 进一步分析"
                fix = "检查 parser 的字段选择/操作符/值/逻辑生成源头"
            return {
                "field": field,
                "failure_mode": mode,
                "field_definition": {"allowed_operators": allowed_ops, "enums": enums, "unit": unit},
                "root_cause_chain": chain,
                "fix_direction": fix,
                "source": "impl/projects/client_search/adapter.py:_capability_manifest/_value_mappings",
            }

        trace_condition_root_cause.__name__ = "trace_condition_root_cause"
        return [trace_condition_root_cause]

    def simulate_trace_nodes(self, trace, judge_result) -> Dict[str, Any]:
        """Issue #3: 沿 trace 逐节点调业务系统函数复现，定位最早分歧。

        对 client_search.routing / adapter.extract_output 节点，用 _capability_manifest 校验
        实际 conditions 中的字段是否合法，比较模拟输出与 trace actual。
        """
        manifest = self._capability_manifest()
        actual_conditions = list((trace.extracted_output or {}).get("structured_output") or
                                  (trace.project_fields or {}).get("conditions") or [])
        if not manifest:
            return {"simulated_nodes": [], "diverged_nodes": [], "note": "capability_manifest 不可加载"}
        source = "impl/projects/client_search/adapter.py:_capability_manifest"
        simulated_nodes: list[Dict[str, Any]] = []
        diverged_nodes: list[Dict[str, Any]] = []
        for node in (trace.execution_trace or []):
            if not isinstance(node, dict):
                continue
            stage = str(node.get("stage") or node.get("node") or "")
            if stage not in ("client_search.routing", "adapter.extract_output", "client_search.api"):
                continue
            if not actual_conditions:
                continue
            unknown_fields = []
            valid_count = 0
            for cond in actual_conditions:
                if not isinstance(cond, dict):
                    continue
                f = cond.get("field")
                if f and f not in manifest and f not in self.field_patterns:
                    unknown_fields.append(f)
                elif f and f in manifest:
                    valid_count += 1
            status = "passed" if not unknown_fields else "diverged"
            node_evidence = node.get("evidence") if isinstance(node.get("evidence"), dict) else {}
            entry = {
                "stage": stage,
                "input_used": {"conditions": actual_conditions[:3], "condition_count": len(actual_conditions)},
                "simulated_output": {"valid_field_count": valid_count, "unknown_fields": unknown_fields, "manifest_field_count": len(manifest)},
                "trace_actual": {"condition_count": node_evidence.get("condition_count")},
                "status": status,
                "function_called": "_capability_manifest",
                "source_file": source,
            }
            simulated_nodes.append(entry)
            if status == "diverged":
                diverged_nodes.append(entry)
        return {"simulated_nodes": simulated_nodes, "diverged_nodes": diverged_nodes, "source": source}

    def build_attribute_context(self, trace: RunTrace, judge_result: JudgeResult) -> Dict[str, Any]:
        project_fields = trace.project_fields if isinstance(trace.project_fields, dict) else {}
        application_boundary = project_fields.get("application_boundary") or self._application_boundary(project_fields.get("downstream_search"))
        chain_nodes = [
            {"name": "request_normalization", "evidence": trace.normalized_request},
            {"name": "client_search_parse", "evidence": trace.extracted_output},
            {"name": "routing_pattern_match", "evidence": project_fields.get("matched_patterns")},
            {"name": "judge_boundary", "evidence": judge_result.boundary_decision},
        ]
        if application_boundary.get("judge_scope") == "parser_and_result_set":
            chain_nodes.insert(3, {"name": "downstream_result_set", "evidence": project_fields.get("downstream_search")})
        return {
            "chain_nodes_to_check": chain_nodes,
            "conditions": project_fields.get("conditions"),
            "query_logic": project_fields.get("query_logic"),
            "matched_level": project_fields.get("matched_level"),
            "application_boundary": application_boundary,
            "attribute_quality_gate": self._attribute_quality_gate(),
            "external_boundary_sources": project_fields.get("external_boundary_sources"),
            "source_config_paths": self._source_config_paths(),
            "attribute_instruction": "application_boundary 由 application adapter 在归因前判定；当 judge_scope=parser_condition_semantics_only 时，下游结果集验证不属于本次归因链路，归因只分析 query、parse 条件、matched_patterns、execution_trace 和项目文档中的可控解析问题；无法定位代码/配置时应标记 incomplete_reason。",
        }

    def normalize_attribute_result(self, trace: RunTrace, judge_result: JudgeResult, attribute_result: AttributeResult) -> AttributeResult:
        # Issue #3: 只在 attribute LLM 真正失败时才用 condition_gap 兜底。
        # 之前无条件在 verdict==incorrect 时覆盖，导致 attribute LLM 连同
        # runtime_checks / simulate_trace_nodes 的细粒度根因（具体字段/操作符/
        # earliest_divergence.node / suspected_locations）被硬编码模板替换成同一句套话，
        # 三个根因不同的 case 输出字面相同，违背 issue3「定位到具体函数/模块」诉求。
        if self._attribute_llm_failed(attribute_result) and judge_result.verdict == "incorrect":
            return self._condition_gap_attribute_result(trace, judge_result, attribute_result)
        # judge 判定为 uncertain 时，attr 不应产出确定性 implementation_bug 根因。
        if judge_result.verdict == "uncertain":
            reason = "judge 判定为 uncertain，当前搜索条件输出无法被明确判定为正确或错误，归因不能给出确定性根因。"
            attribute_result.causal_category = "insufficient_evidence"
            attribute_result.failure_category = "insufficient_evidence"
            attribute_result.failure_stage = "judge_uncertain"
            attribute_result.analysis_method = "judge_uncertain_blocked_attribute"
            attribute_result.evidence_chain = list(judge_result.evidence or [reason])
            attribute_result.incomplete_reason = reason
            attribute_result.suspected_locations = []
            attribute_result.root_cause_hypothesis = "当前 judge 无法确定 client_search 输出是否满足搜索条件契约（verdict=uncertain），建议人工复核后重新判定。"
            attribute_result.analysis_quality = {"passed": False, "status": "insufficient_evidence", "missing": ["deterministic_judge_verdict"], "standard": "judge uncertain 时不能产出确定性归因。"}
            attribute_result.needs_human_review = True
            attribute_result.primary_error_type = "needs_human_review"
            attribute_result.error_types = ["needs_human_review"]
            return attribute_result
        return attribute_result

    def _attribute_llm_failed(self, attribute_result: AttributeResult) -> bool:
        markers = [attribute_result.analysis_method, attribute_result.incomplete_reason, attribute_result.root_cause_hypothesis]
        return (
            "attribute_blocked" in (attribute_result.quality_flags or [])
            or any("attribute agent LLM 调用失败" in str(item) for item in markers if item)
            or any("llm_call_failed" == str(item) for item in markers if item)
        )

    def _condition_gap_attribute_result(self, trace: RunTrace, judge_result: JudgeResult, attribute_result: AttributeResult) -> AttributeResult:
        expected = judge_result.expected or self._intent_expected_conditions(trace) or {}
        actual = judge_result.actual or {"conditions": trace.project_fields.get("conditions") or trace.extracted_output.get("structured_output") or []}
        gaps = list(judge_result.missing or []) + list(judge_result.wrong or []) + list(judge_result.extra or [])
        evidence = [
            {"query": trace.input.get("query") or trace.normalized_request.get("user_text")},
            {"expected": expected},
            {"actual": actual},
            {"wrong_missing_extra": gaps},
        ]
        if judge_result.reasoning_summary:
            evidence.append(judge_result.reasoning_summary)
        stage = "client_search_parse"
        return AttributeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            case_id=str(trace.input.get("case_id") or trace.input.get("id") or ""),
            expectation_attributions=[{
                "expectation_id": "client_search:search_condition_contract",
                "fulfillment_status": "not_fulfilled",
                "causal_category": "implementation_bug",
                "earliest_divergence": {"node": stage, "expected": expected, "actual": actual, "evidence": evidence, "confidence": "high"},
                "causal_chain": [
                    {"name": "adapter.build_request", "status": "succeeded", "evidence": [trace.normalized_request or trace.input]},
                    {"name": stage, "status": "failed", "evidence": evidence},
                    {"name": "client_search.condition_compare", "status": "failed", "evidence": gaps or [judge_result.reasoning_summary]},
                ],
                "local_verifications": [{"method": "judge_wrong_missing_extra", "target": "judge_result", "result": "not_fulfilled", "evidence": evidence}],
                "suspected_locations": [],
                "improvement_direction": ["修正当前 query 对应的字段、操作符、值或逻辑生成链路，不要只改前端展示。"],
                "source_evidence": evidence,
                "probe_evidence": evidence,
                "incomplete_reason": "",
            }],
            causal_category="implementation_bug",
            probe_results=[{"probe": "client_search_condition_gap", "status": "passed", "evidence": evidence}],
            failure_category="client_search_condition_gap",
            failure_stage=stage,
            analysis_method="client_search_condition_gap_attribution_after_attribute_llm_failure",
            evidence_chain=evidence,
            trace_analysis=list(trace.execution_trace or []),
            chain_nodes=[{"name": stage, "status": "failed", "evidence": evidence, "reason": judge_result.reasoning_summary}],
            local_verifications=[{"method": "judge_wrong_missing_extra", "target": "judge_result", "result": "not_fulfilled", "evidence": evidence}],
            earliest_divergence={"node": stage, "expected": expected, "actual": actual, "evidence": evidence, "confidence": "high"},
            evidence_coverage={"query": bool(trace.input or trace.normalized_request), "actual": bool(actual), "expected": bool(expected), "execution_trace": bool(trace.execution_trace), "project_docs": True, "code_or_config": True, "unsupported_claims": []},
            analysis_quality={"passed": True, "missing": [], "status": "supported_root_cause", "standard": "client_search attribution may reuse condition comparison gaps when only the attribute LLM call failed."},
            incomplete_reason="",
            suspected_locations=[],
            root_cause_hypothesis="client_search condition comparison 已判定当前 parser 输出未满足目标客户搜索条件：actual conditions 与 expected conditions 存在 wrong/missing/extra 差异，最早分歧位于客户搜索条件生成链路。",
            verification_steps=["核对当前 query、expected conditions、actual structured_output 与 wrong/missing/extra 差异。", "复跑当前 client_search case，确认条件比较无差异。"],
            patch_direction=["修正客户搜索 parser 的字段选择、值抽取、操作符或布尔逻辑生成源头。"],
            business_impact=judge_result.reasoning_summary or "错误的客户搜索条件会改变目标客户人群。",
            primary_error_type="client_search_condition_gap",
            error_types=["client_search_condition_gap"],
            severity="medium",
            needs_human_review=False,
            scenario=str(trace.project_fields.get("scenario") or ""),
            quality_flags=[flag for flag in list(attribute_result.quality_flags or []) if flag != "attribute_blocked"],
            raw_model_output=attribute_result.raw_model_output,
        )

    def trace_state_graph(self) -> Dict[str, Any]:
        return self.extend_default_trace_graph("collect_evidence", ["client_search_boundary_evidence"])

    def state_executors(self) -> Dict[str, Any]:
        return {"client_search_boundary_evidence": self._client_search_boundary_evidence}

    def _client_search_boundary_evidence(self, context: Dict[str, Any]) -> Dict[str, Any]:
        trace = context.get("trace")
        if not trace:
            return {"status": "failed", "missing_evidence": ["trace"]}
        fields = trace.project_fields or {}
        evidence = {
            "condition_count": len(fields.get("conditions") or []),
            "query_logic": fields.get("query_logic"),
            "downstream_status": (fields.get("downstream_search") or {}).get("status"),
            "application_boundary": fields.get("application_boundary") or {},
            "source_config_paths": (fields.get("external_boundary_sources") or {}).get("config_paths") or {},
        }
        return {
            "status": "succeeded",
            "outputs": evidence,
            "evidence_refs": [{"type": "client_search_boundary", "evidence": evidence}],
            "claims": [{"client_search_boundary": evidence}],
        }

    def collect_state_evidence(self, state_id: str, context: Dict[str, Any]) -> list[Dict[str, Any]]:
        trace = context.get("trace")
        if not trace:
            return []
        fields = trace.project_fields or {}
        return [{"type": "client_search_state_boundary", "state_id": state_id, "application_boundary": fields.get("application_boundary") or {}, "external_boundary_sources": fields.get("external_boundary_sources") or {}}]

    def _application_boundary(self, downstream: Any) -> Dict[str, Any]:
        status = downstream.get("status") if isinstance(downstream, dict) else None
        if status == "ok":
            return {"downstream_result_set_available": True, "judge_scope": "parser_and_result_set", "result_set_verified": True}
        return {
            "downstream_result_set_available": False,
            "downstream_status": status or "not_verified",
            "judge_scope": "parser_condition_semantics_only",
            "result_set_verified": False,
            "reason": "application adapter probed downstream customer search before judge/attribute and constrained evaluation scope to parser output semantics.",
        }

    def pre_judge_result(self, trace: RunTrace, expected_intent: Optional[str] = None) -> Optional[JudgeResult]:
        """client_search pre-judge: do NOT short-circuit the LLM judge.

        Returning a JudgeResult here skips the core LLM judge call (see
        pipeline.judge), which produces a deterministic template reasoning
        summary and 0 LLM judge calls — the client_search judge column then
        lacks the per-item semantic analysis that QA has. The deterministic
        condition comparison is instead merged into the LLM judge result via
        reconcile_judge_result -> _apply_condition_comparison (gaps, expected,
        actual are retained and an llm_original_gaps snapshot is kept).
        Returning None lets the LLM judge run and produce the detailed
        per-requirement analysis; the deterministic comparison still augments
        the result afterwards.
        """
        return None

    def reconcile_judge_result(self, trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
        self._apply_condition_comparison(trace, judge_result)
        downstream = trace.project_fields.get("downstream_search") if isinstance(trace.project_fields, dict) else {}
        application_boundary = trace.project_fields.get("application_boundary") if isinstance(trace.project_fields, dict) else self._application_boundary(downstream)
        if isinstance(downstream, dict) and downstream.get("status") not in {None, "ok"}:
            flags = [
                flag
                for flag in (judge_result.quality_flags or [])
                if "downstream" not in str(flag) and "result_set" not in str(flag)
            ]
            if "application_boundary_parser_only" not in flags:
                flags.append("application_boundary_parser_only")
            judge_result.quality_flags = flags
            judge_result.boundary_decision = {
                **(judge_result.boundary_decision or {}),
                "result_set_verified": False,
                "application_boundary": application_boundary,
            }
        elif isinstance(downstream, dict) and downstream.get("status") == "ok":
            flags = [flag for flag in (judge_result.quality_flags or []) if "downstream" not in str(flag)]
            if "downstream_search_verified" not in flags:
                flags.append("downstream_search_verified")
            judge_result.quality_flags = flags
            judge_result.boundary_decision = {
                **(judge_result.boundary_decision or {}),
                "result_set_verified": True,
                "application_boundary": application_boundary,
            }
            if not any(isinstance(item, dict) and item.get("application_boundary") for item in (judge_result.evidence or [])):
                judge_result.evidence = [*(judge_result.evidence or []), {"application_boundary": application_boundary}]
        return super().reconcile_judge_result(trace, judge_result)

    def build_mock_cases(self) -> list[Dict[str, Any]]:
        all_cases = []
        # 1. Load original mock_cases from impl/data
        legacy_path = Path(__file__).resolve().parents[2] / "data" / "client_search" / "mock_cases.json"
        try:
            legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
            if isinstance(legacy, list):
                all_cases.extend(legacy)
        except Exception:
            pass
        # 2. Load new dataset files from project-root data/
        data_dir = Path(__file__).resolve().parents[3] / "data" / "client_search"
        for fpath in sorted(data_dir.glob("*.json")):
            name = fpath.name
            if name in ("index.json",):
                continue
            try:
                file_cases = json.loads(fpath.read_text(encoding="utf-8"))
                if isinstance(file_cases, list):
                    all_cases.extend(file_cases)
            except Exception:
                pass
        # 3. Drop cases whose `output` is empty/missing. Without a real provided
        # output, has_provided_output() is False and the case tries to call the
        # live external service, which is unavailable in offline/mock mode and
        # yields an empty result (crosssell_* cases run like this). Such cases
        # cannot produce judge/attribute evidence offline and only pollute the
        # batch with `uncertain`/`output missing` rows, so exclude them from
        # the mock pool. They remain usable once a live service is connected.
        kept: list[Dict[str, Any]] = []
        for case in all_cases:
            if not isinstance(case, dict):
                continue
            output = case.get("output")
            if output is None or output == {} or output == "":
                continue
            kept.append(case)
        return kept

    def build_mock_datasets(self) -> list[Dict[str, Any]]:
        index_path = Path(__file__).resolve().parents[3] / "data" / "client_search" / "index.json"
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            pass
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

