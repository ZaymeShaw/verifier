## ADDED Requirements

### Requirement: Judge LLM schema MUST NOT include verdict, score, confidence, or probability fields

`required_output` schema（`judge.py` 中 LLM user prompt 输出契约）SHALL NOT 包含 `verdict`、`score`、`confidence`、`probability` 四个字段。LLM 只产出 fulfillment 域字段（`intent_model`、`business_expectations`、`fulfillment_assessments`、`overall_fulfillment`、`boundary_decision`、`judge_method`、`reasoning_summary`、`verdict_derivation`）。

`verdict` 与 `score` MUST 由代码单点计算：`_compute_verdict(overall_status, boundary_decision)` 与 `_compute_score(fulfillment_assessments)`。下游消费方（attribute/check/frontend）读到的 `JudgeResult.verdict` / `JudgeResult.score` 字段语义不变，但产出方式从"LLM 输出 + 后置改写"变为"代码计算"。

#### Scenario: LLM schema 不包含 verdict

- **WHEN** 检查 `judge.py` 中 `required_output` dict 的 keys
- **THEN** keys 中 MUST NOT 包含 `"verdict"`、`"score"`、`"confidence"`、`"probability"`
- **AND** keys MUST 包含 `"fulfillment_assessments"`、`"overall_fulfillment"`、`"boundary_decision"`

#### Scenario: verdict 由 _compute_verdict 单点计算

- **WHEN** judge_trace 在 LLM 调用成功且 self-check 通过后构造 `JudgeResult`
- **THEN** `JudgeResult.verdict` MUST 来自 `_compute_verdict(overall_status, boundary_decision)` 的返回值
- **AND** `_compute_verdict` MUST 在 judge.py 中只有一处定义、被 `judge_trace` 唯一调用

#### Scenario: score 由 _compute_score 从 fulfillment 派生

- **WHEN** judge_trace 构造 `JudgeResult`
- **THEN** `JudgeResult.score` MUST 来自 `_compute_score(fulfillment_assessments)` 的返回值
- **AND** blocking expectations 全 fulfilled 时 score=1.0；全 not_fulfilled 时 score=0.0；混合时 score=fulfilled_count/blocking_count；无 blocking 时 score=None

### Requirement: _compute_verdict MUST honor boundary_decision when overall is not_fulfilled

`_compute_verdict(overall_status, boundary_decision)` SHALL 按以下规则推导 verdict：

- `overall_status="fulfilled"` → `"correct"`
- `overall_status="not_fulfilled"` 且 `boundary_decision.within_evaluable_scope=false` 且 `evaluable_errors=[]` → `"uncertain"`（失败原因仅来自 uncontrollable_limits）
- `overall_status="not_fulfilled"`（其它情况） → `"incorrect"`
- `overall_status` 为 `partially_fulfilled` / `not_evaluable` / `contested` / 缺失 → `"uncertain"`

#### Scenario: not_fulfilled + within_evaluable_scope=false + 无 evaluable_errors → uncertain

- **WHEN** `overall_status="not_fulfilled"`、`boundary_decision={"within_evaluable_scope": False, "uncontrollable_limits": [...], "evaluable_errors": []}`
- **THEN** `_compute_verdict` MUST 返回 `"uncertain"`

#### Scenario: not_fulfilled + within_evaluable_scope=false 但有 evaluable_errors → incorrect

- **WHEN** `overall_status="not_fulfilled"`、`boundary_decision={"within_evaluable_scope": False, "evaluable_errors": ["..."]}`
- **THEN** `_compute_verdict` MUST 返回 `"incorrect"`（存在可评估的错误，不能逃逸到 uncertain）

#### Scenario: fulfilled → correct

- **WHEN** `overall_status="fulfilled"`
- **THEN** `_compute_verdict` MUST 返回 `"correct"`，无视 boundary_decision

### Requirement: Judge MUST self-check fulfillment consistency before computing verdict

judge_trace 在 LLM 返回 `data` 后、调用 `_compute_verdict` 前，SHALL 调用 `_judge_self_check(data, business_expectations)` 检测以下不一致：

1. `_derive_overall_status(assessment_statuses)` 与 `data["overall_fulfillment"]["status"]` 不一致。
2. `fulfillment_assessments[*].expectation_id` 引用了 `business_expectations` 中不存在的 id（orphan assessment）。
3. `boundary_decision.within_evaluable_scope=false` 但 `evaluable_errors` 非空（schema 内矛盾）。
4. `fulfillment_assessments[*].status` 或 `overall_fulfillment.status` 不在 5 项词表 `{fulfilled, not_fulfilled, partially_fulfilled, not_evaluable, contested}` 内。

不一致非空时，judge MUST 触发**最多 1 次** re-prompt，把 inconsistencies 作为 user prompt 附加段反馈给 LLM，重新调用 `complete_json`。re-prompt 仍不一致时，judge MUST 在 `quality_flags` 加 `"self_check_failed"`、`needs_human_review=True`，**保留 LLM 的 fulfillment 数据原值**（禁止静默改写），然后继续走 `_compute_verdict`。

#### Scenario: 一致时直接计算 verdict

- **WHEN** LLM 返回的 fulfillment 内部一致（overall 与 assessments 派生值一致、expectation_id 引用合法、status 在词表内）
- **THEN** judge MUST 跳过 re-prompt，直接调用 `_compute_verdict`
- **AND** `quality_flags` 不包含 `"self_check_failed"`

#### Scenario: 不一致时 re-prompt 一次

- **WHEN** LLM 返回 `overall_fulfillment.status="fulfilled"` 但 assessments 中存在 status="not_fulfilled" 的 blocking 项
- **THEN** judge MUST 调用一次 re-prompt，user prompt 附加 inconsistencies 描述
- **AND** 如果 re-prompt 后一致，则用 re-prompt 结果继续走 `_compute_verdict`

#### Scenario: re-prompt 后仍不一致

- **WHEN** re-prompt 后 inconsistencies 仍非空
- **THEN** judge MUST 保留 re-prompt 的 fulfillment 原值，不静默改写
- **AND** `quality_flags` MUST 包含 `"self_check_failed"`
- **AND** `needs_human_review` MUST 为 `True`
- **AND** `verdict_derivation.why_verdict` MUST 说明 self-check 失败的具体不一致项
- **AND** `_compute_verdict` 仍基于这份保留的 fulfillment 数据计算 verdict（即使内部矛盾，verdict 也来自单点计算）

#### Scenario: status 词表偏离触发 re-prompt

- **WHEN** LLM 返回 `fulfillment_assessments[0].status="failed"`（不在 5 项词表内）
- **THEN** `_judge_self_check` MUST 把它作为 inconsistency 报告
- **AND** 触发 re-prompt；不做防御性归一（无 alias 表兜底）

### Requirement: Judge MUST return minimal honest result on LLM call failure

LLM 调用失败（含 `complete_json` 内部 retry 用尽）时，judge SHALL 返回最小化 honest `JudgeResult`，**不得**伪造 25 字段假 result，**不得**假装 `uncertain` 来自有效判断。

最小化 result MUST 满足：
- `intent_model={}`、`business_expectations=[]`、`fulfillment_assessments=[]`
- `overall_fulfillment={"status": "not_evaluable", "assessment_count": 0, "blocking_expectations": []}`
- `boundary_decision={}`
- `verdict_derivation={"why_verdict": "LLM 调用失败，未做出算法判断"}`
- `verdict="uncertain"`（由 `_compute_verdict("not_evaluable", {})` 单点推导）
- `score=None`
- `needs_human_review=True`
- `quality_flags=["llm_call_failed"]`
- `judge_method="llm_call_failed"`
- `wrong=[]`、`missing=[]`、`extra=[]`

不引入 transient/permanent 失败分类（无消费方）。不引入 rule-based fallback 二次降级（reference 比对是另一套判断算法，不在 judge 范畴）。失败路径 SHALL 唯一。

#### Scenario: LLM retry 用尽返回 honest empty result

- **WHEN** `LlmClient.complete_json` 返回 `{"error": "..."}`（含所有失败子类）
- **THEN** judge MUST 返回 `JudgeResult` 满足上述最小化 schema
- **AND** `quality_flags` MUST 等于 `["llm_call_failed"]`（恰好 1 项，无其它分类标记）

#### Scenario: 失败 result 不含伪造的 fulfillment 数据

- **WHEN** judge 因 LLM 失败返回 result
- **THEN** `intent_model`、`business_expectations`、`fulfillment_assessments` MUST 全部为空
- **AND** 不得包含从 trace 推断或 placeholder 拼接的内容

### Requirement: Judge MUST load evaluation_boundary from project structured fields, not free-text grep

`load_judge_boundary_standard` SHALL 只读 `spec.frontend_extensions.implementation_standard.judge_boundary` 结构化字段（包含 `document`、`gate` 等子字段，project.yaml 已定义）。缺失时 MUST 抛 `ValueError`，不得回退到 free-text 标签 grep。

`_fallback_evaluation_boundary`、`_extract_boundary_value`、`_line_after_label` 三个函数 SHALL 被删除。`apply_boundary_reconciliation` 函数 SHALL 被删除——`evaluation_boundary` 字段补齐合并到 `judge_trace` 末尾的直接赋值。

`check1.py` 涉及的 4 个项目（client_search、QA、marketting-planning、marketting-planning-intent）已具备 `implementation_standard.judge_boundary` 结构化字段；其它项目需要补齐才能跑 judge（显式错误，不再隐式降级）。

#### Scenario: 项目具备结构化 judge_boundary 字段时正常加载

- **WHEN** `spec.frontend_extensions.implementation_standard.judge_boundary` 存在且非空
- **THEN** `load_judge_boundary_standard` MUST 直接返回该结构
- **AND** 不调用任何 grep / label-extraction 逻辑

#### Scenario: 项目缺失 judge_boundary 字段时抛错

- **WHEN** `spec.frontend_extensions.implementation_standard.judge_boundary` 缺失或空
- **THEN** `load_judge_boundary_standard` MUST 抛 `ValueError`，错误信息包含 `spec.id` 与缺失字段路径
- **AND** judge 调用方（`judge_trace`）不捕获该错误——让上层 pipeline 显式失败

#### Scenario: apply_boundary_reconciliation 函数已删除

- **WHEN** 检查 `judge.py` 中是否存在 `apply_boundary_reconciliation` 函数定义
- **THEN** MUST 不存在（已被删除）
- **AND** `evaluation_boundary` 字段补齐由 `judge_trace` 末尾直接赋值完成（不超过 5 行代码）

### Requirement: Judge prompt MUST lock fulfillment status vocabulary to 5 values

`required_output["fulfillment_assessments"][0]["status"]` 与 `required_output["overall_fulfillment"]["status"]` SHALL 在 schema 中显式列出 5 个合法值用 `|` 分隔：`"fulfilled|not_fulfilled|partially_fulfilled|not_evaluable|contested"`。

system prompt SHALL 包含"## 输出词表"段，显式说明：(a) status 必须从 5 个值中选择、禁用同义词（如 failed/passed/incorrect/wrong/met/unmet）；(b) `boundary_decision.within_evaluable_scope=false` 必须满足"失败原因仅来自 uncontrollable_limits、不存在 evaluable_error"。

`_FULFILLMENT_STATUS_CANON`、`_FULFILLMENT_STATUS_ALIASES`、`_canonicalize_fulfillment_status`、`_normalize_fulfillment` 四个 symbol SHALL 被删除。LLM 偏离词表由 `_judge_self_check` 检测（见 self-check Requirement），不做防御性归一。

#### Scenario: schema 显式列出 5 项词表

- **WHEN** 检查 `judge.py` 中 `required_output["fulfillment_assessments"][0]["status"]` 字面值
- **THEN** MUST 等于字符串 `"fulfilled|not_fulfilled|partially_fulfilled|not_evaluable|contested"`
- **AND** `required_output["overall_fulfillment"]["status"]` 字面值 MUST 相同

#### Scenario: alias 表已删除

- **WHEN** 检查 `judge.py` 中是否存在 `_FULFILLMENT_STATUS_ALIASES` / `_canonicalize_fulfillment_status` / `_normalize_fulfillment`
- **THEN** MUST 全部不存在
- **AND** 任何对这些 symbol 的引用 MUST 被移除（编译/导入时不再可见）

#### Scenario: prompt 锁定词表段存在

- **WHEN** 检查 system prompt 文本
- **THEN** MUST 包含"## 输出词表"或等价节标题
- **AND** MUST 显式列出 5 项 status 词表
- **AND** MUST 显式说明 `within_evaluable_scope=false` 的判定规则

