"""client_search 项目专属静态配置片段检索工具。

该工具只读取 value_mappings 和 enhanced_rules 中与关键词匹配的最小子树，
不执行业务搜索 API，也不证明某条规则在当前 trace 中实际触发。
"""
from __future__ import annotations

from typing import Any, Dict, List

import yaml

from impl.tools import ToolResult, VerifiableTool


def _load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"configuration root must be an object: {path}")
    return data


def _matching_subtree(value: Any, keyword: str) -> Any:
    """Keep only branches that contain the keyword instead of returning a whole top-level list."""
    needle = keyword.casefold()
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if needle in str(key).casefold():
                result[key] = child
                continue
            matched = _matching_subtree(child, keyword)
            if matched not in (None, {}, []):
                result[key] = matched
        return result or None
    if isinstance(value, list):
        result = [child for child in value if needle in str(child).casefold()]
        return result or None
    return value if needle in str(value).casefold() else None


def build_rule_verify_tool(
    value_mappings_path: str,
    enhanced_rules_path: str,
) -> VerifiableTool:
    """创建静态配置片段检索工具。"""
    tool_id = "client_search.rule_verify"

    def execute(**kwargs: Any) -> ToolResult:
        # agno validate_call 按 JSON schema kwargs 传参，用 **kwargs 接收
        params = kwargs
        keyword = params.get("keyword") or params.get("field") or ""
        actual: Dict[str, Any] = {"keyword": keyword, "mappings": {}, "rules": {}}
        matched_any = False
        if not str(keyword).strip():
            return ToolResult(
                tool_id=tool_id,
                status="failed",
                actual=actual,
                error="keyword or field is required; full configuration export is not supported",
            )
        if value_mappings_path:
            try:
                mappings = _load_yaml(value_mappings_path)
            except Exception as exc:
                return ToolResult(
                    tool_id=tool_id,
                    status="failed",
                    actual=actual,
                    error=f"failed to load value mappings: {type(exc).__name__}: {exc}",
                )
            filtered = _matching_subtree(mappings, str(keyword))
            matched_any = matched_any or bool(filtered)
            actual["mappings"] = filtered if filtered else {"note": f"no mapping matched keyword '{keyword}'"}
        if enhanced_rules_path:
            try:
                rules = _load_yaml(enhanced_rules_path)
            except Exception as exc:
                return ToolResult(
                    tool_id=tool_id,
                    status="failed",
                    actual=actual,
                    error=f"failed to load enhanced rules: {type(exc).__name__}: {exc}",
                )
            filtered = _matching_subtree(rules, str(keyword))
            matched_any = matched_any or bool(filtered)
            actual["rules"] = filtered if filtered else {"note": f"no rule matched keyword '{keyword}'"}
        return ToolResult(
            tool_id=tool_id,
            status="succeeded" if matched_any else "inconclusive",
            actual=actual,
            evidence=f"loaded value_mappings + enhanced_rules from {value_mappings_path}, {enhanced_rules_path}",
        )

    execute.__name__ = tool_id.replace(".", "_")
    execute.__doc__ = "查询客户搜索配置规则片段，返回 value_mappings 和 enhanced_rules 中与关键词或字段匹配的内容。"
    return VerifiableTool(
        tool_id=tool_id,
        description="查询客户搜索配置映射和增强规则。必须输入 keyword 或 field；输出匹配的最小配置子树，不支持返回完整配置。该工具提供静态配置证据，不执行搜索 API，也不判断规则是否已在某次运行中触发。",
        applicable_scenario="attr",
        parameters={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "minLength": 1, "description": "过滤 value_mappings 和 enhanced_rules 的业务关键词或字段名，如 年金、premium、clientAge。keyword 与 field 至少提供一个。"},
                "field": {"type": "string", "minLength": 1, "description": "字段名过滤条件，与 keyword 等价；keyword 与 field 至少提供一个。"},
            },
            "required": [],
            "anyOf": [
                {"required": ["keyword"]},
                {"required": ["field"]},
            ],
        },
        execute_fn=execute,
    )
