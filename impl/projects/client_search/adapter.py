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
from impl.core.interaction_protocol import ready_from_spec
from impl.core.schema import AttributeResult, ExecutionTraceEvent, JudgeResult, LiveExecutionResult, LiveRequest, MockDataset, MultiTurnCase, RunTrace, SingleTurnCase, TraceExecutionContext
from impl.projects.client_search.tools import ClientSearchConditionCompareTool, build_field_capability_tool, build_rule_verify_tool, build_search_api_tool
from impl.tools import ToolContext, ToolRegistry, VerifiableTool

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
        return registry

    def get_verifiable_tools(self) -> list[VerifiableTool]:
        """返回 client_search 的可执行验证 tool 集合（spec/tool2.md）。

        通用层只管协议+编排，项目层在这里决定挑哪些函数/API 做成 tool。
        每个 tool 的 execute_fn 真能跑、能产出 actual 作为归因证据。
        tool 内部怎么拿 trace/spec 是实现细节，不由协议规定。
        """
        config_paths = self._source_config_paths()
        api_config = self.spec.application.get("downstream_search") if isinstance(self.spec.application, dict) else None
        # 用主解析 API（project.yaml.api）做 search_api tool，而非 downstream_search
        api_spec = self.spec.api or {}
        tools: list[VerifiableTool] = [
            build_search_api_tool(
                api_base=str(api_spec.get("base_url") or "http://localhost:8000"),
                endpoint=str(api_spec.get("endpoint") or "/api/v1/client_search_query_parse_no_encipher"),
                method=str(api_spec.get("method") or "POST"),
                timeout=float(api_spec.get("timeout") or 10.0),
            ),
        ]
        field_def_path = config_paths.get("source_field_definitions")
        if field_def_path:
            tools.append(build_field_capability_tool(field_def_path))
        value_mappings_path = config_paths.get("source_value_mappings")
        enhanced_rules_path = config_paths.get("source_enhanced_rules")
        if value_mappings_path or enhanced_rules_path:
            tools.append(build_rule_verify_tool(value_mappings_path or "", enhanced_rules_path or ""))

        # spec/apitool_discover.md: 自动发现的 API endpoint tool（通用引擎扫描源码产出）
        # 启动时扫描，合并到 tool 列表。execute_fn 为 None 的占位 tool 由
        # 通用 ToolOrchestrator 在调用时拒绝（避免调到未实现的远程入口）。
        try:
            from impl.projects.client_search.tools.api_discover import load_api_discover_tools
            discovered = load_api_discover_tools(self.spec)
            # 去重：跳过已被手工 tool 覆盖的 endpoint（如 client_search_query_parse_no_encipher）
            existing_ids = {t.tool_id for t in tools}
            for vt in discovered:
                if vt.tool_id not in existing_ids:
                    tools.append(vt)
            if discovered:
                import logging as _logging
                _logging.getLogger(__name__).info(
                    f"[client_search] discovered {len(discovered)} api endpoints, "
                    f"{len(tools) - len(existing_ids)} new merged into verifiable tools"
                )
        except Exception as e:
            import logging as _logging
            _logging.getLogger(__name__).warning(f"[client_search] api discover failed: {e}")
        return tools

    def _source_config_paths(self) -> Dict[str, str]:
        paths = {}
        root = Path(self.spec.root)
        for key, rel in (self.spec.documents or {}).items():
            if key.startswith("source_") and "config/" in str(rel):
                paths[key] = str((root / str(rel)).resolve())
        return paths

    def _external_boundary_sources(self) -> Dict[str, Any]:
        return {"config_paths": self._source_config_paths()}

    def build_request(self, case: SingleTurnCase | MultiTurnCase) -> LiveRequest:
        input_data = dict(case.input or {})
        # mock_agent 路径：case.input 已是 REQUEST_SHAPE 形状（user_text/trace_id/...），直接转发
        if "user_text" in input_data:
            normalized_request = {
                "user_text": input_data.get("user_text"),
                "user_id": input_data.get("user_id") or "eval-user",
                "trace_id": input_data.get("trace_id") or f"general-eval-{int(time.time() * 1000)}",
                "session_id": input_data.get("session_id") or "general-eval-session",
                "source": input_data.get("source") or "askbob",
                "extra_input_params": dict(input_data.get("extra_input_params") or {}),
            }
        else:
            # 手动输入路径：旧格式 {query}，翻译成 REQUEST_SHAPE
            nested_input = input_data.get("input") if isinstance(input_data.get("input"), dict) else {}
            query = input_data.get("query") or input_data.get("user_text") or nested_input.get("query") or nested_input.get("user_text") or ""
            extra = dict(input_data.get("extra_input_params") or nested_input.get("extra_input_params") or {})
            normalized_request = {
                "user_text": query,
                "user_id": input_data.get("user_id") or "eval-user",
                "trace_id": input_data.get("trace_id") or f"general-eval-{int(time.time() * 1000)}",
                "session_id": input_data.get("session_id") or "general-eval-session",
                "source": input_data.get("source") or "askbob",
                "extra_input_params": extra,
            }
        return LiveRequest(
            project_id=self.spec.project_id,
            raw_input=input_data,
            case_id=str(case.id or ""),
            normalized_request=normalized_request,
            execution_mode="live_service",
            session_id=input_data.get("session_id") or "general-eval-session",
        )

    def call_or_prepare(self, request: LiveRequest) -> LiveExecutionResult:
        with _SERVICE_LOCK:
            return super().call_or_prepare(request)

    def provided_output_raw(self, case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> Any:
        input_data = dict(case.input or {})
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
        query = request.normalized_request.get("user_text") or output.get("source_query") or output.get("query") or ""
        return {
            "code": output.get("code", output.get("status_code", 0)),
            "msg": output.get("msg") or output.get("message") or "provided client_search output",
            "data": {
                "robot_text": output.get("robot_text") or output.get("user_visible_text") or output.get("summary") or "provided output",
                "extra_output_params": {
                    "query": query,
                    "query_logic": logic,
                    "conditions": conditions,
                    "matched_level": output.get("matched_level"),
                    "intent_summary": output.get("intent_summary") or output.get("summary") or "provided output",
                    "matched_patterns": output.get("matched_patterns") or [],
                    "rewritten_query": output.get("rewritten_query") or output.get("source_query") or query,
                },
            },
        }

    def application_boundary(self, raw_response: Any, extracted_output: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(raw_response, dict):
            return self._application_boundary({})
        downstream_search = raw_response.get("_downstream_search") if isinstance(raw_response.get("_downstream_search"), dict) else {}
        return self._application_boundary(downstream_search)

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
            return {"code": -1, "msg": str(raw_response), "query": "", "conditions": []}
        extra = (((raw_response.get("data") or {}).get("extra_output_params")) or {})
        data = raw_response.get("data") if isinstance(raw_response.get("data"), dict) else {}
        return {
            "code": int(raw_response.get("code") or 0),
            "msg": str(raw_response.get("msg") or ""),
            "robot_text": data.get("robot_text"),
            "end_flag": data.get("end_flag"),
            "trace_id": data.get("trace_id"),
            "query": self._response_query(raw_response, extra),
            "query_logic": extra.get("query_logic"),
            "conditions": extra.get("conditions") or [],
            "matched_level": extra.get("matched_level"),
            "matched_patterns": extra.get("matched_patterns"),
            "rewritten_query": extra.get("rewritten_query"),
            "intent_summary": extra.get("intent_summary"),
            "confidence": extra.get("confidence"),
            "cost_times": extra.get("cost_times"),
        }

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any]) -> Dict[str, Any]:
        extra = {}
        if isinstance(raw_response, dict):
            data = raw_response.get("data") if isinstance(raw_response.get("data"), dict) else {}
            extra = data.get("extra_output_params") if isinstance(data.get("extra_output_params"), dict) else {}
        return {
            "downstream_search": raw_response.get("_downstream_search") if isinstance(raw_response, dict) and isinstance(raw_response.get("_downstream_search"), dict) else {},
            "external_boundary_sources": self._external_boundary_sources(),
            "empty_result_reason": self._empty_result_reason(extracted_output.get("query", ""), extra),
            "is_empty_result": bool(self._empty_result_reason(extracted_output.get("query", ""), extra)),
        }

    def build_execution_trace(self, input_data: Dict[str, Any], request: Dict[str, Any], raw_response: Any, extracted_output: Dict[str, Any]) -> list[ExecutionTraceEvent]:
        extra = (((raw_response.get("data") or {}).get("extra_output_params")) or {}) if isinstance(raw_response, dict) else {}
        downstream_search = raw_response.get("_downstream_search") if isinstance(raw_response, dict) and isinstance(raw_response.get("_downstream_search"), dict) else {}
        return [
            ExecutionTraceEvent(stage="adapter.build_request", status="ok", evidence={"user_text": request.get("user_text"), "source": request.get("source")}),
            ExecutionTraceEvent(stage="client_search.api", status="ok" if isinstance(raw_response, dict) and raw_response.get("code") == 0 else "suspicious", evidence={"code": raw_response.get("code") if isinstance(raw_response, dict) else None}),
            ExecutionTraceEvent(stage="client_search.routing", status="ok" if extra.get("matched_level") is not None else "not_verified", evidence={"matched_level": extra.get("matched_level"), "matched_patterns": extra.get("matched_patterns")}),
            ExecutionTraceEvent(stage="client_search.downstream_search", status=downstream_search.get("status") or "not_verified", evidence=downstream_search),
            ExecutionTraceEvent(stage="adapter.extract_output", status="ok", evidence={"logic": extracted_output.get("query_logic"), "condition_count": len(extracted_output.get("conditions") or [])}),
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
        source = trace.normalized_request.get("intent_expected") if trace.normalized_request else None
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
            "required_outputs": ["clear root_cause_hypothesis", "evidence-backed chain_nodes", "earliest_divergence", "suspected_locations only when evidenced", "specific verification_steps", "minimal patch_direction", "evidence_coverage", "analysis_quality"],
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
        if wrong or missing or extra:
            assessment = {
                "expectation_id": "client_search:search_condition_contract",
                "status": "not_fulfilled",
                "expected_evidence": [comparison.get("expected")],
                "actual_evidence": [comparison.get("actual"), {"wrong": wrong, "missing": missing, "extra": extra}],
                "boundary_decision": judge_result.boundary_decision or {},
                "downstream_impact": "wrong/missing/extra conditions change the target customer population",
                "blocking": True,
                "confidence": judge_result.confidence,
            }
            judge_result.fulfillment_assessments = [assessment]
        elif comparison and not judge_result.fulfillment_assessments:
            judge_result.fulfillment_assessments = [{
                "expectation_id": "client_search:search_condition_contract",
                "status": "fulfilled",
                "expected_evidence": [comparison.get("expected")],
                "actual_evidence": [comparison.get("actual")],
                "boundary_decision": judge_result.boundary_decision or {},
                "downstream_impact": "search conditions cover the target customer population",
                "blocking": True,
                "confidence": judge_result.confidence,
            }]
        expected = comparison.get("expected")
        actual = comparison.get("actual")
        # comparison.expected / comparison.actual 是条件级判定证据，不是 live_schema 形状的 reference/actual。
        # expected 必须保持 judge 产出的 EXTRACT_OUTPUT_SHAPE；actual 必须保持 live 的 trace.extracted_output。
        derivation = dict(judge_result.verdict_derivation or {})
        if expected:
            derivation.setdefault("condition_comparison_expected", expected)
        if actual:
            derivation.setdefault("condition_comparison_actual", actual)
        if derivation:
            judge_result.verdict_derivation = derivation
        if trace.extracted_output:
            judge_result.actual = trace.extracted_output
        # expected 必须保持 judge 产出的 EXTRACT_OUTPUT_SHAPE；仅当 LLM 失败且 judge_result.expected 为空时，才从 trace 补充。
        if not judge_result.expected and trace.extracted_output:
            judge_result.expected = trace.extracted_output
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
                    "acceptance_criteria": list(judge_result.missing or judge_result.wrong or []),
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

    def _boundary_from_trace(self, trace: RunTrace, downstream: dict[str, Any] | None = None) -> dict[str, Any]:
        live_result = getattr(trace, "live_result", None)
        if live_result and isinstance(getattr(live_result, "application_boundary", None), dict) and live_result.application_boundary:
            return live_result.application_boundary
        return self._application_boundary(downstream or {})

    def build_judge_context(self, trace: RunTrace) -> Dict[str, Any]:
        application_boundary = self._boundary_from_trace(trace)
        condition_comparison = self._condition_comparison(trace)
        return {
            "semantic_equivalence_rules": self._semantic_equivalence_rules(),
            "field_patterns": self.field_patterns,
            "application_boundary": application_boundary,
            "judge_governance": self._judge_governance(),
            "condition_comparison": condition_comparison,
            "protocol_tool_results": [condition_comparison],
            "client_search_judge_basis": "wrong/missing/extra customer-search condition coverage within current field/config boundary",
            "boundary_usage": "application adapter has already decided whether result-set verification is in scope; judge should evaluate only within application_boundary.judge_scope.",
            "external_boundary_sources": self._external_boundary_sources(),
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

    def build_attribute_context(self, trace: RunTrace, judge_result: JudgeResult) -> Dict[str, Any]:
        project_output = trace.extracted_output if isinstance(trace.extracted_output, dict) else {}
        application_boundary = self._boundary_from_trace(trace)
        # chain_nodes_to_check 只保留节点名 + evidence_ref（指向 run_trace 中的字段），
        # 不再内联 evidence 原始数据——这些数据已在 run_trace.normalized_request /
        # extracted_output / matched_patterns 中提供，内联会造成 53% 的重复（量化见
        # demand/context.md §1.2c）。attribute agent 按 evidence_ref 指针去 run_trace 取数。
        chain_nodes = [
            {"name": "request_normalization", "evidence_ref": "run_trace.normalized_request"},
            {"name": "client_search_parse", "evidence_ref": "run_trace.extracted_output"},
            {"name": "routing_pattern_match", "evidence_ref": "run_trace.extracted_output.matched_patterns"},
            {"name": "judge_boundary", "evidence": judge_result.boundary_decision},
        ]
        if application_boundary.get("judge_scope") == "parser_and_result_set":
            chain_nodes.insert(3, {"name": "downstream_result_set", "evidence_ref": "run_trace.project_fields.downstream_search"})
        return {
            "chain_nodes_to_check": chain_nodes,
            "conditions": project_output.get("conditions"),
            "query_logic": project_output.get("query_logic"),
            "matched_level": project_output.get("matched_level"),
            "application_boundary": application_boundary,
            "attribute_quality_gate": self._attribute_quality_gate(),
            "external_boundary_sources": (trace.project_fields or {}).get("external_boundary_sources") if isinstance(trace.project_fields, dict) else {},
            "source_config_paths": self._source_config_paths(),
            "attribute_instruction": "application_boundary 由 application adapter 在归因前判定；当 judge_scope=parser_condition_semantics_only 时，下游结果集验证不属于本次归因链路，归因只分析 query、parse 条件、matched_patterns、execution_trace 和项目文档中的可控解析问题；无法定位代码/配置时应标记 incomplete_reason。chain_nodes_to_check 中带 evidence_ref 的节点，其 evidence 已在 run_trace 对应字段中提供，直接引用即可，无需重复读取。",
        }

    def trace_state_graph(self) -> Dict[str, Any]:
        return self.extend_default_trace_graph("collect_evidence", ["client_search_boundary_evidence"])

    def state_executors(self) -> Dict[str, Any]:
        return {"client_search_boundary_evidence": self._client_search_boundary_evidence}

    def _client_search_boundary_evidence(self, context: TraceExecutionContext) -> Dict[str, Any]:
        trace = context.get("trace")
        if not trace:
            return {"status": "failed", "missing_evidence": ["trace"]}
        project_output = trace.extracted_output if isinstance(trace.extracted_output, dict) else {}
        project_fields = trace.project_fields if isinstance(trace.project_fields, dict) else {}
        downstream_search = project_fields.get("downstream_search") if isinstance(project_fields.get("downstream_search"), dict) else {}
        evidence = {
            "condition_count": len(project_output.get("conditions") or []),
            "query_logic": project_output.get("query_logic"),
            "downstream_status": downstream_search.get("status"),
            "application_boundary": self._boundary_from_trace(trace),
            "source_config_paths": (project_fields.get("external_boundary_sources") or {}).get("config_paths") or {},
        }
        return {
            "status": "succeeded",
            "outputs": evidence,
            "evidence_refs": [{"type": "client_search_boundary", "evidence": evidence}],
            "claims": [{"client_search_boundary": evidence}],
        }

    def collect_state_evidence(self, state_id: str, context: TraceExecutionContext) -> list[Dict[str, Any]]:
        trace = context.get("trace")
        if not trace:
            return []
        project_fields = trace.project_fields if isinstance(trace.project_fields, dict) else {}
        return [{"type": "client_search_state_boundary", "state_id": state_id, "application_boundary": self._boundary_from_trace(trace), "external_boundary_sources": project_fields.get("external_boundary_sources") or {}}]

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

    def reconcile_judge_result(self, trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
        self._apply_condition_comparison(trace, judge_result)
        application_boundary = self._boundary_from_trace(trace)
        if application_boundary.get("downstream_status") not in {None, "ok", "not_verified"}:
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
        elif application_boundary.get("result_set_verified") is True:
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

    # build_mock_cases / build_mock_datasets 已移除：
    # pipeline.mock_cases / mock_datasets 全线走 mock_agent（LLM 生成），不再读 seed JSON / data/client_search/*.json。
    # _strip_non_ready_fields 保留（pipeline.mock_cases 在 mock_agent 失败时可能仍需），但不再在 build_mock_cases 中使用。
    # 详见 impl/core/mock_agent.py 与 impl/core/pipeline.py。

    def _strip_non_ready_fields(self, case: Dict[str, Any]) -> Dict[str, Any]:
        ready = ready_from_spec(self.spec)
        if not isinstance(case, dict):
            return case
        if "output" not in ready and "output" in case:
            case = {k: v for k, v in case.items() if k != "output"}
        if "reference" not in ready and "reference" in case:
            case = {k: v for k, v in case.items() if k != "reference"}
        return case

    # build_mock_datasets / _build_dataset 已移除：
    # pipeline.mock_datasets 全线走 mock_agent（LLM 生成），不再读 data/client_search/*.json 或硬编码模板。
    # 详见 impl/core/mock_agent.py 与 impl/core/pipeline.py。
