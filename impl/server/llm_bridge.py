from __future__ import annotations

from ..core.llm_client import LlmClient


def llm_client_for_analysis(project_id: str) -> LlmClient:
    """创建 L3 分析用的轻量 LLM 客户端，不绑定任何项目 spec。

    caller 固定为 "context_analyzer"，避免与正常 agent 调用混淆。
    """
    client = LlmClient(
        role="context_analyzer",
        tool_call_limit=0,
    )
    client._caller = "context_analyzer"
    client._project_id = str(project_id or "default")
    return client
