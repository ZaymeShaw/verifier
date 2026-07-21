# DeerFlow Mock Draft 优化设计

## 目标

通过 Draft 的 `Investigate → Solidify → Draft Loop` 生命周期，改善 DeerFlow 项目 Mock 生成的用户输入，使其稳定代表 `PA-ALG/yingxiaoguihua` 定义的平安人寿内勤 NBEV 月度规划场景，并在冻结数据上证明相对 Current 实质改善且无可见退化。

本次只优化 verifier 中 DeerFlow 项目的 Mock 角色。业务源仓库和本地 DeerFlow 仓库均只读；不自动 Promotion。

## 已确认问题

当前 DeerFlow Mock 主要依赖公共 `MockAgent` 和简短项目描述，没有 Mock 专属 mandatory ContextUnit。现有 Mock 样本包含订阅促销、电商双十一和渠道投放预算等泛营销语义，与目标业务的内勤 NBEV 达成规划存在明显漂移。

目标业务中的真实用户是平安人寿机构内勤。其核心任务是按月承接 NBEV 目标，从队伍、客户、产品三个视角生成可达成、可解释、可调整的规划。三个视角描述的是同一笔 NBEV，而不是三条互相独立的业务结果。

## 方案

采用项目级 Mock Draft：候选 mandatory ContextUnit、薄 `draft/mock.py` 和冻结 Current/Draft 比较。

不采用仅修改通用 Prompt 的方案，因为它无法隔离 DeerFlow 业务知识；不修改公共 `MockAgent`，除非 Investigate 证明现有项目扩展点无法承载目标。若出现该情况，记录为 blocker 并单独请求扩大范围。

## Investigate

调查源：

- 本地 DeerFlow 仓库，调查时记录 Git revision；
- 私有仓库 `PA-ALG/yingxiaoguihua`，调查时固定并记录 GitHub revision；
- verifier 当前 DeerFlow Mock、输入协议、Live schema、已有 Mock 数据和可执行结果。

调查遵守 Draft Mock 的材料边界，只读取输入协议、业务实体与约束、用户可见能力、合法示例和可执行性结果。不得读取或泄露 promotion-only unseen cases，不把生成样本当成业务规则来源。

调查包写入：

```text
impl/projects/deerflow/draft/investigation/mock/
  manifest.json
  overview.md
  docs/...
```

调查必须回答：

- 用户是谁，以及为什么使用系统；
- 新建规划、查看画像、调整已有规划和范围外请求如何区分；
- 合法输入需要哪些槽位，缺失时如何自然澄清；
- 月份、机构身份、NBEV 目标和队伍/客户/产品视角有什么约束；
- 哪些输入能进入 DeerFlow 真实链路，哪些只能判为无效或范围外；
- 当前 Mock 在哪些场景出现业务漂移或系统视角表达。

调查包通过 `validate_investigation.py` 和语义交接审查后才能进入 Solidify。

## Solidify

把经过验证且稳定的业务事实固化为 Mock 可见的 mandatory ContextUnit。ContextUnit 至少包含：

- 用户画像：经过身份认证的寿险机构内勤；
- 用户目标：完成月度 NBEV 达成路径规划；
- 业务语言：队伍、客户、产品三个视角；
- 意图边界：新建、画像、整体或明细调整、范围外请求；
- 槽位与默认规则：规划月份、目标 NBEV、所选视角、机构身份；
- 表达边界：不得提及文件、路径、JSON 字段、工具名、Verifier 或系统实现细节。

候选 `draft/mock.py` 保持薄封装，继续实现现有 `ProjectMock` 协议并复用公共 `MockAgent`。候选只消费已声明的 Mock Context 资产，不开放 Agent Search/Load。

`project.yaml` 增加默认关闭的 `mock_draft` 配置及 roles 包含 `mock` 的资产映射。Production 默认行为保持不变；Draft Loop 通过冻结 spec 切换 Current/Draft。

Solidify 必须完成：协议自省、调查包门禁、候选模块编译和加载、Context 注册与装载、ProjectMock 实例化和最小生成 smoke。

## 冻结用例

Draft Loop 启动前建立 iteration cases；promotion-only unseen cases 只能来自未向优化过程暴露的独立来源。当前由优化执行者创建或读取的样本全部作为 iteration cases，不声称存在 unseen 泛化证据。启动后不得修改冻结数据。

iteration cases 至少覆盖：

- 开放式规划开场，例如“这个月怎么做规划”；
- 一次给齐目标 NBEV 和单个或多个视角；
- 缺目标、缺视角或月份含糊；
- 多轮追加队伍、客户、产品视角；
- 查看画像；
- 调整已有方案；
- 常规月与活动月参考口径；
- 范围外请求；
- 服务不可用或真实链路不可执行。

用例提供场景和输入意图规格，不提供目标生成答案，不包含 case 专属提示或固定输出文案。

## Draft Loop 判定

Current 和 Draft 使用相同冻结 revision、objective、review、iteration cases、模型和运行环境。每轮保留两侧原始结果、异常和运行事实。

审查维度：

1. 协议合法性：生成结构符合 DeerFlow 请求 schema；
2. 业务意义：表达属于真实内勤 NBEV 规划工作；
3. 用户目标：能识别规划、画像、调整或范围外意图；
4. 场景覆盖：槽位缺失、视角追加、月份口径和边界场景得到覆盖；
5. 真实性：语言自然，不替用户暴露系统字段和内部实现；
6. 业务防漂移：不生成电商、订阅套餐、广告投放等无依据场景；
7. 可执行性：选定样本能通过 schema 校验，并在依赖可用时进入 DeerFlow 真实链路；
8. 泛化：不存在 case ID、专属数值、历史组合或固定答案硬编码。

只有 Draft 相对冻结 Current 实质改善，并且 iteration cases 与 promotion-only unseen cases 均无可见退化，才建议 Promotion。相同、文本更长、字段更多或局部改善伴随退化均不算成功。

## 异常和退出条件

- 业务事实不足：返回 Investigate；
- Context 或候选消费方式不足：返回 Solidify；
- LLM、loader、协议、Live 服务或数据依赖失败：记录 blocker，不伪造比较成功；
- 达到迭代上限或连续没有新信息：停止并报告未证明更优；
- 发现必须修改公共 `MockAgent`：停止并请求用户授权扩大范围；
- Promotion：必须再次取得用户明确确认。

## 非目标

- 不修改 `PA-ALG/yingxiaoguihua`；
- 不修改本地 DeerFlow 业务仓库；
- 不给 Mock 增加文件读取、搜索或修改权限；
- 不优化 Judge、Attribute 或公共 MockAgent；
- 不自动上线候选；
- 不把业务仓库完整 Skill 或文件路径直接注入用户模拟 Prompt。

## 2026-07-21 增量设计：脱敏派生 ContextUnit

仓库材料只在 Investigate 阶段本地读取，用来归纳用户为何使用系统、合法任务、输入槽位和业务边界。Solidify 不把仓库原文、源码、路径或来源标识直接注册为 ContextUnit，而是生成一份单一、脱敏的业务合同文档。该文档不得包含机构名、仓库名、文件路径、实现类、接口地址、端口或测试系统术语，只保留寿险机构内勤、NBEV 规划、画像、已有方案调整、授权边界、服务异常及自然表达约束。

Manifest 继续在调查层保留来源 revision 与 EvidenceRef，供 Harness 审计；Mock runtime 只能消费派生业务合同。Draft Loop 对外部模型的新增暴露范围限定为该派生合同与冻结 iteration cases，不发送仓库原文或无关源码。Current 保持原有行为，不因候选 Context 引入 DashScope 依赖。

本次标准化修复同时纳入实现：

- `authorization_boundary` 必须有规范 fixture，使 live schema、项目配置和 mock 数据覆盖一致；
- validator 只宣称确定性边界验证。规划场景必须同时具备寿险/NBEV 领域锚点和规划动作；无法用稳定规则判断的完整语义质量交给 Harness Review，禁止重新引入坏样本词表；
- candidate-only mandatory Context 仅在候选资产真实存在时从 Current 过滤。production 与 candidate 同时缺失仍须 fail closed；
- 每次修改上述 Current、Draft 或 iteration data 后重新启动 Draft Loop，禁止沿用旧冻结指纹。

## 验收标准

- 调查证据携带可追溯来源和 revision；
- Mock Draft 调查包和候选通过全部结构门禁；
- Current/Draft 比较使用冻结数据并保存原始事实；
- Draft 在业务意义、用户目标、边界准确性和表达真实性上被证明更优；
- 请求协议和真实可执行性无退化；
- 未修改两个只读业务仓库和公共 MockAgent；
- 最终只提出 Promotion 建议，不自动执行 Promotion。
