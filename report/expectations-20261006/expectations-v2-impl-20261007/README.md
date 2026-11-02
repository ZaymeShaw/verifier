# 需求轴 v2 与六轴判准来源：实施报告

日期：2026-10-07。任务：[expectations-v2-impl-task.md](../expectations-v2-impl-task.md)。实施记录：[spec/implementation/process-axes.md §8](../../../spec/implementation/process-axes.md)。

## 结论

**主体代码已实现，离线回归未新增失败；真实端到端验收未通过，不能作为已验收版本交付。**

- 最终全仓：**2416 passed / 14 failed / 5 skipped**，415.60 秒。14 个失败 node ID 与初始已有失败集合一致，没有为它们改实现。
- 两次完整真实重跑均未完成六轴／交付主判：首次候选办法投影被严格校验拒绝；第二次分析阶段遇到余额不足及备用路线地区限制。
- 需求产物不再含系统／工具承诺，但两次同冻结业务样本分别为 **4 条、3 条**。第二次未单列“是谁的保单”，**完整性与稳定性尚未达到定稿样例验收**。
- 没有修改 `demand/`、`spec/alg/`，没有提交 git，没有清理或恢复无关工作区改动。未启用 `response_format`，未新增依赖、兼容层或模型服务 fallback。

## 1. 做了什么、删了什么

| 范围 | 实现 |
|---|---|
| 需求轴 | `expectation_material.py`、`adapters/expectations.py` 只接收独立用户原话、已确认历史、场景判准与背景描述；历史／描述不能独立产需求。首个模型请求的 user 不再自动冒充用户原话。capability 不进入材料，存在时固定 partial／“capability 未拆分”。 |
| 场景材料 | 在既有 `capability_store.validate_entry` 定点保留并校验 criterion／description，避免正常保存丢失；downstream 仅接受 `list[str]` 占位，不读取、不参与 verdict。其他既有修改保留。 |
| 删除承诺映射 | 删除 `ContractBinding`、`contracts`、`tool_expectation_ids`、`attach_criteria`、`unattached` 及对应旧测试路径。E 中不再提取 commitment。 |
| 四问 | 前置只判断 external／none／unknown 与工具原文候选办法；采用 B 短编号、块内路径、原样摘录，程序回填真实引用。运行判断独立给 satisfied／required／unknown；已满足需证据并留覆盖记录、不生成问题；未知保留缺证；必须做未发生不预设规划责任。 |
| 三类判准 | 通用／已确认义务、适用 E、设计规则原文。新 `design_rules.py` 以消息／工具定义／格式字段列完整原文块，保留父级条件；引用核验原文位置、逐字摘录、版本与 owner。配对 span 的当次工具说明可用；采集版不得单独证明违约／漏传。 |
| 块覆盖 | 同次调用逐块 checked／not_applicable／unknown，程序验证完整且唯一、原因非空。**块标注完整不是语义规则全部核实**，错误地忽略规则的记录仍供独立审阅。没有为登记规则新增模型调用。 |
| 统一格式 | 三入口共用 `AxisJudgment`、`validate_submission`；删除 `ProcessAssessment`、旧 `_expand`、过时提交提示词与死辅助函数。结构问题仍严格拒绝并按原纠错轮处理，未转为业务缺证。 |
| 原子结果 | 每条判准保存身份／结论／事实／原文／上游依赖。问题预期由引用原样组成，保留 E 条件与跨位置的规则／例外。问题归属从自己的 breaks 派生，不被单位总 fail 错误升级。单位计数、判准计数、部分输入无效分别保存。 |
| 原子证据门禁 | 任何原子 pass/fail 都不能被另一缺证项免除读取／实际输入门禁；input_invalid 的 E 不因另一通用 pass 被强迫证明已送达。保留 provider 的真实响应、实收及双端证据限制。 |
| 同一 E | 消费前重算 E 指纹，核验投影指纹与 data_needs 全覆盖；两 ToolLoop 保存独立快照，单位及轴结果保存实用 E 指纹。需求与设计材料分别计算指纹。 |
| 主判 | 新项目内 `need_judge.py`：先仅用 E 投影 blocking，再用同一 E 判断交付；禁止模型自推需求。公共 `JudgeResult.business_expectations` 由程序从 E 原样生成，公共 finalize 语义、其他项目主判不改。正常新增一次 blocking 调用，须计入后续成本。 |
| 材料身份 | 共享正文改为 `shared#N`，与可引用 `content#N` 分离；未扩大 readable。transcript 保留真实消息下标与 system 消息边界，原文送达核验不再只认 ID 命中。 |

项目内变更文件及最终指纹：[implementation-files.json](implementation-files.json)。此外仅定点修改 `impl/core/capability_store.py` 的场景字段保留，以及相应测试、实施文档和本轮报告。初始工作区清单：[initial-status.txt](initial-status.txt)；项目原文件快照在 `before/llm_probe/`。

## 2. 离线验证

解释器：`/Users/xiaozijian/miniconda3/envs/agno/bin/python`。守护入口：[offline_tests.py](offline_tests.py)，屏蔽外部服务及业务／付费本地端口，允许临时 loopback 假服务测试。

```bash
/Users/xiaozijian/miniconda3/envs/agno/bin/python \
  report/expectations-20261006/expectations-v2-impl-20261007/offline_tests.py -q tests
```

| 验证 | 结果 / 证据 |
|---|---|
| 最终全仓，含 F1 修复 | **2416 passed / 14 failed / 5 skipped**，415.60s；[tests-final-after-f1.log](tests-final-after-f1.log) |
| F1 修复前完整全仓 | 2406 passed / 同样 14 failed / 5 skipped；[tests-final.log](tests-final.log) |
| F1 新证据矩阵＋来源测试 | 56 passed；两入口无回执混合判准、未送达 E、同案真实已接受上游、案卷实际输入门禁；[atomic-evidence-tests.md](atomic-evidence-tests.md) |
| 相关扩展回归 | 613 passed / 1 deselected（不跑本地 HTTP 假服务）；与其他测试组重叠，不相加作独立总数 |
| 原 R1–R7 独立复审 | 原反例关闭；602 passed / 2 deselected。复审额外发现 F1，之后实现修复并通过上述矩阵；[independent-review-followup.md](independent-review-followup.md) |
| 变更空白检查 | 指定实现／测试路径 `git diff --check` 通过 |

既有 14 项：config_contract 1、deerflow 归因 6、llm_probe 缺 fixture 2、schema_validator 2、tool_loop_lab 1、tool_loop_lab_frontend 1、tool_loop_package 1。精确名称及集合比较：[baseline-comparison.json](baseline-comparison.json)。

### 不隐藏的中途失败

- 初轮全仓守护误设 `EMBEDDING_ENABLED=false`，引出额外 Authority 初始化／embedding 失败；已删除该覆盖值，相关 101 passed / 1 skipped。原日志保留，不能把误配置结果当代码基线。
- 并行迁移期间有旧 schema 导入收集失败、旧 identity fixture 失败；均记录于各阶段日志，最终以 `tests-final-after-f1.log` 为准。
- 原文块初版拆到 JSON 标量、工具 fields 初版扁平路径、混合判准上游／归属与证据门禁等问题，先由反例复现再修复；不是通过删除业务断言、降低校验或补判值取得通过。
- `Quote.path` 是可省略／允许空串的字符串，非 nullable；对明确的 null 继续拒绝。最初测试委派对此有歧义，已明确并补拒绝测试，没有改公共 schema validator 的既有 PEP604 失败。

## 3. 两次真实运行与历史对照

两次都从同一冻结真实 Agno trace 完整启动需求→分析→六轴→主判；没有执行新业务，也没有复用旧 E／分析／判词。请求走现有 4008–4010 网关。实际成功响应模型为 `qwen3.8-flash`；第二次既有调度还尝试 `gemini-3.8-flash-medium` 并被地区限制拒绝，未增加账户或服务。

| 指标 | 历史六轴 replay3 | v2 full-live | v2 full-live2 |
|---|---:|---:|---:|
| 范围 | 只重跑六轴 | 完整流水线尝试 | 修复后完整流水线尝试 |
| E 条数 | 复用旧 167 条 | **4** | **3** |
| E 耗时 | 未重跑；原完整运行约17.7分钟 | **33.49s** | **50.93s** |
| E verdict | 旧产物 | partial：capability 未拆分 | partial：capability 未拆分 |
| 六轴 | **6/6** | **0/6**，投影失败 | **0/6**，全部 blocked |
| 模型请求尝试 | **13** | **18** | **10** |
| 重试 | **2** | **7** | **5** |
| 原文非法 JSON | **2** | **0** | **0** |
| 输出字符，不含 reasoning | **39,413** | **66,093** | **2,466** |
| 主判结论 | 未重跑 | not_evaluable | not_evaluable |
| 完整墙钟 | 六轴862s | 1896.606s | 428.276s |

**不能据这张表声称六轴更省或更准确**：两次新运行都未完成六轴，阶段与分母不同；非法 JSON 为零也不代表结构/引用或环境请求成功。

### 第一次：实现／提示契约失败

目录：[expectations-v2-full-live-20261007](../expectations-v2-full-live-20261007/)。

- E 1 次、分析5次、候选办法投影12次。分析重交1次、投影纠错6次；未发动六轴判断或交付主判。
- 模型混淆块长 ID、原文位置与块内路径，严格摘录校验持续拒绝。旧缓存只保存成功投影，导致六轴各重复两次相同前置失败。
- 之后改为 B 短编号、明确块内 path、具体错误回执、真实字段路径，并缓存前置评测失败，避免重复付费调用；这些修复有离线正反例，**第二次没运行到此处，未真实验证成功**。

### 第二次：环境失败，同时暴露需求条目不稳定

目录：[expectations-v2-full-live2-20261007](../expectations-v2-full-live2-20261007/)。

- 4 次成功请求、6 次环境失败，共10次网关尝试（6个传输请求身份、5次上层 LLM 阶段调用）。重试为同身份传输重复4次＋既有路由切换1次，没有格式纠错。
- 最终 **402 余额不足**；备用路线另有 **400 User location is not supported**。分析失败后六轴 blocked，业务最终交付主判未运行；not_evaluable 是门禁结果，不是用户目标没办成的业务判断。
- E 只包含投保人、被保人、当前状态；未独立列“是谁的保单”。两版实现的来源元数据有变化，不能当成严格同输入稳定性实验，但也不能宣称定稿四项样例已经验收。
- 停止真实尝试，没有更换账户、充值或新增 fallback。最后的 F1 证据门禁修复仅完成离线验证，没有再消耗真实调用。

两目录保留 `input-trace.json`、`manifest.json`、`implementation-snapshot/`、`contexts/`、`gateway-events.jsonl`、`result.json`、`summary.json`、`metrics.json`。统计脚本：[summarize_live.py](summarize_live.py)。计数口径：原始 `pre_api_call` 尝试；字符为 assistant content＋tool arguments；非法 JSON 在修复前计算；格式重交、传输重试与路由切换分别列明。第一次五次额外独立前置重试包含在12次投影调用中，不混称格式纠错。

## 4. 未完成项／与方案的边界

1. **真实需求→六轴→主判未跑通**。没有任何本轮有效六轴结果，不能关闭 B 样本格式违约、漏行动归属、有效缓存／明确刷新、规则漏传等真实语义验收。离线反例只是机械与协议验证。
2. **需求完整性、重复稳定性未通过**。不按样本硬编码“四条”，不由程序补写缺失需求；恢复环境后须用相同冻结输入与对照样本复核。
3. **主判改读 E 仅完成 llm_probe 业务 Trace 链路**。未启用业务 Trace 的旧主判、独立 fulfillment 没有上游 E 生产／依赖登记，本次保留为待定，不改其他项目行为。公共 `business_expectations` 字段保留程序投影，不含模型自推清单；若要求连公共字段也删除，会与“不改公共 JudgeResult 语义”冲突。
4. **capability 仍待配置维护者拆分确认**；当前非空字段保持 partial，没有让模型重新分类，也没有宣称验收要求已覆盖。downstream 仅占位。
5. **块覆盖不是规则语义召回率**。完整句、跨句条件是否选全，数据／示例是否误当规则，必要性／影响判得是否正确，仍需独立语义审阅；程序不替模型补条件。
6. 初始要求先案卷批次最小端到端再推广：本轮先完成案卷批次共享实现与离线接缝，之后迁移两 ToolLoop；**真实案卷端到端未成功，所以没有达到“先真实跑通再推广”的验收顺序**。没有为此保留两套 schema；此差距明确记录，不能以离线通过冒充真实跑通。

下一步不是继续改方案：先恢复既有网关可用额度／区域条件，再用当前实现新建完整运行目录，补需求与六轴／主判真实对照。任何后续成功都不得覆盖本报告的两次失败记录。
