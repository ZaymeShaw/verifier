from __future__ import annotations

from ..core.llm_client import LlmClient


def llm_client_for_analysis(project_id: str) -> LlmClient:
    """创建 L3 分析用的轻量 LLM 客户端，不绑定任何项目 spec。

    caller 固定为 "context_analyzer"，避免与正常 agent 调用混淆。
    """
    from ..core.config import get_llm_config
    from ..core.llm_client import LlmClient
    llm_config = get_llm_config()
    client = LlmClient(
        api_key=llm_config.api_key,
        base_url=llm_config.base_url,
        model=llm_config.model,
        tool_call_limit=0,
    )
    client._caller = "context_analyzer"
    client._project_id = str(project_id or "default")
    return client