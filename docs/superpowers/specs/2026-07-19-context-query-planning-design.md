# 通用 Context 查询规划与候选覆盖设计

日期：2026-07-19

## 1. 背景

当前 Context 骨架已经实现：

- `ContextUnitRecord` 注册、持久化和向量索引；
- Run 级 Policy、角色隔离和预算；
- `search_context_units(queries)` 多查询搜索；
- Search 与 Load 分离；
- Load 时再次鉴权和内容预算控制。

大语料实验表明，直接用完整复合任务做少量宽泛向量查询不可靠。在 835 个通用 ContextUnit 中，完成任务所需的关键规则真实存在，但可能因其他高频语义占据候选而排到数百名之后。

该问题不是某个项目或业务字段的特例，而是通用的复合任务检索问题：一个任务通常包含多个彼此独立的信息需求，单一向量查询无法稳定覆盖所有需求。

## 2. 目标

在不引入项目业务概念、不扩张 Context 公共 schema 的前提下，使任意使用 Context 的 Agent 能够：

1. 使用 LLM 将当前任务拆成多条原子化待检索项；
2. 一次向 Runtime 提交多条查询；
3. 由 Runtime 确定性保证不同查询之间的候选多样性；
4. 清楚记录每条查询召回了哪些候选、最终加载了哪些单元；
5. 区分规划缺失、召回缺失、选择缺失和使用失败；
6. 保持 Context Adapter 只负责知识注册，不理解消费方业务任务。

## 3. 非目标

本次不：

- 将 client_search、Judge、candidate output、字段条件或日期规则写入公共 Context 层；
- 为待检索项新增公共领域 schema；
- 在 Context Runtime 内强制增加一次独立 LLM 调用；
- 修改 `ContextUnit` 或 `ContextUnitRecord`；
- 自动把 Planner 的推测当作业务事实；
- 接入现有 Mock、Judge、Attribute、Check 生产链；
- 修改任何项目 Adapter 或项目知识源；
- 通过无限提高 top-k 解决召回问题。

## 4. 职责边界

### 4.1 Context Adapter

Context Adapter 继续只负责：

- 从公共协议、项目配置或项目动态对象构造 `ContextUnitRecord`；
- 为单元生成可检索的 `name + description`；
- 设置 scope、roles、unit_type、source_type、status 和 tags；
- 调用统一注册入口。

Adapter 不接收当前任务，不生成检索项，不判断消费方需要什么知识。

### 4.2 Agent / LLM

使用 Context 的 Agent 负责：

- 理解自己的当前任务；
- 在 Search 前把任务拆成多个独立信息需求；
- 将这些信息需求作为 `queries: list[str]` 一次提交；
- 根据候选的 name、description 和匹配关系选择要加载的 ID；
- 只把加载后的 ContextUnit 内容作为上下文证据。

### 4.3 Context Runtime

Runtime 负责：

- 查询数量、候选数量和加载数量预算；
- 权限预过滤；
- 每条查询独立检索；
- 跨查询去重和覆盖优先的候选合并；
- Search 不返回 content；
- Load 二次鉴权；
- 记录查询到候选、候选到加载的完整调试链路。

Runtime 不理解查询的业务含义，也不判断哪些查询在语义上“正确”。

## 5. 通用运行链路

```text
任意角色的当前任务
  -> LLM 生成原子化 queries[]
  -> search_context_units(queries)
  -> Runtime 对每条 query 独立检索
  -> 覆盖优先合并候选
  -> 返回 id/name/description/matched_queries
  -> LLM 选择 unit ids
  -> load_context_units(ids)
  -> Agent 使用加载内容完成原任务
```

该链路不引入新的公共对象。检索项、候选和覆盖信息都是一次 Run 内的瞬时数据或 debug metadata。

## 6. 查询规划约定

公共工具说明提供以下通用约定：

1. 不要默认把完整复杂任务作为唯一查询；
2. 先识别完成任务所需的独立信息需求；
3. 每条查询只表达一个主要信息需求；
4. 每条查询应当能够脱离其他查询独立理解；
5. 对任务中含义不明确、存在隐含约束或需要规则确认的部分分别生成查询；
6. 必要时可以使用同义词、别名或假设性表达扩展查询；
7. 合并语义重复的查询；
8. 查询数量不得超过 Policy 的 query limit；
9. 查询文本中的推测不构成证据；最终判断只能依赖加载后的 ContextUnit 或其他权威输入。

第一版继续使用现有接口：

```python
search_context_units(queries: Sequence[str], top_k_per_query: int | None = None)
```

不新增 `ContextQuery`、`RetrievalPlan` 等公共 schema。

## 7. 候选覆盖算法

### 7.1 查询规范化

Runtime 对输入 queries：

- 去除首尾空白；
- 丢弃空字符串；
- 按首次出现顺序去重；
- 在搜索前检查 query limit；
- debug 中只记录规范化后的有效查询。

### 7.2 每查询独立检索

每条查询在同一 Policy 过滤范围内独立生成 embedding 和 Top-K 候选。单条查询最多返回 `top_k_per_query` 条内部候选。

### 7.3 覆盖优先合并

候选选择分两阶段：

1. **覆盖阶段**：按查询输入顺序，为每条有结果的查询选择其尚未被其他查询占用的最高排名候选；
2. **补充阶段**：剩余预算按跨查询 RRF、原始相似度和稳定 ID 顺序补充。

同一单元可以匹配多条查询，只占一个候选位，并记录全部 `matched_queries`。

若有结果的查询数量超过 candidate limit，Runtime 必须抛出明确的 `ContextBudgetError`，提示调用方减少查询或调整 Policy；不得静默丢弃部分查询的候选覆盖。

### 7.4 返回顺序

Search 返回顺序以覆盖选择顺序为主：

- 首先返回每条查询的覆盖候选；
- 然后返回补充候选。

不得在覆盖选择后再次仅按全局相似度重排，从而掩盖查询与候选之间的对应关系。

每个候选继续只返回：

```json
{
  "id": "...",
  "name": "...",
  "description": "...",
  "matched_queries": ["..."]
}
```

不返回 content、治理字段、内部相似度或 embedding。

## 8. Debug 与效果诊断

`ContextRun.debug_snapshot()` 在现有字段基础上增加：

```json
{
  "context_debug": {
    "search_queries": [],
    "query_candidate_coverage": {
      "query text": ["unit-id-1", "unit-id-2"]
    },
    "candidate_ids": [],
    "loaded_ids": []
  }
}
```

其中：

- `search_queries`：规范化后的实际查询；
- `query_candidate_coverage`：本次所有 Search 调用累计的 query 到返回候选映射；
- `candidate_ids`：Run 中出现过的候选；
- `loaded_ids`：实际加载的单元。

诊断规则：

1. 任务所需的信息没有对应 query：规划缺失；
2. query 存在但 coverage 为空：召回缺失；
3. coverage 中有正确候选但未加载：选择缺失；
4. 正确单元已加载但最终结果错误：上下文使用或模型能力问题。

Planner 查询文本本身不得记录为证据引用。

## 9. 工具接口说明

`GuardedContextTools.search_context_units` 保持签名兼容，但增加明确 docstring，说明：

- `queries` 应由模型先拆成多个原子化信息需求；
- 推荐一次提交全部已识别需求；
- 查询是假设和发现手段，不是权威事实；
- Search 只返回候选描述，必须显式 Load 才能使用完整内容。

提供可复用的通用 Context 使用说明常量或函数，供未来 Agno 角色接入时加入工具说明或角色指令。该说明不得包含任何项目或业务 case 文本。

## 10. 兼容性

- `ContextUnit`、`ContextUnitRecord` 不变；
- Adapter 接口不变；
- Search 和 Load 的函数签名不变；
- 单查询调用仍然合法；
- 原有权限、内容预算和 Load 行为不变；
- 新增错误只发生在“有结果查询数量超过候选预算、无法保证覆盖”的情况；
- 骨架仍默认关闭且不自动接入任何项目。

## 11. 测试设计

### 11.1 单元测试

增加或调整测试覆盖：

1. 查询去空、去重并保持顺序；
2. 多查询至少各保留一个可用候选；
3. 同一单元匹配多条查询时去重并保留全部 `matched_queries`；
4. 覆盖候选排在补充候选之前；
5. 有结果查询数超过 candidate limit 时明确失败；
6. debug 正确记录 query 到 candidate 的覆盖；
7. Search 结果仍不泄露 content、score 或治理字段；
8. 单查询和现有 Load 行为保持兼容。

### 11.2 大语料回归

继续使用自动生成的 835 个通用 ContextUnit，不添加 case 专属单元。

比较：

- 单一完整任务查询；
- LLM 生成的原子化多查询。

固定：

- 相同语料；
- 相同 Policy；
- 相同 candidate/load 总预算；
- 不在查询中加入历史 Judge 结论；
- 不使用手工指定的目标 ContextUnit ID。

重点指标：

- 完成任务所需关键 ContextUnit 是否进入候选；
- 每个 LLM 检索项是否获得候选覆盖；
- 关键证据召回率；
- 正向 case 是否出现退化；
- 加载字符数和单元数量。

业务 case 仅作为回归样本，不进入公共实现。

## 12. 实施范围

预计只修改通用骨架文件：

- `impl/core/context/runtime.py`：查询规范化、覆盖优先合并、debug coverage；
- `impl/core/context/tools.py`：通用规划说明和工具契约；
- `tests/test_context_runtime.py`：Runtime 覆盖和兼容性测试；
- 必要时新增独立的 Context planning contract 测试文件。

不修改：

- `impl/projects/**`；
- `impl/data/context_store/**`；
- 现有 Judge、Mock、Attribute、Check；
- 项目配置和项目 Adapter；
- `ContextUnit`、`ContextUnitRecord`。

## 13. 完成标准

满足以下条件后，该改造可视为完成：

1. Agent 可通过现有 Search 工具提交多条原子查询；
2. Runtime 在预算允许时为每条有结果查询保留至少一个候选；
3. 无法覆盖时明确失败而非静默丢失；
4. debug 可定位规划、召回、选择和使用阶段；
5. 所有 Context 骨架测试通过；
6. 835 单元回归中，原先因复合查询沉底的关键规则进入有限候选；
7. 没有新增业务特化逻辑或公共领域 schema；
8. 没有接入任何现有项目运行链。
