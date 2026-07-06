from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .evidence import EvidenceRef


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SubagentResult:
    # 子 agent 执行结果：用于记录独立审查/归因/校验节点的产物。
    executor_id: str
    executor_type: str
    role: str
    status: str = "succeeded"
    output: Any = None
    evidence_refs: List[EvidenceRef] = field(default_factory=list)
    claims: List[Any] = field(default_factory=list)
    contradictions: List[Any] = field(default_factory=list)
    missing_evidence: List[Any] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class GateDecision:
    # 状态机/质量门决策：说明某个阶段为什么通过、阻塞或需要恢复。
    gate_id: str
    gate_type: str
    passed: bool
    checked_inputs: Dict[str, Any] = field(default_factory=dict)
    missing_evidence: List[Any] = field(default_factory=list)
    unsupported_claims: List[Any] = field(default_factory=list)
    contradictions: List[Any] = field(default_factory=list)
    recoverable: bool = False
    recommended_transition: str = ""
    reason: str = ""


@dataclass
class TransitionDecision:
    # 状态迁移记录：用于追踪 trace 在不同执行阶段之间如何流转。
    from_state: str
    to_state: str
    condition: str = ""
    reason: str = ""
    gate_ids: List[str] = field(default_factory=list)
    retry_count: int = 0
    stop_reason: str = ""


def to_dict(value: Any) -> Any:
    # 统一导出工具：保持 dataclass/dict/list 在 API、前端和报告中的序列化口径一致。
    return _to_dict(value, set())


def _json_safe_key(key: Any) -> Any:
    if isinstance(key, (str, int, float, bool)) or key is None:
        return key
    return str(key)


def _to_dict(value: Any, seen: set[int]) -> Any:
    if is_dataclass(value):
        value_id = id(value)
        if value_id in seen:
            return {"recursive_ref": type(value).__name__}
        seen.add(value_id)
        try:
            return {item.name: _to_dict(getattr(value, item.name), seen) for item in fields(value)}
        finally:
            seen.remove(value_id)
    if isinstance(value, list):
        value_id = id(value)
        if value_id in seen:
            return []
        seen.add(value_id)
        try:
            return [_to_dict(item, seen) for item in value]
        finally:
            seen.remove(value_id)
    if isinstance(value, dict):
        value_id = id(value)
        if value_id in seen:
            return {"recursive_ref": "dict"}
        seen.add(value_id)
        try:
            return {_json_safe_key(key): _to_dict(item, seen) for key, item in value.items()}
        finally:
            seen.remove(value_id)
    return value
