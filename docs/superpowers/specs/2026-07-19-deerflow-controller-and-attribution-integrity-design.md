# DeerFlow 控制器状态与归因完整性修复设计

## 背景

目标 trace 已产生两轮有效 DeerFlow 输出，但 Mock 的继续对话决策失败，被提升为整个 RunTrace 的 `decision_error`；Table/Frontend 又用该执行错误覆盖了已经完成的 Judge 分析。同时，DeerFlow 输出提取会把最新 AI 回复与历史 AI 工具调用拼接，stage inference 也会把交付后的“需要我帮您……”误判为 clarification。现有 Attribute 缺少逐轮原始消息探针和证据强度门禁，因而将业务 gap 猜测成模型上下文问题并错误标为 strong。

## 目标

1. DeerFlow 业务调用状态、Mock 交互控制器状态、对话完成性和 Judge fulfillment 分开表达。
2. 保留 `decide_next_action` 的原始异常，不再只留下不透明的 `decision_error`。
3. Table/Frontend 始终保留已经存在的 Judge summary；执行/控制器异常作为独立状态展示。
4. reply 与 tool calls 必须来自同一条最新业务 AI message，不允许跨轮拼接。
5. stage inference 不因交付后 follow-up 中的普通“需要”一词误判 clarification。
6. DeerFlow Attribute 使用当前 trace 的逐轮原始/提取差异作为代码链路证据；无有效 probe/runtime check 时禁止 strong。

## 方案比较

### 方案 A：最小字段补丁

只把 controller error 写入 `conversation_summary`，并删除 Table 对 Judge 的覆盖。

优点：改动小。缺点：状态仍藏在非结构化字典中，API、Check 和前端难以稳定消费，不满足长期状态拆分。

### 方案 B：显式状态拆分（采用）

在 RunTrace/TraceContext 中增加交互控制器状态和错误字段；保留现有 `status/error` 表示被测业务执行。TableRow 增加独立 execution/controller 字段，同时保持现有字段兼容。

优点：责任边界清楚、可查询、兼容现有消费者。缺点：需要同步 normalize/occam/table/frontend/tests。

### 方案 C：统一子系统状态对象

新增通用 `subsystem_statuses` 映射，所有执行器、控制器、Judge 都迁移进去。

优点：扩展性最高。缺点：超出本次 P0/P1，迁移面太大且容易干扰现有未提交改动。

## 详细设计

### 1. 多轮控制器状态

TraceContext 和 RunTrace 增加：

- `interaction_controller_status`: `not_run | ok | error`
- `interaction_controller_error`: 原始异常字符串

`mock.decide_next_action` 两次失败时：

- `stop_reason = decision_error`
- `interaction_controller_status = error`
- `interaction_controller_error = 最后一次异常`
- 已有有效 output 时，`completion_status = incomplete`，不是 `failed`

业务调用轮次全部成功且存在最终 output 时，RunTrace 的 `status/error` 保持 `ok/None`。只有没有有效 output、真实 live 调用失败或协议执行本身失败时才设置顶层 execution error。

### 2. Judge 与执行状态展示

`table_view._judge_summary` 不再因 `trace.error` 提前返回伪 Judge summary。只要 Judge 存在，就使用 Judge 自身 summary/fulfillment；执行错误单独进入 TableRow：

- `execution_status`
- `execution_error`
- `interaction_controller_status`
- `interaction_controller_error`

`status` 保持现有兼容语义，优先展示 Judge fulfillment；`fulfillment_status` 始终来自 Judge。Frontend 执行概览同时展示执行状态、控制器状态、completion status 和 stop reason。

Judge 不存在时，才允许使用 execution error 构造降级摘要，并明确 `reason_source=execution_error`。

### 3. DeerFlow 单消息提取

`_extract_reply_and_tool_calls` 选择最新一条非 middleware 的业务 AI message，并从该同一条 message 同时提取 reply/tool_calls。不得为了补齐空 tool_calls 继续扫描历史 AI message。

增加回归用例：第二轮最新 AI 有 reply 且 `tool_calls=[]`，第一轮有 `ask_clarification`，最终提取必须为空工具列表。

### 4. Stage inference

clarification 仅由明确的澄清信号触发：

- 当前同消息存在 `ask_clarification`；或
- 回复出现明确请求缺失信息的句式，如“请提供”“请补充”“需要先了解/确认”“还缺少”。

普通交付后 follow-up，如“需要我帮您生成 PPT 吗”，不能触发 clarification。存在规划产物工具、NBEV 脚本或明显完整规划结构时优先判 planning；普通非空业务回复保持 intent。

### 5. DeerFlow Attribute probe 与强度门禁

项目 `probes()` 增加当前 trace 的逐轮证据：

- 每轮最新原始业务 AI message 的 reply/tool call 名称；
- 每轮 extracted_output 的 reply/tool call 名称和 stage；
- `raw_vs_extracted_tool_calls_match`；
- stage inference 命中规则；
- interaction controller status/error。

`normalize_result` 校准证据强度：

- `strong`：至少存在成功 probe/runtime check，且明确支持 suspected location；
- `medium`：有当前 trace 差异证据，但缺少一段链路验证；
- `weak`：只有 Judge 文本、汇总计数或间接 execution trace；
- `none`：Judge not_evaluable 或 actual/关键证据缺失。

本次只在 DeerFlow 项目层实施强度校准，避免改变其他项目当前归因行为。公共协议补充最小防线：若 `probe_results` 为空且 `runtime_checks` 为空，不接受 LLM 自报 strong，降为 weak。

## 兼容与边界

- 不修改 DeerFlow 外部服务。
- 不改变 Judge 的业务标准或 blocking 定义。
- 不用 fallback 把真实失败包装成成功。
- 不删除 `stop_reason=decision_error`，仅改变其状态归属并保留原始异常。
- 新 schema 字段全部提供默认值，旧 trace 可继续 normalize。
- 不覆盖工作区中现有 Judge/frontend 未提交改动；只做目标行的最小合并。

## 验证

1. MultiTurn live：两次 decision 异常且已有 output 时，trace execution 为 ok、completion 为 incomplete、controller 为 error，并保留异常文本。
2. Table：trace 有 controller error 且 Judge 完整时，Judge reason/assessment_count/fulfillment 不被覆盖。
3. DeerFlow extraction：最新回复无工具调用时不继承历史 ask_clarification。
4. Stage：完整规划末尾含“需要我帮您……”仍为 planning/intent，不是 clarification；明确“请补充……”仍为 clarification。
5. Attribute：无 probe/runtime check 的 strong 自动降级；raw/extracted tool call 不一致可形成代码级 probe。
6. 运行相关单测及完整 pytest；若完整套件受工作区既有未提交改动影响，单独报告非本次回归。
