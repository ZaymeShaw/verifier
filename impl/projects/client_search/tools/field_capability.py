"""
client_search 项目专属可执行验证 tool：字段定义查询 + 能力清单。

把"查字段定义"做成可执行验证 tool（而非搬运）。execute_fn 真去读 source YAML，
返回 actual 的字段能力（允许的操作符、值类型、枚举、单位）。LLM 拿到 actual 后
可以判断"trace 里 actual 用的操作符是否在字段能力范围内"，做 actual 交叉对照。

注意：这是"查询类"而非"执行类"——它读的是配置事实，不是跑业务函数。但相比
旧 field_retrieval 的"搬运字段定义"，它产出的是标准化 actual + evidence，能直接
被归因当作证据使用。保留它是因为字段能力是 client_search 归因的高频证据来源。
"""
from __future__ import annotations

from typing import Any, Dict

import yaml

from impl.tools import ToolResult, VerifiableTool


def _load_field_definitions(yaml_path: str) -> dict:
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def build_field_capability_tool(field_definitions_path: str) -> VerifiableTool:
    """创建"字段能力查询"可执行验证 tool。"""
    tool_id = "client_search.field_capability"

    def execute(**kwargs: Any) -> ToolResult:
        # agno validate_call 按 JSON schema kwargs 传参，用 **kwargs 接收
        params = kwargs
        field_name = params.get("field") or ""
        if not field_name:
            return ToolResult(
                tool_id=tool_id,
                status="inconclusive",
                evidence="no field name provided",
            )
        data = _load_field_definitions(field_definitions_path)
        intents = data.get("intents") or []
        entries = [item for item in intents if isinstance(item, dict) and item.get("field") == field_name]
        if not entries:
            return ToolResult(
                tool_id=tool_id,
                status="inconclusive",
                actual={"field": field_name, "found": False},
                evidence=f"field '{field_name}' not found in source_field_definitions",
            )
        operators = set()
        value_types = set()
        enums = []
        unit = None
        description = None
        for entry in entries:
            if entry.get("operator"):
                operators.add(entry["operator"])
            if entry.get("value_type"):
                value_types.add(entry["value_type"])
            if entry.get("enum") and not enums:
                enums = list(entry["enum"])
            if entry.get("unit") and not unit:
                unit = entry["unit"]
            if entry.get("description") and not description:
                description = entry["description"]
        actual = {
            "field": field_name,
            "found": True,
            "operators": sorted(operators),
            "value_types": sorted(value_types),
            "enums": enums,
            "unit": unit,
            "description": description,
        }
        return ToolResult(
            tool_id=tool_id,
            status="succeeded",
            actual=actual,
            evidence=f"loaded from source_field_definitions.yaml; {len(entries)} intent entries matched",
        )

    execute.__name__ = tool_id.replace(".", "_")
    execute.__doc__ = "查询业务字段的能力定义：允许的操作符、值类型、枚举值、单位。用于验证 trace actual 里的 field/operator/value 是否在字段能力范围内。"
    return VerifiableTool(
        tool_id=tool_id,
        description="查询业务字段的能力定义：允许的操作符、值类型、枚举值、单位。用于验证 trace actual 里的 field/operator/value 是否在字段能力范围内（actual 交叉对照）。",
        applicable_scenario="attr",
        parameters={
            "type": "object",
            "properties": {
                "field": {"type": "string", "description": "字段名，如 clientAge、annPremSegNum、pCategorys"},
            },
            "required": ["field"],
        },
        execute_fn=execute,
    )