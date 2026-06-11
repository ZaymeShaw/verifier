# 20260611 judge/attribute 机制对齐与 application boundary 审核

## 背景

对比 `llm_attribution_server.py` 里的旧 judge/attribute 机制后，本次优化聚焦两个差异：

1. 旧 judge 只做正确性判定，不把归因、历史状态、HTTP 状态或外部不可用当作 verdict 依据。
2. 旧 attribute 只在 judge 判定失败后做当前 case 的链路定位，并要求 evidence chain、breakpoint proof、analysis_quality，不把不可验证假设伪装成已确认根因。

`review.md` 最新要求指出：`client_search` 的下游不可用应由 application agent 先分析并决定边界，后续 judge/attribute/project 逻辑应避开下游验证相关判断，不应每次重复强调下游不可用。

## 发现的问题

当前实现已有 `application_boundary` 概念，但仍存在边界信息使用方式不清的问题：

- `client_search` adapter 在 `reconcile_judge_result()` 中把下游不可用作为 `judge.evidence` 追加，导致 judge 结果展示层容易反复强调外部依赖不可用。
- attribute context 将 `application_boundary` 放进 `chain_nodes_to_check`，使 attribute agent 容易把“已排除在本次 scope 外的下游验证”当作可归因链路节点。
- 协议虽提到 application boundary，但没有明确说明“排除范围只作为边界元信息，不应重复进入 judge evidence 或归因根因”。

这些问题不是某个样本的过拟合，而是机制源头的边界传递方式不够清晰。

## 修改

### `impl/projects/client_search/adapter.py`

- 在 `project_fields` 中一次性写入 `application_boundary`，由 application adapter 在进入 judge/attribute 前完成边界判定。
- `build_judge_context()` 继续传递 `application_boundary`，并明确 judge 只在 `application_boundary.judge_scope` 内评估。
- `build_attribute_context()` 调整链路节点：
  - 当 `judge_scope=parser_condition_semantics_only` 时，不再把下游结果集验证放入 `chain_nodes_to_check`。
  - 只在 `judge_scope=parser_and_result_set` 时加入 `downstream_result_set` 节点。
  - `application_boundary` 单独作为范围约束传入，不作为 root-cause 链路节点。
- `reconcile_judge_result()` 对下游不可用只写入 `boundary_decision.application_boundary` 和 `application_boundary_parser_only` flag，不再追加到 `judge.evidence`。

### `impl/core/attribute.py`

- 强化 attribute agent 系统提示：
  - 优先使用项目提供的 `chain_nodes_to_check`。
  - 如果 `project_attribute_context.application_boundary` 已排除外部依赖，不要把该外部依赖当作根因或反复要求验证。
  - 归因聚焦当前 scope 内的可控 parser/model/config/code 证据。

### `impl/protocols/judge_protocol.md`

- 明确 application boundary 元信息应放在 `boundary_decision`，不应在每个 verdict 中作为重复 evidence，除非边界本身就是被评估输出。

### `impl/protocols/attribute_protocol.md`

- 明确 project adapter 可以把已排除的外部依赖从 `chain_nodes` 中省略，只作为 boundary metadata 暴露。

### `impl/core/check.py`

- 增加检查：当下游 unavailable/skipped 时，`application_boundary` 应保留在 `boundary_decision`，不应重复作为 judge evidence。

### `impl/core/judge.py`

- 增加 score/confidence/probability 的 0-1 归一，避免 LLM 返回 100 分制导致 check 失败。

## check.md 审核结论

- 机制源头：通过 adapter 的 `project_fields.application_boundary` 在 application 阶段一次性决定范围，符合“先由 application agent 分析下游当前不可用”的要求。
- 协议一致性：judge/attribute 协议均补充 boundary metadata 的使用方式，避免项目实现和通用 agent 语义分裂。
- 避免过拟合：未针对具体 query 写规则；修改的是边界传播、chain node 选择和协议说明。
- 结果可追踪：`boundary_decision.application_boundary` 保留完整范围信息；`judge.evidence` 不再重复携带下游不可用。
- 归因有效性：attribute 只分析当前 judge scope 内的可控链路；排除的外部依赖不会污染 root cause。

## 验证

执行：

```bash
python -m compileall -q impl
```

通过。

执行 client_search smoke：

```python
from impl.core.pipeline import run_chain
run = run_chain('client_search', {'query': '45岁女性保费10万以上'}, mock=False)
```

结果：

```text
trace_status= ok
downstream= unavailable
application_boundary= {'downstream_result_set_available': False, 'downstream_status': 'unavailable', 'judge_scope': 'parser_condition_semantics_only', 'result_set_verified': False, ...}
judge= correct 1.0
judge_flags= ['application_boundary_parser_only']
judge_evidence_has_boundary= False
attribute_method= judge_correct_no_failure
check= True []
```

结论：当前下游不可用由 application boundary 一次性约束，judge/attribute 不再重复把它作为判定或归因核心，check 通过。
