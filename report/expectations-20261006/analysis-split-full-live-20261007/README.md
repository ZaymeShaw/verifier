# 分析轴新提交协议：真实 case 完整重判验收

## 结论

**分析轴的两列表提交协议已在真实 case 上跑通；整套六轴评测仍未通过验收。**

本次不是空案卷探针。使用上次真实业务执行保存的 Agno trace，通过当前 `pipeline.judge` 完整重判：重新生成需求、运行分析、准备六轴材料、执行六轴并运行主判。没有重新调用保险业务，没有复用旧期望集、旧分析提交或旧判定。

- run_id：`analysis-split-full-live-20261007`
- case：`llm-probe-insurance-real-smoke-policy-detail-renyanlin`
- 输入来源：`report/expectations-20261006/agno-singlecase-20261006T155209Z/run-result.json` 中的 trace。
- 运行时长：2748.917 秒，约 **45分49秒**。
- 实际评测模型：**qwen3.8-flash，fallback1**。
- 此 execution 捕获 **25 次请求、25 次响应成功、25 份模型上下文**。没有该 execution 内的网关失败或端点重试。连接探活不在这组 case 调用计数中。
- 普通 Agno 路径，不是之前 B 的共享 transcript 路径。
- 使用当前仓库的项目配置与能力材料；仅在子进程中用已有 tracing 中转地址和凭证替代直连地址。没有修改磁盘配置，没有重启服务、没有覆盖 8021 工作区结果。

## 1. 本次结构修复的验证结果

分析轴约 4分29秒、5 次模型调用完成：

1. 实际 wire.tools 的 `submit_structure` 只包含 `route / coverage_note / existing_link_suspects / new_link_suspects`。
2. 已有环节记录不含新环节类型占位字段；补充环节类型枚举不含空字符串。
3. 模型第一次提交 **8 条已有环节线索、4 条补充环节线索**。
4. 读取回执门禁拒绝一个不存在的证据编号 `turn1/records/run/definitions/0/data`；模型修改提交后通过，未删除整批发现或由程序替模型补值。
5. 程序保留原有 2 条机器线索，最终共 14 条可疑环节记录。
6. 4 条补充发现取得程序编号，并实际进入对应六轴请求：
   - `new:10` → tool_execution；
   - `new:11`、`new:12` → context_memory；
   - `new:13` → planning_routing。
7. 把保存的 5 个原始模型回复通过当前真实 Analysis/ToolLoop 离线回放，5 次请求消息全部与 wire 内容对齐。复现一次拒绝、一次接受；`structure / suspects / selections / coverage` 与本次完整重判最终保存的分析输出逐项一致。

证据：`analysis-replay-audit.json`、`verified-analysis-output.json`、`verification.json`。

这证明新协议、读取回执、结果物化和下游材料交付闭合，**不证明所有可疑点都是真实业务缺陷**。分析轴本来输出调查线索，不是最终裁决。

对其中一条线索另作原文核对：工具结果的两条 records 中 applicant_name/insurant_name 均有值，字段说明也存在，但 execution.status 为 PARTIAL，execution.gaps 同时声称这些字段未返回、含义未定义。该矛盾在原始工具结果中可复核。未对其余所有线索作语义金标验收。

## 2. 完整流程的结果

| 阶段 | 结果 | 说明 |
|---|---|---|
| 需求轴 | succeeded / partial | 重新生成 157 条期望；partial 是材料缺失，不是提取质量已验证 |
| 分析轴 | succeeded / complete | 新协议通过，补充环节已交付下游 |
| 上下文 | failed | 单位 outcome 与逐项检查聚合不一致 |
| 意图理解 | succeeded / sound | 正常产生结果 |
| 规划路由 | failed | 最终批次漏核对 45 条分配的承诺期望 |
| 工具执行 | failed | 结构化解析结果出现非约定字段，被 schema 拒绝 |
| 知识数据 | failed | 最终批次漏核对 17 条分配的承诺期望 |
| 模型能力 | failed | tool_decision 的 pass/fail 未引用定格判准、未逐项核对 |
| 主判 | fulfilled | 当前流程允许结合成功轴和原始案卷判业务交付；不代表六轴完整成功 |

上下文失败已复核到具体单位：`arrives_intact @ new:12` 提交的 outcome 为 pass，唯一逐项检查 outcome 为 not_applicable，违反现有精确聚合校验。错误回执“必须保留偏差/缺证”比实际触发原因宽泛；本轮没有改写它。

工具执行的原始模型文本包含 JSON 格式问题；现有 json_repair/解析流程后的对象出现了“未返回，字段含义未定义”等非 schema 字段。报告不把这些字段直接认定为模型有意创建的字段；最终 schema 拒绝与原始内容均保留。

证据：`result.json`、`summary.json`、`consumer-failure-checks.json`。失败轴没有手工改成正常，也没有拼接前一轮结果。

## 3. 时间与纠错

下表按上下文逻辑调用 elapsed 计，避免把 join 算进上下文轴后又重复累加：

| 阶段 | 调用数 | 累计时间 |
|---|---:|---:|
| 需求轴 | 1 | 8分30秒 |
| 分析轴 | 5 | 4分28秒 |
| 六轴期望匹配 | 1 | 3分58秒 |
| 上下文 | 6 | 7分34秒 |
| 意图 | 3 | 4分36秒 |
| 规划 | 2 | 3分01秒 |
| 工具 | 2 | 4分25秒 |
| 知识 | 2 | 2分42秒 |
| 模型 | 2 | 3分37秒 |
| 主判 | 1 | 2分52秒 |

六轴包含 **8 次整批纠错，累计约 13分23秒**；分析轴另有一次同会话提交修正。此次改动没有解决六轴消费侧的整批重判、承诺覆盖或派生字段重复填写。

不能把本次时长与此前 45 分钟的连接失败运行直接比较为性能改善：上次需求轴失败、六轴根本没有执行；本次已走到全部六轴和主判，模型连接也不同于首次四条批次。

## 4. LLM tracing 与上下文一致性

- 25 份上下文请求都能对应到本 execution 的实际 wire 请求。对 SDK 空字段序列化归一后内容一致；不是声称字节完全相同。
- 分析轴实际提交形状、拒绝原因、接受回执及下游材料可串起来，不只检查代码常量。
- HTML 的 25 次成功表示模型传输成功，**不是业务判断或六轴验证成功**。本次 5 个轴失败发生在模型返回后的消费校验层，需结合最终结果和纠错请求查看。
- 本次全部命中 fallback1，因此验证了 qwen3.8-flash 的实际接受与提交行为；**不能据此宣称 Gemini 的供应商端验收也已完成**。先前 Gemini 空案卷探针仍被访问位置限制阻断。
- 代码/配置实现清单在本轮运行前后没有漂移。保护文档检查发现 `spec/verifier-ready-gate.md` 在执行期间发生变动；本轮没有编辑该文件，也没有回滚它，因此不宣称全部保护文件哈希未变。
- 重放脚本初始化时曾错误假定业务 trace 位于顶层；实际位于 turn_records。仅修正测试脚本的断言后启动正式评测，预检失败时没有调用模型，日志保留。

## 5. 交付与边界

- `llm_trace.html`：仅此 execution 的实际请求/响应；Chrome 初始加载与截图检查无 pageerror。
- `gateway-events.jsonl`、`raw-pairs.jsonl`：原始网关事件及标准配对导出。
- `contexts/`：25 份原始模型上下文。
- `input-trace.json`：本次冻结输入。
- `result.json`、`summary.json`：完整结果与摘要。
- `verification.json`：身份、上下文匹配、分阶段调用、下游交付和文件漂移检查。
- `analysis-replay-audit.json`、`verified-analysis-output.json`：分析轴原始提交的离线复核。
- `consumer-failure-checks.json`：上下文聚合不一致与原始数据/元信息矛盾的复核。
- `manifest.json`：输入与实现身份。

**结论限定：分析轴两列表结构的真实闭环已验证；完整六轴评测和整体语义质量未验收。** 本轮没有修复新暴露的消费侧问题，没有另开付费重判掩盖失败。
