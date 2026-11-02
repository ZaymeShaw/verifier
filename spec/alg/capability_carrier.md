# 能力承载性归位协议（做不了 / 做错了 / 说不清）

> 状态：已落地（2026-08-16）；2026-10-20 起作为主轴的系统能力部分（`demand/main_axis.md`），补两类做不了的依据："信息源本来没有"（§2.1，待落地）、"业务方登记的责任范围"（§2.1，待落地；`demand/information_sources.md` §1.2，`rule.md` 评估责任边界）。`spec/alg/fulfilled.md` 是轴1（办成了没有），本协议是轴2：
> 只对轴1 判"没办成"的案子回答一件事——没办成是因为承载不了，还是承载得了却没做对。
> 不改 fulfilled 三态，不进 JudgeResult，不进 Judge prompt，判后派生。
> 第一章为长期协议，第二章为落地机制与配置。

# 第一章：Spec 标准

## 1. 我们在评什么

三个角色同 `fulfilled.md`。

`fulfilled.md`（轴1）只看：用户要的事办成了没有。

本协议（轴2）只看另一件事：

```text
这件没办成的事，当前产品的受治理能力空间，承载得了吗？
```

```text
单位：一条没办成的 blocking 期望 × 当前能力空间快照
视角：资料。不看这次交付了什么，不看 live 说了什么话
时机：轴1 判定完成之后。轴1 = 办成了 / 说不清 → 本协议不适用，不跑
```

两轴的分工锁死：

```text
轴1（fulfilled.md）   用户要的事办成了没有 —— 纯业务判定
轴2（本协议）         没办成的那条，空间承载得了吗 —— 资料事实判定
```

轴2 永不回写轴1。轴1 判定时轴2 通道物理上不存在（见 §6 判后 pass），
"揣测不越轴"是结构保证，不是纪律要求。

## 2. 三个状态

### 2.1 做不了

没办成的那条期望，当前受治理能力空间承载不了。必须是**资料层自认**。
结构化形态下的自认种类是：缺维度、缺值、缺操作符、`is_supported=false`
（见 §6.1）。其他形态用自己的资料空间给出等价的自认证据。

**责任范围登记里说在系统之外，是做不了**（`demand/main_axis.md` §3.3，2026-10-20）：业务方登记的责任范围（`judge_boundary`，`demand/information_sources.md` §1.2）写明某类数据没有、某类系统不接、某类要求不由本系统负责，期望落在这些限制里 → 做不了，自认证据 = 登记原文的逐字引用。责任范围只写事实（没有哪类数据、不接哪类系统），不写判法；没登记的不自判职责外。被测系统自己的能力描述、系统提示词、"暂不支持"话术都不是登记，不算自认。

**信息源里本来没有，也是做不了**（`demand/main_axis.md` §3.3，2026-10-20）：期望要的对象或那一项，
在被测系统的信息源（数据、知识库）里查实不存在——按该对象查过、结果读全了——系统各部分都正常也给不出，
归做不了。证据是对信息源的查询回执与原文，和资料自认一样须可回溯；查回别的对象、没读全、查询报错都不算查实。
取证方式：本期由承载性自己带知识源工具查（现状，`impl/projects/llm_probe/eval_axes/adapters/carryability.py`），查询回执与原文进引用，程序回读核验；改为向知识查证提待查项、读同一份案卷不在本期。查一次够不够、是否要求数据全量声明，见 `demand/main_axis.md` ⟡3，定下来之前输出必须带查询回执。场景没登记知识源时不出这类做不了。

做不了 ≠ 系统这次没取到：数据在、但这次工具报错 / 服务挂了没取到，是承载得了却没做对，归做错了
（服务也是被测系统的一部分）。

职责外不再是另一类问题：有责任范围登记就是做不了，没登记就不自判（见上）。
做不了 ≠ `product-function.md` 的"没这项功能"（那是产品认账层，本协议是实现空间层）。

### 2.2 做错了

空间承载得了——资料证实存在能完整表达该期望语义的能力——但这次没做对。
漏条件、加错条件、改错值、条件关系理解错，全部归这里，不再细分。

**做错了没有人直接判**：它是合取推导——

```text
轴1 说没办成 ∧ 承载性裁决说承载得了 → 做错了
```

承载性裁决从头到尾只回答承载性，永远不看这次交付的内容。
这一条把"轴2 变成第二个 Judge"的口子封死。

### 2.3 说不清

承载性本身判不了。成因穷尽为两类，必须写清差在哪儿、缺哪份料：

| 差在哪儿 | 什么时候出现 |
|---|---|
| 口径分歧 | 该期望有多个合理读法，且不同读法的承载性答案不一致（缺受治理口径）；或双抽后 2/3 多数票仍无多数 |
| 空间未受治理 | 该维度既无 M1 登记也无信任模型可依，封闭性无从谈起（缺登记） |

口径分歧的判据是确定性的：所有合理读法都承载得了 → 做错了；
都承载不了 → 做不了；**只有读法之间答案不一致才落说不清**。

mapper 重试耗尽、能力快照加载失败不是说不清。该期望归位失败，
本次 run 标记 `run_status=error`，不得进 review/solidify。

## 3. 判断顺序

```text
第零步：轴1 已出。fulfilled / not_evaluable → 不适用，结束
第一步：取该案子里每条未达成的 blocking 期望，逐条独立判
第二步：项目选定的形态，把该期望收成该形态的读法（可一条或多条）
  ├─ 读法之间承载性一致 → 用该答案
  └─ 读法之间承载性不一致 → 说不清（口径分歧）
第三步：形态按自己的资料空间做确定性承载裁决
  ├─ 资料自认承载不了，或责任范围登记说在系统之外，或信息源查实该对象 / 该项本来没有 → 做不了
  ├─ 资料证实能完整表达 → 做错了
  ├─ 资料不够、空间未受治理 → 说不清（须写清差在哪儿 + 缺料）
  └─ 形态运行失败（读法抽取耗尽 / 资料装载失败）→ 归位失败，run 标记 error
```

几个把歧义焊死的判据：

- **"承载"以期望的最小完整表达为准**：不许拿"沾边能力存在"凑数；
- **"信息源没有"只认查询回执**：按期望里的对象去查，读全了仍没有才算；被测系统回答里说"查不到"不算，
  本协议也不读回答——查什么由期望决定，不由交付决定；
- **"自认"只认资料**：资料 = 受治理能力空间、业务方登记的责任范围、信息源查询回执三种。live 的"暂不支持"话术不算——那是话术，
  `material-positioning.md` 的防循环格挡不许它自我背书；被测系统的能力描述、系统提示词同理，它们是被量的对象；
- **单位是期望，不折叠**：一个案子多条 NF blocking 期望各判各的，
  case 级只做罗列展示，本协议不定义 case 级单值；
- **覆盖性**：轴1 三态穷尽 → 只有没办成进轴2 → 轴2 三出口穷尽（§2.3 成因也穷尽）。
  没有漏格。
- **形态不进协议**：字段×操作符×值、口径表 rescue、中文描述解析，
  都是结构化形态的内部规范，见 `capability_carrier-reading.md`。
  协议只认三态、资料自认、可回溯引用、不改写轴1。

## 4. 和邻题的边界

| 问题 | 在哪 | 和本协议 |
|---|---|---|
| 办成了没有 | `fulfilled.md` | 只消费它的"没办成"结果，永不回写 |
| 这类事是不是产品已有功能 | `product-function.md` | 那是产品认账层（种类）；本协议是实现空间层（这条期望）。做不了 ≠ 没这项功能 |
| 该不该由这个产品管 | 业务方登记的责任范围（`judge_boundary`） | 登记了就是做不了的依据之一（§2.1）；没登记的不自答，条目带"归属待登记"进收件箱 |
| 通用裁决通道 | `spec/alg/authority.md` | 共用其调查层与 solidify 资料，**不走其 Request/Resolution 通道**（见 §6） |
| 资料能不能当尺子 | `material-positioning.md` | 承载性定论的依据来源：M1 登记 + 信任模型 |

## 5. 反面情况（永远不许）

```text
1. 轴2 结果回写、改判轴1                                  ✗
2. 让 Judge 运行中填轴2（必须判后派生）                    ✗
3. 拿 live"暂不支持"话术、被测系统的能力描述或系统提示词当资料自认   ✗
4. 承载性用"沾边字段存在"凑数                             ✗
5. 把"做不了"写成职责外 / 没这项功能                      ✗
6. 承载性裁决查看这次交付内容                              ✗
7. 说不清不带差在哪儿、不带缺料                            ✗
8. 对 fulfilled / not_evaluable 案子跑轴2                 ✗
9. 轴2 结果进 draft loop 计分                             ✗
10. 给未开启 scope 的问题类出裁决（见 §7）                 ✗
11. 从长尾 bad case 反推"这类 query 就判做不了"           ✗
```

---

# 第二章：落地

## 6. 机制：独立承载性裁决工具

轴2 是 Authority 体系的**一个消费者**，不是 Authority 的改造理由。
落成一个独立的裁决工具，不动通用裁决通道。

协议层（`impl/core/capability_carrier.py`）拥有主流程，项目与形态不可改：

```text
place(NF payload)
  → 逐条 blocking NF 期望
  → form.verdict_for(expectation) → CarrierVerdict | CarrierError
  → map_placement：承载不了→做不了；承载得了→做错了；判不了→说不清
输出    独立 artifact（per-run 归位记录 + 资料引用），不写入 JudgeResult
```

形态接口 `CapabilityCarrierBase`：`verdict_for` / `snapshot_revision` / `citation_space` 抽象，
`place` 为 `@final`。三态怎么来的形态自己管，三态往 placement 怎么映射协议管。

项目层合同**只有一个符号**：`impl/projects/<id>/live.py` 的 `capability_provider(spec)`
返回一个 `CapabilityCarrierBase`。core 不按项目函数名 getattr 物料。

```text
开 scope 且有 provider → 判后 pass 生效
未开 scope             → 工具不存在，行为与未接入一致
开 scope 但缺 provider → 装载期失败（config check + bind raise），不产生半错 run
```

与通用 Authority 的关系：**共用资料层，不共用裁决通道**。
`authority.md`、judge 运行中的 authority 工具、`judge_authority_*` context 资产、
draft skill ROLE.md 现有规则，全部保持现状。
其余裁决类（职责、口径、等价）的定义与流程本协议一律不碰。

## 6.1 形态

形态是协议之下的实现族。现有唯一形态是结构化形态
（`impl/core/capability_structured.py`，`StructuredCarrier`）：

```text
mapper(期望, 维度目录) → 读法组 / unmapped+nearest / process_only
resolve_carrier(读法, 能力空间快照) → 承载得了 / 承载不了 / 判不了 + 资料引用

物料形状   manifest（字段目录）必填；lexicon / spoken 可选。这是数据 schema，不是函数名。
第二步     期望→字段×值×操作符由 LLM mapper 执行；输入只有期望文本 + 受治理目录，
           不看 live / 轴1 理由。LLM 只出读法，不出三态
第三步     空间查承载是确定性代码。缺维度/缺值定案前，先口径表再全量枚举和描述内
           唯一别名反查；命中则改写成读法再裁，不另调 mapper
做不了自认 is_supported=false / 缺值 / 缺操作符 / unmapped+nearest
去重       按（读法字段集合 × 空间快照）去重
```

非结构化项目不强制套这套物料。新形态只要满足协议输出合同
（三态、资料自认、可回溯引用、不改写轴1）即可。第二个形态等真实项目驱动再落。

文本形态（llm_probe 的 `TextCarrier` / `carryability`）的边界输入必须分两路给模型、分开标注：

```text
依据       业务方登记的责任范围（judge_boundary 资料）、知识源查询回执   → 可作自认，可引用
背景       场景框里系统自己的能力描述、系统提示词、工具说明               → 只帮助理解期望指的是什么，不可作自认
```

现状把两者混在同一段 description 里，模型拿系统自己的能力声明当自认，这是 `demand/main_axis.md` §3.3 "被测系统自己说不算"落不下来的直接原因。改法：场景框引用的责任范围资料单独标 `source=boundary://`，引用回读只认这一类和知识源回执；description 其余文本标为背景。

client_search 通过 `capability_provider` 把自家 `capability_snapshot` /
`capability_lexicon` / `value_mappings` 喂给 `StructuredCarrier.from_materials`。
这三个函数名是项目内部取数入口，不是 core 合同。

## 7. 配置：enabled_scopes 枚举列表

替换 `project.yaml` 里 `verifier.authority.enabled` 布尔开关，不留兼容层：

```yaml
verifier:
  authority:
    enabled_scopes: []              # 空列表 = 全关（等价于原 enabled: false）
    # enabled_scopes: [capability_carrier]   # 只开承载性裁决（轴2）
```

| 枚举值 | 裁什么 | 走哪条通道 | 资料前提 |
|---|---|---|---|
| `capability_carrier` | 能力空间承载性（轴2 唯一依赖） | 独立工具，判后 pass | M1 登记（已有） |
| `responsibility` | 职责归属（轴1 NE(职责外) 入口） | 通用 in-run 通道 | 业务方职责声明 |
| `semantic_mapping` | 口径/术语 | 通用 in-run 通道 | 受治理术语表（对应 `judge_authority_semantic_mapping` 资产） |
| `query_equivalence` | 查询形式等价 | 通用 in-run 通道 | 双查询工具（对应 `judge_authority_query_equivalence` 资产） |
| `conflict_arbitration` | 资料冲突仲裁 | 通用 in-run 通道 | 冲突资料内部有排序 |

语义分两族，互不牵连：

- **`capability_carrier`**：开 → 判后 pass 生效、报表出归位列，且项目必须提供
  `capability_provider`（装载期检查，缺则 config check / bind 失败）；
  不开 → 该工具不存在，行为与未接入一致。不影响 judge 运行；
- **后四个（实验开关）**：列表里出现任何一个 → judge 运行中的通用 authority 工具
  按现状恢复暴露，但只准接列表内问题类。为此需要一个最小机制：
  裁决请求带问题类声明，Core 按列表做成员检查放行或拒绝——
  一个字段加一次检查，不改造裁决逻辑。这四类维持现状，
  实验发现哪类真的立得住，再回头做 `capability_carrier` 级别的正式化。

实验注意：`responsibility` 一旦开启，轴1 才会出现 NE(职责外) 入口，
**直接影响 loop 计分**——只准在 draft 分支跑对照，不得直接开在 production 配置。

## 8. 治理与 draft 落点

轴2 资产走现有 `current_fingerprint`，不另开 draft 角色、不另开 Judge solidify 通道：

- 项目 `capability_provider` 及其喂给形态的物料（client_search 目前是
  `capability_snapshot` / `capability_lexicon.yaml` / `value_mappings`）
  在项目包（`draft/` 除外）里，改动自动进入 `current_fingerprint`；
- 协议层 `impl/core/capability_carrier.py` 与结构化形态
  `impl/core/capability_structured.py` 同属 current 指纹；
- 变更门禁是冻结 NF 金标（`tests/test_capability_carrier.py` 的
  `test_client_search_axis2_frozen_nf`），不是 Judge 对照分。

draft 侧只加展示与审计，不改计分：

1. **loop 计分不变**：净胜继续只看轴1，现有赢案一个不掉；
2. **渲染**：`capability_carrier` 开启时对比表加"归位"列，
   逐条列出 NF 期望的 做不了/做错了/说不清 + 资料引用；
3. **review 增一项审计**：每个归位结论可回溯到资料引用；
   出现"归位试图改判轴1" → fail；
4. **收件箱**：NF×做不了（归属待拍板）与说不清（缺料）聚合成 per-loop 报告，
   不自动打回 Investigate；人拍板产生的声明走 Investigate 进资料空间，
   对应问题下一轮升定论。

## 9. 现在做 / 现在不做

现在做：

- 留下本协议（形态无关合同）；
- `enabled_scopes` 替换布尔开关（空列表默认，行为不变）；
- 结构化形态作为第一个形态落地；仅在 `capability_carrier` 开启且
  `capability_provider` 存在时跑判后 pass。

现在不做：

- 不发明第二个形态（等真实非结构化项目驱动）；
- 不改 Judge prompt、不改 JudgeResult、不改归因；
- 不改 `authority.md` 与通用裁决通道的任何定义；
- 不启用 `responsibility` / `semantic_mapping` / `query_equivalence` /
  `conflict_arbitration`（等各自资料前提补齐、定位讨论清楚再说）。

## 10. 验收

- 每条 NF blocking 期望都能落进三态之一；说不清必带差在哪儿 + 缺料；
- 每个归位结论带资料引用，可回溯到该形态声明的引用空间；
- `enabled_scopes: []` 时确定性面（system prompt 快照、工具暴露列表、配置解析结果）
  与未接入一致；不拿 LLM 输出做逐字节比较（重跑天然波动）；
- 开启 `capability_carrier` 前后，轴1 逐 case 结果不变（结构保证 + 冻结集回归验证）；
- 开 scope 但缺 `capability_provider`：config check 失败，bind raise，不产生半错 run；
- 换一批非长尾数据，协议仍成立；没有一条规则是"这类 query 就判做不了"；
- 未开启 scope 的问题类请求被拒绝，且拒绝不产生任何伪装成"已裁决"的输出。
