"""Mock 通用函数

为 mock_protocol.py 提供通用逻辑，委托给 mock_agent.py 的 MockAgent。
"""
from __future__ import annotations

from typing import Dict, Any, List, Optional

from impl.core.schema import MockCase, MockIntentOutput, ProjectSpec, SingleTurnCase, MultiTurnCase
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
        "user_intent": result.user_intent,
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
    使用 MockBuildResult 的 reference 字段（项目特定 reference_contract）。
    user_intent 作为 case 的意图字段；user_context 放入 case.metadata 供 next_turn 使用，不污染 input 形状。
    """
    result = case_data.get("_result")
    if result:
        metadata = {
            "source": "mock_agent",
            "scenario": case_data.get("scenario", ""),
        }
        if result.user_context:
            metadata["user_context"] = result.user_context
        return SingleTurnCase(
            id=f"mock-{spec.project_id}-{case_data.get('scenario', 'default')}",
            input=dict(result.input or {}),
            output=result.output,
            reference=result.reference,
            user_intent=result.user_intent or "",
            metadata=metadata,
        )

    # fallback：直接从 case_data 构建
    return SingleTurnCase(
        id=f"mock-{spec.project_id}-{case_data.get('scenario', 'default')}",
        input=dict(case_data.get("input") or {}),
        output=case_data.get("output"),
        reference=case_data.get("reference"),
        user_intent=str(case_data.get("user_intent") or ""),
        metadata={
            "source": "mock_agent",
            "scenario": case_data.get("scenario", ""),
        },
    )


# ── MockCase 存储 schema 转换函数 ──
# MockCase 是存储格式（JSON 序列化），SingleTurnCase 是运行时格式（pipeline）。
# 转换在存储边界发生，协议层（_MockProtocol）提供 @final 方法封装。


def build_mock_case(spec: ProjectSpec, case_data: Dict[str, Any]) -> "MockCase":
    """从 MockBuildResult（包在 case_data._result 里）构建 MockCase。

    MockBuildResult → MockCase 的映射：
      case_id          → id
      scenario         → scenario
      user_intent      → intent.user_intent
      query            → intent.query（_map_intent_result 新增字段，step2 不覆盖）
      user_context     → intent.user_context
      input            → live_request（纯 REQUEST_SCHEMA 形状）
      output           → output
      reference        → reference
      metadata[pid]    → project_id（兜底用 spec.project_id）
    """
    from .schema import MockCase, MockIntentOutput
    result = case_data.get("_result")
    if not result:
        # 无 _result 时从 case_data 字段构建（兼容旧调用方）
        inp = dict(case_data.get("input") or {})
        return MockCase(
            id=str(case_data.get("id") or case_data.get("case_id") or f"mock-{spec.project_id}-{case_data.get('scenario', 'default')}"),
            project_id=str(case_data.get("project_id") or getattr(spec, "project_id", "") or case_data.get("metadata", {}).get("project_id", "")),
            scenario=str(case_data.get("scenario", "")),
            intent=MockIntentOutput(
                user_intent=str(case_data.get("user_intent") or ""),
                query=str(inp.get("query") or case_data.get("user_intent") or ""),
                user_context=dict(case_data.get("user_context") or case_data.get("metadata", {}).get("user_context", {})),
            ),
            live_request=inp,
            output=case_data.get("output"),
            reference=case_data.get("reference"),
        )

    meta = dict(result.metadata or {})
    return MockCase(
        id=result.case_id,
        project_id=meta.get("project_id", spec.project_id),
        scenario=result.scenario or case_data.get("scenario", ""),
        intent=MockIntentOutput(
            user_intent=result.user_intent or "",
            query=result.query or str((result.input or {}).get("query", "")),
            user_context=dict(result.user_context or {}),
        ),
        live_request=dict(result.input or {}),
        output=result.output,
        reference=result.reference,
    )


def mock_case_to_single_turn(mc: "MockCase") -> SingleTurnCase:
    """MockCase → SingleTurnCase（运行时格式）。

    mapper:
      MockCase.id              → SingleTurnCase.id
      MockCase.live_request    → SingleTurnCase.input
      MockCase.output          → SingleTurnCase.output
      MockCase.reference       → SingleTurnCase.reference
      MockCase.scenario        → SingleTurnCase.scenario
      MockCase.intent.user_intent → SingleTurnCase.user_intent
      MockCase.project_id      → SingleTurnCase.metadata["project_id"]
      MockCase.intent.user_context → SingleTurnCase.metadata["user_context"]
    """
    from .schema import MockCase, MockIntentOutput
    if not isinstance(mc, MockCase):
        raise TypeError(f"mock_case_to_single_turn 期望 MockCase，实际 {type(mc).__name__}")

    metadata: Dict[str, Any] = {
        "project_id": mc.project_id,
        "source": "mock_case_api",
    }
    if mc.intent.user_context:
        metadata["user_context"] = dict(mc.intent.user_context)

    return SingleTurnCase(
        id=mc.id,
        input=dict(mc.live_request or {}),
        output=mc.output,
        reference=mc.reference,
        scenario=mc.scenario,
        user_intent=mc.intent.user_intent,
        metadata=metadata,
    )


def parse_mock_case(value: Any, *, project_id: str = "") -> MockCase:
    """Parse the only supported persisted/transport case shape.

    Legacy ``input`` cases are deliberately rejected here. Compatibility belongs
    in one-off migration tooling, not in the live protocol boundary.
    """
    if isinstance(value, MockCase):
        case = value
    elif isinstance(value, dict):
        required = {"id", "project_id", "scenario", "intent", "live_request", "output", "reference"}
        missing = sorted(required.difference(value))
        if missing:
            raise ValueError(f"MockCase 缺少字段: {', '.join(missing)}")
        unknown = sorted(set(value).difference(required))
        if unknown:
            raise ValueError(f"MockCase 包含未知字段: {', '.join(unknown)}")
        intent = value.get("intent")
        if not isinstance(intent, dict):
            raise ValueError("MockCase.intent 必须是对象")
        live_request = value.get("live_request")
        if not isinstance(live_request, dict):
            raise ValueError("MockCase.live_request 必须是对象")
        case = MockCase(
            id=str(value.get("id") or ""),
            project_id=str(value.get("project_id") or ""),
            scenario=str(value.get("scenario") or ""),
            intent=MockIntentOutput(
                user_intent=str(intent.get("user_intent") or ""),
                query=str(intent.get("query") or ""),
                user_context=dict(intent.get("user_context") or {}),
                scenario=str(intent.get("scenario") or ""),
                live_request=dict(intent.get("live_request")) if isinstance(intent.get("live_request"), dict) else None,
            ),
            live_request=dict(live_request),
            output=value.get("output"),
            reference=value.get("reference"),
        )
    else:
        raise TypeError(f"MockCase 必须是对象，实际 {type(value).__name__}")
    if not case.id:
        raise ValueError("MockCase.id 不能为空")
    if not case.project_id:
        raise ValueError("MockCase.project_id 不能为空")
    if project_id and case.project_id != project_id:
        raise ValueError(f"MockCase.project_id={case.project_id} 与请求项目 {project_id} 不一致")
    return case


def single_turn_to_mock_case(stc: SingleTurnCase, project_id: str) -> "MockCase":
    """SingleTurnCase → MockCase（旧数据迁移 / 向前兼容）。

    SingleTurnCase 转 MockCase 时需补 project_id（SingleTurnCase 无顶层 project_id）。
    意图层退化：intent.query 从 input.query 或 user_intent 推断。
    """
    from .schema import MockCase, MockIntentOutput
    inp = dict(stc.input or {})
    meta = dict(stc.metadata or {})
    return MockCase(
        id=stc.id,
        project_id=project_id or meta.get("project_id", ""),
        scenario=stc.scenario,
        intent=MockIntentOutput(
            user_intent=stc.user_intent,
            query=str(inp.get("query") or stc.user_intent or ""),
            user_context=dict(meta.get("user_context", {})),
        ),
        live_request=inp,
        output=stc.output,
        reference=stc.reference,
    )
