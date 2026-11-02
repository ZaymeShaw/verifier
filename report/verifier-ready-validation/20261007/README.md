# verifier-ready 审阅者校准试验

用户授权范围：先验证需求中的最大不确定性，不实施完工门，不修改 verifier 或全局模型配置。

## 试验设计

- 12 个构造微型样本、6 组问题/对照：空字符串 schema 冲突、轴枚举冲突、条件失真、无依据业务输出、同请求整块重复、独立请求证据边界。
- 同一组输入在两个新 pi 会话重复审阅。参考答案不放入审阅目录；审阅者只得到随机编号的样本和规范原清单，不知道正负比例。
- 另准备 5 条通过 `llmtrace query show --full` 导出的真实历史调用，覆盖两个业务 case。原文不改写，另附调用账本与轴状态。
- 历史材料不提供源码、历史诊断或完整案卷解引用，测试范围是这些调用中的问题发现，不等同完整四例完工门。
- 审阅者使用当前规范第 5 节清单，包括“整份 dossier_view 再发一遍不行”这一待验证约束。不预先修正它。
- 每个会话使用新的临时工作目录，关闭会话持久化、技能、扩展、项目上下文文件发现；工具为 read/bash/grep/find/ls。此隔离减少金标泄漏，不是完整复刻拟议仓库 cwd 启动方式，也不是操作系统权限沙箱。
- 采集 stdout 事件流、最终 JSON、模型/provider、usage、工具调用、时长和任务目录内容哈希。进程返回 0 但无有效 JSON 仍是执行失败。

## Gold 与评分边界

Gold 在审阅前冻结，由协调代理构造并经独立只读 peer 核对，**不是人工业务金标**。正常或修复后对照是实验构造，不是生产修复重跑。

同一请求重复样本的第一版对照自身含重复正文，peer 在模型启动前发现；正式冻结版已改成 100 条不同交易，问题版重复整个 record，对照版只有一份。独立请求对照仅要求重新提供必要的币种证据，允许提出无关字段裁剪的 diagnostic。

评分区分：目标机制命中、严重级别、其他真实问题、无依据的 high/blocking。只有逐条裁决后的无依据 finding 才算误报。修复后撤销按目标机制计算，不要求整个样本完全没有建议。

这是容易样本的探索试验。两次重复不扩大独立样本数；即使全部通过，也不能估计生产误报率、证明长上下文覆盖、证明真实修复成功。不同模型结果不能混为默认模型表现。

## 产物

- `preregister.json`：预注册范围、判分原则及模型执行修订。
- `private-gold.json`、`frozen-input-hashes.json`：参考标签及冻结哈希；不提供给盲审者。
- `corpus/controlled/`：构造样本。
- `corpus/historical/`：未删节的历史导出、账本、轴状态。
- `runs/<label>/`：每个独立会话的元数据、stdout、stderr、tool-calls、messages、最终结果。
- `fixture-reconciliation.json`：新导出与原存档核对。
- `mechanics-results.json`：临时仓库中复现的 git 状态与同目录哈希局限。
- `methodology-peer.md`、`historical-peer.md`、`historical-peer-checks.json`：独立复核和关键原文反证。
- `technical-report.md`、`product-report.md`：最终技术记录及使用结论。

## 已确认的执行环境问题

默认 pi 的 anyrouter/claude-opus-5-5 返回 HTTP 400，错误信息表示无法供应。三个初始会话均 exit 0、无工具调用、无最终审阅 JSON，全部排除在能力评分之外。只记录真实错误，不采纳错误消息中的替代模型作为未经核对的执行指令；后经本机 `pi --list-models gpt-6-astra` 确认替代模型已配置。

历史保险原文首次发送被自动审批拦截；用户随后明确授权本次原文审阅，并指定使用 DashScope qwen3.8-flash，禁止 OpenRouter。历史原文没有发送给 OpenRouter。最终评分仅包含 `controlled-flash-1`、`controlled-flash-2`、`historical-flash-1`，三者均完成，模型均为 DashScope qwen3.8-flash。之前停供与主动中断的试跑全部排除。构造样本不含真实客户姓名、保单或客户数据。

本机 pi 只注册了 DashScope Max，本次在私有临时 agent 配置中注册 Flash，沿用现有百炼 Token Plan 端点。没有修改全局配置；临时凭据配置在验证结束后删除。官方模型资料及费用边界见 `flash-config-record.json`。

## 复现

`prepare.py` 生成材料。**已有评分时不要重跑生成脚本覆盖冻结输入。**

`run_review.py --model <已确认的provider/model> <新label> ...` 新建审阅会话；label 以 historical 开头时选择历史材料，其余选择构造样本。不会覆盖已存在的会话目录。外发历史数据须在授权范围内。

`check_mechanics.py` 仅在一次性临时 git 仓库中测试完整性机制，不修改业务代码或实际结论。
