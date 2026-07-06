from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class LayerConfig:
    # Config 层：某一层协议/配置的最小声明，后续可映射到 yaml 或 project.yaml。
    layer: str
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""


@dataclass
class SchemaLayerConfig:
    # Config 层：记录本项目有哪些 schema 分层，以及每层当前使用的模块。
    project_id: str = ""
    layers: List[LayerConfig] = field(default_factory=list)
    version: str = "current-dataclass"
