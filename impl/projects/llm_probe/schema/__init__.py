"""llm_probe 项目 dataclass schema。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class LlmProbeRequest:
    """curl 信封：HTTP JSON body 是 body，其余字段给 live/judge 用。"""

    body: Dict[str, Any]
    url: str = ""
    method: str = "POST"
    headers: Dict[str, Any] = field(default_factory=dict)
    capability_ref: str = ""
    capability: str = ""
    boundary: str = ""
    show_schema: Any = None


@dataclass
class LlmProbeExtractOutput:
    """curl 响应 body 的字符串形态。"""

    output_text: str
