# Judge / Attribute / Mock 算法实现机制方案

本文档描述当前 verifier 评测系统中三个核心 trace 型算法的实现机制：Mock（模拟数据构建）、Judge（输出正确性判定）、Attribute（问题归因）。以下说明其架构设计、执行流程、扩展方式和当前已知局限，后续持续优化。

---

## 1. 整体架构：声明式状态机 + 多执行体流水线

三个算法不独立运行，而是挂载在统一的 **Trace 状态机** 上，通过 `pipeline.run_chain()` 串成一条完整的单 case 执行链路。

### 1.1 状态机

定义在 `impl/core/state_machine.py` 的 `DEFAULT_TRACE_GRAPH`，共 13 个状态：

```
prepare_trace → mock_or_input → execute_or_capture → collect_evidence
    → judge_plan → judge_compare → judge_critic
    → attribute_plan → attribute_probe → attribute_critic
    → finalize → [completed | incomplete_or_human_review]
```

每个状态可以挂载：
- **executor**：确定性函数或 LLM 子代理调用
- **gates**：质量门，状态执行后校验输出是否满足进入下一状态的条件
- **transitions**：条件路由，包括 `always`、`gate_failed_recoverable`、`gate_failed_unrecoverable`、`judge_requires_attribute`、`stop`

关键质量门包括：
| 门 ID | 作用 | 触发位置 |
|-------|------|----------|
| `trace_available` | 确认 execute 产出非空 trace | execute_or_capture |
| `judge_intent_present` | 确认意图已重建 | judge_compare |
| `judge_expected_actual` | 确认 expected/actual 可比较 | judge_compare |
| `judge_verdict_derivation` | 确认判决可追溯到证据 | judge_compare |
| `judge_boundary` | 确认边界决策已应用 | judge_critic |
| `contradiction_free` | 确认 verdict 和 reasoning 不自相矛盾 | judge_critic, finalize |
| `unsupported_claims_absent` | 确认无凭空断言 | judge_critic, finalize |
| `attribute_judge_gap` | 确认 judge 有可归因的差距 | attribute_plan |
| `probe_available_or_incomplete` | 确认归因探测已完成 | attribute_probe |
| `attribute_evidence` | 确认归因证据链存在 | attribute_critic |
| `attribute_chain_coverage` | 确认链路节点覆盖 | attribute_critic |
| `attribute_patch_direction` | 确认有修改方向 | attribute_critic |
| `finalization_ready` | 确认所有输出可最终化 | finalize |

### 1.2 执行体调度

`TraceStateMachineRunner` 支持三种执行模式：
- **单执行体**：直接调用注册的 executor 函数
- **顺序累积**（`sequential_accumulation`）：多个 executor_ref 按序调用
- **并行协议**（`parallel_agreement`）：多执行体并行调用，合并结果并检测矛盾

### 1.3 项目扩展

每个项目通过 `ProjectAdapter` 可以：
- 替换/扩展 trace 图：`trace_state_graph()` → `extend_default_trace_graph()`
- 注入项目专有执行体：`state_executors()` 返回 `{executor_id: callable}`
- 注入证据收集器：`collect_state_evidence()` 在 `collect_evidence` 状态被调用

---

## 2. Mock 算法：用例数据构建

### 2.1 用例来源

Mock 数据通过 `pipeline.mock_cases(project_id)` 获取，调用链：

```
pipeline.mock_cases(project_id)
  → load_adapter(spec).build_mock_cases()
    → 读取 impl/data/<project>/mock_cases.json
    → 返回标准化 case 列表
```

### 2.2 用例结构

每个 mock case 遵循统一协议：

```json
{
  "id": "唯一标识",
  "scenario": "业务场景分类",
  "input": {"query": "用户输入/意图"},
  "output": {"模拟的业务系统输出"},
  "reference": {"expected_*": "预期正确输出"},
  "metadata": {"business_axis": "业务维度", "expected_error_type": "预期错误类型"},
  "expected_quality": "correct|incorrect|uncertain",
  "source": "data_mock_seed",
  "status": "pending"
}
```

关键约束：
- `output` 是可选的，不提供时会走 live 模式调用真实业务 API
- `reference` 定义预期正确输出，不提供时由 judge agent 自动生成
- `expected_quality` 声明此 case 的期望判决结果，用于回归测试验证 judge 一致性

### 2.3 两种执行模式

在 `pipeline.live_run()` 中自动判断：

1. **provided 模式**（offline）：case 已提供 `output`/`raw_response`/`response` → 直接构造 RunTrace，不调真实 API
2. **live 模式**（online）：case 无预置输出 → 通过 `adapter.call_or_prepare()` 调用真实业务服务

两种模式产出的 `RunTrace` 经过完全相同的 judge/attribute/cluster/check 链路，保证评估口径一致。

### 2.4 交互式多轮 Mock

通过 `NormalizedCaseInteraction` 协议支持：
- `single_run`：单轮输入输出
- `static_turns`：预定义多轮对话
- `interactive_intent`：由 adapter 实现 `run_interactive()` 实时模拟多轮用户交互

### 2.5 用例池管理

前端通过 `/api/mock_cases` 加载用例到候选区，支持：
- 全选/取消全选
- 按场景/状态过滤
- 自定义 JSON 导入
- 命名保存为持久化用例池（`case_pool.save_case_pool`，自动过滤瞬态字段）

---

## 3. Judge 算法：业务预期达成评估

### 3.1 总体流程

```
pipeline.judge(project_id, trace)
  → judge_trace(spec, trace, project_judge_context)  ← 步骤 A
  → adapter.reconcile_judge_result(trace, result)      ← 步骤 B
```

**步骤 A**（LLM 判定，`impl/core/judge.py:judge_trace`）：

1. 加载项目的评判标准文档、边界标准文档、源文档
2. 构造 system prompt，要求 LLM：
   - 重建当前 query 的核心意图与下游 consumer contract
   - 将意图分解为可评估的 business_expectations
   - 逐项比较 expected-vs-actual，产出 fulfillment_assessments
   - 检查字段语义、操作符兼容性、值归一化、逻辑关系
   - 输出 overall_fulfillment，并从 fulfillment 派生兼容 verdict
3. 调用 LLM（deepseek-v4-pro，max thinking 模式）
4. 解析 JSON 输出为 `JudgeResult`

**步骤 B**（项目侧协调，`impl/core/adapter.py:reconcile_judge_result`）：

项目 adapter 对 LLM 产出的 `JudgeResult` 进行三层后处理：

| 步骤 | 方法 | 作用 |
|------|------|------|
| B1 | `normalize_judge_result()` | 项目专有归一化与确定性合约检测：合约不满足时**注入** `fulfillment_assessments`（`status=not_fulfilled, blocking=true`），不得直接写 `verdict`/`score` |
| B2 | `reconcile_equivalent_judge_result()` | 语义等价规则反向纠偏：LLM 判失败但 actual 与 expected 经项目等效规则归一后一致 → 把对应的 `not_fulfilled` 翻成 `fulfilled` 并附 `semantic_equivalence_reconciled` 标记 |
| B3 | `ensure_fulfillment_judge_result()` | 单点派生：从最终的 `fulfillment_assessments` 调 `_compute_verdict(overall_status, boundary_decision)` 与 `_compute_score(fulfillment_assessments)` 写回 `verdict`、`score`、`overall_fulfillment` |

### 3.2 Fulfillment 与单点派生的 Verdict

Judge 的中心产物是：

- `consumer_contract`：当前输出服务的下游消费者和业务合约
- `business_expectations`：从用户意图、case reference、项目文档和边界中重建出的业务预期
- `fulfillment_assessments`：每个 expectation 的 `fulfilled / partially_fulfilled / not_fulfilled / not_evaluable / contested` 状态、证据和 downstream impact
- `overall_fulfillment`：聚合状态和 blocking expectations

`verdict` 与 `score` 由 `impl/core/judge.py` 中的 `_compute_verdict` / `_compute_score` 单点派生，LLM 不输出这两个字段。映射规则：`fulfilled → correct`；`not_fulfilled` 且 boundary 内 → `incorrect`；`partially_fulfilled / not_evaluable / contested / boundary 外` → `uncertain`。`score = (fulfilled + 0.5 * partially_fulfilled) / |evaluable assessments|`，无可评估项时为 `None`。后续 Attribute、Cluster、Frontend 的主逻辑不再以 verdict 作为概念中心。

### 3.3 边界决策

在 `judge_trace` 中，LLM 输出的 `boundary_decision` 直接进入 `_compute_verdict`：

- 当 `overall_fulfillment.status == "not_fulfilled"` 且 `boundary_decision.within_evaluable_scope == false` 时，`_compute_verdict` 返回 `uncertain` 而非 `incorrect`。
- 边界标准从项目的 `judge_boundary-template.md` 加载，由用户填写该项目有什么不可控的外部依赖。
- 不再有独立的 `apply_boundary_reconciliation` 阶段——边界判定完全归一到单点派生。

### 3.3 语义等价规则

项目在 `project.yaml` 的 `frontend_extensions.semantic_equivalence_rules` 中声明：

- `equivalent_condition_forms`：字段/操作符/值的等价形式（如 MATCH → CONTAINS 单值）
- `operator_compatibility`：操作符兼容性（如 MATCH 与 CONTAINS 在单枚举值下等价）
- `equivalent_fields`：字段等效（如 familyAge → familyBirthday）

这些规则在 B2 阶段用于纠偏 LLM 对表示差异的误判，使 judge 关注业务语义而非表面形态。

### 3.4 Intent Contract Gate（marketting-planning-intent 专有）

intent 项目的 `normalize_judge_result` 实现了确定性合约门：

1. 检查 `actual.intent` 是否匹配 `reference.intent`
2. 检查 `required_slots` 是否都存在
3. 检查 `allow_fallback` 约束
4. 检查 `confidence` 是否达到 `min_confidence`

- 合约失败 → 注入 `fulfillment_assessments`（`expectation_id=intent_contract, status=not_fulfilled, blocking=true`），加 `intent_contract_gate_failed` 质量旗标与 `verdict_derivation.contract_gate` 证据；**不再** 直接写 `verdict=incorrect, score=0`，最终由 B3 单点派生给出 `incorrect / 0.0`。
- 合约通过 → 注入 `fulfillment_assessments`（`status=fulfilled, blocking=true`），加 `intent_contract_gate_passed` 旗标；其余 expectation 的 LLM 判断仍正常计入，B3 按聚合状态派生最终 verdict/score。

### 3.5 Reference 生成

当 case 未提供 reference 时，judge 自动生成：

1. 优先取 case 自带的 `reference` 字段
2. 其次取 `expected_intent`
3. 最后从 LLM 的 `expected` 输出中重建

生成的 reference 会与 actual 对齐形状（按 `_align_reference_shape`），确保前端 Reference 面板和 Output 面板格式一致。

---

## 4. Attribute 算法：Expectation 因果归因

### 4.1 总体流程

```
pipeline.attribute(project_id, trace, judge_result)
  → attribute_failure(spec, trace, judge, project_attribute_context)  ← 步骤 C
  → adapter.normalize_attribute_result(trace, judge, result)          ← 步骤 D
```

**步骤 C**（LLM 归因，`impl/core/attribute.py:attribute_failure`）：

1. 如果所有 `fulfillment_assessments` 均为 `fulfilled` → 生成 `no_issue` 的 expectation attribution，作为正向聚合证据
2. 否则加载项目归因文档，构造 system prompt，要求 LLM：
   - 针对每个需要归因的 business expectation 重建 expected-vs-actual gap 或 contested reason
   - 按 `chain_nodes_to_check` 或 `execution_trace` 逐段标记 normal/suspicious/failed/not_verified
   - 找出 earliest_divergence（最早偏离点）
   - 给出 expectation_attributions、probe_results、verification_steps、improvement_direction
   - 不编造路径、函数、行号、日志或测试结果
3. 调用 LLM（deepseek-v4-pro，max thinking 模式）

**步骤 D**（归一化，`impl/core/attribute.py:normalize_attribute_trace_result`）：

归因结果经过质量门检查，分为三种状态：

| 状态 | 条件 | 含义 |
|------|------|------|
| `supported_root_cause` | 有 query/actual/expected 证据 + 有链路证据 + 有代码/配置/文档证据 + quality gate 通过 | 根因充分，可直接指导修改 |
| `insufficient_evidence` | 有凭空断言（unsupported_claims）或 suspected_locations 无证据支撑 | 证据不足，清空疑似位置 |
| `next_verification_step` | 有当前 gap 和链路证据，但缺少代码/配置层面的具体定位 | 需要下一步验证 |

### 4.2 归因质量标准

归因必须满足（来自 `attribute_quality_gate`）：

1. **围绕当前 query**：所有字段、条件、修复方向必须来自当前 case 的证据链路
2. **可核验证据链**：`chain_nodes` 逐节点标记状态和证据
3. **最早偏离点**：指出链路中哪个节点开始与预期不符
4. **疑似位置**：仅在代码/配置/文档证据支撑时填写，否则标记为假设或清空
5. **具体修改方案**：`patch_direction` 描述最小源码修改，非一次性输出/展示补丁
6. **业务影响**：说明该问题对业务的实际影响

### 4.3 项目专有归因上下文 + 源码级证据

项目 adapter 通过 `build_attribute_context()` 注入：
- `chain_nodes_to_check`：需要逐段检查的链路节点列表
- `application_boundary`：应用边界范围信息
- `attribute_quality_gate`：项目级质量门标准
- `source_config_paths`：指向业务项目源码/配置文件的路径映射

**源码加载机制**（`_load_source_code_evidence`）：

在 LLM 调用前，归因引擎自动加载三层源码证据：

1. **adapter 指定的 source_config_paths**：包括外部业务仓库的 `.py` 文件、项目自身源码文档
2. **项目 `source_*` 前缀文档**：从 `project.yaml.documents` 中自动读取（如 `source_prompt`、`source_field_definitions`）
3. **项目 adapter.py 自身**：归因时可以引用 adapter 的实现逻辑

源码内容作为 `source_code_evidence` 字段直接送入 LLM prompt，使 LLM 能够：
- 引用真实文件路径、函数名、配置键
- 对比实际 prompt 模板与预期行为
- 定位字段映射/枚举值/解析逻辑的具体代码位置
- 在 `suspected_locations` 中填写源码中真实存在的路径/函数/配置键

这使得 attribute 输出与 judge 输出有本质区别：judge 只看 RunTrace 判断对错，attribute 在此基础上还读取源码定位具体原因。

### 4.4 状态机不完整时的归因兜底

当状态机因某些原因未完成 `run_attribution_probes`（如提前进入 `incomplete_or_human_review`），`pipeline.incomplete_state_attribute_result()` 会生成一个兜底 attribution：
- expectation attribution 标记为 `not_evaluable` 或 `insufficient_evidence`
- incomplete_reason 明确说明状态机未完成
- verification_steps 引导检查 state_history 和 gate_decisions

---

## 5. 三算法串联关系

```
Mock 用例池
  │
  ├── case 有预置 output? ──→ provided 模式：直接构造 RunTrace
  │
  └── case 无预置 output? ──→ live 模式：调业务 API → RunTrace
                                    │
                                    ▼
                              Judge fulfillment 评估
                    (business expectations + 边界 + 等效规则)
                                    │
                                    ▼
                         Expectation Attribution
                 (fulfilled→no_issue；gap/contested→因果归因)
                                    │
                                    ▼
                         Cluster fulfillment/causal 聚合
                                          │
                                          ▼
                                    Check 审核
```

## 6. 当前局限与已知待优化点

1. **Judge 单 prompt 深度不足**：当前 judge 是一次 LLM 调用完成全部判断，没有多轮推理/自我纠偏机制。理想方案是将 judge 拆为 judge_plan → judge_compare → judge_critic 三步，每步独立调用 LLM 并经过质量门。

2. **Attribute 仍以 LLM 为主，缺少确定性本地探测**：已实现源码加载机制使 attribute 能引用真实文件路径和函数名，但尚未实现 `import` 业务代码后调用具体函数进行确定性验证（如实际执行解析函数看输出是否与 trace 一致）。下一步应在此之上补齐 `local_verifications` 的自动执行。

3. **Mock 数据覆盖度**：当前 mock 用例以手工编写的 seed 数据为主，缺少基于生产日志/真实用户 query 的自动生成机制。

4. **状态机流控**：`DEFAULT_TRACE_GRAPH` 定义了完整的 13 状态，但当前 `pipeline.run_chain()` 中的 executor 实现大部分是单函数直通（如 `compare_judge` 一步完成 plan+compare+critic），状态机的分步设计未被充分利用。

5. **语义等价规则表达力**：当前仅支持等价值映射，不支持范围等价（如年龄区间与生日的双向转换）、复合条件等价等更复杂场景。

6. **跨项目复用**：intent contract gate 当前硬编码在 `marketting-planning-intent/adapter.py` 中，尚未抽象为通用协议供其他项目复用。

7. **属性源码加载量大**：当前对最多 30 个 `.py` 文件 + 项目文档无差别加载，单文件截断 64KB。后续可按 judge 输出的 `failure_stage`/`failure_category` 选择性与归因相关的文件子集，减少 token 消耗。
