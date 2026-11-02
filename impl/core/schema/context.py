from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ContextRecord:
    """通用 LLM 上下文追踪记录。不绑定任何特定 agent 的字段结构。

    任何走 LlmClient 的 agent 调用都会自动生成一条 ContextRecord，
    记录完整输入输出，用于上下文审计、预算分析和调试。
    """
    record_id: str
    trace_id: str
    project_id: str
    caller: str  # 开放字符串，非枚举："judge"|"attribute"|"live"|"cluster"|"check"|...
    # 本次发给模型的输入消息；SDK 返回的完整会话另见 response.run_messages。
    messages: List[Dict[str, Any]] = field(default_factory=list)
    response: Any = None
    created_at: str = ""
    prompt_size: int = 0
    llm_model: str = ""
    elapsed_ms: int = 0
    error: Optional[str] = None
    # Optional deterministic Context Governance snapshot/finding report.
    # Full messages remain the replay source; governance stores hashes,
    # provenance metadata and gates rather than duplicating prompt text.
    governance: Dict[str, Any] = field(default_factory=dict)
    # 同一次逻辑调用被重复落档的次数（重试会产生内容与结果完全相同的记录）。
    retry_count: int = 0


@dataclass
class ContextRecordSummary:
    """上下文记录摘要，list 接口使用，不含 prompt 全量。"""
    record_id: str
    trace_id: str
    project_id: str
    caller: str
    prompt_size: int = 0
    llm_model: str = ""
    elapsed_ms: int = 0
    created_at: str = ""
    error: Optional[str] = None
    governance_blocking: bool = False
    # 同一逻辑调用被重复落档的次数（重试产生）。
    retry_count: int = 0
    # response.runtime.stage；ToolLoop 的段编码在里面（如 main:s2），L2 异常按 caller + stage 分组。
    stage: str = ""
