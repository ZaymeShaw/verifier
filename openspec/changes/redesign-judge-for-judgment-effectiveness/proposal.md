## Why

issue2 指出现有算法 agent "按 schema 跑通"而非"按如何做出有效判断"设计。重读 `demand/demand.md` + `demand/rule.md` + `demand/algorithm.md`（信息密度原则）+ `demand/context.md`（judge 40k 预算）+ `judge_protocol.md` 后发现根因：

协议明确说 `verdict` 是 derived（`judge_protocol.md:22-23,68`），但当前代码让 LLM 同时产出 `verdict` 与 `fulfillment_assessments`，verdict 改写补丁因此散布在**三层 5 处**：

1. `judge.py:_normalize_fulfillment` — derived status ↔ verdict 静默改写
2. `judge.py:apply_boundary_reconciliation` — boundary → verdict + 清空 missing/wrong/extra
3. `core/adapter.py:reconcile_equivalent_judge_result` — 等价规则归一后 `incorrect→correct` + 清空 fulfillment_assessments + 改 score/confidence/probability
4. `core/adapter.py:ensure_fulfillment_judge_result` — 末尾调 `derive_verdict_from_fulfillment()` 派生
5. `projects/<intent|mp|QA>/adapter.py:normalize_judge_result` — 项目层契约门强制 verdict + score

5 处共存 = 三套并行的 verdict 真理来源（LLM 输出 / 后置规则 / 项目契约门）。issue2 的两个现象都是这个问题的下游表现：
- `report.md` 5 个 client_search `uncertain` case：源自 `judge.py:586-624` LLM 失败时伪造 25 字段假 result。
- `report.md` 3 种 `not_fulfilled` summary 形态：源自 `server.py:_judge_display_reason` 按 `wrong→missing→extra→reasoning_summary→...` 顺序探测。

按 demand.md / rule.md / algorithm.md（信息密度 + 奥卡姆剃刀）+ context.md（预算约束）做减法做统一：把 verdict 改为**单点计算**（`_compute_verdict`），让 5 处改写在不同层各司其职，但都不直接改 verdict——adapter 层把 contract-gate 结果**注入** `fulfillment_assessments`，让 `_compute_verdict` 自然派生。整个补丁体系失去存在理由：alias 表、status canonicalization、verdict 静默改写、boundary post-hoc rewrite、`derive_verdict_from_fulfillment` 等都可以直接删除或归并。

非 judge 的 22 个 finding 留给 issue3-6。

## What Changes

**净删除（约 320 行，覆盖 judge.py / core/adapter.py / projects/<3>/adapter.py / server.py）**：
- **BREAKING** 删除 `_FULFILLMENT_STATUS_CANON`、`_FULFILLMENT_STATUS_ALIASES`、`_canonicalize_fulfillment_status`（`judge.py:237-279`）。词表锁定在 prompt 里，LLM 偏离由 self-check 检测，不做防御性归一。
- **BREAKING** 删除 `_normalize_fulfillment`（`judge.py:294-344`）整个函数。status 不归一，verdict 不改写。
- **BREAKING** 删除 `apply_boundary_reconciliation`（`judge.py:172-193`）——`evaluation_boundary` 字段补齐合并到 judge_trace 末尾的 5 行直接赋值。
- **BREAKING** 删除 `_fallback_evaluation_boundary`、`_extract_boundary_value`、`_line_after_label`（`judge.py:123-158`）。`load_judge_boundary_standard` 改为只读 `spec.frontend_extensions.implementation_standard.judge_boundary` 结构化字段；缺失则报错。
- **BREAKING** 删除 LLM 失败时构造的 25 字段假 `JudgeResult`（`judge.py:586-624`）。失败返回最小化 result：空 `intent_model`/`business_expectations`/`fulfillment_assessments`，`needs_human_review=True`，`quality_flags=["llm_call_failed"]`。
- **BREAKING** 删除 `required_output["verdict"]`、`required_output["score"]`、`required_output["confidence"]`、`required_output["probability"]` 从 LLM 输出 schema（`judge.py:540-543`）。LLM 不再产出这些；统一从 fulfillment_assessments 计算。
- **BREAKING** 删除 `_score_from_verdict`（`judge.py:213-223`）。score 改为从 `fulfillment_assessments` 加权平均。
- **BREAKING** 删除 `server.py:_judge_display_reason` 5 段探测（`server.py:59-83`）和 `_gap_reason`（`server.py:40-56`）。
- **BREAKING** 删除 `JudgeResult.derive_verdict_from_fulfillment`（`impl/core/schema.py` 中该方法）——与 `_compute_verdict` 概念重叠，统一由后者取代。
- **BREAKING** 改造 `core/adapter.py:reconcile_equivalent_judge_result`（255-292 行）：删除 `judge_result.verdict = "correct"`、`score/confidence/probability` 改写与 `fulfillment_assessments = []` 清空分支；改为向 `fulfillment_assessments` 注入 `{"expectation_id": "semantic_equivalence_reconciled", "status": "fulfilled", "blocking": False, "evidence": ...}`，并同步把原 not_fulfilled assessment 的 status 改为 `fulfilled`（保留 evidence），让 overall_fulfillment.status 在 ensure 阶段重新派生。
- **BREAKING** 删除 `core/adapter.py:apply_judge_consistency_gate`（294-309 行）：`judge_verdict_diff_conflict` / `uncertain_without_blocking_gaps` 两种检测都已被 `_judge_self_check`（检测 overall_fulfillment.status 与 assessments 派生值不一致）覆盖。函数整体删除。
- **BREAKING** 改造 `core/adapter.py:ensure_fulfillment_judge_result`（约 380-418 行）：末尾的 `judge_result.derive_verdict_from_fulfillment()` 调用替换为 `judge_result.verdict = _compute_verdict(overall_status, boundary_decision)` 与 `judge_result.score = _compute_score(fulfillment_assessments)`；其它字段重建（assessment_count、blocking_expectations）保留。
- **BREAKING** 改造 `projects/marketting-planning-intent/adapter.py:normalize_judge_result`（310-361 行）：删除 `judge_result.verdict = "incorrect"/"correct"`、`score = 0/1`、`fulfillment_assessments = []`、`overall_fulfillment = {}` 等直接 verdict/score 改写；保留 intent contract 确定性检测逻辑（这是 rule.md 要求的"通过流程而非 prompt 实现边界判断"），改为向 `fulfillment_assessments` 注入 `{"expectation_id": "intent_contract", "status": "fulfilled"|"not_fulfilled", "blocking": True, "evidence": ...}`，让 verdict 在 ensure 阶段由 `_compute_verdict` 派生。
- **BREAKING** 改造 `projects/marketting-planning/adapter.py:normalize_judge_result`（214-255 行）：删除 `judge_result.verdict = "incorrect"`、`score = min(...)`；保留 stage/path/fallback 确定性检测，改为向 `fulfillment_assessments` 注入 `{"expectation_id": "mp_contract:<requirement>", "status": "not_fulfilled", "blocking": True, "evidence": ...}`。
- **BREAKING** 改造 `projects/QA/adapter.py:normalize_judge_result`（185-209 行）+ `_weak_quality_probe` / `_fallback_judge`：这些路径直接构造 fallback `JudgeResult` 并赋 verdict；改造为构造时只填 fulfillment_assessments（不填 verdict/score），由 `_compute_verdict` 在末尾派生。
- 删除 prompt 中 verdict 相关引导段（"verdict 只是派生兼容摘要"等表述与新规则统一）。

**新增（约 120 行，全部为单点函数）**：
- `_compute_verdict(overall_status, boundary_decision) -> str`：唯一 verdict 推导点。`fulfilled→correct`，`not_fulfilled→incorrect`（除非 `boundary_decision.within_evaluable_scope=false` 且无 `evaluable_errors`，则 `uncertain`），其它→`uncertain`。
- `_compute_score(fulfillment_assessments) -> Optional[float]`：blocking 全 fulfilled→1，blocking 全 not_fulfilled→0，混合→fulfilled 占比。
- `_judge_self_check(data, business_expectations) -> list[dict]`：检测 (a) status 词表偏离 5 项、(b) `_derive_overall_status` vs `data["overall_fulfillment"]["status"]`、(c) `expectation_id` 引用完整性、(d) `within_evaluable_scope=false` 与 `evaluable_errors` 非空的矛盾。
- `_summary_from_fulfillment(judge_result) -> dict`：`server.py` 中替代 `_judge_display_reason`，summary 从 `fulfillment_assessments` 聚合 + verdict + quality_flags 构造，单一源。
- adapter 层 `ensure_fulfillment_judge_result` 末尾的 verdict/score 派生调用（替换 `derive_verdict_from_fulfillment`）。

**执行流（统一后）**：
```
LLM (无 verdict 输出) → judge_trace 内 _judge_self_check (+1 次 re-prompt)
  → JudgeResult 只含 fulfillment 域字段（无 verdict）
  → adapter.reconcile_judge_result
      → normalize_judge_result (项目层契约门：注入 contract-gate assessment，不改 verdict)
      → reconcile_equivalent_judge_result (等价规则归一后注入 equivalence assessment，不改 verdict)
      → apply_judge_consistency_gate  ← 已删除
      → ensure_fulfillment_judge_result
          → 重建 overall_fulfillment.status / assessment_count / blocking_expectations
          → _compute_verdict(overall_status, boundary_decision) → verdict
          → _compute_score(fulfillment_assessments) → score
```

## Capabilities

### New Capabilities
- `judge-effective-judgment`：约束 judge 算法 agent 单一路径产出有效判断——LLM 只产 fulfillment 域字段，verdict/score 单点计算；失败时诚实最小化兜底；prompt 锁定词表，self-check 守住一致性；不做后置静默改写。
- `judge-summary-construction`：summary 由 `fulfillment_assessments` 单一源聚合构造，不按字段顺序探测；同一 fulfillment 状态产出形态一致。
- `judge-adapter-contract-gates`：项目层 / 通用层 contract-gate（intent contract / semantic equivalence / mp contract / QA fallback）通过向 `fulfillment_assessments` 注入 assessment 表达，禁止直接改写 verdict/score；verdict 由 `_compute_verdict` 在 adapter 链末尾统一派生。

### Modified Capabilities
（无；`openspec/specs/` 为空。）

## Impact

- 代码：
  - `impl/core/judge.py`（净减 ~250 行；删 6 个函数 + 1 个常量表 + 1 个 schema 字段；新增 3 个单点函数）
  - `impl/core/adapter.py`（删 `apply_judge_consistency_gate` + `derive_verdict_from_fulfillment` 调用；改造 `reconcile_equivalent_judge_result` 与 `ensure_fulfillment_judge_result`；净增/减 ~0）
  - `impl/core/schema.py`（删 `JudgeResult.derive_verdict_from_fulfillment` 方法）
  - `impl/projects/marketting-planning-intent/adapter.py`（改造 `normalize_judge_result`：verdict 改写 → assessment 注入）
  - `impl/projects/marketting-planning/adapter.py`（改造 `normalize_judge_result`：同上）
  - `impl/projects/QA/adapter.py`（改造 `normalize_judge_result` + `_weak_quality_probe` + `_fallback_judge`：fallback 不再赋 verdict）
  - `impl/projects/client_search/adapter.py`（`reconcile_judge_result` override 不涉及 verdict 改写，仅 boundary/quality_flags，无需改造；但需验证 super 链路）
  - `impl/server.py`（删 `_judge_display_reason` + `_gap_reason`；新增 `_summary_from_fulfillment`）
  - `impl/core/llm_client.py`（无改动；现有 1 次 retry 复用）
- 协议：`impl/protocols/judge_protocol.md` 修改 verdict 字段说明（"由 _compute_verdict 单点推导，LLM 不再输出；adapter 层契约门通过注入 fulfillment_assessments 表达，不改 verdict"），新增 self-check 节、failure handling 节、contract gates 节，删除 `evaluation_boundary` 字段中"normalized before verdict reconciliation"的过时表述。
- 项目配置：4 个 check1 项目（QA/client_search/mp/mpi）已有 `implementation_standard.judge_boundary` 字段；本 change 不要求其它项目立刻补齐，但保留协议层校验——`load_judge_boundary_standard` 在缺失时报错（其它项目跑 judge 会失败直到补齐）。
- 下游消费方（attribute/check/frontend）：仍读 `judge.verdict` / `judge.score` 字段不变；这些字段语义未变，只是产出方式从"LLM 输出 + 后置改写"改为"代码计算"。`quality_flags=["self_check_failed", "llm_call_failed", "semantic_equivalence_reconciled", "intent_contract_gate_failed", "intent_contract_gate_passed", "mp_contract_mismatch"]` 等是新增/调整标记，下游识别由 issue3-6 处理；本 change 仅在 protocol 标注。前端 `judge_summary.reason_source` 取值从 `"judge_wrong"/"judge_missing"/"judge_extra"` 迁移到新词表（`aggregated_fulfillment` 等），可能需要前端同步（check.md 完整更新原则）。
- 验证：用 `tmp/20260618-185102/` 复现 5 个 client_search `uncertain` case 与 3 种 `not_fulfilled` summary，确认：(a) `uncertain` case 产出最小 honest result（不再 25 字段伪造）；(b) summary 形态统一；(c) verdict 与 fulfillment 永远一致（来自单点计算，含 adapter 层 contract-gate 路径）；(d) intent/mp/QA 项目 contract-gate 路径产出与改造前一致的 verdict（回归测试，确保只是改写位置变了、不是行为变了）。
