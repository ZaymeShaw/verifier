# 当前 verifier 前端实际上下文审查

结论：本次样本的全链路上下文一致性不通过。已确认正文与缺口互相矛盾、业务输出格式违约后被桥接改形、对话记录失真，以及 verifier 工具结构契约被实际服务拒绝。不能据此宣称整个工作区都已审查，也不能把现有 Check 通过理解为上下文一致性通过。

## 审查范围和证据

- 入口：本机 8021，页面标题“通用评估系统”；8030 是“ToolLoop 试验台”。
- 项目：llm_probe。当前工作区有 87 个用例、22 个运行结果，混合保留多个批次。
- 本次选取当前工作区 batch 指向的唯一用例，而非任意挑选日志最新记录：批次 `1016a2d852a3465c9f66fdaf27feb999`，execution `1016a2d852a3465c9f66fdaf27feb999:0`，用例 `llm-probe-insurance-real-smoke-policy-detail-renyanlin`。这是前端当前保留的 2026-10-06 运行，不是对今天修改后的代码重新执行。
- 用户目标：指定完整保单号，查询归属、投保人、被保人及当前状态。
- 通过 llmtrace 正式 CLI 导出该 execution 全部 16 条调用：7 succeeded、9 failed，导出状态 complete，无 pending/conflicts。保留 full call、HTML、命令清单与哈希。
- verifier 自身的实际请求来自 llmtracing 原文；业务模型输入来自该请求通过 dossier 工具取回的业务案卷，其中模型输入被标记为 verified 重建。未将重建等同于独立保存的业务 HTTP 请求。审查未启动新业务运行、未调用外部审阅模型、未修改主流程。

## 已确认的问题

### 1. 同一份工具结果，姓名值与缺口声明直接冲突

`policy_detail` 的 `data.records` 两条险种行都返回 `applicant_name` 与 `insurant_name`，值一致；同一响应的 `execution.gaps` 却称“投保人姓名：险种行 1,2 未返回……本次源数据未提供”以及相同的被保人姓名缺口。

这不是信息不足：内容已经在 data 中。`content#18` 是工具消息；它也出现在 `content#20` 的模型输入重建工具消息中，程序比较两者内容相等。verifier 的 `trace_analysis` 在调用 `b04889ac…` / `08969c1d…` 已收到这些原文。因此，这是进入本案 verifier 上下文的明确语义矛盾，模型不得同时按“已返回姓名”和“源数据未提供姓名”作结论。工具说明和实际执行对 fields 中文名称的映射也值得修复方核对，但本次不凭此推断具体代码根因。

### 2. 业务 prompt、业务模型输出、bridge 的结构没有遵守同一契约

案卷 `content#71` 的业务 system 明确要求“输出 JSON：answer_draft:string 必须是首字段”，以及 fact_refs、gaps、needs_user_input、task_updates 等字段。末次模型输出 `content#78` 是普通 Markdown 文本，不能解析为 JSON；聚合 agent 输出 `content#13` 还拼入了调用工具前的过程话“我注意到……我将使用 policy_detail 来查询”。

`content#25` 的 bridge 随后包装成含 answer_draft 的对象，写入 task_updates“Agent output_schema 非标准形态已由 bridge 归一”，加入“本轮部分内容缺少可核验来源”的 gaps；最终 HTTP 实收使用 answer 字段。内部草稿和最终接口采用不同结构本身可以有明确转换契约；这里已确认的问题是模型没有完成输入要求的结构，bridge 的包装不能证明模型遵守了契约，也不应遮掉这个失败。

### 3. verifier 的工具 schema 与实际 provider 接受的契约不一致

实际 `trace_analysis` 请求 `tools[5].function` 为 `submit_structure`，`suspects.items.properties.new_link_type.enum` 包含空字符串；system 同时要求表内环节将该值留空。Gemini 请求 `2e7cc8f2…` 和最终 `15cc58c3…` 返回 400，明确报该 enum 第一项不能为空。这是运行证据，不是猜测 provider 兼容性。

Qwen 备用调用能够继续读案卷，但本案最终没有完成 submit_structure。前端记录 expectations / trace_analysis 为 failed，其余六轴 blocked，Judge 为 not_evaluable。故没有完整的下游评测结论；不能把阻断包装成上下文审查通过。

### 4. verifier 保存的 assistant 对话内容失真

同一运行的 live_exchanges.response.answer 和 extracted_output 包含完整保单答复，但 trace.conversation_transcript 的 assistant.content 只有“ok”。“ok”不保留本轮答复的对象、事实或缺口，也未被标为单纯执行状态。

这证明前端对应的 RunTrace 内部表述不一致。本案的 trace_analysis 直接读取了更完整的业务案卷；本次没有证据证明它读取了这个“ok”，也不声称该失真已导致本案下游误判。

## 没有发现问题的部分与判断边界

用户指定的保单号、投保人/被保人/状态查询目标在业务请求、agent_input 和 policy_detail 参数中保持一致；核心答复的姓名、状态与两条 data 记录一致。verifier expectations 各请求输入相同，trace_analysis 各调用的 system / tools 保持一致，后续轮次保留此前消息前缀，未发现本样本中跨用例串线的证据。这些局部成立不能抵消上面的语义矛盾。

现有前端 Check 显示 passed=true，来自有限的程序协议检查；同一个页面仍正确展示 not_evaluable。Check 的通过不能证明模型上下文整体自洽，不能以这次审查将其直接定性为业务判断造假。

本次是对真实保存运行的本地语义审查，没有给出缺少标定依据的“准确率”或“一致性百分比”，没有验证整个 22 结果工作区，也没有验证新 hook 是否会自动发现这些问题。

证据入口：[结构化证据](evidence.json)、[前端对应运行](latest-run.json)、[完整调用清单](raw/calls.json)、[llmtrace HTML](raw/html/llm_trace.html)、[导出命令](raw/export-manifest.json)。
