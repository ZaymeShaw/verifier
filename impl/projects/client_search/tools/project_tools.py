"""Client Search 项目的 Tools 实现

实现 ProjectTools 协议。
"""
from __future__ import annotations

from typing import Any, Dict, List

from impl.core.tools_protocol import ProjectTools
from impl.core.config_schema import ConfigError
from impl.tools import ToolRegistry, VerifiableTool
from impl.projects.client_search.tools import (
    ClientSearchConditionCompareTool,
    build_field_capability_tool,
    build_rule_verify_tool,
    build_search_api_tool,
)


class ClientSearchTools(ProjectTools):
    """Client Search 项目 Tools 实现"""

    def verifiable_tools(self) -> List[Any]:
        """返回可验证工具列表"""
        config_paths = self._source_config_paths()
        api_spec = self.spec.service("primary")
        required = ("base_url", "endpoint", "method", "timeout_seconds")
        missing = [field for field in required if api_spec.get(field) in (None, "")]
        if api_spec and missing:
            raise ConfigError(f"client_search runtime.services.primary missing: {', '.join(missing)}")
        tools: list[VerifiableTool] = []
        if api_spec:
            tools.append(build_search_api_tool(
                api_base=str(api_spec["base_url"]),
                endpoint=str(api_spec["endpoint"]),
                method=str(api_spec["method"]),
                timeout=float(api_spec["timeout_seconds"]),
            ))
        field_def_path = config_paths.get("source_field_definitions")
        if field_def_path:
            tools.append(build_field_capability_tool(field_def_path))
        value_mappings_path = config_paths.get("source_value_mappings")
        enhanced_rules_path = config_paths.get("source_enhanced_rules")
        if value_mappings_path or enhanced_rules_path:
            tools.append(build_rule_verify_tool(value_mappings_path or "", enhanced_rules_path or ""))

        # 自动发现的 API endpoint tool
        try:
            from impl.projects.client_search.tools.api_discover import load_api_discover_tools
            discovered = load_api_discover_tools(self.spec)
            existing_ids = {t.tool_id for t in tools}
            for vt in discovered:
                if vt.tool_id not in existing_ids:
                    tools.append(vt)
        except Exception:
            pass
        return tools

    def protocol_tools(self) -> Any:
        """返回协议工具注册表"""
        registry = ToolRegistry()
        registry.register(ClientSearchConditionCompareTool())
        return registry

    def _source_config_paths(self) -> Dict[str, str]:
        """获取源码配置文件路径"""
        return {
            "source_field_definitions": self.spec.source_path("field_definitions"),
            "source_field_enums": self.spec.source_path("field_enums"),
            "source_value_mappings": self.spec.source_path("value_mappings"),
            "source_enhanced_rules": self.spec.source_path("enhanced_rules"),
        }
