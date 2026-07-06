from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .schema import MultiTurnCase, ProjectSpec, SingleTurnCase, normalize_mock_case


# ready 枚举值：声明此场景可直接从输入获取的信息，无需经 trace 生成。
READY_OUTPUT = "output"       # case 携带 output，走 provided 模式，不调真实 API
READY_REFERENCE = "reference" # case/trace 携带 reference，judge 直接采信，不自生成


@dataclass
class ReadyDecision:
    # 协议层 ready 判定结果：output/reference 是否就绪，真值只来自 common.ready 一处配置。
    output: bool = False
    reference: bool = False

    @property
    def any_provided(self) -> bool:
        return self.output or self.reference


def resolve_ready(spec: ProjectSpec | None, case: SingleTurnCase | MultiTurnCase | Dict[str, Any] | None) -> ReadyDecision:
    # ready 的唯一解析入口：adapter/pipeline/judge 都调此函数，禁止各自再内联 "output" in spec.common.get("ready")。
    # output ready = 声明 output 就绪且 case 实际携带 output（声明但未携带时回落 live）。
    # reference ready = 声明 reference 就绪（采信与否由 judge 侧再核对 case 是否真带 reference）。
    ready: List[str] = list((spec.common.get("ready") if spec and isinstance(spec.common, dict) else {}) or [])
    output_value = _case_output(case)
    return ReadyDecision(
        output=READY_OUTPUT in ready and bool(output_value),
        reference=READY_REFERENCE in ready,
    )


def ready_from_spec(spec: ProjectSpec | None) -> List[str]:
    # 供 pipeline 在构造 trace 时把 ready 快照注入 trace.ready，单一数据源。
    if not spec or not isinstance(spec.common, dict):
        return []
    return list(spec.common.get("ready") or [])


def _case_output(case: SingleTurnCase | MultiTurnCase | Dict[str, Any] | None) -> Any:
    if case is None:
        return None
    if isinstance(case, dict):
        output = case.get("output")
        if isinstance(output, dict) and output:
            return output
        input_data = case.get("input") if isinstance(case.get("input"), dict) else {}
        return input_data.get("output") or input_data.get("response") or input_data.get("raw_response")
    output = getattr(case, "output", None)
    if isinstance(output, dict) and output:
        return output
    input_data = getattr(case, "input", None) or {}
    if isinstance(input_data, dict):
        return input_data.get("output") or input_data.get("response") or input_data.get("raw_response")
    return None


@dataclass
class NormalizedCaseInteraction:
    case_id: str
    mode: str
    source_case: Dict[str, Any]
    execution_input: Dict[str, Any]
    interaction: Dict[str, Any]
    adapter_payload: Dict[str, Any] = field(default_factory=dict)
    policy: Dict[str, Any] = field(default_factory=dict)


def normalize_case_interaction(project_id: str, case: Dict[str, Any] | SingleTurnCase | MultiTurnCase, index: int = 0) -> NormalizedCaseInteraction:
    schema_case = normalize_mock_case(case)
    raw_case = _case_to_dict(schema_case) if schema_case is not None else (case if isinstance(case, dict) else {})
    case_id = str(raw_case.get("id") or raw_case.get("case_id") or f"case-{index + 1}")
    interaction = raw_case.get("interaction") if isinstance(raw_case.get("interaction"), dict) else None
    if interaction:
        mode = str(interaction.get("mode") or "single_run")
        normalized_interaction = dict(interaction)
    elif isinstance(raw_case.get("turns"), list):
        mode = "static_turns"
        normalized_interaction = {"mode": mode, "turns": list(raw_case.get("turns") or [])}
    else:
        mode = "single_run"
        normalized_interaction = {"mode": mode}

    execution_input = _execution_input(schema_case or raw_case, case_id, mode)
    adapter_payload = {
        key: value
        for key, value in raw_case.items()
        if key not in {"id", "case_id", "selected", "source", "status", "expected_intent"}
    }
    return NormalizedCaseInteraction(
        case_id=case_id,
        mode=mode,
        source_case=raw_case,
        execution_input=execution_input,
        interaction=normalized_interaction,
        adapter_payload=adapter_payload,
        policy=dict((normalized_interaction.get("policy") or {}) if isinstance(normalized_interaction.get("policy"), dict) else {}),
    )


def _case_to_dict(case: SingleTurnCase | MultiTurnCase | None) -> Dict[str, Any]:
    if case is None:
        return {}
    result = {
        "id": case.id,
        "input": dict(case.input or {}),
        "scenario": case.scenario,
        "expected_intent": case.expected_intent,
        "reference": case.reference,
        "source": case.source,
        "status": case.status,
        "metadata": dict(case.metadata or {}),
    }
    if isinstance(case, SingleTurnCase) and isinstance(case.output, dict):
        result["output"] = case.output
    if isinstance(case, MultiTurnCase):
        result["user_intent"] = dict(case.user_intent or {})
        result["interaction"] = {
            "mode": case.interaction.mode,
            "policy": {"max_turns": case.interaction.policy.max_turns, "stop_when": list(case.interaction.policy.stop_when or [])},
            "turn_expectations": [
                {"turn": item.turn, "stage": item.stage, "missing_fields": list(item.missing_fields or []), "required_path_types": list(item.required_path_types or [])}
                for item in case.interaction.turn_expectations or []
            ],
        }
        result["mock_agent"] = dict(case.mock_agent or {})
    return {key: value for key, value in result.items() if value not in (None, {}, [], "")}


def _execution_input(case: Dict[str, Any] | SingleTurnCase | MultiTurnCase, case_id: str, mode: str) -> Dict[str, Any]:
    raw_case = _case_to_dict(case) if isinstance(case, (SingleTurnCase, MultiTurnCase)) else case
    if any(key in raw_case for key in ("input", "output", "reference", "metadata", "scenario")):
        result = {key: raw_case[key] for key in ("input", "output", "reference", "metadata", "scenario") if key in raw_case}
    else:
        result = {
            key: value
            for key, value in raw_case.items()
            if key not in {"id", "case_id", "selected", "source", "status", "expected_intent", "interaction", "mock_agent"}
        }
    if mode == "static_turns" and "turns" in raw_case:
        result["turns"] = raw_case["turns"]
    result["case_id"] = case_id
    return result
