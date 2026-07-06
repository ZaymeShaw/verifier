from __future__ import annotations

from typing import Any, Optional


def _non_empty_reference(value: Any) -> bool:
    # reference 是否真正携带可比较内容。
    if value is None:
        return False
    if isinstance(value, dict):
        return any(item not in (None, "", [], {}) for item in value.values())
    if isinstance(value, list):
        return bool(value)
    return value != ""


def _first_list_value(data: Any) -> Any:
    # 返回 dict 中第一个 list 值，用于 output/reference 形状对齐。
    if not isinstance(data, dict):
        return None
    for value in data.values():
        if isinstance(value, list):
            return value
    return None


def _first_list_key(data: Any) -> Optional[str]:
    # 返回 dict 中第一个 list 字段名，用于 output/reference 形状对齐。
    if not isinstance(data, dict):
        return None
    for key, value in data.items():
        if isinstance(value, list):
            return key
    return None
