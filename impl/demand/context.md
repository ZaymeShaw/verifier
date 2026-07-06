# 上下文工程管理

> 来源需求：`demand/context.md`。本文档是落实方案 + 实现记录。

## 0. 目标与预算

核心是上下文资源分配：给定预算，如何分配上下文以最大化信息密度、最小化有效信息损失。

- judge 预算：~40k chars
- attribute 预算：~80k chars

三条铁律（来自需求）：
1. 排除冗余无用的信息
2. 实现动态加载
3. 常驻 prompt 信息不允许放大文档；大文档只能按需动态加载或压缩

约束：尽量不要遗漏有效信息。

工具分层（来自需求）：
- 协议通用工具 → `impl/tools/`
- 项目专属工具 → `impl/projects/<project>/tools/`
- 加载实现按协议/项目专属区分

## 1. 当前问题分析（结合 algorithm.md §3/§4 + 实际代码）

### 1.1 judge 上下文

**a) 常驻 prompt 偏大且含项目范式泄漏（违反铁律 3）**
- `judge.py` system prompt 把 `evaluation / judge_boundary / judge_standard` 三个文档全量塞进常驻 prompt。
- 之前还把 client_search 的"字段-操作符-值核对 / 语义等价 / 口语映射 / 增强正则"写进通用 system prompt（已修：改为仅当项目提供 capability_manifest 时才注入）。
- 仍未解决：三个文档全量常驻，QA/marketing 这类小文档项目浪费不大，但 client_search 的 `judge_standard`(judge.md) 可能很大，撑爆 40k 预算。

**b) judge_context 字段无契约，构建了不消费（违反铁律 1 + 数据/代码不同步）**
- 4 个项目 `build_judge_context` 返回的 key 各不相同（见下表）。
- 核心 judge 的 `_extract_compact_*` 只认 `capability_manifest / semantic_equivalence_rules / value_mappings / enhanced_rules / critical_intent_dimensions`。
- QA 的 `score_dimensions/error_taxonomy`、marketing 的 `stage_rules/expected_stage/expected_path_types/expected_cards`、client_search 的 `client_search_judge_basis/boundary_usage/judge_governance/field_patterns/external_boundary_sources` → 构建了但 judge 不消费，是死字段。

| 项目 | judge_context 实际 key | judge 消费 |
|---|---|---|
| QA | project_type, reference_contract, score_dimensions, error_taxonomy, application_boundary | application_boundary, reference_contract |
| client_search | semantic_equivalence_rules, field_patterns, application_boundary, judge_governance, condition_comparison, client_search_judge_basis, boundary_usage, external_boundary_sources, capability_manifest, value_mappings, enhanced_rules | capability_manifest, semantic_equivalence_rules, value_mappings, enhanced_rules, application_boundary |
| marketing | project_type, reference_contract, output_summary, application_boundary, expected_stage, expected_path_types, expected_cards, stage_rules | reference_contract, application_boundary |
| intent | project_type, reference_contract, expected_intent, application_boundary, critical_intent_dimensions | reference_contract, application_boundary, expected_intent, critical_intent_dimensions |

**c) build_intent_frame 与 build_judge_context 字段重复（数据不同步）**
- client_search `build_intent_frame` 把 `semantic_equivalence_rules/field_patterns/condition_comparison/capability_manifest` 又从 context 拷了一遍。
- 同一份数据在 context 和 intent_frame 存两份，改一处漏一处。

**d) critical_intent_dimensions 两个来源**
- `build_intent_frame` 返回一份，`build_judge_context` 也可能返回一份；judge 只从 context 取。

### 1.2 attribute 上下文

**a) 源码无差别加载（违反铁律 2，algorithm.md §6.7 已列为待优化）**
- `_load_source_code_evidence` 对最多 30 个 `.py` 文件 + 项目文档无差别加载，单文件截断 64KB。
- 应按 judge 输出的 `failure_stage/failure_category` 选择性加载相关文件子集。

**b) attribute_context 与 judge_context 字段重叠**
- `application_boundary` 在两个 context 都构建。

## 2. 优化方案

### 2.1 judge 上下文契约化（解决 1.1b/c/d）

在 `ProjectAdapter` 基类定义 `build_judge_context` 的标准返回结构（dataclass `JudgeContext`），各项目只填自己有的字段：

```python
@dataclass
class JudgeContext:
    # 通用（所有项目都填）
    application_boundary: Dict = {}
    reference_contract: Dict = {}
    critical_intent_dimensions: List[str] = []
    expected_intent: Optional[str] = None
    # 结构化字段项目可选（仅 client_search 类项目填）
    capability_manifest: Dict = {}
    semantic_equivalence_rules: Dict = {}
    value_mappings: Dict = {}
    enhanced_rules: Dict = {}
```

- 各项目 adapter 返回这个结构，不再自由加 key。
- 删掉 judge 不消费的死字段：`score_dimensions/error_taxonomy/stage_rules/expected_stage/expected_path_types/expected_cards/client_search_judge_basis/boundary_usage/judge_governance/field_patterns/external_boundary_sources`。
  - 其中确有价值的（如 marketing 的 expected_stage/expected_cards）挪到 `judge_standard` 文档，由 `load_project_document` 注入，不进 context。
- `critical_intent_dimensions` 单一来源：只在 `build_judge_context` 返回，`build_intent_frame` 不再重复。
- `build_intent_frame` 不再拷贝 judge_context 字段，只放 intent 推导字段。

### 2.2 judge prompt 分层：常驻协议 + 动态项目（解决 1.1a，落实铁律 3）

把 system prompt 分三层，控制常驻体量：

| 层 | 内容 | 加载方式 | 预算 |
|---|---|---|---|
| L0 常驻协议 | intent→expectations→fulfillment 协议、输出词表、verdict 单点派生说明 | 硬编码在 judge.py | ~8k |
| L1 项目常驻 | evaluation / judge_boundary / judge_standard 文档 | `load_project_document`，**全量但要求小** | ~10-15k |
| L2 case 动态 | compact capability_manifest/rules（按 trace 字段裁剪）+ run_trace | 动态裁剪 | 剩余预算 |

约束：
- L1 文档要求"小而精"，超出预算的项目必须自己压缩（不靠核心代码截断）。
- L2 已经是按 trace 字段动态裁剪（`_extract_compact_*`），保留。

### 2.3 attribute 源码按需加载（解决 1.2a，落实铁律 2）

按 algorithm.md §6.7 方向：
- 加载前先读 judge 的 `failure_stage`/`causal_category`，按类别选相关源码文件子集。
- 文件优先级排序（marketing-intent 已有 `_prioritized_ext_repo_files` 范式，抽到通用）。
- 总量按 80k 预算硬上限，超限按优先级截断并记录 `truncated` 标记。

### 2.4 context 去重（解决 1.2b）

`application_boundary` 等共享字段：attribute_context 不再自己构建，直接从 judge_context 透传。

## 3. 信息密度损失预估

| 优化项 | 损失评估 |
|---|---|
| 删除 judge 死字段 | 0 损失（本来就没人消费） |
| judge_context 契约化 | 0 损失（字段还在，只是统一来源） |
| L1 文档要求项目自压缩 | 低风险：项目若压缩不当可能丢细节，但有 L2 动态 compact 兜底 |
| attribute 源码按需加载 | 中风险：按 failure_stage 选文件可能漏掉无关但实际相关的文件；用优先级排序 + 80k 上限 + truncated 标记缓解，且 truncated 标记让 LLM 知道有缺失 |
| intent_frame 不再拷 context | 0 损失（单一来源） |

## 4. 实现步骤

1. 定义 `JudgeContext` dataclass + 基类 `build_judge_context` 返回它
2. 4 个项目 adapter 改返回 `JudgeContext`，删死字段
3. `build_intent_frame` 去掉 context 字段拷贝
4. judge.py 改为从 `JudgeContext` 字段读（而非自由 dict key）
5. attribute 源码按需加载（failure_stage 驱动）
6. attribute_context 透传 judge_context 共享字段
7. 跑 api-check 验证

## 4b. 已实现（2026-07-01 上下文工程优化）

### 4b.1 P0: judge run_trace 去掉 live_result 重复

`judge.py` 中 `to_dict(trace)` 把整个 `RunTrace`（含 `live_result`）全量序列化到
user prompt，而 `live_result.raw_response` / `extracted_output` / `normalized_request` /
`execution_trace` 与 `RunTrace` 顶层同名字段完全一致（146/150 traces 100% 重复）。

**量化**：150 条 judge trace 平均 37.5% 的 user prompt 是 live_result 冗余。

**修复**：新增 `_judge_run_trace_view(trace)`，只保留 judge 真实消费的 14 个字段
（input / normalized_request / raw_response / extracted_output / execution_trace /
evidence_refs / application_boundary / reference_contract / scenario / status / error
+ trace_id / project_id / case_id），去掉 live_result / state_history /
gate_decisions / transition_decisions / conversation_* 等不需要的字段。

**效果**：run_trace 体积平均减少 48-56%，client_search judge 从 57.6KB → ~38KB（进 40k 预算）。

### 4b.2 P1: 精简 run_trace 空字段 + required_output 模板上移

- `_JUDGE_OUTPUT_SCHEMA` / `_ATTRIBUTE_OUTPUT_SCHEMA` 上移到模块级常量，不再在
  每条 trace 的 user prompt 中内联构建（代码整洁，不变更语义）。
- 15 个始终为空的字段（runtime_logs / stop_reason / turn_index 等）随 live_result
  一起从 `_judge_run_trace_view` 中自然剔除。

### 4b.3 P2: 精简 attribute 系统 prompt + chain_nodes 去重

- attribute 系统 prompt 中关于 divergence_analysis 的 4 处重复指令（"禁止调用
  search_source_file" / "不需要调用" / "可以不执行 probe" / "不需要再执行任何 probe"）
  精简为 1 处清晰的条件说明，省去 1263 个字符。
- `chain_nodes_to_check` 的 node evidence 不再内联 `trace.normalized_request` /
  `extracted_output` / `matched_patterns` 原始数据，改为 `evidence_ref` 指针
  （如 `"run_trace.extracted_output"`），省去 53% 的重复（8.3KB avg）。

### 4b.4 P3: marketting-planning SSE raw_response 压缩

marketting-planning 的 `raw_response.raw` 是 51KB 的 SSE 事件流，judge 不需要。
新增 `_compact_raw_response_for_judge()` 函数，对 raw_response 做 4KB 截断
（保留首尾 + truncated 标记），让 marketting-planning judge 从 96KB → ~23KB。

### 4b.5 P4: 测试验证

- tests/test_runtime_config.py: 4/4 passed
- tests/test_project_yaml_template.py: 3/3 passed
- hooks/schema/test_occam_schema_roles.py: 4/4 passed
- hooks/fixture-check 和 hooks/api-check 的失败在 clean tree 上已存在，非本次变更引入

## 5. review 待办（来自 demand/context.md）

- `impl/tools/field_retrieval.py` 需处理
- 了解 agno 实现，核心信息放 `impl/docs/`（用 gh skill）
