"""结构化输出协议层（spec/struct_output.md）。

所有 LLM 调用（judge / live_stub / mock_agent 等）凡是有明确输出结构的，都通过本模块
声明"我要什么输出"，由协议层统一负责：

1. 从 dataclass 提取 JSON Schema（递归支持嵌套 dataclass）
2. 生成 prompt 文案注入 system prompt（兜底强化，DeepSeek 不支持 json_schema response_format）
3. LLM 返回后用同一份 schema 校验，不合规直接阻断（不放行"结构正确但内容为空"的假货）

## 真相源分层（与 spec/reference.md / spec/schema.md 对齐）

- live schema（impl/projects/<project>/schema/）= 系统侧事实，项目级通用
- impl/projects/<project>/schema/ = 评估侧/模拟侧的特化需求，按项目覆盖
- impl/core/schema/ = 评估侧/模拟侧的通用需求

## 可选 vs nullable 映射规则

- **可缺失字段**（旧描述符 `?`）：`field(default=None)` 且不放 required —— 字段可以不出现在 JSON 里
- **nullable 字段**（旧描述符 `|null`）：`Optional[str]` 但仍在 required 里 —— 字段必须在，值可以是 None

## 嵌套 dataclass 硬约束

嵌套层级里只能包含可序列化内容：基本类型（str/int/float/bool）、list、dict、嵌套 dataclass。
不允许把任意 Python 类、函数、复杂对象塞进 dataclass 字段，保证提取出的 JSON Schema 干净。
"""
from __future__ import annotations

import dataclasses
import json
import typing
from typing import Any, Dict, List, Optional, Type, Union, get_args, get_origin, get_type_hints


# ------------------------------------------------------------------
# 类型 → JSON Schema 基本类型映射
# ------------------------------------------------------------------

_PRIMITIVE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}

_PY_NAME_TO_SCHEMA = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "dict": "object",
    "Any": None,  # Any → 不约束类型
}


def _is_dataclass_type(tp: Any) -> bool:
    return isinstance(tp, type) and dataclasses.is_dataclass(tp)


def _strip_optional(tp: Any) -> tuple[Any, bool]:
    """剥离 Optional/Union[...]/None，返回 (基础类型, is_nullable)。

    Optional[str] → (str, True)
    Union[str, int] → (str, False)  # 取第一个非 None 分支，不严格
    str            → (str, False)
    """
    origin = get_origin(tp)
    if origin is Union or (origin is not None and tp.__class__ is typing.Union):
        args = [a for a in get_args(tp) if a is not type(None)]
        if not args:
            return (Any, True)
        return (args[0], True)  # Union 视为 nullable，取第一个分支
    return (tp, False)


def _type_to_schema(tp: Any, _defs: dict, _seen: set) -> Dict[str, Any]:
    """把一个类型注解转成 JSON Schema 片段。递归处理嵌套 dataclass。

    _defs 收集嵌套 dataclass 的 schema（用于 $defs），_seen 防递归循环。
    """
    tp, nullable = _strip_optional(tp)

    # 基本类型
    if tp in _PRIMITIVE_MAP:
        schema: Dict[str, Any] = {"type": _PRIMITIVE_MAP[tp]}
        if tp is str:
            schema["minLength"] = 1  # 字符串非空（防假货）
        if nullable:
            schema["type"] = [schema["type"], "null"] if isinstance(schema.get("type"), str) else schema["type"]
        return schema

    # 字符串形式的前向引用（"str" / "list" 等）—— 兼容旧式注解
    if isinstance(tp, str):
        base = _PY_NAME_TO_SCHEMA.get(tp)
        if base is None:
            return {}  # Any / 未知 → 不约束
        schema = {"type": base}
        if base == "string":
            schema["minLength"] = 1
        if nullable and isinstance(schema.get("type"), str):
            schema["type"] = [schema["type"], "null"]
        return schema

    origin = get_origin(tp)

    # List[X] / list
    if origin in (list, List):
        args = get_args(tp)
        item_tp = args[0] if args else Any
        item_schema = _type_to_schema(item_tp, _defs, _seen)
        schema = {"type": "array", "items": item_schema}
        if nullable:
            schema["type"] = ["array", "null"]
        return schema

    # Dict[K, V] / dict
    if origin in (dict, Dict):
        schema = {"type": "object"}
        if nullable:
            schema["type"] = ["object", "null"]
        return schema

    # 嵌套 dataclass
    if _is_dataclass_type(tp):
        if tp.__name__ not in _defs:
            _defs[tp.__name__] = _dataclass_to_schema(tp, _defs, _seen, include_defs=False)
        schema = {"$ref": f"#/$defs/{tp.__name__}"}
        if nullable:
            schema = {"anyOf": [{"$ref": f"#/$defs/{tp.__name__}"}, {"type": "null"}]}
        return schema

    # Any / 未知 → 不约束
    return {}


def _dataclass_to_schema(dc_type: Type, _defs: Optional[dict] = None, _seen: Optional[set] = None, *, include_defs: bool = True) -> Dict[str, Any]:
    """从 dataclass 类型提取 JSON Schema。

    required 字段 = 没有 default 且不是 field(default=None) 的字段。
    """
    if _defs is None:
        _defs = {}
    if _seen is None:
        _seen = set()

    # 防递归：如果已经处理过这个类型，返回 $ref（不在 _defs 里注册，避免重复）
    ref_name = dc_type.__name__
    if ref_name in _seen:
        return {"$ref": f"#/$defs/{ref_name}"}

    _seen.add(ref_name)

    try:
        hints = get_type_hints(dc_type)
    except Exception:
        hints = getattr(dc_type, "__annotations__", {})

    properties: Dict[str, Any] = {}
    required: List[str] = []
    dc_fields = {f.name: f for f in dataclasses.fields(dc_type)}

    for name, tp in hints.items():
        properties[name] = _type_to_schema(tp, _defs, _seen)
        f = dc_fields.get(name)
        if f is None:
            required.append(name)
            continue
        # 有 default（包括 None / "" / "xxx" / 0 / False）→ 可缺失，不放 required。
        # 字段是否可缺由 default/default_factory 控制，字段值是否可为 None 由 Optional 控制。
        if f.default is not dataclasses.MISSING:
            continue
        # 有 default_factory → 可缺失（字段是可选的，LLM 可以不产或产空）
        # 业务上必填的字段由调用方在 required_nonempty 里显式声明，不靠 dataclass default 推断。
        if f.default_factory is not dataclasses.MISSING:
            continue
        # 无 default、无 default_factory → dataclass schema 基础必传字段
        required.append(name)

    schema: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    if include_defs and _defs:
        schema["$defs"] = _defs
    return schema


# ------------------------------------------------------------------
# StructuredOutputSpec
# ------------------------------------------------------------------

@dataclasses.dataclass
class StructuredOutputSpec:
    """结构化输出规范：调用方声明"我要求 LLM 产出什么结构"。

    Attributes:
        model: dataclass 类型（或已经提取好的 JSON Schema dict）。协议层从中提取 JSON Schema。
        required_nonempty: 必须在产出中"非空"的字段名列表（空字符串/空数组/空对象/None 都算空）。
                           这些字段会被加进 required，并在校验时强制非空。
        description: 对输出整体的一句话描述，注入 prompt 文案用。
        nested_schemas: 嵌套子字段的结构化约束。键是字段名，值是对该字段的 StructuredOutputSpec。
                        用于约束 expected/actual/reference 等 Any 字段的内部结构。
                        渲染 prompt 时递归展开，enforce 层不做递归校验（深层校验由 live_schema_check 做事后覆盖）。
    """
    model: Any
    required_nonempty: List[str] = dataclasses.field(default_factory=list)
    description: str = ""
    nested_schemas: Dict[str, "StructuredOutputSpec"] = dataclasses.field(default_factory=dict)

    @classmethod
    def from_dataclass(
        cls,
        model: Type,
        required_nonempty: Optional[List[str]] = None,
        description: str = "",
        nested_schemas: Optional[Dict[str, "StructuredOutputSpec"]] = None,
    ) -> "StructuredOutputSpec":
        """从 dataclass 类型构造 spec。

        Args:
            model: dataclass 类型（如 JudgeLLMOutput、项目的 ExtractOutput dataclass）。
            required_nonempty: 必须非空的字段名（顶层）。None 时默认所有 required 字段都要求非空。
            description: 输出整体描述，注入 prompt。
            nested_schemas: 嵌套子字段约束。键是字段名，值是对该字段的 StructuredOutputSpec。
                            用于约束 expected/actual/reference 等 Any 字段的内部结构。
        """
        if not (isinstance(model, type) and dataclasses.is_dataclass(model)):
            raise ValueError(
                f"StructuredOutputSpec.from_dataclass 需要 dataclass 类型，收到 {model!r}。"
                "项目形状定义请用 dataclass，放在 impl/projects/<project>/schema/ 或 impl/core/schema/。"
            )
        return cls(
            model=model,
            required_nonempty=list(required_nonempty) if required_nonempty else [],
            description=description,
            nested_schemas=dict(nested_schemas) if nested_schemas else {},
        )

    def json_schema(self) -> Dict[str, Any]:
        """提取标准 JSON Schema（draft-07）。

        required_nonempty 里的字段强制加进 required，并在 properties 里加上非空约束
       （字符串 minLength=1、数组 minItems=1、对象 minProperties=1）。
        """
        schema = _dataclass_to_schema(self.model)
        required = list(schema.get("required") or [])
        properties = dict(schema.get("properties") or {})

        for name in self.required_nonempty:
            if name not in required:
                required.append(name)
            prop = properties.get(name, {})
            prop = dict(prop)
            t = prop.get("type")
            if t == "string":
                prop["minLength"] = 1
            elif t == "array":
                prop["minItems"] = 1
            elif t == "object":
                prop["minProperties"] = 1
            elif isinstance(t, list):  # nullable 形式 ["string","null"]
                if "string" in t:
                    prop["minLength"] = 1
                elif "array" in t:
                    prop["minItems"] = 1
                elif "object" in t:
                    prop["minProperties"] = 1
            properties[name] = prop

        schema["required"] = required
        schema["properties"] = properties
        schema.setdefault("type", "object")
        schema["additionalProperties"] = False

        # 嵌套子字段约束：把 nested_schemas 提取的 JSON Schema 覆盖到对应字段
        # （这些字段在顶层 dataclass 里通常是 Any/Dict，default schema 不约束类型）
        if self.nested_schemas:
            for fname, sub_spec in self.nested_schemas.items():
                sub_schema = sub_spec.json_schema()
                # 嵌套子 spec 自己的 $defs 提到顶层 $defs，避免 ref 命名冲突时丢失
                sub_defs = sub_schema.pop("$defs", None)
                if sub_defs:
                    top_defs = schema.setdefault("$defs", {})
                    for k, v in sub_defs.items():
                        top_defs.setdefault(k, v)
                properties[fname] = sub_schema
            schema["properties"] = properties

        return schema


def dataclass_to_output_spec(schema_cls: Type, *, description: str = "") -> StructuredOutputSpec:
    """从项目 dataclass schema 生成结构化输出约束。"""
    return StructuredOutputSpec.from_dataclass(schema_cls, description=description)


def dataclass_to_json_schema(schema_cls: Type, *, description: str = "") -> Dict[str, Any]:
    """从项目 dataclass schema 生成 JSON Schema；项目侧禁止手写等价 dict。"""
    return dataclass_to_output_spec(schema_cls, description=description).json_schema()


# ------------------------------------------------------------------
# prompt 文案渲染
# ------------------------------------------------------------------

def render_output_constraint(spec: StructuredOutputSpec) -> str:
    """生成 prompt 段落：JSON Schema + 每个字段的语义 + 必须非空标记。

    DeepSeek 不支持 json_schema response_format，所以 prompt 文案是兜底强化的主战场。
    嵌套子字段约束（nested_schemas）也会递归展开，让 LLM 知道 Any 字段的内部结构。
    """
    schema = spec.json_schema()
    schema_str = json.dumps(schema, ensure_ascii=False, indent=2)
    required = schema.get("required") or []
    nonempty = set(spec.required_nonempty)

    lines: List[str] = []
    if spec.description:
        lines.append(f"## 输出约束：{spec.description}")
    else:
        lines.append("## 输出约束")
    lines.append("你的输出必须是合法 JSON，且严格符合以下 JSON Schema：")
    lines.append("```json")
    lines.append(schema_str)
    lines.append("```")
    lines.append("")
    lines.append("### 强约束")
    lines.append("- 最终回答必须只包含一个 JSON object；不要输出 Markdown，不要使用 ```json 代码块，不要在 JSON 外输出解释、前缀或后缀。")
    lines.append("- 最终回答首字符必须是 `{`，末字符必须是 `}`。")
    lines.append("- JSON 字符串内部如需引用用户原词，禁止直接写未转义英文双引号；请使用中文引号“”或转义为 `\\\"`。")
    lines.append("- 必须包含 `required` 列表中的所有字段。")
    lines.append("- 每个字段值必须匹配 schema 中的类型。")
    if nonempty:
        lines.append(f"- 以下字段必须非空（空字符串/空数组/空对象/None 均视为不合规，会被阻断）：{sorted(nonempty)}")
    lines.append("- `additionalProperties: false`：禁止输出 schema 未定义的字段。")
    lines.append("- 禁止把 schema 里的类型描述符（如 \"string\"）原样当作内容填进去——每个字段必须填入真实内容。")

    # 递归展开嵌套子字段约束（spec/schema.md：Expected 子结构约束）
    if spec.nested_schemas:
        lines.append("")
        lines.append("### 嵌套字段子结构约束")
        lines.append("以下字段内部的子结构也必须严格遵守，不可随意编造字段名或类型：")
        for fname, sub_spec in spec.nested_schemas.items():
            sub_label = sub_spec.description or fname
            sub_schema = sub_spec.json_schema()
            sub_schema_str = json.dumps(sub_schema, ensure_ascii=False, indent=2)
            sub_nonempty = set(sub_spec.required_nonempty)
            lines.append(f"- **`{fname}`** 字段 ({sub_label}) 必须符合以下结构：")
            lines.append("  ```json")
            lines.append("  " + "\n  ".join(sub_schema_str.splitlines()))
            lines.append("  ```")
            if sub_nonempty:
                lines.append(f"  其中必须非空的子字段：{sorted(sub_nonempty)}")
            # 递归更深层
            if sub_spec.nested_schemas:
                lines.append("  **子字段内部约束：**")
                for sub_fname, sub_sub_spec in sub_spec.nested_schemas.items():
                    sub_sub_schema = sub_sub_spec.json_schema()
                    sub_sub_schema_str = json.dumps(sub_sub_schema, ensure_ascii=False, indent=2)
                    lines.append(f"  - `{sub_fname}` 内部结构：")
                    lines.append("    ```json")
                    lines.append("    " + "\n    ".join(sub_sub_schema_str.splitlines()))
                    lines.append("    ```")

    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------
# 校验 + 阻断
# ------------------------------------------------------------------

# _is_empty / _check_type 已迁移到 schema_validator.py。
# 校验逻辑统一从 SchemaValidator 取，不再临时写。


def validate_output(data: Any, spec: StructuredOutputSpec) -> List[str]:
    """校验 LLM 产出，返回错误列表（空列表表示通过）。

    委托给 SchemaValidator（协议级统一校验入口）。
    LLM 产出场景固定语义：strict=True, allow_extra=False；当前输出必须严格遵循声明的最小协议。
    """
    from .schema_validator import SchemaValidator
    return SchemaValidator(spec).validate(data, strict=True, allow_extra=False)


def enforce_output(data: Any, spec: StructuredOutputSpec, caller: str = "") -> None:
    """校验 + 阻断：有错误就抛 ValueError，不重试，不放行。

    spec/struct_output.md：LLM 返回后立刻校验，字段缺失/类型错/空内容 → 直接抛异常阻断。
    """
    errors = validate_output(data, spec)
    if errors:
        tag = f"[{caller}] " if caller else ""
        raise ValueError(
            f"{tag}LLM 产出不符合结构化输出约束，已阻断（不放行假货）：\n"
            + "\n".join(f"  - {e}" for e in errors)
            + f"\n产出预览：{json.dumps(data, ensure_ascii=False)[:300]}"
        )


# ------------------------------------------------------------------
# 特殊 schema：自由文本输出（无结构约束场景）
# ------------------------------------------------------------------

@dataclasses.dataclass
class _FreeTextOutput:
    """自由文本输出：单字段 str，用于 context-analyze 等无结构约束场景。

    仍走结构化输出协议（output_spec 必填），但只要求一个非空字符串字段。
    这样所有 LLM 调用都过同一套协议，没有"无约束"这回事。
    """
    result: str


FREE_TEXT_OUTPUT = StructuredOutputSpec.from_dataclass(
    _FreeTextOutput,
    required_nonempty=["result"],
    description="自由文本输出（单字段 result）",
)


@dataclasses.dataclass
class _FreeDictOutput:
    """自由对象输出：任意键值，至少一个字段非空。

    用于产出结构依赖运行时项目 dataclass schema 的场景（如 mock_agent.build_live_request）、
    无法静态定义 dataclass 的场景。仍过结构化协议——至少要求产出非空 dict。
    """
    pass  # 无字段 → additionalProperties 允许任意键


FREE_DICT_OUTPUT = StructuredOutputSpec.from_dataclass(
    _FreeDictOutput,
    required_nonempty=[],  # 无必填字段，但 enforce 仍要求产出是 dict
    description="自由对象输出（任意键值，至少非空）",
)
