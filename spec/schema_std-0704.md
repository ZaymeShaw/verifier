⏺ 协议级统一校验方案（终版）

一、总体设计

1.1 目标

把当前分散在 8 处的校验逻辑统一到一个协议层入口，以后所有校验都从这一处取，不再临时写校验。

1.2 核心原则

一处定义、一处校验、调用方零认知负担。

- 一处定义：所有形状描述统一用 dataclass。形状来源是 impl/core/schema/ 或 impl/projects/<project>/schema/。
- 一处校验：唯一一个 SchemaValidator 类负责按 spec 校验，只暴露两个参数 strict 和 allow_extra。
- 调用方零认知：调用方只需"给定一个基础 dataclass + 声明动态需求（哪些必填、哪些非空、嵌套子结构是什么）"，不需要知道内部校验逻辑。

1.3 三层架构

┌─────────────────────────────────────────────────┐
│ 调用方层（judge / mock_agent / live_stub /      │
│ attribute / pipeline / api-check / adapter）    │
│   只做：给定基础 dataclass + 声明动态需求       │
│   不直接操作校验器                              │
└──────────────────┬──────────────────────────────┘
                    │
┌──────────────────▼──────────────────────────────┐
│ 协议层（SchemaValidator）                       │
│   唯一校验入口，通用类，不关心业务场景           │
│   validate(data, *, strict, allow_extra)         │
│   两个参数组合覆盖所有语义                       │
└──────────────────┬──────────────────────────────┘
                    │
┌──────────────────▼──────────────────────────────┐
│ Schema 构建层（StructuredOutputSpec）           │
│   从 dataclass 构建 spec（字段+类型+required）   │
│   调用方通过 required_nonempty / nested_schemas │
│   声明动态需求                                  │
└─────────────────────────────────────────────────┘

二、协议层设计

2.1 唯一真相源：dataclass

所有形状描述统一用 dataclass。两个来源：

┌─────────────┬─────────────────────────────────┬────────────────────────────────────────────┐
│    来源     │              路径               │                    示例                    │
├─────────────┼─────────────────────────────────┼────────────────────────────────────────────┤
│ 核心 schema │ impl/core/schema/               │ JudgeLLMOutput、AttributeLLMOutput         │
├─────────────┼─────────────────────────────────┼────────────────────────────────────────────┤
│ 项目 schema │ impl/projects/<project>/schema/ │ QAExtractOutput、ClientSearchExtractOutput │
└─────────────┴─────────────────────────────────┴────────────────────────────────────────────┘

2.2 调用方使用方式

调用方只需做一件事：给定一个基础 dataclass + 声明动态需求。

# 方式 1：直接用 dataclass
spec = StructuredOutputSpec.from_dataclass(MyDataclass)
┌─────────────┬─────────────────────────────────┬────────────────────────────────────────────┐
│    来源     │              路径               │                    示例                    │
├─────────────┼─────────────────────────────────┼────────────────────────────────────────────┤
│ 核心 schema │ impl/core/schema/               │ JudgeLLMOutput、AttributeLLMOutput         │
├─────────────┼─────────────────────────────────┼────────────────────────────────────────────┤
│ 项目 schema │ impl/projects/<project>/schema/ │ QAExtractOutput、ClientSearchExtractOutput │
└─────────────┴─────────────────────────────────┴────────────────────────────────────────────┘

2.2 调用方使用方式

调用方只需做一件事：给定一个基础 dataclass + 声明动态需求。

# 方式 1：直接用 dataclass
spec = StructuredOutputSpec.from_dataclass(MyDataclass)

# 方式 2：声明哪些字段必须非空
spec = StructuredOutputSpec.from_dataclass(
    MyDataclass,
    required_nonempty=["expected", "business_expectations"],
)

# 方式 3：声明嵌套子结构约束
spec = StructuredOutputSpec.from_dataclass(
    JudgeLLMOutput,
    required_nonempty=["expected", "business_expectations"],
    nested_schemas={"expected": StructuredOutputSpec.from_dataclass(QAExtractOutput)},
)

三个参数的含义：

┌───────────────────┬────────────────────────────────────────────┬───────────────────────────────────┐
│       参数        │                    含义                    │               示例                │
├───────────────────┼────────────────────────────────────────────┼───────────────────────────────────┤
│ model             │ 基础 dataclass，定义"有哪些字段、什么类型" │ JudgeLLMOutput                    │
├───────────────────┼────────────────────────────────────────────┼───────────────────────────────────┤
│ required_nonempty │ 动态声明"哪些字段必须存在且非空"           │ ["expected", "reasoning_summary"] │
├───────────────────┼────────────────────────────────────────────┼───────────────────────────────────┤
│ nested_schemas    │ 动态声明"Any 字段的内部结构"               │ {"expected": sub_spec}            │
└───────────────────┴────────────────────────────────────────────┴───────────────────────────────────┘

required_nonempty 和 nested_schemas 是调用方的动态需求，不是基础 schema 的一部分。dataclass 只定义字段和类型，调用方按场景声明约束。

2.3 协议层：SchemaValidator

通用类，不关心业务场景。只暴露两个参数。

class SchemaValidator:
    def __init__(self, spec: StructuredOutputSpec): ...

    def validate(self, data, *, strict=True, allow_extra=False) -> list[str]:
        """返回错误列表，空列表 = 通过。

        strict:
        True  → required 字段缺失 → 报错
        False → required 字段缺失 → 跳过

        allow_extra:
        True  → 额外字段 → 跳过
        False → 额外字段 → 报错
        """
        ...

    def is_valid(self, data, **opts) -> bool:
        return not self.validate(data, **opts)

两个参数组合覆盖所有语义：

┌────────┬─────────────┬─────────────────────────────────────────────────┐
│ strict │ allow_extra │                    适用场景                     │
├────────┼─────────────┼─────────────────────────────────────────────────┤
│ True   │ False       │ 精确匹配：live 系统输出、请求体校验             │
├────────┼─────────────┼─────────────────────────────────────────────────┤
│ True   │ True        │ LLM 产出：必须字段不能缺，但 LLM 多塞字段不阻断 │
├────────┼─────────────┼─────────────────────────────────────────────────┤
│ False  │ False       │ reference：允许 missing（子集），不允许 extra   │
└────────┴─────────────┴─────────────────────────────────────────────────┘

校验维度（全部按 spec 跑，不单独写逻辑）：

1. data 必须是 dict
2. strict=True 时，required 字段必须存在
3. required_nonempty 字段必须非空（None / "" / [] / {} 都算空）
4. 字段类型匹配（按 dataclass 类型注解，含嵌套 dataclass、泛型）
5. nested_schemas 递归校验子结构
6. allow_extra=False 时，额外字段报错

关键设计：
- required = 纯声明字段（无 default、无 default_factory）+ required_nonempty 显式声明
- 非空约束 = required_nonempty 声明的字段
- 嵌套校验 = 按 nested_schemas 递归
- 错误格式统一："字段路径: 错误描述"

2.4 现有 LiveSchemaCheck 怎么办

LiveSchemaCheck 是业务语义别名，内部委托给 SchemaValidator，不增加新概念：

class LiveSchemaCheck:
    def __init__(self, request_shape, output_shape, ready):
        self._request_validator = SchemaValidator(_to_spec(request_shape))
        self._output_validator = SchemaValidator(_to_spec(output_shape))
        self._ready = set(ready or [])

    def output(self, data) -> bool:
        return self._output_validator.is_valid(data, strict=True, allow_extra=False)

    def reference(self, data) -> bool:
        return self._output_validator.is_valid(data, strict=False, allow_extra=False)

    def request(self, data) -> bool:
        return self._request_validator.is_valid(data, strict=True, allow_extra=False)

    def case(self, case) -> bool:
        # 按 ready 协议校验完整 case
        ...

2.5 错误格式统一

所有校验错误走同一格式：字段路径: 错误描述

- expected: 必填字段缺失
- expected.actual_answer: 类型不匹配，期望 str，实际 int
- expected.actual_answer: 必须非空但产出为空

调用方拿到错误列表自己决定：抛 ValueError / 标 quality_flags / 打 WARNING / 抛 AssertionError。

三、调用方示例

3.1 judge 调用

# 场景 1：有 actual + 无 reference（judge 自己产 expected）
spec = StructuredOutputSpec.from_dataclass(
    JudgeLLMOutput,
    required_nonempty=["expected", "business_expectations", "overall_fulfillment", "reasoning_summary"],
    nested_schemas={"expected": StructuredOutputSpec.from_dataclass(QAExtractOutput)},
)

# 场景 2：有 actual + 有 reference（judge 不产 expected）
spec = StructuredOutputSpec.from_dataclass(
    JudgeLLMOutput,
    required_nonempty=["business_expectations", "overall_fulfillment", "reasoning_summary"],
)

# 场景 3：无 actual（仅生成 reference）
spec = StructuredOutputSpec.from_dataclass(
    JudgeReferenceOutput,
    required_nonempty=["expected", "business_expectations"],
    nested_schemas={"expected": StructuredOutputSpec.from_dataclass(QAExtractOutput)},
)

3.2 mock_agent 调用

spec = StructuredOutputSpec.from_dataclass(
    MockIntentOutput,
    required_nonempty=["query"],
)

3.3 attribute 调用

spec = StructuredOutputSpec.from_dataclass(
    AttributeLLMOutput,
    required_nonempty=["expectation_attributions", "causal_category", "root_cause_hypothesis"],
)

3.4 live_stub 调用

spec = StructuredOutputSpec.from_dataclass(
    QAExtractOutput,
    required_nonempty=[],
)

3.5 项目 live_schema 校验

# impl/projects/QA/live_schema.py
from impl.projects.QA.schema import QAExtractOutput

EXTRACT_OUTPUT_SHAPE = QAExtractOutput

check = LiveSchemaCheck(REQUEST_SHAPE, EXTRACT_OUTPUT_SHAPE, READY)

check.output(data)    # strict=True, allow_extra=False
check.reference(data) # strict=False, allow_extra=False

四、新接入指南

接入任何 schema 校验，只需回答三个问题：

1. 基础形状是什么？ → 一个 dataclass
2. 哪些字段必须非空？ → required_nonempty=["field1", "field2"]
3. Any 字段内部结构是什么？ → nested_schemas={"field": sub_spec}

使用方式：

# 方式 A：LLM 产出校验（通过 complete_json 自动走）
spec = StructuredOutputSpec.from_dataclass(MyDataclass, required_nonempty=["x"])
data = client.complete_json(system, user, output_spec=spec)

# 方式 B：临时校验
validator = SchemaValidator(spec)
errors = validator.validate(data, strict=True, allow_extra=True)
if errors:
    raise ValueError(errors)

# 方式 C：项目级校验（通过 live_schema）
check = LiveSchemaCheck(request_shape, output_shape, ready)
ok = check.output(data)

五、迁移方案

5.1 文件结构

impl/core/
schema_validator.py     # 新增：唯一校验入口 SchemaValidator
structured_output.py    # 缩减：只负责 dataclass→spec 构建，validate 委托
live_schema_check.py    # 保留：业务语义别名，内部委托 SchemaValidator

5.2 迁移步骤

┌──────┬──────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ 步骤 │           文件           │                                                  改动                                                  │
├──────┼──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 1    │ 新建 schema_validator.py │ 实现 SchemaValidator 类                                                                                │
├──────┼──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 2    │ structured_output.py     │ 保留 from_dataclass/json_schema，validate_output 委托给 SchemaValidator，删除 _is_empty/_check_type    │
├──────┼──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 3    │ live_schema_check.py     │ __init__ 接受 dataclass，内部委托给 SchemaValidator，删除 _check_shape/_parse_descriptor/_type_matches │
├──────┼──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 4    │ pipeline.py              │ _enforce_judge_live_schema 改用 check API                                                              │
├──────┼──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 5    │ normalize.py             │ _check_normalized_case_with_live_schema 改用 check.case()                                              │
├──────┼──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 6    │ api_check_registry.py    │ _assert_judge_business_shape 改用 check API                                                            │
├──────┼──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 7    │ judge.py                 │ 删除 _check_judge_reference_with_live_schema                                                           │
├──────┼──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 8    │ 项目 live_schema.py      │ EXTRACT_OUTPUT_SHAPE 逐步改为 dataclass 引用                                                           │
└──────┴──────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────┘

5.3 接口不变

┌──────────────────────────────────────────┬──────────────────────────────────────────┬──────┐
│                 原有调用                 │                  迁移后                  │ 变化 │
├──────────────────────────────────────────┼──────────────────────────────────────────┼──────┤
│ validate_output(data, spec)              │ validate_output(data, spec)              │ 无   │
├──────────────────────────────────────────┼──────────────────────────────────────────┼──────┤
│ enforce_output(data, spec)               │ enforce_output(data, spec)               │ 无   │
├──────────────────────────────────────────┼──────────────────────────────────────────┼──────┤
│ check.output(data)                       │ check.output(data)                       │ 无   │
├──────────────────────────────────────────┼──────────────────────────────────────────┼──────┤
│ StructuredOutputSpec.from_dataclass(...) │ StructuredOutputSpec.from_dataclass(...) │ 无   │
├──────────────────────────────────────────┼──────────────────────────────────────────┼──────┤
│ LiveSchemaCheck(REQ, EXTRACT, READY)     │ LiveSchemaCheck(REQ, EXTRACT, READY)     │ 无   │
└──────────────────────────────────────────┴──────────────────────────────────────────┴──────┘

六、扩展性保证

- 新加项目：在项目 schema 定义 dataclass，在 live_schema 引用，零改动
- 新加 LLM 场景：定义 dataclass + 调 from_dataclass，零改动
- 协议层稳定后不改：调用方只需要 dataclass + required_nonempty + nested_schemas，要改的是调用方，不是协议层