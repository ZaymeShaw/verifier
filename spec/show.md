# Show Schema 与 Trace 核心链路展示规范

## 文档目标

当前前端只能展示完整 `RunTrace` JSON，虽然事实完整，但难以快速读出以下核心链路：

1. Mock 用户是谁、目标是什么；
2. 每一轮 Mock 实际输入了什么；
3. 每一轮 AI 返回了什么；
4. 哪一轮发生校验失败、fallback 或调用错误；
5. 最终输出来自哪一轮。

本规范新增项目级 `show_schema`，由项目显式声明 REQUEST 与 EXTRACT_OUTPUT 中应优先展示的字段。前端使用该声明生成核心摘要，同时继续保留每轮完整事实和完整原始 Trace。

`show_schema` 只控制展示投影，不改变业务协议、数据内容、Judge 输入或 Trace 原件。

# 第一章：项目 Spec 标准

本章是新项目接入和现有项目持续维护时必须遵守的稳定契约。

## 1. 设计原则

- 完整性：任何摘要都不能替代或删除原始 Trace。
- 可解释：每个展示值都能定位回 REQUEST_SCHEMA、EXTRACT_OUTPUT_SCHEMA 或 RunTrace 的明确字段。
- 不猜测：前端禁止根据 `text`、`reply`、`answer` 等字段名启发式猜测核心内容。
- 项目自治：项目决定其输入与输出的核心业务字段。
- 协议统一：Mock 意图、执行状态、错误、fallback 等通用事实由协议层统一组织。
- 同构展示：Output 与 Reference 均遵循 EXTRACT_OUTPUT_SCHEMA，并使用同一组输出展示字段。
- 顺序稳定：字段在列表中的顺序就是展示优先级。

## 2. 项目文件

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
- 第一项必须指向标量值，业务项目应优先选择能代表用户表达或 AI 主回复的字符串字段；
- 后续项允许指向标量、对象或列表；
- v1 不支持 label、renderer、formatter 或项目自定义展示函数。

## 3. 字段路径语法

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

路径校验分为三个层级：

- `schema-valid`：路径可由 REQUEST_SCHEMA 或 EXTRACT_OUTPUT_SCHEMA 的 dataclass/JSON Schema 结构静态证明；
- `fixture-valid`：路径进入 `Dict[str, Any]` 等动态结构，静态类型无法证明，但可由代表性 fixture 验证；
- `runtime-missing`：路径配置合法，但某次运行没有产生该值，只影响该字段展示，不使整个 Trace 失败。

项目 check 必须覆盖 schema-valid；动态字典路径还必须覆盖 fixture-valid。

## 4. Trace 展示所需协议事实

Show Schema 只负责业务字段的展示选择。Mock 意图与逐轮表达属于 RunTrace 通用事实，必须由协议层直接保存。

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
- 不从 request 反推或重建 Mock intent。

### 4.1 逐轮 Mock 表达

每条 turn_record 新增协议字段：

```python
mock_message: str
```

多轮 ProjectMock 新增语义提取扩展点：

```python
def extract_mock_message(self, request: REQUEST_SCHEMA) -> str:
    ...
```

该方法只从本轮已生成并通过 REQUEST_SCHEMA 校验的 request 中提取 Mock 实际表达，不生成新内容。多轮项目必须实现；协议层在 `build_next_request()` 后立即调用，并把结果传给 `TraceContext.record_turn()`。

要求：

- mock_message 是 Mock 本轮实际表达，不是前端从 request 猜测的摘要；
- 多轮 mock 在生成下一轮 request 时同步提供该语义事实；
- TraceContext 将 mock_message 与同一轮 request、raw_response、extracted_output 一起记录；
- conversation_transcript 从逐轮 mock_message 和 AI 输出生成，不再硬编码 `query/content`；
- Show Schema 仅决定 request/output 哪些字段优先展示，不参与 Trace 原件构造。

## 5. 后端展示投影

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
      "mock_message": "有子女的客户",
      "mock_message_source": "trace",
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

展示投影在读取/响应阶段动态生成，不持久化到 RunTrace、MockCase 或 case pool。修改 Show Schema 后，历史 Trace 应立即使用新规则重新投影，不能继续展示旧摘要。

单轮与多轮统一从 `turn_records` 生成轮次卡片。

## 6. 前端信息架构

### 6.1 默认展开

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
- 主字段为空时保留字段名并显示“主展示字段无值”，将其作为可见的数据质量信号；
- 次要字段为空时不占用主视图，在“已配置但本轮为空”折叠区中列出；
- 长文本可以在视觉上收起，但必须提供展开入口，不能丢弃内容。

### 6.2 每轮完整事实

每轮卡片下方提供折叠区：

```text
完整 Request
完整 Raw Response
完整 Extracted Output
本轮 Validation / Fallback / Error / Execution Events
```

### 6.3 全局非输入输出信息

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

### 6.4 原始事实兜底

Trace 区域最后保留“完整原始 Trace JSON”折叠面板，内容来自未经展示投影裁剪的 RunTrace。

完整 Raw Response、每轮完整事实和完整 Trace 应在用户展开时再格式化/挂载到 DOM，不能为批量列表中的每一行预先生成大体积 JSON 节点。

## 7. Output 与 Reference

用例表中的 Output 和 Reference 保持相邻，并统一使用 `SHOW_SCHEMA.output_fields` 生成核心展示。

- Output 的完整值继续来自 RunTrace.extracted_output；
- Reference 的完整值继续来自 MockCase.reference 或 RunTrace.reference_contract；
- 两者使用相同字段顺序；
- 两者都保留完整 JSON 展开入口；
- show_schema 不改变 Output 与 Reference 的 EXTRACT_OUTPUT_SCHEMA 校验。

## 8. 加载与错误处理

- 项目存在 `live_schema.py` 时必须存在 `show_schema.py`；
- show_schema 缺失、类型错误、列表为空或路径不合法时，项目 check 失败；
- 运行时缺失 show_schema 时，运行结果和完整 Trace 仍必须返回，前端降级为完整 JSON 展示并明确提示“缺少 Show Schema”；
- 缺失 Show Schema 不能导致整批用例无数据、永久 pending 或前端渲染中断；
- 非法配置不能由前端静默忽略；
- 单条运行数据缺失某个合法路径时，仅该字段显示“无值”，Trace 仍可展示；
- 完整原始 Trace 始终可用，即使展示投影生成失败。

## 9. 校验职责

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

## 10. 测试要求

协议测试至少覆盖：

- ShowSchema 两个列表的类型、非空和去重校验；
- 第一项为标量且优先为字符串的校验；
- 简单路径、嵌套路径、数组下标和 `[-1]`；
- schema-valid、fixture-valid 和 runtime-missing 三类行为；
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
- 多轮项目逐轮 mock_message 与实际 request 用户表达一致。

前端测试至少覆盖：

- Mock 用户信息默认可见；
- 多轮 Mock/AI 信息按轮次配对，不跨 case、不跨轮错配；
- 每轮完整 Request、Raw Response、Extracted Output 可展开；
- 全局技术事实位于轮次之后；
- 完整原始 Trace 位于最后；
- 长内容的展开不会导致信息丢失。

## 11. 非目标

- 不允许 show_schema 修改、清洗或补全业务数据；
- 不在 show_schema 中定义 Judge 或 Attribute 的展示；
- 不加入项目自定义 JavaScript/Python formatter；
- 不以摘要替代 RunTrace、REQUEST_SCHEMA 或 EXTRACT_OUTPUT_SCHEMA；
- 不在 v1 中支持通用 JSONPath 或复杂表达式。

# 第二章：当前迁移 Changes

本章只描述当前仓库从现状迁移到第一章标准所需的一次性工程改造，不是未来每个业务项目都要重复执行的标准。

## 1. 当前差异

- `trace_from_live()` 已获得 MockIntentOutput，但当前 RunTrace 没有保存 mock_intent；
- 多轮 transcript 当前只读取 request 顶层的 `query` 或 `content`；
- marketting-planning 的用户表达位于 `request.user_text`；
- deerflow 的用户表达位于 `request.input.messages[-1].content`；
- 当前 5 个业务项目和 fixture 尚未提供 show_schema.py；
- 当前前端默认只提供完整 Trace JSON，未形成 Mock/AI 轮次主线；
- 当前大体积 JSON 在批量表格中的预渲染方式需要调整。

## 2. 协议层 Changes

1. 为 RunTrace 增加 mock_intent，并完成 normalize、序列化、accessor 和 fixture 兼容；
2. 为 turn_records 增加 mock_message，修复 conversation_transcript 的硬编码提取；
3. 新增 ShowSchema、项目加载器、受限字符串路径解析器；
4. 新增 schema-valid、fixture-valid 校验和 runtime-missing 行为；
5. 新增只读、动态生成的展示投影；
6. 保证展示投影失败不影响 RunTrace 原件返回；
7. 历史 Trace 缺少 mock_intent 时允许读取，前端明确显示“无 Mock Intent”；
8. 历史 Trace 缺少 mock_message 时，用 input_fields 第一项生成标记为 derived 的只读摘要，不回写原 Trace；
9. 历史单轮 Trace 缺少 turn_records 时，从 normalized_request、raw_response、extracted_output 构造只读兼容视图，不修改原 Trace。

## 3. 当前业务项目 Changes

当前项目迁移采用以下映射；迁移验收必须使用业务 fixture 验证这些字段能稳定表达核心内容：

| 项目 | input_fields | output_fields |
|---|---|---|
| QA | `question`, `contexts` | `actual_answer` |
| client_search | `user_text` | `robot_text`, `conditions`, `query_logic`, `confidence` |
| deerflow | `input.messages[-1].content` | `reply_text`, `stage`, `tool_calls`, `errors` |
| marketting-planning | `user_text` | `robot_text`, `stage`, `card_summary`, `session_summary`, `errors` |
| marketting-planning-intent | `query` | `intent`, `confidence`, `target_value`, `path_types` |

迁移任务包括：

1. 为上述 5 个项目新增 show_schema.py；
2. 为 core fixture、fixture-project 和测试 fixture 注册 Show Schema；
3. 使用各项目代表性 fixture 校验动态路径和主字段非空；
4. 为所有多轮项目实现 extract_mock_message，并修复 deerflow、marketting-planning 的逐轮 mock_message 记录；
5. 执行跨项目批量回归，防止 input/output 跨 case 或跨轮错配。

## 4. 前端 Changes

1. 将当前 Trace 首屏的完整 JSON 改为 Mock 用户 + 轮次卡片；
2. 保留每轮 Request、Raw Response、Extracted Output 完整展开；
3. 将全局技术事实放在轮次之后；
4. 将完整原始 Trace 放在最后；
5. 对大 JSON 使用展开时渲染；
6. 对缺失/非法 Show Schema 提供可见降级，不阻断整批数据。

## 5. 验收 Changes

1. 执行协议、项目、fixture 与前端自动化测试；
2. 在 QA、client_search、deerflow、marketting-planning、marketting-planning-intent 各抽取单轮和多轮代表用例；
3. 浏览器 UAT 核对 Mock 表达、AI 输出、完整事实和原始 Trace；
4. 确认历史结果仍可读取，缺失 Show Schema 时不会无数据或永久 pending。
