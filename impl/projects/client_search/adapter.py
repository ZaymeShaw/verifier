from __future__ import annotations

from typing import Dict

from impl.core.adapter_v2 import ProjectAdapter
from impl.core.schema import ProjectSpec
from impl.projects.client_search.mock import ClientSearchMock
from impl.projects.client_search.tools import build_field_capability_tool, build_rule_verify_tool, build_search_api_tool
from impl.projects.client_search.tools.api_discover import load_api_discover_tools
from impl.tools import ToolRegistry, VerifiableTool


class Adapter(ProjectAdapter):
    def __init__(self, spec: ProjectSpec):
        super().__init__(spec)

    def _load_live(self):
        from impl.projects.client_search.live import ClientSearchLive
        return ClientSearchLive(self.spec)

    def _load_mock(self):
        return ClientSearchMock(self.spec)

    def _load_judge(self):
        from impl.projects.client_search.judge import ClientSearchJudge
        return ClientSearchJudge(self.spec)

    def _load_attribute(self):
        from impl.projects.client_search.attribute import ClientSearchAttribute
        return ClientSearchAttribute(self.spec, self.get_verifiable_tools())

    def _load_tools(self):
        return ToolRegistry()

    def get_verifiable_tools(self) -> list[VerifiableTool]:
        from impl.projects.client_search.live import source_config_paths

        config_paths: Dict[str, str] = source_config_paths(self.spec)
        api_spec = self.spec.api or {}
        tools: list[VerifiableTool] = [
            build_search_api_tool(
                api_base=str(api_spec.get("base_url") or "http://localhost:8000"),
                endpoint=str(api_spec.get("endpoint") or "/api/v1/client_search_query_parse_no_encipher"),
                method=str(api_spec.get("method") or "POST"),
                timeout=float(api_spec.get("timeout") or 10.0),
            ),
        ]
        field_def_path = config_paths.get("source_field_definitions")
        if field_def_path:
            tools.append(build_field_capability_tool(field_def_path))
        value_mappings_path = config_paths.get("source_value_mappings")
        enhanced_rules_path = config_paths.get("source_enhanced_rules")
        if value_mappings_path or enhanced_rules_path:
            tools.append(build_rule_verify_tool(value_mappings_path or "", enhanced_rules_path or ""))

        try:
            discovered = load_api_discover_tools(self.spec)
            existing_ids = {t.tool_id for t in tools}
            for vt in discovered:
                if vt.tool_id not in existing_ids:
                    tools.append(vt)
        except Exception:
            pass
        return tools
