"""MPI intent recognition probe tool.

验证 query 是否匹配宽松正则，定位 Tier 0 的 gap。

设计意图：
1. 暴露 Tier 0 正则的覆盖范围
2. 检测 query 是否包含口语化表达
3. 提供可复用的 probe，供 draft attribute 调用
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from impl.tools.protocol import ToolResult, VerifiableTool


@dataclass
class RelaxedMatchResult:
    """宽松正则匹配结果。"""
    matched_intent: Optional[str]
    matched_pattern: Optional[str]
    tier0_matched: bool
    tier0_pattern: Optional[str]
    relaxed_matched: bool
    gap_detected: bool
    explanation: str


# 实际 Tier 0 正则（来自 /Users/xiaozijian/WorkSpace/package/marketing-planning/app/workflow/steps/intent_recognition.py）
TIER0_RULES = [
    (re.compile(r"怎么达成.*NBEV.*目标", re.IGNORECASE), "nbev_planning"),
    (re.compile(r"客户.*(?:画像|分布|结构|分层)"), "customer_portrait"),
    (re.compile(r"客群.*(?:画像|分布|结构)"), "customer_portrait"),
    (re.compile(r"(?:客温|客价).*(?:分布|画像)"), "customer_portrait"),
    (re.compile(r"(?:队伍|团队).*(?:画像|分布|结构|分层|人力)"), "team_portrait"),
    (re.compile(r"人力.*(?:画像|分布|结构)"), "team_portrait"),
]

# 宽松正则（覆盖口语化表达）
RELAXED_RULES = [
    (re.compile(r"客户.*(?:画像|分布|结构|分层|啥样|什么样|情况)"), "customer_portrait"),
    (re.compile(r"客群.*(?:画像|分布|结构|啥样|什么样)"), "customer_portrait"),
    (re.compile(r"(?:看看|分析|查).*(?:客户|客群)"), "customer_portrait"),
    (re.compile(r"(?:队伍|团队).*(?:画像|分布|结构|分层|人力|状况|情况)"), "team_portrait"),
    (re.compile(r"(?:看看|分析|查).*(?:队伍|团队)"), "team_portrait"),
    (re.compile(r"NBEV.*(?:规划|达成|路径|提升|增长)"), "nbev_planning"),
    (re.compile(r"(?:保费|业绩|目标).*(?:提升|增长|提高)"), "nbev_planning"),
]


def _match_tier0(query: str) -> tuple[bool, Optional[str]]:
    """检查是否匹配 Tier 0 正则。"""
    normalized = re.sub(r"\s+", "", query)
    for pattern, intent in TIER0_RULES:
        if pattern.search(normalized):
            return True, f"{intent}: {pattern.pattern}"
    return False, None


def _match_relaxed(query: str) -> tuple[bool, Optional[str], Optional[str]]:
    """检查是否匹配宽松正则。"""
    normalized = re.sub(r"\s+", "", query)
    for pattern, intent in RELAXED_RULES:
        if pattern.search(normalized):
            return True, intent, pattern.pattern
    return False, None, None


def probe_intent_recognition_gap(query: str, expected_intent: Optional[str] = None) -> RelaxedMatchResult:
    """探测意图识别的 gap。

    Args:
        query: 用户查询
        expected_intent: 期望的意图标签（可选）

    Returns:
        RelaxedMatchResult: 匹配结果和 gap 检测
    """
    tier0_matched, tier0_pattern = _match_tier0(query)
    relaxed_matched, relaxed_intent, relaxed_pattern = _match_relaxed(query)

    gap_detected = (
        not tier0_matched and
        relaxed_matched and
        (expected_intent is None or relaxed_intent == expected_intent)
    )

    if gap_detected:
        explanation = (
            f"Tier 0 正则未匹配，但宽松正则匹配到 '{relaxed_intent}'。"
            f"Query '{query}' 是口语化表达，未包含 Tier 0 的显式关键词。"
            f"这是 Tier 0 正则覆盖范围过窄的 gap。"
        )
    elif tier0_matched:
        explanation = (
            f"Tier 0 正则匹配到 '{tier0_pattern}'。"
            f"Query '{query}' 包含显式关键词，Tier 0 正常工作。"
        )
    else:
        explanation = (
            f"Tier 0 和宽松正则都未匹配。"
            f"Query '{query}' 可能是 LLM fallback 场景或无法识别的意图。"
        )

    return RelaxedMatchResult(
        matched_intent=relaxed_intent,
        matched_pattern=relaxed_pattern,
        tier0_matched=tier0_matched,
        tier0_pattern=tier0_pattern,
        relaxed_matched=relaxed_matched,
        gap_detected=gap_detected,
        explanation=explanation,
    )


class IntentRecognitionGapProbe(VerifiableTool):
    """意图识别 gap 探测工具。"""

    @property
    def tool_id(self) -> str:
        return "intent_recognition_gap_probe"

    @property
    def description(self) -> str:
        return "探测 MPI 意图识别的 Tier 0 正则覆盖范围 gap。验证 query 是否匹配宽松正则，定位口语化表达的识别失败。"

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "用户查询"},
                "expected_intent": {
                    "type": "string",
                    "description": "期望的意图标签（可选）",
                    "enum": [
                        "other", "customer_portrait", "nbev_planning",
                        "nbev_planning_fallback", "achievement_measurement_adjustment",
                        "team_portrait", "target_value_adjustment"
                    ]
                }
            },
            "required": ["query"]
        }

    def execute(self, query: str, expected_intent: Optional[str] = None) -> ToolResult:
        result = probe_intent_recognition_gap(query, expected_intent)
        return ToolResult(
            status="success" if result.gap_detected else "neutral",
            actual={
                "matched_intent": result.matched_intent,
                "matched_pattern": result.matched_pattern,
                "tier0_matched": result.tier0_matched,
                "tier0_pattern": result.tier0_pattern,
                "relaxed_matched": result.relaxed_matched,
                "gap_detected": result.gap_detected,
                "explanation": result.explanation,
            },
            evidence=[
                f"query: {query}",
                f"expected: {expected_intent}",
                f"tier0_matched: {result.tier0_matched}",
                f"relaxed_matched: {result.relaxed_matched}",
                f"gap_detected: {result.gap_detected}",
            ],
            missing_evidence=[] if result.gap_detected else ["query not matched by relaxed rules"],
            boundary_limits=None,
        )
