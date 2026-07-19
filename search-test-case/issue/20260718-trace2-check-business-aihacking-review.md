# Trace2 实施：Check / Business / AI-Hacking 审查报告

审查日期：2026-07-18  
审查范围：`spec/adapter/trace2.md`、核心 Mock/Live/Trace 协议、deerflow 与 marketting-planning 多轮项目实现、相关 fixture 与回归测试。  
审查方式：只读代码审查、协议对照、REQUEST_SCHEMA 对照、现有自动化回归复核；本报告不修改实现。

## 结论

Request-first、Intent 可选、Intent/Request 解耦和独立继续决策的主方向正确，且现有 146 项回归通过；但当前实现还不宜作为最终长期标准推广。发现 3 个高优先级问题和 2 个中优先级问题。它们不会被现有 dummy mock 与 smoke tests 暴露，却会在真实长对话、不同 scenario 或业务身份连续性场景中造成错误。

## Findings

### P1-1：协议要求限制 Mock 输入长度，但实现把最多 12 轮完整 Request/Output 重复发送给两个模型

- 证据：`impl/core/live_protocol.py` 的 `interaction_turns` 永久保留每轮完整 `live_request` 和 `extract_output`；每轮将完整列表放入 `accumulated_output`。`MockAgent.decide_next_action()` 全量序列化它；两个项目的 `build_next_request()` 又把全量 `turns` 传给 `MockAgent.next_turn()`，并把最后一轮 output 作为 `live_feedback` 重复发送。
- 协议差异：`trace2.md` 明确要求输入长度受控、最近轮优先、超过上限确定性裁剪。当前没有字符、token、轮数或字段投影上限。
- Business：用户此前指出 Request/Output 信息很多，轻量继续判断不能输入过长。真实多轮下成本和延迟会随轮次增长，长 output 还可能挤掉最关键的 Intent/最近回复。
- AI-hacking：把 Trace 级完整事实直接复用为模型输入虽然最省实现代码，但属于参数越界；“完整可追溯”是 Trace 的职责，不等于 Mock 模型应看到全部 Trace 事实。
- 建议：协议层同时维护 `trace_turns` 和受限 `mock_turns`。Trace 保持完整；Mock 输入只保留确定性投影后的最近 N 轮，字段由 show/live schema 或项目扩展声明，且对单字段设长度上限。继续判断和下一轮构建复用同一受限视图，禁止重复附带最后 output。

### P1-2：两个项目的下一轮 Request 不是续写首轮 Request，而是重造并覆盖业务身份/上下文

- 证据：`impl/projects/marketting-planning/mock.py` 每轮硬编码 `org_id=eval-org`、`user_id=eval-user`、`token=mock_token`、`app_scenario=customer_service`、`source=offline_task`，清空 `history`，并将 `trace_id` 强制改成 `session_id`。首轮 Request 中真实的 org/user/token/history/application_setting/module/model 等字段会丢失。
- 证据：`impl/projects/deerflow/mock.py` 只保留上一轮 `thread_id`，丢弃 `config.configurable` 中其余 user/session/config 字段；缺 thread_id 时现场构造时间戳 ID。
- Business：同一多轮会话必须保持调用身份、租户、会话和项目配置连续。当前行为可能让第二轮切用户、切租户、丢历史，或者让服务端认为是另一条调用。
- AI-hacking：硬编码测试值让 REQUEST_SCHEMA 校验通过，但没有满足真实业务请求连续性，属于通过自定义占位字段“跑通 schema”的参数越界。
- 建议：项目层以最近一轮合法 Request 为模板做最小不可变更新，只替换用户本轮消息及协议明确要求变化的时间/trace 字段；身份、租户、token、session、应用配置默认原样保留。是否追加 `history/messages` 应按各项目真实 API 语义实现，不能统一清空。补充首轮使用非默认身份字段、第二轮逐字段一致性的契约测试。

### P1-3：Intent 缺省时，项目实现硬编码 scenario，导致不同业务场景被错误建模

- 证据：deerflow 的 `infer_user_intent()` 无条件写入 `multi_turn_dimension_accumulation`；marketting-planning 从 REQUEST_SCHEMA 中通常为空的 `scenario` 读取，缺失时统一写入 `multi_turn_field_accumulation`。
- 数据反证：两项目 fixture 分别包含 clarification、non_agent_intent、service_unavailable、execution_planning、fallback_data_unavailable、streaming_protocol 等多个 scenario。
- Business：Intent 可选的价值正是从实际首轮行为反推用户，而不是把所有请求归到一个“常见多轮”场景。硬编码会污染 MockIntentOutput，进而影响继续判断和下一轮问题。
- AI-hacking：用固定 scenario 绕过“仅凭 Request 不一定能确定 scenario”的设计难点，属于为当前 happy path 强制构造答案。
- 建议：`infer_user_intent` 只反推 Request 可证实的信息；无法确定 scenario 时保留空值。若 scenario 是运行编排已知事实，应由协议以独立、明确的执行上下文传递，不能伪装成从 Request 推断的结果。禁止项目默认成某个业务 case。

### P2-1：控制阶段异常只留下通用 stop_reason，完整 Trace 无法定位原始错误

- 证据：`infer_user_intent`、`decide_next_action`、`build_next_request` 异常被 `live_protocol.py` 捕获后只写日志，并设置 `intent_unavailable`、`decision_error` 或 `request_build_error`。Trace 最终 `error` 只有这个通用枚举，原始异常文本和控制阶段事件没有进入 `turn_records/execution_trace`。
- Business：这会复现“结果跑了但看不到为什么没数据”的诊断问题；尤其模型 schema 错误、API key 错误和项目构建错误在前端表现完全一样。
- 建议：增加结构化 control event，记录 stage、status、error_type、sanitized error message 和关联 turn_index；stop_reason 继续保持稳定枚举，但不能替代错误证据。

### P2-2：现有测试证明核心模板流程，却没有覆盖真实项目的多轮职责边界

- 证据：核心测试使用 `_MultiMock`，只验证两轮与 Intent 推断；项目 smoke 通常只验证首轮 normalized_request/trace 结构。没有测试 accumulated_output 裁剪、Request 身份连续性、多 scenario 推断、无效 stop_reason、控制错误可观测性。
- 影响：146 passed 对主干无回归有意义，但不能证明上述业务边界正确。
- 建议：增加项目级纯函数/假 Live 多轮测试，不依赖外部网络：至少覆盖 12 轮大 output 的输入上限、首轮非默认身份字段、clarification/non-agent scenario、三类控制错误 Trace。

## 已通过项

- `execute_live(initial_request, ctx, intent=None)` 已实现首轮 Request-first，单轮不再通过 Intent 重造 Request。
- `MockIntentOutput` 已移除 `live_request`，`MockCase.intent` 可为空，顶层 `live_request` 保持必填。
- 多轮协议通过 ABC 强制 `infer_user_intent`、`decide_next_action`、`build_next_request` 和 `safety_max_turns`。
- `build_next_request(intent, accumulated_output)` 的现有签名未被擅自改变。
- 旧 `{query: goal}` 执行 fallback 已删除；Request/Output schema 校验失败不会伪装成功。
- `system_understanding` 的定义面向 `project_id` 业务系统，未发现把 verifier/Judge 信息直接注入该字段的硬编码。
- 历史 fixture 的 Request 位于 Case 顶层；未发现继续写入 `intent.live_request`。
- 自动化证据：`tests + hooks/schema` 共 146 项通过，另有一个第三方依赖弃用警告。

## Check List

- [x] 协议、核心实现与 5 个项目扩展已同步扫描
- [x] Intent/Request 权责边界检查
- [x] fallback 与错误掩盖检查
- [x] fixture/data 旧字段残留检查
- [x] REQUEST_SCHEMA 对照
- [x] 自动化回归复核
- [ ] Mock 输入长度与确定性裁剪满足协议
- [ ] 多轮 Request 保持业务身份与上下文连续
- [ ] Intent 缺省时 scenario 不被项目硬编码污染
- [ ] 控制阶段原始错误进入完整 Trace
- [ ] 真实项目多轮专项测试覆盖上述边界

## 建议修复顺序

1. 先修多轮 Request 续写，避免真实调用发生身份/上下文错乱。
2. 在协议层实现 Trace 完整态与 Mock 受限态分离，并补长度测试。
3. 去掉项目 scenario 硬编码，明确“未知”与“编排上下文”的传递方式。
4. 补控制阶段结构化错误事件。
5. 增加两个多轮项目的离线链路测试，再进行真实 UAT。

