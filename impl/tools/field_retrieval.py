"""
通用 Tool 协议：字段定义检索（辅助 tool，已降级）。

⚠️ 降级说明（spec/tool2.md）：
此 tool 是"信息搬运"而非"可执行验证"，不作为归因主力。归因主力是各项目 adapter
在 get_verifiable_tools() 里提供的可执行验证 tool（execute_fn 真能跑、能产出 actual）。
本 tool 仅作为兜底辅助，供 judge/attr 在没有项目级字段能力 tool 时使用。

具体字段能力验证应由项目层提供（如 client_search/tools/field_capability.py）。
"""
from __future__ import annotations

from typing import Protocol, Optional


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


def create_field_search_tool(provider: FieldDefinitionProvider):
    """
    协议通用：创建字段搜索 tool。

    Args:
        provider: 字段定义提供者（项目专属实现）

    Returns:
        search_field_definition 函数（用于 Agno Agent tools）
    """

    def search_field_definition(field_name: str) -> str:
        """
        Search for a specific field's definition from project source documents.

        Args:
            field_name: The field name to search (e.g., "clientAge", "annPremSegNum")

        Returns:
            Field definition including operators, value types, description, and examples.
            Returns "Field not found" if the field doesn't exist.
        """
        try:
            field_def = provider.get_field_definition(field_name)

            if not field_def:
                return f"Field '{field_name}' not found in field definitions"

            # 协议通用：格式化输出
            lines = [f"Field: {field_def['field']}"]

            if field_def.get('description'):
                lines.append(f"Description: {field_def['description']}")

            if field_def.get('operators'):
                lines.append(f"Allowed operators: {', '.join(field_def['operators'])}")

            if field_def.get('value_types'):
                lines.append(f"Value types: {', '.join(field_def['value_types'])}")

            if field_def.get('enums'):
                lines.append(f"Valid values: {', '.join(field_def['enums'])}")

            if field_def.get('unit'):
                lines.append(f"Unit: {field_def['unit']}")

            if field_def.get('examples'):
                lines.append(f"Examples: {'; '.join(field_def['examples'])}")

            if field_def.get('notes'):
                lines.append(f"Notes: {field_def['notes']}")

            return "\n".join(lines)

        except Exception as e:
            return f"Error retrieving field definition: {str(e)}"

    # Tool metadata
    search_field_definition.__name__ = "search_field_definition"
    search_field_definition.__doc__ = (
        "Search for a specific field's definition from project source documents. "
        "Use this when you need to verify field capabilities, operators, or value types "
        "that are not provided in the capability_manifest. "
        "Returns field description, allowed operators, value types, and examples."
    )

    return search_field_definition
