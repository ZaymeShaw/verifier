# 六轴提示词、结构契约与真实请求对齐验收（2026-10-06）

本轮只处理评测器的提示词、输出 schema、来源/证据引用和上下文记录口径。未修改 `demand/` 或 `spec/` 下的需求与方案文档，未重启 8021，也未调用被测保险业务。此前暂停的批次监控保持暂停。冻结 B 案来自 `report/llmtracing-calibration-draft/frozen-inputs/B.trace.json`，实测只把这份已保存的轨迹送进评测器。

## 发现与修正

| 原有冲突 | 处理后的单一口径 |
|---|---|
| 提示词用希腊轴符号，程序只认英文 ID，schema 又允许任意字符串；场景 `process_obligations` 仍配置 `ρ`。 | 六轴仅用 `intent_understanding`、`planning_routing`、`tool_execution`、`knowledge_data`、`model_capability`、`context_memory`。同一枚举进入问题归因、期望映射、案卷 link type、场景配置和工具 JSON schema。模型提示不再出现旧符号。 |
| 单轴与共享 ToolLoop 复用提示词，却把 `dimension`、`links.links` 说成两条路径共同的输入。 | 明确单轴使用 `dimension`/`links.links`，共享会话使用 `briefing.axis`/`briefing.links`；两条路径各自说明取证和提交方式。 |
| `{"instructions":[规则A,规则B]}` 是采集声明容器，实际请求的规则是 system 消息正文；原校验按 dict 对字符串比较，误判规则未送达。 | 对本次模型请求逐条检查全部声明规则是否出现在 **system** 消息；规则只在 user 消息、别次调用或采集定义里出现均不算。 |
| `expectation_sources.id` 与案卷可读证据 ID 混淆；模型把 `t1.user` 当证据提交。 | 输入加 `source_to_evidence`，只列本次目录中存在的候选编号；schema 对 `source_refs` 给出合法命名空间和禁止项。冻结 B 的 `t1.user` 对应 `t1.c1.m2`，须先完整读取后引用。 |
| 已确认的 `project:` 项目义务自身就是判准，但旧校验要求在独立提取的 E 中找同名期望，形成不可满足条件。 | `project:` 义务可直接引用自己的 `obligation_id`；`trace/case` 仍需 E 的对应要求。 |
| schema 曾要求模型重复填程序可推导的 `expected`，归因/匹配字段约束没与提示词一致；承诺覆盖到轴尾才查。 | 模型只交 schema 字段，程序生成 expected；归因 ID 与空字符串匹配值写入 schema；每批分配承诺期望并在可纠错的提交范围内检查，轴尾总覆盖检查保留。 |
| context_store 的 `messages` 混入本轮生成的 assistant/tool 消息，容易把输出误认成模型输入，`prompt_size` 也因此失真。 | `messages` 只存本次传给客户端的请求，Agno 返回的会话列表单列在 `response.run_messages`，响应正文继续单列。网关 `pre_api_call` 是实际 wire 输入的核对基准。 |

这些改动不解决六轴整批生成、重复材料、长上下文和整批重试带来的耗时；本轮没有通过放松引用、承诺覆盖或语义验收门禁来换取 accepted。

## 真实证据

1. [firstwave-mu-audit.json](firstwave-mu-audit.json)：用 8021 首批四条已归档的原始案卷，递归展开共享正文后逐条核对本次模型调用的 system 消息。4/4 的两段声明规则均找到；分别添加一段不存在的规则时 4/4 被拒。这个结果只证明这四条的该次调用，不外推到其他调用。
2. 冻结 B 单轴最终版评测以 `run_id=prompt-contract-freeze-B-final-intent-20261006` 发出 [3 次网关请求](raw-pairs.jsonl)：两次 `evidence_read`，一次 `eval_intent_understanding`，无网关失败。工具提交一次接受，程序核对 15 个待判单位。独立脚本使用相同读取回执与提交参数重新运行本地校验，仍为 accepted；见 [wire audit](final-intent-wire-audit.json)、[简要结果](final-intent-summary.json) 与 [HTML llmtrace](llm_trace.html)。wire 请求的 system 无旧轴符号，`attribution_axes` 具有六值枚举，`source_to_evidence['t1.user']=['t1.c1.m2']`，提交没有把 `t1.user` 当证据。
   三次网关调用分别为 10.48 秒、5.64 秒和 157.21 秒，合计约 173.33 秒；整次轴执行墙钟 180.22 秒。可见瓶颈仍在那次生成 15 个单位结果的模型请求。网关上报的输入 token 分别为 18,577、20,240、21,529，输出 token 为 78、42、4,195；这些是提供方口径，不据此推算账单。
3. 上一版隔离重放首先在六轴入口被场景旧 `ρ` 阻断；修正后它又给出来源 ID 混淆和项目义务判准冲突的真实拒绝回执。以上修复来自回执，不是仅按代码猜测。该版运行在这些诊断足够后主动中止，**不是**完整六轴结果。
4. 修复 context_store 后另发一次极小结构化调用 `run_id=prompt-contract-context-wire-20261006`。记录的 `messages` 与网关 `pre_api_call.client_request.messages` 逐条相等；输入角色为 system/user，生成后的 assistant 只在 `response.run_messages`，`prompt_size` 由输入计算。见 [context-wire-audit.json](context-wire-audit.json) 和 [上下文记录](contexts/)。
5. 真实仓库的相关回归：**296 passed, 1 skipped**，覆盖 ToolLoop、结构化输出、六轴材料、来源边界、项目配置、上下文落档及所有六轴离线完整提交。`git diff --check` 通过。受保护的 162 个已有 `demand/` 与 `spec/` 文件在应用前哈希均未漂移，且本轮未写它们。

真实单轴探针后仅进一步明确了提示词中 `project:<id>` 问题来源的一句话；没有改动输出 schema 或判定程序，该最终文字由相关回归覆盖，未因此再发模型请求。

## 解释范围与下一步

这次实测证明了最终提示词、工具 schema、来源映射、一次真实轴提交及新上下文落档与网关 trace 的一致性。它**不证明** 32 条业务批次或六轴真实模型评判都已语义通过；accepted 只是程序协议验收。完整六轴真实重放仍可能被执行层的大 prompt、引用补读、整批重试及 1200 秒预算阻断。若继续提速，需另行设计材料并集规划、按单位纠错和输出规模控制，不能把本轮的结构对齐误报成性能问题已经解决。

本轮代码对已启动的 8021 进程不会热生效；后续实测须由用户在合适时机以新代码启动服务。本轮未操作该服务或批次。
