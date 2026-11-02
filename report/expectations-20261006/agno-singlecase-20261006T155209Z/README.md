# 8021 单 case 实跑与 LLM tracing 质量复核

## 结论

按用户授权停止原批次、重启 8021，用当前实现、并发 1 从业务执行开始运行一条普通 Agno case。任务已终止并保存结果，但**没有形成有效的六轴评测**：需求轴与分析轴执行失败，六轴全部 blocked，主判由程序返回 not_evaluable，未调用主判模型。

本轮未修改实现、配置、需求或方案文档；未操作 8022、8030 或保险服务进程。162 份需求/方案文件、383 个实施前登记的实现/配置文件哈希均未变化。

- 原批次：`b9712b378fba4f1cbb08e4ca22d94293`。SIGTERM 正常停止 PID 15594；重启后系统将旧批次标为 failed，保留已完成 22 条。
- 新服务：PID `87001`，实例 `inst-16fa340ac786414f`，端口 8021，启用原有 tracing 中转。
- 新批次：`1016a2d852a3465c9f66fdaf27feb999`，1/1 completed。completed 只表示任务结束，不表示评测成功。
- Case：`llm-probe-insurance-real-smoke-policy-detail-renyanlin`，候选区位置 24。
- 范围：真实业务新执行 → 需求轴 → 案卷分析 → 六轴依赖判定 → 主判失败返回。未复用旧评测结果。

## 1. 实测时间与调用口径

| 阶段 | 耗时 | 结果 |
|---|---:|---|
| 业务执行 | 11.307 秒 | 完成业务调用并进入评测 |
| 需求轴 | 2063.293 秒，约 34分23秒 | failed |
| 分析轴 | 659.783 秒，约 11分钟 | failed |
| 六轴 | 无模型调用 | 全部 blocked |
| 评测整体 | 2723.112 秒，约 45分23秒 | not_evaluable |
| 业务 + 评测 | 2734.419 秒，约 45分34秒 | 没有有效六轴结果 |

调用必须分三层数：

- **6 次逻辑模型调用**：需求轴一次，分析轴五轮。
- **16 次客户端端点尝试 / 不同 call_id**。
- **34 次实际网关 pre_api_call**：同一个 call_id 下可以重试多次。27 次 failure、7 次 gateway success。

27 次失败分为：访问位置被拒 12 次、余额不足 9 次、空枚举工具 schema 被拒 6 次。

7 次网关成功不等于 7 次客户端成功：其中 3 次是需求轴已超时、客户端不再采用的迟到响应。

## 2. 真实发现

### A. 当前模型连接不可用于这次完整验收

主端点 gemini-3.8-flash-medium 多次返回 `User location is not supported for the API use`；第二备用 qwen3.8-flash 返回 402 余额不足。第一备用的三次需求生成在客户端分别耗尽约 600 秒。需求轴一次逻辑调用用了 9 次端点尝试，最终失败。

这不是业务证据不足，也没有证据表明它源于六轴语义 prompt。

### B. 分析轴的工具 schema 与实际供应商不兼容

实际 wire 的 `submit_structure` 参数包含：

```json
"new_link_type": {
  "type": "string",
  "enum": ["", "intent_understanding", "planning_routing", "tool_execution", "knowledge_data", "model_capability", "context_memory", "unclassified"]
}
```

Gemini 返回：`function_declarations[5].parameters.properties[suspects].items.properties[new_link_type].enum[0]: cannot be empty`。

代码位置：`impl/projects/llm_probe/process_loop/analysis.py:42`。这是该供应商对工具参数 schema 的直接拒绝，不是模型没有按 prompt 填写字段。普通 JSON Schema 可以表达空字符串枚举，但不能据此假定当前供应商接受。

这也说明必须区分：complete_json 的响应 schema 目前是文本约束；ToolLoop 的工具参数 schema 则真实发给供应商，并接受其原生校验。

### C. 客户端超时与网关请求生命周期未闭合

需求轴第一次备用调用 `110831e6-8df3-4c72-bae4-55e218ad9d16`：

- 16:13:59 UTC 发出；客户端约 600 秒时报 TimeoutError。
- 旧请求仍在网关继续生成，到 16:34:16 UTC 才 success，总计 1216.775 秒。
- 新的同端点尝试已在 16:24:15 UTC 发出，两次生成在时间上重叠。

另两次迟到 success 分别为 654.420 秒与 655.760 秒，也超过客户端的 600 秒终止点。

`impl/core/llm_client.py::_events_until` 当前超时后设置停止标志、放弃消费线程，没有在该处保证 HTTP 流同步关闭。日志证明客户端已转入重试而旧网关请求仍继续；不能进一步据此推算供应商账单。

### D. 阶段预算没有约束一次调用的所有重试

需求轴声明 1200 秒，但实际耗时 2063 秒。`ensure_time_left` 在模型调用前检查；一次 complete_json 内的三次 600 秒超时、失败切换、30/60/120 秒退避并未共享该轴截止时间。

因此“有每轴时限”不等于总耗时被该时限约束。需求轴失败后分析轴仍运行约 11 分钟，是当前两个独立分析轴的串行调度行为；六轴最终按依赖正确阻断。

## 3. tracing 本身哪些能确认，哪些不能

**可确认：**

- 34 次请求都有当前 job/execution 身份，可以排除旧批次和后台探活。
- 6 份 context_store 输入与对应 wire 请求内容经空值序列化归一后相符；不是宣称逐字节相同。
- 需求输入仅有 sources/missing/sha256，系统 prompt 没有旧轴符号。实际来源为用户原文及独立采集的系统/工具声明，未观察到本轮模型输出、工具返回被直接投影进去。
- 客户端失败、端点尝试和迟到网关响应可以交叉核对。
- 六轴没有被伪造为 sound；评测器失败留在执行状态。

**仍有缺口：**

- HTML / 查询按 call_id 展示时是 16 组，不是 34 次真实尝试；必须结合原始事件统计。
- 不能把 gateway success 当作评测器采用了结果；本次有三个明确反例。
- 需求轴保存了治理快照且静态 findings 为空；分析轴五轮没有记录同样的治理元数据。现有 `impl.context audit` 回退扫描因为没有正文 JSON 输出标记，报 `output_contract_count`，但这些调用实际使用工具 schema；这条回退诊断不足以证明其没有输出协议，须核对 wire.tools。其“历史记录缺少元数据”文案也不能说明这些刚生成的记录确实是历史旧版。
- 没有六轴生成与提交，不能审定六轴 prompt、引用闭合或业务判断准确性。不得用前一轮 B transcript 成功替代本次结果。

## 4. 后续次序（未实施）

1. 修正当前供应商不接受的工具 schema 表达，保持已有语义与空值适用条件；用实际 wire 验证。
2. 恢复可用的模型连接。访问位置限制、余额不足不是继续重试能解决的契约问题。
3. 让阶段截止时间覆盖内部端点重试，并核对超时取消是否结束传输；记账明确逻辑调用、端点尝试与网关尝试。
4. 再用本次已保存的业务 trace 重判，避免重复请求业务；不能预先声称届时六轴会成功。

## 5. 复核入口

- `llm_trace.html`：仅此 execution 的浏览报告；已用 Chrome 打开并截图，初始加载无 pageerror。
- `gateway-events.jsonl`：75 条原始事件，保留同 call_id 的多次尝试。
- `raw-pairs.jsonl`：原工具生成的配对记录。
- `quality-audit.json`：分阶段计数、上下文对应关系、端点尝试、迟到响应和 schema 原文。
- `run-result.json`：服务器真实最终结果和新业务 trace。
- `contexts/`：六份模型上下文，不混入旧 case 记录。
- `server.log`：本次重启与客户端重试日志。
- `latest-context-governance.json`：原有审计入口的实际输出，适用边界见上文。
- `previous-run.json`、`frozen-trace.json`：重跑前该行结果的留存，不作为本次新输出。
