from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Dict

from impl.core.adapter import ProjectAdapter
from impl.core.interaction_protocol import ready_from_spec
from impl.core.schema import AttributeResult, JudgeResult, LiveRequest, MockDataset, MultiTurnCase, RunTrace, SingleTurnCase, TraceExecutionContext
from impl.projects.client_search.tools import ClientSearchConditionCompareTool, build_field_capability_tool, build_rule_verify_tool, build_search_api_tool
from impl.tools import ToolContext, ToolRegistry, VerifiableTool

import yaml as _yaml

from impl.projects.client_search.capability_manifest import build_capability_manifest


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
            return build_capability_manifest(config_paths.get('source_field_definitions'))
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
        normalized_request = {
            "user_text": input_data.get("user_text"),
            "user_id": input_data.get("user_id") or "eval-user",
            "trace_id": input_data.get("trace_id") or f"general-eval-{int(time.time() * 1000)}",
            "session_id": input_data.get("session_id") or "general-eval-session",
            "source": input_data.get("source") or "askbob",
            "extra_input_params": dict(input_data.get("extra_input_params") or {}),
        }
        return LiveRequest(
            project_id=self.spec.project_id,
            raw_input=input_data,
            case_id=str(case.id or ""),
            normalized_request=normalized_request,
            execution_mode="live_service",
            session_id=input_data.get("session_id") or "general-eval-session",
        )

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
            "required_outputs": ["clear root_cause_hypothesis", "evidence-backed suspected_locations", "evidence_strength", "current-case evidence", "business impact"],
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
            judge_result.wrong = wrong
            judge_result.missing = missing
            judge_result.extra = extra
        if wrong or missing or extra:
            assessment = {
                "expectation_id": "client_search:search_condition_contract",
                "status": "not_fulfilled",
                "expected_evidence": [comparison.get("expected")],
                "actual_evidence": [comparison.get("actual"), {"wrong": wrong, "missing": missing, "extra": extra}],
                "downstream_impact": "wrong/missing/extra conditions change the target customer population",
                "blocking": True,
            }
            judge_result.fulfillment_assessments = [assessment]
        elif comparison and not judge_result.fulfillment_assessments:
            judge_result.fulfillment_assessments = [{
                "expectation_id": "client_search:search_condition_contract",
                "status": "fulfilled",
                "expected_evidence": [comparison.get("expected")],
                "actual_evidence": [comparison.get("actual")],
                "downstream_impact": "search conditions cover the target customer population",
                "blocking": True,
            }]
        if trace.extracted_output:
            judge_result.actual = trace.extracted_output
        if not judge_result.expected and trace.extracted_output:
            judge_result.expected = trace.extracted_output

    def _default_business_expectation(self, trace: RunTrace, judge_result: JudgeResult) -> Dict[str, Any]:
        comparison = self._comparison_outputs(trace)
        return {
            "expectation_id": "client_search:search_condition_contract",
            "downstream_consumer": "downstream client search",
            "required_capabilities": ["field_operator_value_logic", "semantic_equivalence", "downstream_search_executability"],
            "comparison_basis": comparison.get("comparison_basis") or "client_search wrong/missing/extra customer-search coverage",
            "expected_source": comparison.get("expected_source"),
        }

    def _default_fulfillment_assessment(self, trace: RunTrace, judge_result: JudgeResult, expectation: Dict[str, Any]) -> Dict[str, Any]:
        comparison = self._comparison_outputs(trace)
        gaps = list(comparison.get("wrong") or []) + list(comparison.get("missing") or []) + list(comparison.get("extra") or [])
        if comparison and comparison.get("evaluable") is False:
            status = "not_evaluable"
        elif comparison and comparison.get("expected_source_label") == "reference_fallback" and not gaps:
            status = "fulfilled"
        elif comparison:
            status = "not_fulfilled" if gaps else "fulfilled"
        else:
            status = "not_evaluable"
        return {
            "expectation_id": expectation.get("expectation_id"),
            "status": status,
            "expected_evidence": [comparison.get("expected")] if comparison else [judge_result.expected or self.field_patterns],
            "actual_evidence": [comparison.get("actual"), {"wrong_missing_extra": gaps}] if comparison else [judge_result.actual or trace.extracted_output],
            "downstream_impact": "search conditions cover the target customer population" if status == "fulfilled" else (judge_result.reasoning_summary or "wrong/missing/extra conditions change the target customer population"),
            "blocking": status in {"not_fulfilled", "not_evaluable"},
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
            {"name": "judge_boundary", "evidence": application_boundary},
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
            "attribute_instruction": "application_boundary 由 application adapter 在归因前判定；当 judge_scope=parser_condition_semantics_only 时，下游结果集验证不属于本次归因链路，归因只分析 query、parse 条件、matched_patterns、execution_trace 和项目文档中的可控解析问题；无法定位代码/配置时应将 evidence_strength 设为 none 或 weak，并在 root_cause_hypothesis 中说明缺失的当前证据。chain_nodes_to_check 中带 evidence_ref 的节点，其 evidence 已在 run_trace 对应字段中提供，直接引用即可，无需重复读取。",
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
        from impl.projects.client_search import live

        return live._application_boundary(downstream)

    def reconcile_judge_result(self, trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
        self._apply_condition_comparison(trace, judge_result)
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
