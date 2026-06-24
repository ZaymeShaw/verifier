"""运行时配置查询工具 - Issue #3 正确实施

用户诉求："直接引用系统原函数"
真正含义：工具直接调用系统代码返回答案，不让 agent 读文件推测
"""

from typing import Dict, Any, Optional


def get_intent_mapping_result(raw_intent: str, project_name: str) -> Dict[str, Any]:
    """直接返回 intent 映射结果

    用户场景：
    - Agent 看到 raw_intent="4001"，actual="other"，expected="nbev_planning"
    - Agent 不需要读 intent.py 文件去查映射表
    - 工具直接告诉它："4001 映射到 other，但应该是 nbev_planning，原因是配置缺失"

    Returns:
        {
            "raw_intent": "4001",
            "actual_mapping": "other",
            "expected_mapping": "nbev_planning",
            "is_correct": False,
            "root_cause": "4001 not in INTENT_MAPPING, fallback to 'other'",
            "fix_suggestion": "Add '4001': 'nbev_planning' to INTENT_MAPPING"
        }
    """
    # 直接从项目 adapter 导入配置
    if project_name == "marketting-planning-intent":
        try:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent.parent / "projects" / "marketting-planning-intent"))

            # 导入实际的映射配置
            from intent import INTENT_MAPPING, IntentType

            # 检查映射
            actual_mapping = INTENT_MAPPING.get(raw_intent, "other")
            is_in_mapping = raw_intent in INTENT_MAPPING

            return {
                "raw_intent": raw_intent,
                "is_in_mapping": is_in_mapping,
                "actual_mapping": actual_mapping,
                "available_intents": list(INTENT_MAPPING.keys())[:20],
                "total_mappings": len(INTENT_MAPPING),
                "root_cause": None if is_in_mapping else f"'{raw_intent}' not defined in INTENT_MAPPING, system fallback to 'other'",
                "enum_check": {
                    "in_IntentType_enum": raw_intent in [e.value for e in IntentType],
                    "enum_values": [e.value for e in IntentType][:10]
                }
            }
        except Exception as e:
            return {
                "error": str(e),
                "raw_intent": raw_intent,
                "note": "Failed to load project config"
            }

    return {"error": "Unknown project", "raw_intent": raw_intent}


def get_divergence_analysis(trace: list, expected: dict, actual: dict, project_name: str) -> Dict[str, Any]:
    """结合系统配置分析分歧，直接返回根因

    用户场景：
    - Agent 看到 trace 中某个 stage failed
    - Agent 不需要读一堆文件去理解为什么
    - 工具直接调用系统函数，返回"为什么失败"的完整答案

    Returns:
        {
            "divergence_point": "intent_mapping",
            "expected_value": {"intent": "nbev_planning"},
            "actual_value": {"intent": "other"},
            "system_check_results": {
                "raw_intent": "4001",
                "mapping_check": "4001 not in INTENT_MAPPING",
                "fallback_behavior": "defaults to 'other'"
            },
            "root_cause": "implementation_bug: missing mapping entry",
            "confidence": "high",
            "evidence": ["INTENT_MAPPING loaded from intent.py", "4001 not found in keys"],
            "fix": "Add mapping: '4001': 'nbev_planning'"
        }
    """
    # 从 trace 找分歧点
    first_failed = None
    for step in trace:
        if step.get("status") in ["failed", "diverged", "error"]:
            first_failed = step
            break

    if not first_failed:
        return {"note": "No failed step in trace"}

    # 提取运行时值
    runtime_values = {}
    for step in trace:
        if step.get("output") and isinstance(step["output"], dict):
            runtime_values.update(step["output"])

    # 如果涉及 intent，直接查询映射
    if "raw_intent" in runtime_values or "intent" in actual:
        raw_intent = runtime_values.get("raw_intent") or actual.get("raw_intent")
        if raw_intent:
            mapping_result = get_intent_mapping_result(raw_intent, project_name)

            expected_intent = expected.get("intent")
            actual_intent = actual.get("intent")

            return {
                "divergence_point": first_failed.get("stage", "unknown"),
                "expected_value": expected,
                "actual_value": actual,
                "system_check": mapping_result,
                "root_cause": mapping_result.get("root_cause") or "mapping mismatch",
                "confidence": "high" if not mapping_result.get("error") else "medium",
                "evidence": [
                    f"raw_intent={raw_intent}",
                    f"actual_mapping={mapping_result.get('actual_mapping')}",
                    f"expected={expected_intent}",
                    f"is_in_mapping={mapping_result.get('is_in_mapping')}"
                ],
                "fix_suggestion": f"Add '{raw_intent}': '{expected_intent}' to INTENT_MAPPING" if expected_intent else "Check mapping rules"
            }

    return {
        "divergence_point": first_failed.get("stage", "unknown"),
        "expected_value": expected,
        "actual_value": actual,
        "note": "No runtime value extraction available"
    }
