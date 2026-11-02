"""多轮会话 stop_reason 的归责分组（spec/mock/protocol.md 4.7）。

只有"用户决定"和"live 故障"两组计入 live 质量指标；预算、Driver 故障、adapter 故障
进入独立的 driver_health 指标。旧值（safety_max_turns / request_build_error 等）继续被
接受并归到对应组，legacy 路径与 golden trace 不受改名影响。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

ATTRIBUTION_USER = "user"
ATTRIBUTION_BUDGET = "budget"
ATTRIBUTION_DRIVER = "driver"
ATTRIBUTION_ADAPTER = "adapter"
ATTRIBUTION_LIVE = "live"
ATTRIBUTION_LEGACY = "legacy"
ATTRIBUTION_UNKNOWN = "unknown"

USER_STOP_REASONS = frozenset({"goal_satisfied", "user_abandons", "perceived_no_progress"})
BUDGET_STOP_REASONS = frozenset({
    "max_turns",
    "safety_max_turns",
    "session_timeout",
    "driver_timeout",
    "driver_budget_exceeded",
})
DRIVER_STOP_REASONS = frozenset({"driver_error"})
ADAPTER_STOP_REASONS = frozenset({"adapter_error", "request_build_error"})
LIVE_STOP_REASONS = frozenset({"live_error", "execution_error"})
LEGACY_STOP_REASONS = frozenset({"intent_unavailable", "decision_error"})

_ATTRIBUTION: Dict[str, str] = {
    **{reason: ATTRIBUTION_USER for reason in USER_STOP_REASONS},
    **{reason: ATTRIBUTION_BUDGET for reason in BUDGET_STOP_REASONS},
    **{reason: ATTRIBUTION_DRIVER for reason in DRIVER_STOP_REASONS},
    **{reason: ATTRIBUTION_ADAPTER for reason in ADAPTER_STOP_REASONS},
    **{reason: ATTRIBUTION_LIVE for reason in LIVE_STOP_REASONS},
    **{reason: ATTRIBUTION_LEGACY for reason in LEGACY_STOP_REASONS},
}

# 单轮路径的结束原因不属于多轮归责，但要能被识别为"正常"。
SINGLE_TURN_STOP_REASONS = frozenset({"single_turn_completed", ""})


def attribution(stop_reason: str) -> str:
    reason = str(stop_reason or "")
    if reason in SINGLE_TURN_STOP_REASONS:
        return ATTRIBUTION_USER
    return _ATTRIBUTION.get(reason, ATTRIBUTION_UNKNOWN)


def counts_toward_live_quality(stop_reason: str) -> bool:
    """是否计入 live 质量指标：只有用户决定与 live 故障两组。"""
    return attribution(stop_reason) in {ATTRIBUTION_USER, ATTRIBUTION_LIVE}


def is_user_decision(stop_reason: str) -> bool:
    return str(stop_reason or "") in USER_STOP_REASONS


@dataclass
class DriverHealth:
    """从 stop_reason 与 interaction_controller 状态派生的用户方健康度（4.9）。"""

    status: str = "ok"          # ok | error | not_run
    attribution: str = ATTRIBUTION_UNKNOWN
    error: str = ""
    counts_toward_live_quality: bool = True
    budget_usage: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "attribution": self.attribution,
            "error": self.error,
            "counts_toward_live_quality": self.counts_toward_live_quality,
            "budget_usage": dict(self.budget_usage),
        }


def driver_health(
    stop_reason: str,
    controller_status: str = "not_run",
    controller_error: str = "",
    budget_usage: Optional[Dict[str, Any]] = None,
) -> DriverHealth:
    group = attribution(stop_reason)
    status = str(controller_status or "not_run")
    if group in {ATTRIBUTION_DRIVER, ATTRIBUTION_ADAPTER, ATTRIBUTION_LEGACY}:
        status = "error"
    return DriverHealth(
        status=status,
        attribution=group,
        error=str(controller_error or ""),
        counts_toward_live_quality=counts_toward_live_quality(stop_reason),
        budget_usage=dict(budget_usage or {}),
    )
