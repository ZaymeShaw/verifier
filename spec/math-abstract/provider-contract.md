# d / e / g Provider 接入合同

> 状态：抽象层协议，`spec/math-abstract/judge.md` 的配套合同。judge.md §4 说
> "项目差异只在 provider"，§8 说"provider 合同应当一等公民化"——本文就是那份合同：
> 定义什么东西有资格当 d / e / g 的 provider、它必须交出什么、失败时算什么。
> 本文不是实现计划；实施分层见 `spec/alg/capability_carrier-generalization.md`。

## 1. 判别式：什么算 provider

一个机制要归位，先过 judge.md §5 的判别式，本文将其收敛为合同门槛：

```text
供出一个值（交付快照 / 期望 / 能力证据）      → provider，适用本合同
限定哪些值合法（定义域声明，如 judge_boundary） → 不是 provider，不适用本合同
下三态结论 / 复述 J 的判定                     → 冒充 J，拒绝接入
```

三条推论：

1. provider 只交**值**，不交结论。探针探到"目标返回 4xx 明确拒绝"是值；
   探针宣布"该期望做不了"是冒充 J。
2. provider 不因供料方式获得特权。YAML 装的、探出来的、调用方声明的能力证据，
   都压进 §2 的戳记；J 不看出身，只看档位（judge.md §1、§6）。
3. 一个机制可以同时为多路供料（如 source 阅读既可产 g 证据也可佐证 e 的口径），
   但每一路各自过一遍本合同，不共享失败语义。

## 2. 合同：provider 必须声明与交出的东西

### 2.1 装载期声明（可校验的一等对象）

每个 provider 在装载期必须能回答，缺一即接入未完成、fail-fast：

| 声明项 | 内容 |
|---|---|
| 供哪一路 | d / e / g 之一（多路则逐路声明） |
| 引用空间 | 本 provider 产出的值允许被 citation 到哪些稳定标识上（key 集合、工件 id 形态等）；J 的引用必须落在此空间内（judge.md §1 "引用"） |
| 失败面 | 哪些情况是装载期失败、哪些是运行期失败、哪些是合法的"值缺失"（§3） |

装载期声明的存在性检查对齐既有卡点：开 scope 而 provider 缺失 → config check
直接报错，不进运行期（capability_carrier-generalization §2b 已落地此模式，
`capability_provider` 是本合同在轴2 g 路上的第一个实例）。

### 2.2 运行期输出（值 + 戳记 + 引用锚点）

戳记随路而定（judge.md §6：三件套只构成 G）。

**g 路输出**（能力证据）必须携带（三件套 + 引用锚点）：

| 字段 | 内容 |
|---|---|
| value | 一件能力证据 |
| provenance（出处） | 从哪份资料、哪次探测、谁的声明来，可回溯到具体源 |
| trust tier（信任档位） | 档位随"谁担保 / 担保多强"定，不由内容类型单独决定（judge.md §6）；`normative_rule` / `external_fact` > `inlive_boundary`（须信任模型登记）> `current_behavior` 的定位序保留为典型担保强度的缺省映射（`spec/alg/material-positioning.md`）；caller-stated（`caller_stated`）无独立担保时落低档；被测系统自述不得自我背书（judge.md §7.4） |
| staleness（新鲜度） | 值定格于哪个 revision / 时刻；源漂移后按消费模式路由重算或重验（`spec/grill/staleness_public_facility.md`） |
| citation 锚点 | 该值在已声明引用空间内的定位标识，供 J 的 citations 回溯 |

J 消费这五项的方式是确定性的（judge.md §6）：g 缺失或低置信 → 诚实的
"说不清 + 差在哪儿 + 缺料清单"，不是自信的错误结论。

**e 路输出**默认无戳记：期望的出处结构上就是诉求文本 y 本身。仅当期望附加了
超出诉求字面的口径（派生解释）时，那条口径必须携带担保/出处，
给不出 → 诚实的"说不清（口径无担保）"；有担保口径彼此冲突、
分歧材料定夺不了 → 诚实的"说不清（口径分歧）"，不许静默择一（judge.md §6）。

**d 路输出**无戳记合同：交付快照的出处结构上就是本次运行，C 不消费信任档位
与新鲜度，J 永不看 d(x)（judge.md §6、§7.2）。

## 3. 失败语义

三种状态互斥、不许混同（对齐 judge.md §7.7 与 capability_carrier-generalization §2c）：

| 状态 | 定义 | 处置 |
|---|---|---|
| 装载期失败 | provider 声明缺失 / 物料装不出来 / 合同字段不齐 | fail-fast，run 不启动，不产生半错数据 |
| 运行期失败 | 设施故障：检索索引崩、网络重试耗尽、mapper 耗尽 | 本次运行 **error**，fail-closed；**不得伪装成 J 的"说不清"业务结论** |
| 值缺失 | 设施正常，但资料里没有这个维度 / 探测得到明确拒绝 | **合法输出**：这本身就是 G 的自认缺料/边界证据，正常入料，可支撑"做不了"或"说不清（缺料）" |

判别口诀：**查不了是 error，查了没有是证据。**混同的代价是双向的——
把设施故障算成"说不清"会污染业务结论分布；把"资料没有"算成 error
会把最有价值的自认证据（judge.md §1"自认"）丢在管线外。

## 4. 对照例

两个现存机制逐字段过合同。它们今天都是隐式 provider（judge.md §8 第二条的
待剥离对象）；本节是显式化后的目标形态，不改变其现有行为。

### 4.1 key_live（client_search enhanced-rules key-index）

| 合同项 | 填写 |
|---|---|
| 供哪一路 | g（受治理规则物料 → 能力空间快照的组成部分） |
| value | 按稳定 key（field 名）检索出的规则条目（`retrieve_enhanced_rules_for_fields`，40 万字符大材料检索化，不整块注入） |
| provenance | 受治理源 YAML（`project.yaml` 声明的 `enhanced_rules` 源）+ key-index 切片定位（`impl/projects/client_search/draft/enhanced_rules_key_index.py`） |
| trust tier | `normative_rule`（受治理业务规则） |
| staleness | 定格于 manifest 钉住的源 revision/hash；源漂移按 `key_live` 消费模式自动吸收（重钉 hash + 审计，不阻断不重查） |
| 引用空间 | key-index 的稳定 key 集合（field 名 + 规则定位键 name）；citations 必须落在检索命中的键上 |
| 失败语义 | 源文件装载失败 / index 构建异常 → 运行期 error；**field 在索引中无条目 → 合法的"缺维度"证据**，不是失败 |

### 4.2 llm_probe（探针）

按 judge.md §5 的归位，llm_probe 机制作为 g 的 provider（探针探测得到的能力证据入 G）。
llm_probe 同时是一个被测项目（有自己的 d/e/g），两个身份互不混同。

| 合同项 | 填写 |
|---|---|
| 供哪一路 | g（对目标 HTTP 服务探测得到的能力证据） |
| value | 一次探测的能力证据：响应行为、错误形态（如 4xx 明确拒绝）、schema 线索 |
| provenance | 探针请求现场（url / method / 脱敏 headers / body）+ 响应原文，可回溯到该次探测 |
| trust tier | 默认 `current_behavior`（探到的是当下行为）；目标系统的明确拒绝声明经信任模型登记后可作 `inlive_boundary`；探针证据永不 `normative_rule`；目标自述"支持"不能自我背书为承载性证据（judge.md §7.4 防循环） |
| staleness | 定格于探测时刻（时间戳 + 目标版本线索）；无治理 revision，过期即重探（重算，非重验） |
| 引用空间 | 该次探测的请求/响应工件标识 |
| 失败语义 | 网络失败 / 重试耗尽 → 运行期 error，不得伪装成"探不到能力"；**探到明确拒绝 → 合法值**（能力证据：不支持） |

两例的对照点：key_live 的档位来自治理（`normative_rule`，漂移自动吸收），
llm_probe 的档位来自观测（`current_behavior`，过期重探）。同一份合同、
同一个 J，差异全部体现在三件套里——这正是 judge.md §1"J 不关心实参怎么来的"
在供料侧的对偶。

## 5. 调查产物：f / g 输出的缓存（薄记）

调查资料（investigation 产物）不是第四种 provider：它是 f / g 映射输出的
**物化缓存**，天然带 staleness（judge.md §5）。缓存过期 ≠ 判定逻辑变化，
按漂移协议路由重算/重验即可；缓存条目复用时，原有戳记照原样携带，
不因"从缓存读"而升档或洗掉出处。

## 6. 实施状态（judge.md §8 的落地进度）

- **g 路：已显式化。** `capability_provider` 装载合同 fail-fast
  （`impl/core/capability_carrier.py`，getattr 探测链已删）；`key_live` 剥离为
  显式 g-provider 实例（§4.1，`impl/core/provider_contract.py` 承载合同形状）。
- **d / e 路：无戳记合同。** judge.md §6 收窄后，d 不带戳记、e 默认无戳记
  （仅附加口径须带担保）。现有的隐式装载约定（live 模块的
  `REQUEST_SCHEMA` / `EXTRACT_OUTPUT_SCHEMA` 发现式 getattr、期望物料的
  项目内直连装载）不欠三件套——这不是延期，是合同本来就不覆盖。
- **e 路口径义务：无运行期执行机制（判后自报方案已证伪）。** §2.2 的 e 路
  输出规则是装配期合同：无担保口径不得进入期望集。判后自报落地
  （interpretations 字段 + 口径 gate）已于 2026-08-26 实施并当日回滚——
  "是否超字面"不可由产出口径的同一判定 LLM 自判，fail-closed 使诚实上报自毁
  （误杀数据与固化约束见 judge.md §8）。执行时机只能是 e-provider 显式拆分后
  的装载期校验，或 semantic_mapping authority 裁决；拆分仍是 judge.md §8 的
  刻意暂缓待办（收益条件 / 合同复用 / 不变量见该节）。
