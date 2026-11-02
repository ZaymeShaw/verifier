"""协议级统一校验入口（spec/struct_output.md）。

SchemaValidator 是唯一的通用校验类，不关心业务场景。
只暴露两个参数：strict 和 allow_extra，组合覆盖所有语义。

调用方：
- LLM 产出校验：strict=True, allow_extra=False（必填不能缺，额外字段阻断，保证最小协议）
- 精确匹配：strict=True, allow_extra=False（live 系统输出、请求体）
- 子集匹配：strict=False, allow_extra=False（reference，允许 missing 不允许 extra）

所有校验逻辑统一从此处取，不再临时写校验。
"""
from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence as ABCSequence
from typing import Any, Dict, List, Literal, Optional, get_args, get_origin, get_type_hints

from .structured_output import StructuredOutputSpec, tagged_union, union_discriminator


# ------------------------------------------------------------------
# 类型匹配
# ------------------------------------------------------------------

_JSON_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _json_type_name(py_type: type) -> Optional[str]:
    """Python 类型 → JSON Schema type 名称。"""
    return _JSON_TYPE_MAP.get(py_type)


def _match_type(value: Any, tp: Any) -> tuple[bool, str]:
    """校验 value 是否匹配 Python 类型注解 tp。

    支持：基本类型、Optional[X]、List[X]、Dict[K,V]、嵌套 dataclass、Any。
    """
    # Any / 未知 → 通过
    if tp is Any:
        return True, ""

    origin = get_origin(tp)
    args = get_args(tp)

    # nullable 只能由 Optional/Union[..., None] 或 Literal[..., None] 声明。
    # 非 nullable 字段不能仅因为“字段存在”就接受 JSON null。
    if value is None:
        if origin is Literal and any(candidate is None for candidate in args):
            return True, ""
        if any(candidate is type(None) for candidate in args):
            return True, ""
        return False, f"期望非 null 的 {tp!r}，实际 NoneType"

    # 多选一：这里只确认是 object；分支由区分字段决定，在 SchemaValidator 里逐字段校验。
    if tagged_union(tp) is not None:
        if not isinstance(value, dict):
            return False, f"期望 object（多选一结构），实际 {type(value).__name__}"
        return True, ""

    # Literal 同时约束类型和值；类型也必须精确匹配，避免 True 满足 Literal[1]。
    if origin is Literal:
        if any(type(value) is type(candidate) and value == candidate for candidate in args):
            return True, ""
        return False, f"期望枚举值之一 {list(args)!r}，实际 {type(value).__name__}：{value!r}"

    # Optional[X] → 剥离 Optional
    if origin is not None:
        # Union[..., None] → Optional
        if origin is not None:
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) < len(args):  # 有 None 分支
                if len(non_none) == 1:
                    return _match_type(value, non_none[0])
                if len(non_none) == 0:
                    return True, ""
                return _match_type(value, non_none[0])

    if origin is None and isinstance(tp, str):
        # 字符串形式前向引用
        return True, ""

    if origin is not None:
        # JSON sequences must arrive as arrays (Python list after decoding),
        # including fields declared as tuple[T, ...] or Sequence[T].
        if origin in (list, tuple, ABCSequence):
            if not isinstance(value, list):
                return False, f"期望 array，实际 {type(value).__name__}"
            if origin is tuple and args and args[-1] is not Ellipsis:
                if len(value) != len(args):
                    return False, f"期望长度 {len(args)} 的 array，实际长度 {len(value)}"
                for i, (item, item_type) in enumerate(zip(value, args)):
                    ok, err = _match_type(item, item_type)
                    if not ok:
                        return False, f"[{i}]: {err}"
            elif args:
                for i, item in enumerate(value):
                    ok, err = _match_type(item, args[0])
                    if not ok:
                        return False, f"[{i}]: {err}"
            return True, ""

        # Dict[K,V]
        if origin in (dict, Dict):
            if not isinstance(value, dict):
                return False, f"期望 object，实际 {type(value).__name__}"
            return True, ""  # 不校验 dict 内部值类型

    # 基本类型
    if tp in (str, int, float, bool):
        if isinstance(value, bool) and tp is not bool:
            return False, f"期望 {tp.__name__}，实际 bool"
        if not isinstance(value, tp):
            # int 可以被 float 接受
            if tp is float and isinstance(value, int):
                return True, ""
            return False, f"期望 {tp.__name__}，实际 {type(value).__name__}"
        return True, ""

    if tp is list:
        return isinstance(value, list), f"期望 array，实际 {type(value).__name__}"
    if tp is dict:
        return isinstance(value, dict), f"期望 object，实际 {type(value).__name__}"

    # 嵌套 dataclass
    if dataclasses.is_dataclass(tp):
        if not isinstance(value, dict):
            return False, f"期望 object（dataclass {tp.__name__}），实际 {type(value).__name__}"
        return True, ""  # 结构校验由 nested_schemas 管

    return True, ""


def _unwrap_optional(tp: Any) -> Any:
    """Optional[X] → X（仅当去掉 None 后只剩一个分支）；多分支 Union 原样返回。"""
    if tagged_union(tp) is not None:
        return tp
    args = get_args(tp)
    non_none = [a for a in args if a is not type(None)]
    if args and len(non_none) == 1 and len(non_none) < len(args):
        return non_none[0]
    return tp


def _is_structured(tp: Any) -> bool:
    return dataclasses.is_dataclass(tp) or tagged_union(tp) is not None


# ------------------------------------------------------------------
# 非空判定
# ------------------------------------------------------------------

def _is_empty(value: Any) -> bool:
    """None / 空字符串 / 空数组 / 空对象都算空。"""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


# ------------------------------------------------------------------
# SchemaValidator
# ------------------------------------------------------------------

class SchemaValidator:
    """协议级统一校验入口。

    用法：
        spec = StructuredOutputSpec.from_dataclass(MyDataclass, required_nonempty=["x"])
        validator = SchemaValidator(spec)
        errors = validator.validate(data, strict=True, allow_extra=True)
        if errors:
            raise ValueError(errors)
    """

    def __init__(self, spec: StructuredOutputSpec):
        self._spec = spec

    @property
    def spec(self) -> StructuredOutputSpec:
        return self._spec

    def validate(self, data: Any, *, strict: bool = True, allow_extra: bool = False) -> list[str]:
        """返回错误列表，空列表 = 通过。

        strict:
          True  → required 字段缺失 → 报错
          False → required 字段缺失 → 跳过

        allow_extra:
          True  → 额外字段 → 跳过
          False → 额外字段 → 报错
        """
        errors: list[str] = []

        if not isinstance(data, dict):
            errors.append(f"产出不是 JSON 对象，而是 {type(data).__name__}：{str(data)[:200]}")
            return errors

        # 收集 required 字段
        required = self._collect_required()

        # 校验 required 字段存在
        if strict:
            for name in required:
                if name not in data:
                    errors.append(f"必填字段缺失：{name}")

        # 校验 required_nonempty 非空，以及字段上显式声明 nonempty 的（嵌套层级同样适用）
        declared = [f.name for f in dataclasses.fields(self._spec.model) if f.metadata.get("nonempty") is True] \
            if dataclasses.is_dataclass(self._spec.model) else []
        for name in dict.fromkeys([*self._spec.required_nonempty, *declared]):
            if name in data and _is_empty(data[name]):
                errors.append(f"字段必须非空但产出为空：{name}")
        # 固定格式：声明了 pattern 的字符串字段（嵌套层级同样适用）
        if dataclasses.is_dataclass(self._spec.model):
            for f in dataclasses.fields(self._spec.model):
                pattern = f.metadata.get("pattern")
                value = data.get(f.name)
                if pattern and isinstance(value, str) and not re.search(pattern, value):
                    errors.append(f"字段格式不符：{f.name}={value[:60]!r}，须匹配 {pattern}")

        # 校验字段类型
        type_hints = self._get_type_hints()
        for name, value in data.items():
            if name not in type_hints:
                continue
            tp = type_hints[name]
            ok, err = _match_type(value, tp)
            if not ok:
                errors.append(f"字段类型不匹配：{name}，{err}")
            errors.extend(self._validate_nested_dataclass_value(name, value, tp, strict=strict, allow_extra=allow_extra))

        # 校验额外字段
        if not allow_extra:
            all_fields = set(type_hints.keys())
            for name in data:
                if name not in all_fields:
                    errors.append(f"额外字段不允许：{name}")

        # 递归校验 nested_schemas
        for fname, sub_spec in self._spec.nested_schemas.items():
            if fname not in data:
                continue
            value = data[fname]
            if value is None or _is_empty(value):
                continue
            sub_validator = SchemaValidator(sub_spec)
            sub_errors = sub_validator.validate(value, strict=strict, allow_extra=allow_extra)
            for e in sub_errors:
                errors.append(f"{fname}.{e}")

        return errors

    def is_valid(self, data: Any, *, strict: bool = True, allow_extra: bool = False) -> bool:
        return not self.validate(data, strict=strict, allow_extra=allow_extra)

    def _validate_nested_dataclass_value(self, name: str, value: Any, tp: Any, *, strict: bool, allow_extra: bool) -> list[str]:
        if value is None:
            return []
        tp = _unwrap_optional(tp)
        origin = get_origin(tp)
        args = get_args(tp)
        if origin in (list, tuple, ABCSequence) and args and _is_structured(_unwrap_optional(args[0])):
            if not isinstance(value, list):
                return []
            errors: list[str] = []
            for index, item in enumerate(value):
                errors.extend(self._validate_item(f"{name}.[{index}]", item, args[0], strict=strict, allow_extra=allow_extra))
            return errors
        if _is_structured(tp):
            return self._validate_item(name, value, tp, strict=strict, allow_extra=allow_extra)
        return []

    def _validate_item(self, label: str, value: Any, tp: Any, *, strict: bool, allow_extra: bool) -> list[str]:
        """校验一个 dataclass 或多选一结构的取值；类型不对的交给 _match_type 报，这里不重复。"""
        if value is None or not isinstance(value, dict):
            return []
        tp = _unwrap_optional(tp)
        union = tagged_union(tp)
        if union is not None:
            field_name, mapping = union_discriminator(union[0])
            tag = value.get(field_name)
            branch = next((b for k, b in mapping.items() if type(k) is type(tag) and k == tag), None)
            if branch is None:
                return [f"{label}.{field_name}：期望 {list(mapping)!r} 之一，实际 {tag!r}"]
            tp = branch
        sub_validator = SchemaValidator(StructuredOutputSpec.from_dataclass(tp))
        return [f"{label}.{err}" for err in sub_validator.validate(value, strict=strict, allow_extra=allow_extra)]

    def _collect_required(self) -> list[str]:
        """收集 required 字段：dataclass 推断 + required_nonempty 显式声明。"""
        required: list[str] = []
        hints = self._get_type_hints()
        if not hints:
            return list(self._spec.required_nonempty)

        dc_fields = {f.name: f for f in dataclasses.fields(self._spec.model)}

        for name, tp in hints.items():
            f = dc_fields.get(name)
            if f is None:
                # 无 field 定义的字段 → required
                required.append(name)
                continue
            # 有 default（包括 None / "" / "xxx" / 0 / False）→ 可缺失
            # 字段是否可缺由 default/default_factory 控制，字段值是否可为 None 由 Optional 控制。
            if f.default is not dataclasses.MISSING:
                continue
            # 有 default_factory → 可缺失
            if f.default_factory is not dataclasses.MISSING:
                continue
            # 无 default、无 default_factory → dataclass schema 基础必传字段
            required.append(name)

        for name in self._spec.required_nonempty:
            if name not in required:
                required.append(name)

        return required

    def _get_type_hints(self) -> dict[str, Any]:
        try:
            return get_type_hints(self._spec.model)
        except Exception:
            return getattr(self._spec.model, "__annotations__", {})
