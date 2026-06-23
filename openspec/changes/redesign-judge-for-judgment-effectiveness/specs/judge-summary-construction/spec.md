## ADDED Requirements

### Requirement: Judge summary MUST be constructed by aggregation over fulfillment_assessments, not by field-order probing

`server.py:_judge_display_reason`（5 段字段顺序探测：`wrong → missing → extra → reasoning_summary → ...`）SHALL 被删除。新函数 `_summary_from_fulfillment(judge_result)` SHALL 按两阶段构造：

1. **聚合阶段**：从 `judge.fulfillment_assessments` 筛选 `status in {not_fulfilled, partially_fulfilled, contested}`，提取 `{expectation_id, blocking, downstream_impact, within_evaluable_scope}`，按 `blocking=True` 优先排序。
2. **构造阶段**：根据 `verdict` 决定 summary 形态：
   - `verdict="correct"` → `"fulfilled · {N} expectations all met · {reasoning_summary?}"`
   - `verdict="incorrect"` → `"not_fulfilled · blocking=[{expectation_ids}] · {primary_downstream_impact}"`，附维度明细
   - `verdict="uncertain"` → `"uncertain · {verdict_derivation.why_verdict || judge_method}"`

`judge.wrong` / `judge.missing` / `judge.extra` 列表 SHALL NOT 作为 summary 主源；仅作为维度明细附加在聚合 summary 之后。

#### Scenario: 同一 not_fulfilled 状态产出形态一致的 summary

- **WHEN** 两个 case 都是 `verdict="incorrect"`、`overall_fulfillment.status="not_fulfilled"`、有 ≥1 个 blocking assessment
- **THEN** 两个 summary 的形态 MUST 一致（都以 `"not_fulfilled · blocking=[...]"` 开头）
- **AND** 即便其中一个 case 的 `judge.wrong` 列表为空，另一个非空，summary 形态依然一致

#### Scenario: gap 缺识别字段时不再产出零信息字面值

- **WHEN** `judge.wrong` 包含一个 dict，但 `error_type` / `expected_fragment` / `expected` / `actual_fragment` / `actual` 全部为空
- **THEN** summary 构造阶段 MUST 跳过该 gap，使用 `fulfillment_assessments` 聚合作为 summary 主源
- **AND** 不再出现 `"wrong: gap"` 字面值（`_gap_reason` 函数已删除）

#### Scenario: 优先使用 blocking 维度作为 summary 主源

- **WHEN** `fulfillment_assessments` 中同时存在 blocking=True 和 blocking=False 的 not_fulfilled 项
- **THEN** 聚合阶段 MUST 把 blocking=True 的 expectation_id 列在 summary 主体
- **AND** blocking=False 的项作为附加维度明细放在后面

### Requirement: Judge summary MUST surface degradation flags from quality_flags

当 `JudgeResult.quality_flags` 包含 `"llm_call_failed"` 或 `"self_check_failed"` 时，`_summary_from_fulfillment` 产出的 summary MUST 在头部以 `[<flag>] ` 前缀显式标注降级类型，便于运营/前端识别。

不引入 transient/permanent 失败分类（judge-effective-judgment spec 已锁定单一失败路径）。

#### Scenario: llm_call_failed 在 summary 头部标注

- **WHEN** `JudgeResult.quality_flags` 包含 `"llm_call_failed"`
- **THEN** summary MUST 以 `"[llm_call_failed] "` 前缀开头
- **AND** 后续聚合内容仍按 verdict 形态构造（uncertain 时引用 `verdict_derivation.why_verdict`）

#### Scenario: self_check_failed 在 summary 头部标注

- **WHEN** `JudgeResult.quality_flags` 包含 `"self_check_failed"`
- **THEN** summary MUST 以 `"[self_check_failed] "` 前缀开头
- **AND** summary 主体引用 `verdict_derivation.why_verdict` 描述具体不一致

### Requirement: Compact judge_summary MUST carry aggregation-derived fields, not field-probe outputs

`server.py:_compact_summaries` 产出的 `judge_summary` dict SHALL 把按字段顺序探测的旧逻辑替换为按聚合结果填充的字段。具体：

- `reason` 字段 MUST 来自 `_summary_from_fulfillment` 的输出文本，而不是旧版 `_judge_display_reason` 按字段顺序探测的结果。
- 新增 `primary_failure_dimensions: list[dict]` 字段，包含聚合阶段抽出的失败维度结构化数据（每条至少含 `expectation_id`、`blocking`、`status`、`downstream_impact`）；前端可据此渲染明细而无需再解析 `reason` 文本。
- `reason_source` 字段取值更新为：`"aggregated_fulfillment"`（聚合主源）、`"degradation_marker"`（降级标记前缀）、`"reasoning_summary"`（无聚合源时回退）、`"execution_error"`（trace/run 异常）。旧取值 `"judge_wrong"` / `"judge_missing"` / `"judge_extra"` SHALL 被移除。

#### Scenario: judge_summary.primary_failure_dimensions 暴露结构化维度

- **WHEN** judge 产出 `verdict="incorrect"`、≥2 个 not_fulfilled assessments
- **THEN** `judge_summary.primary_failure_dimensions` MUST 是非空 list
- **AND** 每条 MUST 含 `expectation_id`、`blocking`、`status`、`downstream_impact` 至少四个字段

#### Scenario: reason_source 反映聚合来源

- **WHEN** judge 产出正常 incorrect verdict（无降级标记）
- **THEN** `judge_summary.reason_source` MUST 是 `"aggregated_fulfillment"`
- **AND** 不再是旧版的 `"judge_wrong"` / `"judge_missing"` / `"judge_extra"`
