"""live_schema 校验器公共实现（spec/live_schema.md）。

每个项目的 live_schema.py 实例化一个 LiveSchemaCheck，
调用方走 load_live_schema(pid).check.<method>(data) 拿到 bool。

内部委托给 SchemaValidator（协议级统一校验入口），
不再自己写校验逻辑，不再临时写 _check_shape / _parse_descriptor / _type_matches。

schema 参数以 dataclass 类型为主（如 QAExtractOutput）。旧式简写 dict 仅作为兼容层保留，项目 live_schema 不再显式手写 dict schema。
"""
from __future__ import annotations

import dataclasses
from typing import Any, Dict, Optional, Set

from .schema_validator import SchemaValidator
from .structured_output import StructuredOutputSpec


def _to_spec(schema: Any) -> StructuredOutputSpec:
    """将 dataclass schema 转成 StructuredOutputSpec；dict 仅保留旧数据兼容。

    支持：
    - dataclass 类型 → StructuredOutputSpec.from_dataclass
    - 旧式简写 dict → 用 _BareDict dynamic dataclass 包装

    旧式简写语义：
    - 无 ? 后缀的字段（如 "str"）= 必填字段（必须存在），但不强制非空
    - 有 ? 后缀的字段（如 "str?"）= 可选字段
    - 有 |null 的字段（如 "str|null"）= 必填字段，但值允许 None/null
    所以这里只把必填字段加入 required，不加 required_nonempty（保持与旧版 _check_shape 一致）。
    """
    if isinstance(schema, type) and dataclasses.is_dataclass(schema):
        return StructuredOutputSpec.from_dataclass(schema)
    if isinstance(schema, dict):
        # 旧式简写 dict：必填字段（无 ? 后缀）加入 required，不加 required_nonempty
        required = []
        for name, desc in schema.items():
            if not _is_optional(desc):
                required.append(name)
        return StructuredOutputSpec.from_dataclass(
            _dict_to_dataclass(schema),
            required_nonempty=[],  # 旧式简写不强制非空，只校验字段存在
            description="live_schema 形状（旧式简写 dict）",
        )
    return StructuredOutputSpec.from_dataclass(
        _dict_to_dataclass({}),
        description="空形状",
    )


def _is_optional(desc: Any) -> bool:
    """判断描述符是否可选（? 后缀）。|null 只表示 nullable，不表示字段可缺。"""
    if isinstance(desc, dict):
        return False
    if not isinstance(desc, str):
        return False
    s = desc.strip()
    return s.endswith("?")


def _dict_to_dataclass(shape: dict) -> type:
    """旧式简写 dict → 动态 dataclass。

    简写规则：
      "str" → str（必传）, "str?" → Optional[str]（可缺）, "str|null" → Optional[str]（必传但可为 None）
      "int" → int, "number" → float
      "list" → list, "list?" → Optional[list]
      "dict" → dict, "dict?" → Optional[dict]
      "bool" → bool
    """
    from typing import Optional as _Optional

    required_fields = []
    optional_fields = []
    for name, desc in shape.items():
        py_type = _desc_to_type(desc)
        if _is_optional(desc):
            optional_fields.append((name, py_type, dataclasses.field(default=None)))
        else:
            required_fields.append((name, py_type))

    # dataclass 要求无 default 字段排在有 default 字段之前；旧 dict 的声明顺序可能混排。
    cls = dataclasses.make_dataclass("_LiveSchemaShape", [*required_fields, *optional_fields])
    return cls


def _desc_to_type(desc: Any) -> Any:
    """解析类型描述符 → Python 类型。"""
    if isinstance(desc, dict):
        return Optional[dict]
    if not isinstance(desc, str):
        return Any
    from typing import Any as AnyType, Optional as _Optional
    s = desc.strip()
    # nullable: "str|null"
    nullable = "|null" in s
    if nullable:
        s = s.split("|null")[0].strip()
    optional = s.endswith("?")
    if optional:
        s = s[:-1].strip()
    base = s.split("[", 1)[0].split("(", 1)[0].strip().lower()
    type_map = {
        "string": str, "str": str,
        "list": list, "array": list,
        "dict": dict, "object": dict,
        "int": int, "integer": int, "number": float,
        "float": float,
        "bool": bool,
    }
    py_type = type_map.get(base, AnyType)
    if optional or nullable:
        return _Optional[py_type]
    return py_type


class LiveSchemaCheck:
    """live_schema dataclass 校验器。每个 live_schema.py 实例化一个，调用方零字段名知识。

    用法（在 live_schema.py 末尾）：
        check = LiveSchemaCheck(REQUEST_SCHEMA, EXTRACT_OUTPUT_SCHEMA, ready)
    调用方：
        load_live_schema(pid).check.output(data)  → True/False

    ready 来源：live_schema 模块定义 READY 常量，或运行时从 project.yaml 读。
    """

    def __init__(self, request_schema: Any, output_schema: Any, ready: Optional[list] = None):
        self._request_validator = SchemaValidator(_to_spec(request_schema))
        self._output_validator = SchemaValidator(_to_spec(output_schema))
        self._ready = set(ready or [])

    def request(self, data: Any) -> bool:
        """校验 live 请求体是否符合 REQUEST_SCHEMA。"""
        return self._request_validator.is_valid(data, strict=True, allow_extra=False)

    def output(self, data: Any) -> bool:
        """校验 output 是否符合 EXTRACT_OUTPUT_SCHEMA。"""
        return self._output_validator.is_valid(data, strict=True, allow_extra=False)

    def reference(self, data: Any) -> bool:
        """reference 与 output 同形状，但允许缺少字段（reference 可以是 output 的子集）。"""
        return self._output_validator.is_valid(data, strict=False, allow_extra=False)

    def case(self, case: Any) -> bool:
        """校验一条 mock case 是否完整合规。按 ready 协议决定校验范围。

        - output 在 ready → 必须有 output 且 output(case.output) 为 True
        - output 不在 ready → 不能有 output
        - reference 同理
        - input 永远校验 request(case.input)
        """
        if not isinstance(case, dict):
            return False
        if not self.request(case.get("input")):
            return False
        has_output = "output" in case and case.get("output") is not None
        if "output" in self._ready:
            if not has_output or not self.output(case.get("output")):
                return False
        else:
            if has_output:
                return False
        has_ref = "reference" in case and case.get("reference") is not None
        if "reference" in self._ready:
            if not has_ref or not self.reference(case.get("reference")):
                return False
        else:
            if has_ref:
                return False
        return True

    def case_errors(self, case: Any) -> list[str]:
        """单条 case 校验，返回错误描述列表（空列表表示通过）。"""
        errors: list[str] = []
        if not isinstance(case, dict):
            return ["case 不是 dict"]
        cid = str(case.get("id") or case.get("case_id") or "")
        tag = f"[{cid}] " if cid else ""
        if not self.request(case.get("input")):
            errors.append(f"{tag}input 不符合 REQUEST_SCHEMA")
        has_output = "output" in case and case.get("output") is not None
        if "output" in self._ready:
            if not has_output:
                errors.append(f"{tag}ready 含 output 但 case 缺 output")
            elif not self.output(case.get("output")):
                errors.append(f"{tag}output 不符合 EXTRACT_OUTPUT_SCHEMA")
        else:
            if has_output:
                errors.append(f"{tag}ready 不含 output 但 case 携带了 output")
        has_ref = "reference" in case and case.get("reference") is not None
        if "reference" in self._ready:
            if not has_ref:
                errors.append(f"{tag}ready 含 reference 但 case 缺 reference")
            elif not self.reference(case.get("reference")):
                errors.append(f"{tag}reference 不符合 EXTRACT_OUTPUT_SCHEMA")
        else:
            if has_ref:
                errors.append(f"{tag}ready 不含 reference 但 case 携带了 reference")
        return errors

    def check_all(self, cases: list) -> dict:
        """对一批 case 逐条校验，返回汇总。

        返回 {passed, failed, total, details: [{case_id, scenario, passed, errors}]}。
        不阻断：失败的 case 仍由调用方决定如何处理。
        """
        details: list[dict] = []
        passed = failed = 0
        for case in cases or []:
            if not isinstance(case, dict):
                failed += 1
                details.append({"case_id": "", "scenario": "", "passed": False, "errors": ["case 不是 dict"]})
                continue
            errs = self.case_errors(case)
            ok = not errs
            if ok:
                passed += 1
            else:
                failed += 1
            details.append({
                "case_id": str(case.get("id") or case.get("case_id") or ""),
                "scenario": str(case.get("scenario") or ""),
                "passed": ok,
                "errors": errs,
            })
        return {"passed": passed, "failed": failed, "total": passed + failed, "details": details}