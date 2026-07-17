# Show Schema 与 Trace 核心链路展示规范

## 1. 目标

当前前端只能展示完整 `RunTrace` JSON，虽然事实完整，但难以快速读出以下核心链路：

1. Mock 用户是谁、目标是什么；
2. 每一轮 Mock 实际输入了什么；
3. 每一轮 AI 返回了什么；
4. 哪一轮发生校验失败、fallback 或调用错误；
5. 最终输出来自哪一轮。

本规范新增项目级 `show_schema`，由项目显式声明 REQUEST 与 EXTRACT_OUTPUT 中应优先展示的字段。前端使用该声明生成核心摘要，同时继续保留每轮完整事实和完整原始 Trace。

`show_schema` 只控制展示投影，不改变业务协议、数据内容、Judge 输入或 Trace 原件。

## 2. 设计原则

- 完整性：任何摘要都不能替代或删除原始 Trace。
- 可解释：每个展示值都能定位回 REQUEST_SCHEMA、EXTRACT_OUTPUT_SCHEMA 或 RunTrace 的明确字段。
- 不猜测：前端禁止根据 `text`、`reply`、`answer` 等字段名启发式猜测核心内容。
- 项目自治：项目决定其输入与输出的核心业务字段。
- 协议统一：Mock 意图、执行状态、错误、fallback 等通用事实由协议层统一组织。
- 同构展示：Output 与 Reference 均遵循 EXTRACT_OUTPUT_SCHEMA，并使用同一组输出展示字段。
- 顺序稳定：字段在列表中的顺序就是展示优先级。

## 3. 项目文件

每个项目在以下位置提供展示声明：

```text
impl/projects/<project_id>/show_schema.py
```

模块必须导出 `SHOW_SCHEMA`：

```python
from impl.core.show_schema import ShowSchema

SHOW_SCHEMA = ShowSchema(
    input_fields=[
        "user_text",
        "extra_input_params",
    ],
    output_fields=[
        "robot_text",
        "conditions",
        "query_logic",
    ],
)
```

`ShowSchema` 只包含两个必填字段：

```python
@dataclass(frozen=True)
class ShowSchema:
    input_fields: list[str]
    output_fields: list[str]
```

约束：

- 两个字段都必须是 `list[str]`；
- 两个列表都不得为空；
- 不允许重复路径；
- `input_fields` 相对于项目 REQUEST_SCHEMA；
- `output_fields` 相对于项目 EXTRACT_OUTPUT_SCHEMA；
- 第一项是主展示字段，其余项是结构化要点；
- v1 不支持 label、renderer、formatter 或项目自定义展示函数。

## 4. 字段路径语法

字段选择器使用受限字符串路径，不引入完整 JSONPath。

支持：

```text
user_text
extra_input_params.filters
input.messages[0].content
input.messages[-1].content
tool_calls[0].name
```

语义：

- `.` 访问对象或 dataclass 字段；
- `[n]` 访问数组的指定下标；
- `[-1]` 访问数组最后一项；
- 路径不存在、数组为空或下标越界时返回“无值”，不抛出前端运行时异常；
- 不支持通配符、过滤表达式、函数调用和任意代码执行。

字段路径由后端统一解析。前端只消费后端生成的展示投影，不重复实现路径解析规则。

## 5. 协议层前置：保存 Mock Intent

`trace_from_live()` 在执行前已经获得 `MockIntentOutput`，但当前 `RunTrace` 没有保存该事实，导致运行后无法稳定展示 Mock 用户信息。

RunTrace 新增：

```python
mock_intent: MockIntentOutput | None = None
```

内容包括：

```text
user_intent
query
user_context
scenario
```

要求：

- `trace_from_live()` 将本次执行实际使用的 intent 原样写入 `RunTrace.mock_intent`；
- normalize、序列化、反序列化、fixture 与 accessors 同步支持该字段；
- Mock 信息属于通用协议事实，不进入项目 `show_schema.input_fields`；
- 不从 request 反推或重建 Mock intent；
- 缺失 intent 的历史 Trace 允许 `mock_intent = null`，前端明确显示“无 Mock Intent”。

## 6. 后端展示投影

后端加载项目 `SHOW_SCHEMA`，针对每条 RunTrace 生成只读展示投影：

```json
{
  "mock": {
    "user_intent": "筛选有子女的客户",
    "query": "有子女的客户",
    "user_context": {},
    "scenario": "family_property_claim"
  },
  "overview": {
    "status": "ok",
    "interaction_mode": "single_turn",
    "turn_count": 1,
    "stop_reason": "completed",
    "final_output_turn": 0
  },
  "turns": [
    {
      "turn_index": 0,
      "input": [
        {"path": "user_text", "value": "有子女的客户"},
        {"path": "extra_input_params", "value": {}}
      ],
      "output": [
        {"path": "robot_text", "value": "已生成查询条件"},
        {"path": "conditions", "value": []}
      ],
      "status": "succeeded",
      "runtime_ms": 1200,
      "error": null
    }
  ]
}
```

投影中的 `path` 保留值的来源，避免摘要失去可追溯性。投影只用于前端显示，不回写 RunTrace。

单轮与多轮统一从 `turn_records` 生成轮次卡片。若历史单轮 Trace 没有 `turn_records`，允许从 `normalized_request`、`raw_response`、`extracted_output` 构造只读兼容视图，但不得修改原 Trace。

## 7. 前端信息架构

### 7.1 默认展开

```text
执行概览
Mock 用户
第 1 轮：核心输入 + 核心输出 + 状态
第 2 轮：核心输入 + 核心输出 + 状态
...
```

每轮规则：

- input_fields 第一项作为 Mock 输入主内容；
- output_fields 第一项作为 AI 输出主内容；
- 其余字段按声明顺序显示为结构化要点；
- 空值保留字段名并显示“无值”，避免用户误以为字段未配置；
- 长文本可以在视觉上收起，但必须提供展开入口，不能丢弃内容。

### 7.2 每轮完整事实

每轮卡片下方提供折叠区：

```text
完整 Request
完整 Raw Response
完整 Extracted Output
本轮 Validation / Fallback / Error / Execution Events
```

### 7.3 全局非输入输出信息

轮次卡片之后统一展示：

```text
Application Boundary
Execution Trace
Evidence Refs
Runtime Logs
State History
Gate / Transition Decisions
```

这些字段不由 show_schema 控制，不与 Mock/AI 对话争夺主视觉层级。

### 7.4 原始事实兜底

Trace 区域最后保留“完整原始 Trace JSON”折叠面板，内容来自未经展示投影裁剪的 RunTrace。

## 8. Output 与 Reference

用例表中的 Output 和 Reference 保持相邻，并统一使用 `SHOW_SCHEMA.output_fields` 生成核心展示。

- Output 的完整值继续来自 RunTrace.extracted_output；
- Reference 的完整值继续来自 MockCase.reference 或 RunTrace.reference_contract；
- 两者使用相同字段顺序；
- 两者都保留完整 JSON 展开入口；
- show_schema 不改变 Output 与 Reference 的 EXTRACT_OUTPUT_SCHEMA 校验。

## 9. 加载与错误处理

- 项目存在 `live_schema.py` 时必须存在 `show_schema.py`；
- show_schema 缺失、类型错误、列表为空或路径不合法，项目 check 失败；
- 非法配置不能由前端静默忽略；
- 单条运行数据缺失某个合法路径时，仅该字段显示“无值”，Trace 仍可展示；
- 历史 Trace 缺少 mock_intent 时兼容读取，不伪造用户信息；
- 完整原始 Trace 始终可用，即使展示投影生成失败。

## 10. 校验职责

协议层负责：

- ShowSchema 的结构和字符串路径语法；
- 路径解析器；
- 对 REQUEST_SCHEMA、EXTRACT_OUTPUT_SCHEMA 的静态路径校验；
- RunTrace.mock_intent 的保存与序列化；
- 展示投影的稳定输出结构。

项目层负责：

- 声明本项目真正有业务价值的 input_fields；
- 声明本项目真正有业务价值的 output_fields；
- 随业务 schema 变更同步更新 show_schema。

前端负责：

- 根据展示投影渲染核心信息；
- 提供每轮完整事实和完整 Trace 的展开入口；
- 不猜测项目字段语义，不重新解释 schema。

## 11. 测试要求

协议测试至少覆盖：

- ShowSchema 两个列表的类型、非空和去重校验；
- 简单路径、嵌套路径、数组下标和 `[-1]`；
- 非法路径被项目 check 捕获；
- RunTrace.mock_intent 的构造、normalize、序列化和 fixture；
- 单轮与多轮展示投影；
- 缺失运行值显示为空但不报错；
- Output 与 Reference 使用相同 output_fields；
- 展示投影失败时完整 Trace 仍可查看。

项目测试至少覆盖：

- input_fields 全部可由 REQUEST_SCHEMA 解析；
- output_fields 全部可由 EXTRACT_OUTPUT_SCHEMA 解析；
- 代表性 fixture 能提取出预期核心输入和输出；
- 多轮项目每轮均使用相同规则生成摘要。

前端测试至少覆盖：

- Mock 用户信息默认可见；
- 多轮 Mock/AI 信息按轮次配对，不跨 case、不跨轮错配；
- 每轮完整 Request、Raw Response、Extracted Output 可展开；
- 全局技术事实位于轮次之后；
- 完整原始 Trace 位于最后；
- 长内容的展开不会导致信息丢失。

## 12. 实施顺序

1. 在协议层为 RunTrace 增加 mock_intent，并完成兼容与测试；
2. 新增 ShowSchema、加载器、路径解析器和静态校验；
3. 为 fixture、client_search、deerflow、QA、marketting-planning 等现有项目补齐 show_schema；
4. 后端生成展示投影；
5. 前端将当前完整 JSON 首屏改为轮次卡片，同时保留完整事实；
6. 执行协议测试、项目测试和浏览器 UAT。

## 13. 非目标

- 不允许 show_schema 修改、清洗或补全业务数据；
- 不在 show_schema 中定义 Judge 或 Attribute 的展示；
- 不加入项目自定义 JavaScript/Python formatter；
- 不以摘要替代 RunTrace、REQUEST_SCHEMA 或 EXTRACT_OUTPUT_SCHEMA；
- 不在 v1 中支持通用 JSONPath 或复杂表达式。
