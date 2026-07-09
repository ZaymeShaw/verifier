"""
通用 Tool 协议：字段定义检索。

本模块将项目字段定义 provider 包装成统一 VerifiableTool，作为 judge 在 capability_manifest
信息不足时的按需检索兜底。具体字段能力验证仍应优先由项目层可执行 tool 提供。
"""
from __future__ import annotations

from typing import Any, Protocol, Optional

from impl.tools.protocol import ToolResult, VerifiableTool


class FieldDefinitionProvider(Protocol):
    """
    协议：字段定义提供者。

    每个项目需要实现这个协议，提供自己的字段定义查找逻辑。
    """

    def get_field_definition(self, field_name: str) -> Optional[dict]:
        """
        获取字段定义。

        Args:
            field_name: 字段名

        Returns:
            字段定义字典，包含：
            - field: 字段名
            - description: 描述
            - operators: 允许的操作符列表
            - value_types: 值类型列表
            - examples: 示例列表
            - enums: 枚举值列表（如果适用）
            - unit: 单位（如果适用）
            - notes: 备注（如果适用）

            如果字段不存在，返回 None。
        """
        ...


def create_field_search_verifiable_tool(provider: FieldDefinitionProvider) -> VerifiableTool:
    def search_field_definition(**kwargs: Any) -> ToolResult:
        field_name = str(kwargs.get("field_name") or kwargs.get("field") or "")
        try:
            field_def = provider.get_field_definition(field_name)

            if not field_def:
                return ToolResult(
                    tool_id="field.search_definition",
                    tool_type="field_retrieval",
                    status="inconclusive",
                    actual={"field_name": field_name, "found": False},
                    evidence=f"field '{field_name}' not found in field definitions",
                )

            actual = {
                "field": field_def.get("field"),
                "description": field_def.get("description"),
                "operators": field_def.get("operators") or [],
                "value_types": field_def.get("value_types") or [],
                "examples": field_def.get("examples") or [],
                "enums": field_def.get("enums") or [],
                "unit": field_def.get("unit"),
                "notes": field_def.get("notes"),
            }
            return ToolResult(
                tool_id="field.search_definition",
                tool_type="field_retrieval",
                status="succeeded",
                actual=actual,
                evidence=f"retrieved field definition for {field_name}",
            )
        except Exception as e:
            return ToolResult(
                tool_id="field.search_definition",
                tool_type="field_retrieval",
                status="failed",
                error=f"Error retrieving field definition: {str(e)}",
            )

    search_field_definition.__name__ = "field_search_definition"
    return VerifiableTool(
        tool_id="field.search_definition",
        description="当 user prompt 中的 capability_manifest 不足以判断某个字段是否合法或如何取值时调用。输入字段名，返回该字段的业务含义、允许操作符、值类型、示例、枚举、单位和备注；如果 prompt 已包含该字段完整能力清单，应优先使用 prompt 信息。",
        applicable_scenario="judge",
        parameters={
            "type": "object",
            "properties": {
                "field_name": {"type": "string", "description": "必填。需要查询定义的项目字段名，应使用项目文档或 actual output 中出现的原始字段标识，如 clientAge、annPremSegNum。"},
                "field": {"type": "string", "description": "字段名别名，同 field_name；仅在调用方无法使用 field_name 参数名时作为兼容入口。"},
            },
            "required": ["field_name"],
        },
        execute_fn=search_field_definition,
    )
