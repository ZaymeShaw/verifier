"""Policy Search 的语义判定上下文。"""
from __future__ import annotations

from typing import Any, Dict

from impl.core.judge_protocol import ProjectJudge
from impl.core.schema import RunTrace


def _query_from_trace(trace: RunTrace) -> str:
    request = trace.normalized_request if isinstance(trace.normalized_request, dict) else {}
    extra = request.get("extra_input_params") or {}
    args = extra.get("policySearchParseArgs") or {}
    return str(args.get("query") or "")


def _query_from_request(request: Any) -> str:
    if not isinstance(request, dict):
        return ""
    extra = request.get("extra_input_params") or {}
    args = extra.get("policySearchParseArgs") or {}
    return str(args.get("query") or "")


def _turn_views(trace: RunTrace) -> list[Dict[str, Any]]:
    views: list[Dict[str, Any]] = []
    for record in list(trace.turn_records or []):
        if not isinstance(record, dict):
            continue
        request = record.get("request") or {}
        extra = request.get("extra_input_params") if isinstance(request, dict) else {}
        output = record.get("extracted_output") if isinstance(record.get("extracted_output"), dict) else {}
        views.append({
            "turn_index": record.get("turn_index"),
            "query": _query_from_request(request),
            "status": output.get("status"),
            "message": output.get("message"),
            "filter": output.get("filter"),
            "contexts": list(((extra or {}).get("args") or {}).get("contexts") or []),
        })
    return views


class PolicySearchJudge(ProjectJudge):
    def build_context(self, trace: RunTrace) -> Dict[str, Any]:
        source_paths = {
            key: self.spec.source_path(key)
            for key in (
                "api_contract",
                "filter_contract",
                "technical_design",
                "business_config",
                "runtime_config",
                "golden_manifest",
            )
        }
        turns = _turn_views(trace)
        interactive = str(trace.scenario or "") in set(self.spec.interactive_scenarios)
        extras = (
            "你评价的是保单筛选语义是否被完整、可执行且安全地表达。"
            "先判断服务依赖是否成功，再比较 query 与 filter。忽略 node_id 命名差异；"
            "允许逻辑等价的树。字段、操作符、值、角色、AND/OR/NOT 作用域、日期边界和条件完整性都必须正确。"
            "SUCCESS 必须有完整 filter；歧义、条件缺失或越界场景应 UNSUPPORTED 且不得返回部分 filter。"
            "业务实现、prompt 和配置是当前能力证据，不是不可质疑的自证。"
        )
        if interactive:
            extras += (
                "这是澄清追问 case：必须结合全部 turn_records。"
                "clarification_reply 第一轮应 UNSUPPORTED 且 message 可补槽，第二轮应把短答接到未闭合字段。"
                "clarification_then_new_query 第二轮是完整新问题，不得继承上一轮未闭合条件。"
                "不要只根据最后一轮短答判定整句残缺。"
            )
        dimensions = [
            "field_selection",
            "operator_and_value",
            "logical_scope",
            "time_boundary",
            "condition_completeness",
            "safe_failure",
        ]
        if interactive:
            dimensions.extend(["turn_resolution", "clarification_slot_recovery", "new_query_isolation"])
        return {
            "project_type": "natural_language_to_policy_filter_tree",
            "user_intent": _query_from_trace(trace),
            "application_boundary": trace.application_boundary or {},
            "system_prompt_extras": extras,
            "user_prompt_extras": {
                "query": _query_from_trace(trace),
                "actual_output": trace.extracted_output or {},
                "turn_records": turns,
                "interactive_scenario": interactive,
                "reference_contract": trace.reference_contract or {},
                "business_evidence_paths": source_paths,
                "evaluation_dimensions": dimensions,
            },
        }

    def build_intent_frame(self, trace: RunTrace, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        query = _query_from_trace(trace)
        turns = _turn_views(trace)
        request_candidates = [{"source": "policySearchParseArgs.query", "value": query}]
        if turns:
            request_candidates = [
                {"source": f"turn_{item.get('turn_index')}.query", "value": item.get("query")}
                for item in turns
                if item.get("query")
            ] or request_candidates
        return {
            "project_id": self.spec.project_id,
            "downstream_consumer": "policy query execution service",
            "user_goal": query,
            "request_candidates": request_candidates,
            "output_semantics": "an executable policy filter tree or an explicit safe UNSUPPORTED decision",
        }
