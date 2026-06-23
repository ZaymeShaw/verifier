## Context

协议-代码错位：`judge_protocol.md:22-23,68` 明确说 `verdict` 是 derived，但当前实现让 verdict 改写散布在**三层 5 处**——

| # | 层 | 位置 | 行为 |
|---|---|---|---|
| 1 | judge.py | `_normalize_fulfillment` | derived status ↔ verdict 静默改写 |
| 2 | judge.py | `apply_boundary_reconciliation` | boundary → verdict + 清空 missing/wrong/extra |
| 3 | core/adapter.py | `reconcile_equivalent_judge_result` | 等价规则归一后 `incorrect→correct` + 清空 fulfillment_assessments + 改 score/confidence/probability |
| 4 | core/adapter.py | `ensure_fulfillment_judge_result` | 末尾调 `derive_verdict_from_fulfillment` 派生 |
| 5 | projects/<intent\|mp\|QA>/adapter.py | `normalize_judge_result` | 项目层契约门强制 verdict + score |

5 处共存 = 三套并行的 verdict 真理来源（LLM 输出 / 后置规则 / 项目契约门）。围绕这一错位，judge.py 维护着一整套后置补丁：`_FULFILLMENT_STATUS_ALIASES`（29 条同义词）、`_canonicalize_fulfillment_status`、`_normalize_fulfillment`、`apply_boundary_reconciliation`、`_fallback_evaluation_boundary`（prose 标签 grep）、`_score_from_verdict`（从被改写的 verdict 反推 score）。`server.py:_judge_display_reason` 的 5 段字段顺序探测是同一类问题的下游表现：summary 不是被构造的，是被按字段顺序读出来的，所以同一 `not_fulfilled` 状态可以产出 3 种形态。

下游 attribute/cluster/check 假设"`judge.verdict` 已被 normalize 过、一定一致"——这个假设在删除 silent rewrite 后必须靠"verdict 单点计算"真实成立。

**本 change 与 demand 文档的对齐**（即"做减法做统一"的依据）：
- `demand/algorithm.md`（信息密度 + 奥卡姆剃刀） → 删 5 处补丁、删 alias 表、删 prose grep、删 25 字段假 result，相同有效信息量下方案最简洁。
- `demand/context.md`（judge 40k 预算） → 删 LLM `verdict/score/confidence/probability` schema 字段、删假 25 字段 result，prompt + 输出体积下降；常驻 prompt 不放大、动态加载维持。
- `demand/rule.md`（"通过流程而非 prompt 实现边界判断"） → `_compute_verdict` 是代码流程；contract-gate 由项目 adapter 注入 `fulfillment_assessments` 而非靠 prompt 引导 LLM。
- `check.md`（完整更新原则、协议对齐、最简化、不仅改展示要改源头） → tasks 9 节包含前端 `reason_source` 词表迁移、协议同步、E2E 实测；改源头（移走 verdict 输出）而非加补丁掩盖矛盾。

本 change 是 issue2 的第一个 issue（judge + adapter 层 verdict 单点化）。issue3-6 处理 attribute/cluster/check/pipeline；mock 本 change 不动。

## Goals / Non-Goals

**Goals:**
- 把 `verdict` 从 LLM 输出移除，改为单点计算（`_compute_verdict` / `_compute_score`），让协议"verdict is derived"在代码层落地。
- 删除整套后置补丁：alias 表、status canonicalization、verdict 静默改写、boundary post-hoc rewrite、prose 标签 grep、5 段 summary 探测。一次减法，不再回头打补丁。
- 把 adapter 三层 5 处 verdict 改写统一为"contract-gate 通过注入 `fulfillment_assessments` 表达，verdict 在 `ensure_fulfillment_judge_result` 末尾由 `_compute_verdict` 单点派生"。**业务检测逻辑保留**（intent contract / semantic equivalence / mp contract / QA gold-answer probe），仅改"检测结果如何表达"。
- LLM 失败时返回最小化 honest result（空 fulfillment 域 + `needs_human_review=True` + `quality_flags=["llm_call_failed"]`），不伪造 25 字段假 result，不假装 `uncertain`。
- `boundary_decision` 与 `evaluation_boundary` 由 LLM 显式产出 / 现有 `implementation_standard.judge_boundary` 结构化字段直接读，不靠 free-text grep。
- summary 由 `fulfillment_assessments` 单一源构造，形态由 `verdict` 决定，杜绝按字段顺序探测。

**Non-Goals:**
- 不改 attribute/cluster/check 的算法逻辑（issue3-5）。
- 不改 pipeline.run_chain 的状态机和 batch representative 选择（issue6）。
- 不改 mock 用例生成（独立 issue）。
- 不改 adapter 层业务检测逻辑本身——intent contract 是否成立、等价规则是否命中、mp contract 是否满足、QA gold-answer 是否匹配，这些判断保留；本 change 只改"检测结果如何影响 verdict"（从直接改写改为注入 assessment）。
- 不引入 transient/permanent 失败分类、不引入 rule-based fallback 二次降级、不引入 judge_boundary.yaml sidecar——这些是上一版过度设计，本 change 全部剔除。
- 不重写整个 prompt 模板；只删 verdict/score/confidence/probability 输出 schema 段，加 status 词表锁定段。
- 不替换 LLM 客户端（`llm_client.py`）；现有 1 次 retry 行为复用。
- 不改下游 attribute/cluster/check 对 `judge.verdict` / `judge.score` 字段的读取契约——字段语义不变，只是产出方式从"LLM 输出 + 后置改写"改为"代码计算"；新 `quality_flags` 取值（`self_check_failed` 等）的下游识别留 issue3-6。

## Decisions

### D1. verdict 单点计算：LLM 只产 fulfillment 域，verdict 由代码推导

`judge_protocol.md:22-23,68` 说 verdict 是 derived，当前代码却让 LLM 输出 verdict。这是所有补丁的根因。

**决策**：
1. 从 `required_output` schema 删除 `verdict`、`score`、`confidence`、`probability` 四个字段。LLM 只产 `intent_model`、`business_expectations`、`fulfillment_assessments`、`overall_fulfillment`、`boundary_decision`、`judge_method`、`reasoning_summary`、`verdict_derivation` 等 fulfillment 域字段。
2. 新增 `_compute_verdict(overall_status, boundary_decision) -> str`：唯一 verdict 推导点。
   - `overall_status="fulfilled"` → `verdict="correct"`
   - `overall_status="not_fulfilled"` → `verdict="incorrect"`，**除非** `boundary_decision.within_evaluable_scope=false` 且 `evaluable_errors=[]`（失败原因仅来自 uncontrollable_limits），此时 `verdict="uncertain"`
   - 其它（`partially_fulfilled` / `not_evaluable` / `contested`）→ `verdict="uncertain"`
3. 新增 `_compute_score(fulfillment_assessments) -> Optional[float]`：
   - blocking expectations 全 fulfilled → `1.0`
   - blocking expectations 全 not_fulfilled → `0.0`
   - 混合 → `fulfilled_count / blocking_count`
   - 无 blocking → `None`（score 缺省）
4. 删除 `_score_from_verdict`（从被改写的 verdict 反推 score 的逻辑彻底消失）。

**为什么不做 transient/permanent 失败分类**：上一版 D1 引入 `error_class` 字段做失败分类，但失败分类本身不产生判断——它只是给降级阶梯贴标签。本 change 的失败路径只有一条（D3），分类信息没有消费方。

**为什么不做 rule-based fallback**：上一版 D2 降级 B 让 LLM 失败时用 reference 比对兜底。但 reference 比对是另一套判断算法，引入它等于在 judge 之外再维护一个 mini-judge；issue2 的诉求是"做有效判断"而非"做更多种判断"。LLM 失败时诚实返回 `needs_human_review=True` 比假装做了一个判断更符合 demand.md 的"评估业务服务输出是否 cover 用户需求"——评估不了就说评估不了。

### D2. self-check + 1 次 re-prompt：保留这一项

删除 `_normalize_fulfillment` 的 verdict 改写后，LLM 仍可能产出内部矛盾的 fulfillment 数据（如 `overall_fulfillment.status` 与 `fulfillment_assessments[*].status` 派生值不一致）。必须主动检测。

**决策**：在 `judge_trace` 拿到 LLM `data` 后、`_compute_verdict` 之前，调用 `_judge_self_check(data, business_expectations)`：

- 检测 (a)：`_derive_overall_status(assessments_statuses)` vs `data["overall_fulfillment"]["status"]`
- 检测 (b)：`fulfillment_assessments[*].expectation_id` 引用 `business_expectations` 中不存在的 id（orphan assessment）
- 检测 (c)：`boundary_decision.within_evaluable_scope=false` 但 `evaluable_errors` 非空（schema 内矛盾）

不一致非空时触发 **最多 1 次** re-prompt，把 inconsistencies 作为 user prompt 附加段反馈给 LLM，重新调用 `complete_json`。re-prompt 仍不一致时：保留 LLM 的 fulfillment 数据 + `quality_flags=["self_check_failed"]` + `needs_human_review=True`，然后继续走 `_compute_verdict`。

**为什么不静默改写**：静默改写让下游永远看不到矛盾，但矛盾本身是 judge 算法失效的信号；保留 + 标记才能让 issue3-5 的下游有机会识别。self_check_failed 标记让下游知道"这个 verdict 来自矛盾输入"。

**为什么最多 1 次而不是多次**：1 次覆盖 LLM 偶发错误；多次则是 prompt/schema 本身有问题的信号，此时再 re-prompt 也是浪费——直接标记 self_check_failed 让人工介入。

### D3. LLM 失败 → 最小化 honest result（单一失败路径）

`judge.py:586-624` 当前在 LLM 失败时构造 25 字段假 `JudgeResult`，假装做了判断（`verdict="uncertain"` + 假 intent_model + 假 fulfillment_assessments）。`tmp/20260618-185102/report.md` 的 5 个 client_search uncertain case 就源自这里。

**决策**：删除 25 字段假 result。LLM 失败时返回最小化 honest result：
- `intent_model={}`、`business_expectations=[]`、`fulfillment_assessments=[]`、`overall_fulfillment={"status": "not_evaluable", ...}`
- `boundary_decision={}`、`verdict_derivation={"why_verdict": "LLM 调用失败，未做出算法判断"}`
- `verdict="uncertain"`（由 `_compute_verdict("not_evaluable", {})` 单点推导）
- `score=None`
- `needs_human_review=True`
- `quality_flags=["llm_call_failed"]`
- `judge_method="llm_call_failed"`

**为什么单一路径不分 transient/permanent**：分类信息没有消费方（D1 已说明）。失败就是失败，运营看 `quality_flags=["llm_call_failed"]` + `needs_human_review=True` 即可决定是否重跑；不需要在 judge 层面给"transient"做自动 retry——`llm_client.complete_json` 内部已有 1 次 retry。

**为什么不引入降级 B（rule-based fallback）**：见 D1 的"为什么不做 rule-based fallback"。

### D4. boundary 从现有 `implementation_standard.judge_boundary` 结构化字段读，缺失报错

`_fallback_evaluation_boundary`（`judge.py:141-158`）对 `judge_boundary.md` 做 `_line_after_label(judge_boundary, "判题目标")` 等 prose 标签 grep，or-链 fallback。这是 free-text 解析补丁。

**决策**：
1. `load_judge_boundary_standard` 改为只读 `spec.frontend_extensions.implementation_standard.judge_boundary` 结构化字段（4 个 check1 项目已具备，见 `project.yaml`）；缺失则抛 `ValueError("project {spec.id} missing implementation_standard.judge_boundary")`。
2. 删除 `_fallback_evaluation_boundary`、`_extract_boundary_value`、`_line_after_label` 三个函数。
3. 删除 `apply_boundary_reconciliation` 中 verdict 改写 + missing/wrong/extra 清空分支（172-193 行的 verdict 相关逻辑）；`evaluation_boundary` 字段补齐合并到 `judge_trace` 末尾的 5 行直接赋值，整个 `apply_boundary_reconciliation` 函数删除。

**为什么不保留 grep fallback**：grep fallback 是"为了让缺失字段的项目也能跑"的补丁——但补丁让缺失显式错误变成隐式降级，违反 demand.md "应在协议中体现，分析系统是怎么样的来在协议范围内制定 judge/attribute 的 impl 或 impl/project 实现"。缺失就报错，让项目方显式补齐 `judge_boundary` 字段。

**为什么不引入 judge_boundary.yaml sidecar**：上一版 D5 提议新增 yaml sidecar。但 4 个 check1 项目的 `project.yaml` 已有 `implementation_standard.judge_boundary.{document, gate}` 结构化字段——已经有结构化数据载体，再新增 yaml 是重复。本 change 直接用现有字段，缺失报错。

### D5. summary 从 `fulfillment_assessments` 单一源构造

`server.py:_judge_display_reason`（59-83 行）按 `wrong → missing → extra → reasoning_summary → verdict_derivation → primary_assessment → fulfillment_assessments` 顺序读首个非空。`tmp/20260618-185102/report.md` 的 3 种 `not_fulfilled` summary 形态就源自这里。

**决策**：
1. 删除 `_judge_display_reason`（5 段探测）和 `_gap_reason`（"无 error_type 时硬塞 'gap' 字面值"分支）。
2. 新增 `_summary_from_fulfillment(judge_result) -> dict`：
   - **聚合阶段**：从 `fulfillment_assessments` 筛选 `status in {not_fulfilled, partially_fulfilled, contested}`，提取 `{expectation_id, blocking, downstream_impact, within_evaluable_scope}`，按 `blocking=True` 优先排序。
   - **构造阶段**：根据 `verdict` 决定 summary 形态：
     - `verdict="correct"` → `"fulfilled · {N} expectations all met · {reasoning_summary?}"`
     - `verdict="incorrect"` → `"not_fulfilled · blocking=[{expectation_ids}] · {primary_downstream_impact}"`，附维度明细
     - `verdict="uncertain"` → `"uncertain · {verdict_derivation.why_verdict || judge_method}"`
   - `quality_flags` 含 `llm_call_failed` / `self_check_failed` 时，summary 头部加 `[llm_call_failed]` / `[self_check_failed]` 前缀。
3. `_compact_summaries` 的 `judge_summary` dict：
   - `reason` 字段取自 `_summary_from_fulfillment` 的输出
   - 新增 `primary_failure_dimensions: list[dict]`（聚合阶段的结构化数据）
   - `reason_source` 取值 `"aggregated_fulfillment"` / `"degradation_marker"` / `"reasoning_summary"` / `"execution_error"`

**为什么从 `fulfillment_assessments` 起手**：它是 D6 之后 schema 约束最严的字段（5 项 status 词表锁定 + expectation_id 引用完整性），且天然按 expectation 组织。以它为锚点，summary 形态由 `verdict` + `fulfillment` 决定，而非由"哪个字段先非空"决定。

### D6. prompt 锁定 5 项 status 词表，删除 alias 表

29 条 alias（`judge.py:240-270`）证明 prompt 没约束 LLM。删 alias 不可一蹴而就——但本 change 既然删 `_normalize_fulfillment`，alias 表就没有消费方了，可以一起删。

**决策**：
1. 删除 `_FULFILLMENT_STATUS_CANON`、`_FULFILLMENT_STATUS_ALIASES`、`_canonicalize_fulfillment_status`。
2. 修改 `required_output["fulfillment_assessments"][0]["status"]` 与 `required_output["overall_fulfillment"]["status"]`：值改为 `"fulfilled|not_fulfilled|partially_fulfilled|not_evaluable|contested"` 字符串字面值。
3. system prompt 增加"## 输出词表"段：显式说明 status 必须从 5 个值中选择、禁用同义词；`within_evaluable_scope=false` 必须满足"失败原因仅来自 uncontrollable_limits、不存在 evaluable_error"。
4. LLM 偏离词表由 `_judge_self_check` 检测——偏离时触发 re-prompt（D2），不再做防御性归一。

**为什么不保留 alias 表作为防御性归一**：上一版 D7 保留 alias 表"防御 LLM 偶发漏出同义词"。但保留 alias 表就是承认 prompt 约束失效——既然 D6 锁定词表 + D2 self-check 检测偏离，alias 表就是冗余。删干净，让 self_check_failed 标记显式暴露 prompt 失效，而不是用 alias 表把失效藏起来。

### D7. adapter 三层 contract-gate 改造为 assessment 注入，verdict 由 ensure 阶段单点派生

5 处 verdict 改写中，3 处在 adapter 层（reconcile_equivalent / ensure / 项目 normalize）。改造原则：**业务检测保留，表达方式从"直接改 verdict"改为"注入 fulfillment_assessments"**，让 `_compute_verdict` 在 `ensure_fulfillment_judge_result` 末尾统一派生。

**决策**：

1. `core/adapter.py:reconcile_equivalent_judge_result`（255-292 行）：
   - 删除 `judge_result.verdict = "correct"`、`score/confidence/probability` 改写、`fulfillment_assessments = []` 清空、`overall_fulfillment = {}` 清空分支。
   - 改为向 `fulfillment_assessments` 注入 `{"expectation_id": "semantic_equivalence_reconciled", "status": "fulfilled", "blocking": False, "evidence": ...}`；同步把原 not_fulfilled assessment 的 `status` 改为 `fulfilled`（保留 evidence）。
   - 保留 `quality_flags=["semantic_equivalence_reconciled"]` 标记。
   - overall_fulfillment.status 由 ensure 阶段重新派生。

2. `core/adapter.py:apply_judge_consistency_gate`（294-309 行）：**整函数删除**。
   - `judge_verdict_diff_conflict`（LLM verdict 与 fulfillment 派生值不一致）已被 D2 `_judge_self_check` 覆盖（LLM 不再输出 verdict，diff 自然消失）。
   - `uncertain_without_blocking_gaps`（uncertain 但无 blocking gap）被 D1 `_compute_verdict` 的 boundary-aware 规则覆盖（uncertain 必然来自 boundary 或 not_evaluable，不存在"uncertain 但无原因"）。

3. `core/adapter.py:ensure_fulfillment_judge_result`（约 380-418 行）末尾：
   - 删除 `judge_result.derive_verdict_from_fulfillment()` 调用。
   - 替换为 `judge_result.verdict = _compute_verdict(overall_status, judge_result.boundary_decision)` 与 `judge_result.score = _compute_score(judge_result.fulfillment_assessments)`。
   - 其它字段重建（`assessment_count`、`blocking_expectations`、`overall_fulfillment.status` 重新派生）保留。

4. `core/schema.py:JudgeResult.derive_verdict_from_fulfillment`：**方法删除**（与 `_compute_verdict` 概念重叠）。

5. `projects/marketting-planning-intent/adapter.py:normalize_judge_result`（310-361 行）：
   - 删除 `judge_result.verdict = "incorrect"/"correct"`、`score = 0/1`、`fulfillment_assessments = []`、`overall_fulfillment = {}` 直接改写。
   - **保留 intent contract 确定性检测逻辑**（这是 rule.md "通过流程而非 prompt 实现边界判断"的体现）。
   - 检测失败 → 注入 `{"expectation_id": "intent_contract", "status": "not_fulfilled", "blocking": True, "evidence": ...}`；检测通过且 match → 注入 `{"expectation_id": "intent_contract", "status": "fulfilled", "blocking": True, "evidence": ...}`。
   - verdict 在 ensure 阶段由 `_compute_verdict` 派生（注入的 blocking assessment 直接决定 overall_status）。

6. `projects/marketting-planning/adapter.py:normalize_judge_result`（214-255 行）：
   - 删除 `judge_result.verdict = "incorrect"`、`score = min(...)`。
   - 保留 stage/path/fallback 确定性检测，改为注入 `{"expectation_id": "mp_contract:<requirement>", "status": "not_fulfilled", "blocking": True, "evidence": ...}`。

7. `projects/QA/adapter.py:normalize_judge_result`（185-209 行）+ `_weak_quality_probe` / `_fallback_judge`：
   - 这些路径直接构造 fallback `JudgeResult` 并赋 verdict；改造为构造时只填 `fulfillment_assessments`（不填 verdict/score），由 `_compute_verdict` 在末尾派生。

8. `projects/client_search/adapter.py:reconcile_judge_result` override（584-614 行）：**无需改造**——只设 `quality_flags` 与 `boundary_decision`，不直接改 verdict；调用 `super().reconcile_judge_result()` 走统一 ensure 路径。

**为什么不删 contract-gate 检测本身**：intent contract / mp contract / QA gold-answer 是各项目的业务边界（rule.md 要求"在协议范围内制定 impl/project 实现"），删了就失去项目特异性判断。本 change 改的是"检测结果如何影响 verdict"——从"直接覆盖 verdict"改为"作为 fulfillment_assessments 的一项参与派生"，让 verdict 真理来源唯一。

**为什么 `apply_judge_consistency_gate` 整函数删而不改造**：它两个检测分支都是冗余的——`judge_verdict_diff_conflict` 在 LLM 不再输出 verdict 后天然消失；`uncertain_without_blocking_gaps` 在 D1 boundary-aware `_compute_verdict` 下不可能出现。删函数 = 删冗余，符合奥卡姆剃刀。

### D8. 信息密度损失估计（context.md 要求）

`demand/context.md` 要求"给出上下文管理方案时，请同时给出信息密度损失预估"。本 change 的减法对信息密度的影响：

| 改动 | 删除/缩减的内容 | 信息密度影响 |
|---|---|---|
| 删 LLM verdict/score/confidence/probability schema 字段 | LLM 不再输出这 4 个字段 | **无损失**：这 4 个字段原本是 LLM 输出后被后置改写，最终值由代码决定；删 LLM 输出只是去掉"被覆盖的中间值"，不影响最终 judge result 字段语义。 |
| 删 25 字段假 result（LLM 失败时） | 失败 case 不再伪造 intent_model/business_expectations/fulfillment_assessments | **正向增益**：原 25 字段全是 placeholder/trace 推断，是"无效、偏差、误导性信息"；改为空 + `needs_human_review=True` 是诚实表达，符合 algorithm.md "不引入无效信息"。 |
| 删 alias 表 + `_normalize_fulfillment` | LLM 偏离词表时不再静默归一 | **无损失**：D6 prompt 锁定 5 项词表 + D2 self-check 检测偏离 + re-prompt 修正；偏离词表的 case 由 `self_check_failed` 标记显式暴露，信息更透明。 |
| 删 `apply_boundary_reconciliation` | boundary 不再后置改写 verdict + 清空 missing/wrong/extra | **无损失**：boundary 逻辑合并到 `judge_trace` 末尾 5 行直接赋值；`evaluation_boundary` 字段保留，`boundary_decision` 仍由 LLM 产出。 |
| 删 prose grep fallback | 缺失 `judge_boundary` 字段时不再 free-text grep | **正向增益**：grep fallback 把"缺失"变成"隐式降级"，违反 rule.md "在协议范围内制定 impl"；改为显式报错，信息更准确。 |
| 删 `apply_judge_consistency_gate` | 两个冗余检测分支消失 | **无损失**：`judge_verdict_diff_conflict` 在 LLM 不输出 verdict 后天然消失；`uncertain_without_blocking_gaps` 在 boundary-aware `_compute_verdict` 下不可能出现。 |
| adapter contract-gate 改注入 assessment | verdict 不再被直接改写，改为注入 fulfillment_assessments | **无损失**：业务检测结果（intent contract / equivalence / mp contract / QA gold）保留为 assessment 的 evidence；下游反而能从 assessment 看到具体哪条 contract 触发，信息更完整。 |
| summary 从 fulfillment_assessments 构造 | 不再按字段顺序探测 wrong/missing/extra | **正向增益**：原 5 段探测让同一状态产出 3 种形态（零信息字面值 `"wrong: gap"`）；新构造形态由 verdict 决定，结构化 `primary_failure_dimensions` 字段暴露给前端。 |

**总估计**：信息密度**提升**（删的都是"无效/冗余/被覆盖的中间值"，新增的都是"单一真理来源 + 结构化维度"），无有效信息损失。Judge prompt 体积下降（4 字段 schema + 25 字段假 result 消失），未触及 40k 预算上限。

## Risks / Trade-offs

- **[Risk] 删除 alias 表后 LLM 偏离词表** → D6 prompt 显式锁定 5 项词表；D2 self-check 检测偏离触发 re-prompt；re-prompt 仍偏离则 `self_check_failed` 标记 + 人工介入。比 alias 表静默归一更透明。
- **[Risk] 删除 silent verdict 改写后，下游 attribute/check 收到矛盾输入** → D2 self-check + `quality_flags=["self_check_failed"]` 让下游可识别；本 change 不改下游代码，但 protocol 标注新契约。issue3-5 处理下游消费方。
- **[Risk] re-prompt 增加成本** → re-prompt 最多 1 次，且仅在 self-check 失败时触发；按 `tmp/20260618-142809/` 数据，judge 平均 input 5.7k tokens，1 次 re-prompt 成本可控。
- **[Risk] `load_judge_boundary_standard` 缺失报错会让未补齐 `judge_boundary` 字段的项目跑不了 judge** → 这是显式错误，优于 grep fallback 的隐式降级。4 个 check1 项目已具备；其它项目需要补齐。issue3-6 期间一并处理。
- **[Risk] adapter contract-gate 改注入 assessment 后，业务检测行为可能微变** → 改造原则是"检测逻辑保留，表达方式改变"；但原代码 `fulfillment_assessments = []` 清空会丢失 LLM 产出的 assessment，新代码保留 + 注入——行为更完整。需 E2E 回归测试（tasks 9.3）确认 intent/mp/QA contract-gate 路径产出与改造前一致的 verdict。
- **[Risk] `JudgeResult.derive_verdict_from_fulfillment` 删除后，外部调用方编译失败** → grep 确认只有 `ensure_fulfillment_judge_result` 一处调用；改造后无外部消费方。
- **[Risk] 前端 `judge_summary.reason_source` 词表迁移**（旧值 `judge_wrong/judge_missing/judge_extra` → 新值 `aggregated_fulfillment` 等） → check.md 完整更新原则要求前端同步；tasks 9 节纳入 E2E 验证，若前端有硬编码旧值则需同步迁移。
- **[Trade-off] 删除 `_normalize_fulfillment` 整个函数 vs 只删 verdict 改写分支** → 整个删。status canonicalization 随 alias 表一起消失（D6 锁词表）；`overall_fulfillment` 重建由 `_derive_overall_status` 在 `_compute_verdict` 内部一次性完成。减法做到底。
- **[Trade-off] D5 改写 `_judge_display_reason` 影响前端展示** → 前端读 `judge_summary.reason` 字段，字段名不变，内容形态变；frontend 视图回归测试纳入 verification。
- **[Trade-off] D7 保留 contract-gate 检测逻辑 vs 整体删** → 保留检测、只改表达。删检测会失去项目特异性判断（违反 rule.md）；保留检测但用 assessment 注入表达，让 verdict 真理来源唯一。

## Migration Plan

1. **Phase 1（本 change 内）**：实现 D1-D8，单测覆盖每个决策点。
2. **Phase 2（本 change 内）**：跑 `impl/checklist/check1.py` 4 项目，对照 `tmp/20260618-185102/`：
   - 5 个 client_search uncertain case 应产出最小化 honest result（`quality_flags=["llm_call_failed"]` + `needs_human_review=True`），不再 25 字段伪造。
   - 3 种 `not_fulfilled` summary 形态应统一为 D5 构造形态。
   - verdict 与 fulfillment 永远一致（来自单点计算，含 adapter 层 contract-gate 路径）。
   - intent/mp/QA contract-gate 路径产出与改造前一致的 verdict（回归测试，确保只是改写位置变了、不是行为变了）。
3. **Phase 3（issue3-6）**：下游 agent 适配新契约（识别 `self_check_failed` / `llm_call_failed` / `needs_human_review` 标记）；前端 `reason_source` 词表迁移（若需要）。
4. **回滚**：所有改动集中在 `judge.py` / `core/adapter.py` / `core/schema.py` / `server.py` / 3 个项目 adapter；git revert 单 commit 即可回滚；alias 表、`_normalize_fulfillment`、`apply_judge_consistency_gate`、`derive_verdict_from_fulfillment` 已彻底删除，回滚即恢复旧补丁体系。

## Open Questions

- **OQ1**：`_judge_self_check` 检测到的 inconsistencies 是否落盘到 `RunTrace` 供 attribute agent 参考？当前 plan 只放在 `JudgeResult.quality_flags` + `verdict_derivation`，不侵入 RunTrace。
- **OQ2**：`_compute_score` 在无 blocking expectations 时返回 `None`——下游 attribute/check 是否能处理 `score=None`？当前 plan 保留 `score: Optional[float]`，下游若不能处理则在 issue3-5 期间补齐。
