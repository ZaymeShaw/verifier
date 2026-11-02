# 过程评测 v4 校准报告（Step 5）

- 日期：2026-09-18
- 方式：5 个真实快照 × 完整八轴链（trace_analysis 自动纳入 + fulfillment + 六过程轴），真实 LLM 无 mock
- 模型：qwen3.8-flash（fallback1；主端点 gemini-3.8-flash-medium 不可用回落），model_policy=any
- 脚本：tmp/calibrate_v4.py（一次性校准脚本）；原始结果：calib-results.json
- 单快照耗时 491–836s；trace_analysis 单次探测 20 次工具读、约 52 万输入 token

## 一、verdict 总表

| 快照（case） | fulfillment | intent | planning | tool | context | knowledge | model |
|---|---|---|---|---|---|---|---|
| case01 cash-value（P002 现金价值，Direct） | not_fulfilled | sound | sound | sound | **problematic** | problematic | sound |
| case08 and-procedure（P002+犹豫期退保，Agent） | not_fulfilled | sound | **problematic** | **problematic** | **problematic** | problematic | sound |
| case18 unknown-policy（P999999） | not_fulfilled | sound | sound | sound | sound | problematic | sound |
| multi-turn（那它的缴费方式呢） | not_fulfilled | sound | sound | sound | sound | problematic | sound |
| policy-with-data（P260…001 保单状态） | not_fulfilled | sound | sound | sound | **problematic** | problematic | sound |

trace_analysis 5/5 verdict=complete；无轴执行失败（status=failed 为 0）——Step 4 降级校验在真实链路上未出现杀轴。

## 二、与 v3 预期对照

| v3 论断 | 校准结果 |
|---|---|
| case01 故障点是系统上下文组装（hint「未查询到该保单，请核对保单号」在 Direct→agent_input 投影中丢失），不是模型 | ✅ context_memory `projection_keeps_information: fail`，finding 精确到「信封 6 个信息原子，hint/ok=false/source/request_id 在 direct 步输出中丢弃、模型输入未携带」；model_capability sound |
| case08 缓存把可重试失败结果当有效复用（同 request_id、9ms）是系统状态管理问题；模型重试本身合理 | ✅ context_memory `cache_reuse_valid: fail`（replayed、9.1ms、同 request_id、retryable=true 仍入缓存）；model_capability sound |
| case18（查无此保单）回答正确 | ✅ 六过程轴除 knowledge_data（数据源未命中，事实如此）外全 sound |
| 事实层必须程序化：「某条信息在哪一步丢了」要算出来，不能靠 Judge 猜 | ✅ 每个 fail 检查项都有 evidence_refs 指向具体 /records/ 记录，语义归因全部由 Judge 读证据正文得出，无硬编码 |

## 三、校准发现（需人工定夺）

### A. fulfillment 规则对「对象不存在/字段缺失」型查询过严（最重要）

5/5 全部 not_fulfilled。其中 case18 / multi-turn / policy-with-data 三个 case 的数据源结果是**合法业务结果**（保单不存在、字段本身未返回），系统如实转达未命中原因 + 给可行动建议（judge 在 reasoning 里都承认「完全兑现如实反馈与缺口澄清的纪律要求」），但仍按 Step 4 写入的规范「数据源没给数据 → 该期望 not_fulfilled」机械判罚。

对照：case01 判 not_fulfilled 的额外理由成立——回答只说「未取得该字段的数据」，未准确传达 hint 里的「保单未命中、请核对保单号」（因为 hint 被投影丢了），披露不准确。同一标准下 case18（准确复述未命中）应可判 fulfilled。

**建议**：把 build_context 里的规范细化为——数据源未命中且回答如实转达未命中与原因/下一步 → 该期望可判 fulfilled（「查无」是查询的有效结果）；数据源报错/服务失败，或回答对未命中的转达含糊、遗漏数据源给出的具体原因 → not_fulfilled。需用户确认后改。

### B. context_memory `projection_keeps_information` 不分层信息重要性

policy-with-data：投影丢了 3 个原子，但丢的是调用标识 CALL-TR-… 等技术原子，非业务关键信息（hint 类）。观测真实（bigram 比对确有其事），fail 字面成立，但「丢了什么重要吗」未分层，problematic 偏严。可接受；若要精化，check 措辞可改为「业务关键信息原子是否保留」，重要性由 Judge 按其对下游回答的影响判断。

### C. case08 双计观察

同一缓存回放事实被 context_memory（cache_reuse_valid）与 planning_routing（retry_policy）各记一次 fail。两处 evidence_refs 均真实、视角不同（缓存该不该存 vs 重试编排未绕过缓存），无编造；但与 v3「不双计」的个人拆法不同。轴边界讨论点，暂不改。

## 四、结论

Step 5 验收「与 v3 文档预期一致」**达成**：v3 两条核心归因（case01→context_memory 非模型、case08 缓存回放）在真实 LLM 链路上全部复现，且归因链路（程序观测→结构信号→Judge 读正文定语义）全程可定位、无硬编码。发现 A 为 Step 4 规范措辞的已知边界，留待用户定夺后单独修改。
