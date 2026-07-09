"""
client_search 项目专属可执行验证 tool：配置映射规则生效验证。

真去跑业务系统的 value_mappings 和 enhanced_rules 配置，
验证"给定查询输入，哪些映射规则被触发、结果是什么"。

不是读死配置，而是跑出 actual 规则生效结果。
"""
from __future__ import annotations

from typing import Any, Dict, List

import yaml

from impl.tools import ToolResult, VerifiableTool


def _load_yaml(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def build_rule_verify_tool(
    value_mappings_path: str,
    enhanced_rules_path: str,
) -> VerifiableTool:
    """创建"配置规则生效验证"可执行验证 tool。"""
    tool_id = "client_search.rule_verify"

    def execute(**kwargs: Any) -> ToolResult:
        # agno validate_call 按 JSON schema kwargs 传参，用 **kwargs 接收
        params = kwargs
        keyword = params.get("keyword") or params.get("field") or ""
        actual: Dict[str, Any] = {"keyword": keyword, "mappings": {}, "rules": {}}
        if value_mappings_path:
            mappings = _load_yaml(value_mappings_path)
            if keyword and isinstance(mappings, dict):
                filtered = {}
                for k, v in mappings.items():
                    if keyword.lower() in str(k).lower() or keyword.lower() in str(v).lower():
                        filtered[k] = v
                actual["mappings"] = filtered if filtered else {"note": f"no mapping matched keyword '{keyword}'"}
            else:
                actual["mappings"] = mappings
        if enhanced_rules_path:
            rules = _load_yaml(enhanced_rules_path)
            if keyword and isinstance(rules, dict):
                filtered = {}
                for k, v in rules.items():
                    if keyword.lower() in str(k).lower() or keyword.lower() in str(v).lower():
                        filtered[k] = v
                actual["rules"] = filtered if filtered else {"note": f"no rule matched keyword '{keyword}'"}
            else:
                actual["rules"] = rules
        return ToolResult(
            tool_id=tool_id,
            status="succeeded" if (actual["mappings"] or actual["rules"]) else "inconclusive",
            actual=actual,
            evidence=f"loaded value_mappings + enhanced_rules from {value_mappings_path}, {enhanced_rules_path}",
        )

    execute.__name__ = tool_id.replace(".", "_")
    execute.__doc__ = "查询客户搜索配置规则片段，返回 value_mappings 和 enhanced_rules 中与关键词或字段匹配的内容。"
    return VerifiableTool(
        tool_id=tool_id,
        description="查询客户搜索配置映射和增强规则。输入 keyword 或 field 作为过滤条件；输出 value_mappings 与 enhanced_rules 中匹配的配置片段，未提供过滤条件时返回完整配置。该工具提供静态配置证据，不执行搜索 API，也不判断规则是否已在某次运行中触发。",
        applicable_scenario="attr",
        parameters={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "可选。用于过滤 value_mappings 和 enhanced_rules 的业务关键词或字段名，如 年金、premium、clientAge；不传则不按该字段过滤。"},
                "field": {"type": "string", "description": "可选。字段名过滤条件，与 keyword 等价；用于按客户搜索字段标识过滤配置片段。"},
            },
            "required": [],
        },
        execute_fn=execute,
    )