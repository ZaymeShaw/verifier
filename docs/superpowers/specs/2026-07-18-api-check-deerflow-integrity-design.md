# API Check 与 DeerFlow 链路完整性修复设计

## 目标

修复最新 api-check 报告中“结构通过但业务失败仍不直观”、同一 Trace 对应多份矛盾 Judge、DeerFlow 未纳入检查，以及 DeerFlow 首轮 fixture 使用失效 thread 导致 404 的问题。修复必须保留真实失败，不通过 fallback、写死输出或放宽 schema 制造通过结果。

## 设计

### DeerFlow thread 生命周期

- 首轮 fixture 不携带占位 `thread_id`，由 `POST /api/threads` 创建真实线程。
- 后续轮次只能复用上一轮真实响应中提取的 thread ID。
- 外部明确传入的 thread ID 仍按原请求执行；不存在时返回 `thread_not_found`/`stale_thread`，不静默创建新线程替换。
- Gateway health、HTTP 404、网络不可达分别分类，不能把 thread 404 包装为 Gateway unavailable。

### API Check canonical flow

- 将 DeerFlow 加入 api-check 项目矩阵。
- 每个项目生成一次 canonical `run_chain`，后续 Attribute、Check、Frontend、Trace 与 Table 消费其中同一份 Trace/Judge/Attribute。
- `/api/judge` 独立接口行也必须使用 canonical Trace，并将其实际返回传播给后续消费者；同一个 trace ID 不允许在报告中关联两份不同 Judge。
- 报告继续保留每个接口的真实 request/response，不用缓存响应冒充接口调用结果。

### 业务状态展示

Excel 增加独立业务状态信息，至少展示：

- `trace_status` / `completion_status` / `stop_reason`；
- `judge_fulfillment`；
- `check_passed`；
- `business_check` 与可读错误摘要。

`schema_check=pass` 只表示响应结构合法，不得等价为业务成功。

### 多轮停止约束

- `goal_satisfied` 必须有用户可见 Output 的正向完成证据。
- 空回复、`stage=unknown`、协议未完成或 `business_completed=false` 时，不得归一化为 `goal_satisfied`。
- 决策模型格式异常按 trace2 协议受控重试一次；仍失败记录 `decision_error`。
- 对无进展但格式合法的输出，允许用户决策为 `perceived_no_progress`，不得伪装完成。

## 数据流

```text
mock_cases first case
→ canonical run_chain
→ canonical Trace + Judge + Attribute + Check
→ judge API 使用 canonical Trace 得到 canonical Judge
→ Attribute/Check/Frontend 使用该 canonical Judge
→ Excel 同时记录 schema 状态与业务状态
```

DeerFlow：

```text
首轮无 thread_id
→ GET /health
→ POST /api/threads
→ POST /api/threads/{real_id}/runs/wait
→ GET /api/threads/{real_id}/messages
→ 下一轮复用 real_id
```

## 错误处理

- `404 Thread ... not found`：`thread_not_found`，保留真实 Exchange 和 response body。
- health/连接失败：`gateway_unavailable`。
- 决策结构失败：重试一次，失败后 `decision_error`。
- 业务未完成：保留 HTTP 200/schema pass，但 `business_check` 失败。

## 验证

1. 局部单测覆盖 stale thread 分类、首轮建 thread、续轮复用 thread。
2. api-check 契约测试覆盖 DeerFlow 在项目矩阵中。
3. 同一 trace 的 Judge response、Attribute request、Check request、Frontend request 逐字段一致。
4. 空营销 Output 不能产生 `goal_satisfied`。
5. 真实调用 DeerFlow，核对 LiveExchange 顺序及真实 request/response。
6. 运行完整 pytest。
7. 执行 `sh run.sh api-check`，逐行复核新报告的 schema 与业务状态。

## 非目标

- 不修改 DeerFlow 外部仓库。
- 不为失败用例注入成功 fallback。
- 不把 Judge 改成确定性规则以强求相同结论；一致性通过一次 canonical 判断和稳定身份保证。
- 不重构无关前端或 Judge/Attribute 算法。
