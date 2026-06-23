## ADDED Requirements

### Requirement: Adapter contract-gates MUST inject into fulfillment_assessments, not directly modify verdict/score

`core/adapter.py:reconcile_equivalent_judge_result`、`projects/marketting-planning-intent/adapter.py:normalize_judge_result`、`projects/marketting-planning/adapter.py:normalize_judge_result`、`projects/QA/adapter.py:normalize_judge_result`（含 `_weak_quality_probe` / `_fallback_judge`）SHALL NOT 直接改写 `judge_result.verdict`、`judge_result.score`、`judge_result.confidence`、`judge_result.probability`，SHALL NOT 把 `fulfillment_assessments` 或 `overall_fulfillment` 清空。

业务检测逻辑（intent contract / semantic equivalence / mp contract / QA gold-answer probe）SHALL 保留——这是 rule.md "通过流程而非 prompt 实现边界判断"的体现。检测结果 SHALL 通过向 `fulfillment_assessments` 注入一项表达：

- 等价规则归一：`{"expectation_id": "semantic_equivalence_reconciled", "status": "fulfilled", "blocking": False, "evidence": ...}`，并把原 not_fulfilled assessment 的 status 改为 `fulfilled`（保留 evidence）。
- intent contract 失败/通过：`{"expectation_id": "intent_contract", "status": "not_fulfilled"|"fulfilled", "blocking": True, "evidence": ...}`。
- mp contract 不满足：`{"expectation_id": "mp_contract:<requirement>", "status": "not_fulfilled", "blocking": True, "evidence": ...}`。
- QA fallback：构造时只填 `fulfillment_assessments`，不填 verdict/score。

verdict / score SHALL 在 `core/adapter.py:ensure_fulfillment_judge_result` 末尾由 `_compute_verdict` / `_compute_score` 单点派生。

#### Scenario: 等价规则归一通过注入 assessment 表达

- **WHEN** `reconcile_equivalent_judge_result` 命中等价规则
- **THEN** `judge_result.fulfillment_assessments` MUST 包含一项 `expectation_id="semantic_equivalence_reconciled"` 且 `status="fulfilled"`
- **AND** `judge_result.verdict` MUST NOT 在该函数内被直接赋值
- **AND** verdict 由后续 `ensure_fulfillment_judge_result` 末尾的 `_compute_verdict` 派生

#### Scenario: intent contract 检测失败通过注入 assessment 表达

- **WHEN** intent normalize_judge_result 检测到 intent contract 不满足
- **THEN** `judge_result.fulfillment_assessments` MUST 追加一项 `expectation_id="intent_contract"`、`status="not_fulfilled"`、`blocking=True`
- **AND** 该函数 MUST NOT 出现 `judge_result.verdict = "incorrect"` 或 `judge_result.score = 0`
- **AND** `quality_flags` 可保留 `intent_contract_gate_failed` 标记

#### Scenario: 项目 normalize_judge_result 不清空 fulfillment_assessments

- **WHEN** 任意项目层 `normalize_judge_result` 被调用
- **THEN** MUST NOT 出现 `judge_result.fulfillment_assessments = []` 或 `judge_result.overall_fulfillment = {}`
- **AND** LLM 产出的原 assessments 与 contract-gate 注入项共存

### Requirement: ensure_fulfillment_judge_result MUST derive verdict/score via single-point compute, replacing derive_verdict_from_fulfillment

`core/adapter.py:ensure_fulfillment_judge_result` 末尾的 `judge_result.derive_verdict_from_fulfillment()` 调用 SHALL 被替换为 `judge_result.verdict = _compute_verdict(overall_status, judge_result.boundary_decision)` 与 `judge_result.score = _compute_score(judge_result.fulfillment_assessments)`。

`JudgeResult.derive_verdict_from_fulfillment` 方法 SHALL 从 `core/schema.py` 中删除（与 `_compute_verdict` 概念重叠）。

`core/adapter.py:apply_judge_consistency_gate` SHALL 整函数删除——`judge_verdict_diff_conflict`（LLM verdict 与 fulfillment 派生值不一致）在 LLM 不再输出 verdict 后天然消失；`uncertain_without_blocking_gaps` 在 boundary-aware `_compute_verdict` 下不可能出现。

#### Scenario: ensure_fulfillment_judge_result 使用 _compute_verdict

- **WHEN** `ensure_fulfillment_judge_result` 处理一个 `JudgeResult`
- **THEN** 末尾 MUST 调用 `_compute_verdict(overall_status, boundary_decision)` 赋给 `judge_result.verdict`
- **AND** MUST 调用 `_compute_score(fulfillment_assessments)` 赋给 `judge_result.score`
- **AND** MUST NOT 调用 `judge_result.derive_verdict_from_fulfillment()`（该方法已被删除）

#### Scenario: derive_verdict_from_fulfillment 与 apply_judge_consistency_gate 已删除

- **WHEN** 检查 `core/schema.py` 中 `JudgeResult` 类
- **THEN** MUST NOT 包含 `derive_verdict_from_fulfillment` 方法定义
- **AND** `core/adapter.py` MUST NOT 包含 `apply_judge_consistency_gate` 函数定义
- **AND** `reconcile_judge_result` 链路中 MUST NOT 调用 `apply_judge_consistency_gate`

### Requirement: client_search adapter MUST keep verdict-safe invariant

`projects/client_search/adapter.py:reconcile_judge_result` override SHALL 仅修改 `quality_flags` 与 `boundary_decision`，SHALL NOT 直接改写 `verdict` / `score` / `confidence` / `probability` / `fulfillment_assessments` / `overall_fulfillment`，SHALL 在末尾调用 `super().reconcile_judge_result()` 进入统一 ensure 链路。

#### Scenario: client_search override 仅触碰 quality_flags 与 boundary_decision

- **WHEN** 检查 `projects/client_search/adapter.py:reconcile_judge_result`
- **THEN** 函数体内 MUST NOT 出现 `judge_result.verdict = ...` / `judge_result.score = ...` / `judge_result.fulfillment_assessments = ...` / `judge_result.overall_fulfillment = ...` 赋值
- **AND** MUST 在末尾调用 `super().reconcile_judge_result(...)`
