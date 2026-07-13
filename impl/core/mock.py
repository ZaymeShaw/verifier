"""Mock 通用函数

为 mock_protocol.py 提供通用逻辑，委托给 mock_agent.py 的 MockAgent。
"""
from __future__ import annotations

from typing import Dict, Any, List, Optional

from impl.core.schema import ProjectSpec, SingleTurnCase, MultiTurnCase
from impl.core.mock_agent import MockAgent, build_spec_from_project


def build_mock_spec(
    spec: ProjectSpec,
    scenario: str,
    intent: Optional[str] = None,
    intent_labels: Optional[List[str]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    构建 Mock 规格。

    委托给 mock_agent.build_spec_from_project。
    """
    build_spec = build_spec_from_project(spec, scenario=scenario)
    # 合并 intent_labels：优先使用调用者传入的，否则用 build_spec 默认值
    final_intent_labels = list(intent_labels) if intent_labels else list(build_spec.intent_labels or [])
    # 如果传入 intent 且不在列表中，插入头部
    if intent and intent not in final_intent_labels:
        final_intent_labels = [intent] + final_intent_labels
    build_spec.intent_labels = final_intent_labels

    return {
        "project_id": spec.project_id,
        "scenario": scenario,
        "intent": intent,
        "intent_labels": list(build_spec.intent_labels or []),
        "required_input_fields": list(build_spec.required_input_fields or []),
        "template": dict(build_spec.template or {}),
        "_build_spec": build_spec,
    }


def apply_mock_strategy(
    spec: ProjectSpec,
    mock_spec: Dict[str, Any]
) -> Dict[str, Any]:
    """
    应用 Mock 生成策略。

    委托给 MockAgent.build。
    """
    build_spec = mock_spec.get("_build_spec")
    if not build_spec:
        return {"error": "missing build_spec"}

    agent = MockAgent(spec)
    result = agent.build(build_spec)

    return {
        "input": dict(result.input or {}),
        "expected_intent": result.expected_intent,
        "scenario": mock_spec.get("scenario", ""),
        "_result": result,
    }


def build_case_from_spec(
    spec: ProjectSpec,
    case_data: Dict[str, Any]
) -> SingleTurnCase:
    """
    从规格构建 Case。

    将 case_data 转换为 SingleTurnCase 对象。
    优先使用 MockBuildResult 的 reference 字段（项目特定 reference_contract），
    其次使用 expected_intent（如果它是 dict）。
    """
    result = case_data.get("_result")
    if result:
        # 使用 MockBuildResult 构建 SingleTurnCase
        reference = result.reference
        if reference is None and isinstance(result.expected_intent, dict):
            reference = result.expected_intent
        return SingleTurnCase(
            id=f"mock-{spec.project_id}-{case_data.get('scenario', 'default')}",
            input=dict(result.input or {}),
            output=result.output,
            reference=reference,
            metadata={
                "source": "mock_agent",
                "scenario": case_data.get("scenario", ""),
                "expected_intent": result.expected_intent,
            },
        )

    # fallback：直接从 case_data 构建
    expected_intent = case_data.get("expected_intent")
    reference = case_data.get("reference")
    if reference is None and isinstance(expected_intent, dict):
        reference = expected_intent
    return SingleTurnCase(
        id=f"mock-{spec.project_id}-{case_data.get('scenario', 'default')}",
        input=dict(case_data.get("input") or {}),
        output=case_data.get("output"),
        reference=reference,
        metadata={
            "source": "mock_agent",
            "scenario": case_data.get("scenario", ""),
        },
    )
