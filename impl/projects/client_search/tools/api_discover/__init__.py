"""
client_search 项目 api_discover 目录（spec/apitool_discover.md）。

此目录下的文件由通用引擎 impl.core.endpoint_discovery 扫描产出，
**不手工编辑**。每次扫描全量覆盖，不和手工 tool 混。

加载入口：tools/__init__.py 通过 load_api_discover_tools(spec) 读取
_manifest.json，构建 VerifiableTool 列表。
"""
from __future__ import annotations

from typing import Any, List

from impl.core.endpoint_discovery import load_discovered_tools
from impl.tools import VerifiableTool


def load_api_discover_tools(spec: Any) -> List[VerifiableTool]:
    """加载本项目自动发现的 API endpoint tool。

    从 tools/api_discover/_manifest.json 读取已落盘的扫描结果，
    构建为 VerifiableTool 返回。若 manifest 不存在则先触发扫描。
    若项目未配置 endpoint_discovery 则返回空列表（完全兼容）。
    """
    return load_discovered_tools(spec)


__all__ = ["load_api_discover_tools"]