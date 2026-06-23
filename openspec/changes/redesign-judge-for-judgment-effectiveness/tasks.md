## 1. 删除 silent verdict rewrite 与 alias 表（D6 + D1）

- [ ] 1.1 删除 `impl/core/judge.py` 中 `_FULFILLMENT_STATUS_CANON`、`_FULFILLMENT_STATUS_ALIASES`、`_canonicalize_fulfillment_status` 三个 symbol（约 237-279 行）。全文 grep 确认无其它引用。
- [ ] 1.2 删除 `impl/core/judge.py:_normalize_fulfillment` 整个函数（294-344 行），不保留任何分支。`overall_fulfillment` 重建由 `_derive_overall_status` 在 `_compute_verdict` 内部一次性完成。
- [ ] 1.3 删除 `impl/core/judge.py:_score_from_verdict`（213-223 行）。score 改由 `_compute_score` 从 fulfillment_assessments 派生。
- [ ] 1.4 单测：构造一个 LLM 输出 dict（含 `overall_fulfillment.status` 与 assessments），断言导入 `judge.py` 不再出现 `_FULFILLMENT_STATUS_ALIASES` / `_canonicalize_fulfillment_status` / `_normalize_fulfillment` / `_score_from_verdict` 任何 symbol（`hasattr(judge, name)` 全为 False）。

## 2. verdict / score 单点计算（D1）

- [ ] 2.1 在 `impl/core/judge.py` 新增 `_compute_verdict(overall_status: str, boundary_decision: dict) -> str`：`fulfilled→correct`；`not_fulfilled` + `within_evaluable_scope=False` + `evaluable_errors=[]` → `uncertain`；`not_fulfilled`（其它）→ `incorrect`；其它 status / 缺失 → `uncertain`。
- [ ] 2.2 在 `impl/core/judge.py` 新增 `_compute_score(fulfillment_assessments: list) -> Optional[float]`：blocking 全 fulfilled→1.0；全 not_fulfilled→0.0；混合→fulfilled/blocking；无 blocking→None。
- [ ] 2.3 修改 `judge.py:required_output` schema（约 540-543 行）：删除 `verdict`、`score`、`confidence`、`probability` 四个 key。LLM 只产 fulfillment 域字段。
- [ ] 2.4 修改 `judge_trace`（约 583-584 行）：`client.complete_json` 成功且 self-check 通过后，调用 `data["verdict"] = _compute_verdict(...)` 与 `data["score"] = _compute_score(...)`；删除任何直接读 LLM `data.get("verdict")` 的代码路径。
- [ ] 2.5 单测：构造 `overall_status="not_fulfilled"` + `boundary_decision={"within_evaluable_scope": False, "evaluable_errors": []}` → 断言 `_compute_verdict` 返回 `"uncertain"`；同 overall 但 `evaluable_errors=["..."]` → 断言返回 `"incorrect"`；`overall_status="fulfilled"` → 断言返回 `"correct"`。

## 3. self-check + 1 次 re-prompt（D2）

- [ ] 3.1 在 `impl/core/judge.py` 新增 `_judge_self_check(data: dict, business_expectations: list) -> list[dict]`：返回 inconsistency 列表，逐项检测 (a) `_derive_overall_status` vs `data["overall_fulfillment"]["status"]`、(b) `expectation_id` 引用完整性、(c) `boundary_decision.within_evaluable_scope=false` 与 `evaluable_errors` 非空的矛盾、(d) status 不在 5 项词表 `{fulfilled, not_fulfilled, partially_fulfilled, not_evaluable, contested}`。
- [ ] 3.2 在 `judge_trace` 中（`complete_json` 成功后、`_compute_verdict` 之前）调用 `_judge_self_check`；非空时调一次 re-prompt：在 user prompt 末尾追加 `"\n\n## 上次输出存在不一致\n{inconsistencies json}\n请仅修正以上不一致后重新输出完整 JSON。"`，重新调用 `complete_json`。
- [ ] 3.3 re-prompt 后再次 `_judge_self_check`：仍不一致则在 `data["quality_flags"]` 加 `"self_check_failed"`、`data["needs_human_review"]=True`、`data["verdict_derivation"]["why_verdict"]` 改为说明具体不一致项；**不修改 fulfillment 数据原值**；继续走 `_compute_verdict`。
- [ ] 3.4 单测：mock LLM 第一次返回 `overall_fulfillment.status=fulfilled` + assessments 中有 blocking not_fulfilled → 断言触发 re-prompt（`complete_json` 调用计数=2）；mock re-prompt 仍返回不一致 → 断言 `quality_flags` 含 `self_check_failed`、`needs_human_review=True`、fulfillment 原值保留。

## 4. LLM 失败最小化 honest result（D3）

- [ ] 4.1 删除 `judge.py:586-624` 的 25 字段假 `JudgeResult` 构造。
- [ ] 4.2 在 LLM 失败分支（`data.get("error")` 非空或 `complete_json` 抛异常）返回最小化 result：`intent_model={}`、`business_expectations=[]`、`fulfillment_assessments=[]`、`overall_fulfillment={"status": "not_evaluable", "assessment_count": 0, "blocking_expectations": []}`、`boundary_decision={}`、`verdict_derivation={"why_verdict": "LLM 调用失败，未做出算法判断"}`、`needs_human_review=True`、`quality_flags=["llm_call_failed"]`、`judge_method="llm_call_failed"`、`wrong=[]`、`missing=[]`、`extra=[]`；`verdict` 由 `_compute_verdict("not_evaluable", {})` 推导（= `"uncertain"`）、`score=None`。
- [ ] 4.3 单测：mock `complete_json` 返回 `{"error": "llm_request_failed"}` → 断言 result 的 `quality_flags==["llm_call_failed"]`、`intent_model=={}`、`business_expectations==[]`、`fulfillment_assessments==[]`、`needs_human_review==True`、`verdict=="uncertain"`、`score is None`。

## 5. evaluation_boundary 结构化字段读取（D4）

- [ ] 5.1 修改 `impl/core/judge.py:load_judge_boundary_standard`（约 161-169 行）：只读 `spec.frontend_extensions.implementation_standard.judge_boundary` 结构化字段；缺失或空则抛 `ValueError(f"project {spec.id} missing implementation_standard.judge_boundary")`。
- [ ] 5.2 删除 `impl/core/judge.py:_fallback_evaluation_boundary`、`_extract_boundary_value`、`_line_after_label` 三个函数（约 123-158 行）。grep 确认无其它引用。
- [ ] 5.3 删除 `impl/core/judge.py:apply_boundary_reconciliation` 整个函数（172-193 行）。`evaluation_boundary` 字段补齐合并到 `judge_trace` 末尾的直接赋值（不超过 5 行）：`if not judge_result.evaluation_boundary: judge_result.evaluation_boundary = boundary_standard.get("evaluation_boundary", {})`。
- [ ] 5.4 单测：构造 `spec.frontend_extensions.implementation_standard.judge_boundary` 非空 → 断言 `load_judge_boundary_standard` 返回该结构、不调任何 grep；构造缺失 → 断言抛 `ValueError`；断言 `apply_boundary_reconciliation` symbol 不再存在。

## 6. prompt 锁定 5 项 status 词表（D6）

- [ ] 6.1 修改 `judge.py:required_output["fulfillment_assessments"][0]["status"]` 与 `required_output["overall_fulfillment"]["status"]`：值改为 `"fulfilled|not_fulfilled|partially_fulfilled|not_evaluable|contested"` 字符串字面值。
- [ ] 6.2 修改 `judge.py:required_output["boundary_decision"]`：`within_evaluable_scope` 由 `None` 改为 `"true|false"` 字符串字面值；`uncontrollable_limits` / `evaluable_errors` 加 inline comment 说明何时填。
- [ ] 6.3 修改 system prompt（约 493-525 行）：在"## 核心原则"之后插入"## 输出词表"段，显式说明 (a) status 必须从 5 个值中选择、禁用同义词（列出 `failed/passed/incorrect/wrong/met/unmet` 等禁用项）；(b) `within_evaluable_scope=false` 必须满足"失败原因仅来自 uncontrollable_limits、不存在 evaluable_error"；(c) LLM 不再输出 verdict/score/confidence/probability。
- [ ] 6.4 单测：构造 LLM 返回 `status="failed"`（不在词表内）→ 断言 `_judge_self_check` 把它作为 inconsistency 报告（kind=`"status_off_vocabulary"`）。

## 7. summary 从 fulfillment_assessments 单源构造（D5）

- [ ] 7.1 在 `impl/server.py` 新增 `_aggregate_failure_dimensions(judge: dict) -> list[dict]`：从 `judge["fulfillment_assessments"]` 筛选 `status in {not_fulfilled, partially_fulfilled, contested}`，返回每项 `{expectation_id, status, blocking, downstream_impact, within_evaluable_scope}`，按 `blocking=True` 优先排序。
- [ ] 7.2 新增 `_summary_from_fulfillment(judge_result) -> dict`：先取 `quality_flags` 的降级标记（`llm_call_failed` / `self_check_failed`）决定前缀；调 `_aggregate_failure_dimensions`；按 `verdict` 选 summary 形态（correct/incorrect/uncertain 三种构造模板）；返回 `{"reason": str, "primary_failure_dimensions": list, "reason_source": str}`。`reason_source` 取值 `"aggregated_fulfillment"` / `"degradation_marker"` / `"reasoning_summary"` / `"execution_error"`。
- [ ] 7.3 删除 `server.py:_judge_display_reason`（59-83 行）与 `_gap_reason`（40-56 行）。grep 确认无其它引用。
- [ ] 7.4 修改 `server.py:_compact_summaries`（113-141 行）：`judge_summary` dict 的 `reason` 取自 `_summary_from_fulfillment` 输出；新增 `primary_failure_dimensions` 字段；`reason_source` 取值更新到新词表。
- [ ] 7.5 单测：构造同一 not_fulfilled 状态 + 不同 wrong/missing 列表的两个 judge → 断言 summary 形态一致；构造 gap 缺识别字段 → 断言 summary 主源是 fulfillment_assessments，不出现 `"wrong: gap"` 字面值；构造 `quality_flags=["llm_call_failed"]` → 断言 summary 头部带 `[llm_call_failed]` 前缀。

## 8. 协议文档同步

- [ ] 8.1 修改 `impl/protocols/judge_protocol.md`：verdict 字段说明改为"由 `_compute_verdict` 单点推导，LLM 不再输出"；新增 "Self-check before verdict computation" 节描述 `_judge_self_check` 与 re-prompt 契约；新增 "Failure handling" 节描述单一失败路径（最小化 honest result，不分类、不降级阶梯）；新增 "Adapter contract gates" 节，说明项目层 / 通用层 contract-gate 通过向 `fulfillment_assessments` 注入 assessment 表达，禁止直接改写 verdict/score；删除 `evaluation_boundary` 字段中"normalized before verdict reconciliation"等过时表述。
- [ ] 8.2 在 `impl/protocols/judge_protocol.md` 输出词表节列出 5 项 status 与 `within_evaluable_scope` 决策规则；标注 LLM 不再输出 verdict/score/confidence/probability。

## 9. adapter 三层 contract-gate 改造（D7）

- [ ] 9.1 改造 `impl/core/adapter.py:reconcile_equivalent_judge_result`（255-292 行）：删除 `judge_result.verdict = "correct"`、`score = 1`、`confidence = 0.9`、`probability = 0.9`、`fulfillment_assessments = []`、`overall_fulfillment = {}` 6 行直接改写。改为：(a) 把原 not_fulfilled assessment 的 `status` 改为 `"fulfilled"`（保留 evidence）；(b) 向 `fulfillment_assessments` 追加 `{"expectation_id": "semantic_equivalence_reconciled", "status": "fulfilled", "blocking": False, "evidence": <equivalence_rule_id>}`；(c) 保留 `quality_flags` 中 `"semantic_equivalence_reconciled"` 标记。
- [ ] 9.2 删除 `impl/core/adapter.py:apply_judge_consistency_gate`（294-309 行）整函数。`reconcile_judge_result` 调用链中移除该调用。grep 确认无其它引用。
- [ ] 9.3 改造 `impl/core/adapter.py:ensure_fulfillment_judge_result`（约 380-418 行）末尾：删除 `judge_result.derive_verdict_from_fulfillment()` 调用。替换为 `judge_result.verdict = _compute_verdict(overall_status, judge_result.boundary_decision)` 与 `judge_result.score = _compute_score(judge_result.fulfillment_assessments)`。其它字段重建（`assessment_count`、`blocking_expectations`、`overall_fulfillment.status`）保留。
- [ ] 9.4 删除 `impl/core/schema.py:JudgeResult.derive_verdict_from_fulfillment` 方法。grep 确认只有 `ensure_fulfillment_judge_result` 一处调用（已在 9.3 改造）。
- [ ] 9.5 改造 `impl/projects/marketting-planning-intent/adapter.py:normalize_judge_result`（310-361 行）：删除 `judge_result.verdict = "incorrect"`、`judge_result.verdict = "correct"`、`score = 0`、`score = 1`、`fulfillment_assessments = []`、`overall_fulfillment = {}` 直接改写。**保留 intent contract 检测逻辑**。检测失败 → 向 `fulfillment_assessments` 追加 `{"expectation_id": "intent_contract", "status": "not_fulfilled", "blocking": True, "evidence": <reason>}` + `quality_flags` 加 `"intent_contract_gate_failed"`。检测通过且 match → 追加 `{"expectation_id": "intent_contract", "status": "fulfilled", "blocking": True, "evidence": <match_summary>}` + `quality_flags` 加 `"intent_contract_gate_passed"`。
- [ ] 9.6 改造 `impl/projects/marketting-planning/adapter.py:normalize_judge_result`（214-255 行）：删除 `judge_result.verdict = "incorrect"`、`score = min(...)` 直接改写。保留 stage/path/fallback 检测，改为向 `fulfillment_assessments` 追加 `{"expectation_id": "mp_contract:<requirement>", "status": "not_fulfilled", "blocking": True, "evidence": <stage_or_path_reason>}` + `quality_flags` 加 `"marketing_planning_contract_mismatch"`。删除对 `condition_assessments` / `missing` / `wrong` / `extra` 的直接 append（这些字段由 `ensure_fulfillment_judge_result` 重建）。
- [ ] 9.7 改造 `impl/projects/QA/adapter.py:normalize_judge_result`（185-209 行）+ `_weak_quality_probe` + `_fallback_judge`：fallback 构造 `JudgeResult` 时只填 `fulfillment_assessments`（不填 `verdict` / `score` / `confidence` / `probability`，让 dataclass 默认值生效）。`_fallback_judge` 检测失败 → 注入 `{"expectation_id": "qa_fallback:<probe>", "status": "not_fulfilled", "blocking": True, "evidence": ...}`；检测通过 → 注入 `{"expectation_id": "qa_fallback:<probe>", "status": "fulfilled", "blocking": True, "evidence": ...}`。
- [ ] 9.8 验证 `impl/projects/client_search/adapter.py:reconcile_judge_result` override（584-614 行）：grep 确认函数体内无 `judge_result.verdict = ...` / `judge_result.score = ...` / `judge_result.fulfillment_assessments = ...` / `judge_result.overall_fulfillment = ...` 赋值；末尾调用 `super().reconcile_judge_result(...)` 进入统一 ensure 链路。无需改造。
- [ ] 9.9 单测：构造 `judge_result` LLM 原值 `verdict="incorrect"` + `fulfillment_assessments=[blocking not_fulfilled]`，调用 `reconcile_equivalent_judge_result` 命中等价规则 → 断言：(a) `fulfillment_assessments` 中原 not_fulfilled 项 status 改为 `fulfilled`；(b) 多了一项 `expectation_id="semantic_equivalence_reconciled"`；(c) 函数返回前 `judge_result.verdict` 字段未被本函数改写（由后续 `ensure` 派生）。
- [ ] 9.10 单测：构造 mpi `judge_result` LLM 原值 + intent contract 检测失败 → 调 `normalize_judge_result` → 断言 `fulfillment_assessments` 中追加 `expectation_id="intent_contract"`、`status="not_fulfilled"`、`blocking=True`；断言函数体内未直接赋 `verdict`/`score`。
- [ ] 9.11 单测：完整跑 `reconcile_judge_result` 链路（normalize → reconcile_equivalent → ensure），断言：(a) intent contract 失败 case 最终 `verdict="incorrect"`、`score=0.0`（与改造前一致）；(b) intent contract 通过 case 最终 `verdict="correct"`、`score=1.0`（与改造前一致）；(c) 等价规则归一 case 最终 `verdict="correct"`、`score=1.0`。这三条 = 改造前后行为等价证明。

## 10. 端到端验证

- [ ] 10.1 跑 `python3 impl/checklist/check1.py` 全 4 项目，对照 `tmp/20260618-185102/report.md`：5 个 client_search uncertain case 应产出最小化 honest result（`quality_flags=["llm_call_failed"]` + `needs_human_review=True`），不再 25 字段伪造、不再统一显示"judge LLM call failed; verdict is uncertain"。
- [ ] 10.2 同上验证：3 种 `not_fulfilled` summary 形态（report.md 11/35/43 行）应统一为 D5 构造形态；不再出现 `"wrong: gap"` 零信息字面值。
- [ ] 10.3 验证 verdict 与 fulfillment 永远一致：抽取新 `tmp/<ts>/results.json` 中所有 judge result，断言 `verdict == _compute_verdict(overall_status, boundary_decision)` 对每条都成立（单点计算的反向校验，含 adapter 层 contract-gate 路径）。
- [ ] 10.4 验证 contract-gate 行为等价：抽取新 `tmp/<ts>/results.json` 中 mpi/mp/QA 项目所有 case，对比改造前 `tmp/20260618-185102/results.json` 同 case 的 verdict —— 期望 verdict 分布完全一致（改造只改"verdict 真理来源"，不改"判断行为"）。
- [ ] 10.5 对比 token usage：re-prompt 引入的额外成本应 <10% judge 平均 input tokens（基于 `tmp/20260618-142809/results.json` baseline，judge avg 5.7k）；记录在新 `tmp/<ts>/report.md`。
- [ ] 10.6 验证下游 attribute/check 在新 quality_flags 下的兼容性：`quality_flags=["self_check_failed"]` / `["llm_call_failed"]` / `["intent_contract_gate_failed"]` / `["semantic_equivalence_reconciled"]` 不应触发 `attribute._fulfilled_attribute_result` fast-path（attribute.py:389-390）误跳过；当前 issue 不改 attribute，但需确认未引入回归。
- [ ] 10.7 前端 `judge_summary.reason_source` 词表迁移检查：grep 前端代码（如有 `tmp/` 外的 frontend 目录）中是否硬编码旧值 `"judge_wrong"` / `"judge_missing"` / `"judge_extra"`；若存在则在本 change 内同步迁移到新词表（`"aggregated_fulfillment"` / `"degradation_marker"` / `"reasoning_summary"` / `"execution_error"`）；若无前端硬编码，记录在 issue3-6 跟进。
- [ ] 10.8 重启服务实测验证（check.md 要求）：跑完 `check1.py` 后启动 `python3 impl/server.py` 浏览器实测 4 项目 sample case，确认前端 `judge_summary` 渲染正常、`primary_failure_dimensions` 字段正确暴露、降级标记前缀正确显示。

## 11. issue 同步

- [ ] 11.1 在 `issue/issue2-algorithm-agents-arbitrary-design-redesign.md` 末尾追加一条 Claude 对话框（按当前日期 2026-06-19），简述：(a) 已系统审视 5 个算法 agent + pipeline，得 32 个 finding；(b) 决定先动 judge + adapter 三层 verdict 改写（共 5 处），本 change 落地于 `openspec/changes/redesign-judge-for-judgment-effectiveness/`；(c) judge 部分遵循 demand.md / algorithm.md / context.md / rule.md / check.md 做减法——删除 alias 表、`_normalize_fulfillment`、`apply_boundary_reconciliation`、prose grep、25 字段假 result、`apply_judge_consistency_gate`、`derive_verdict_from_fulfillment`，把 verdict 从"LLM 输出 + 后置改写"移到"代码单点计算 `_compute_verdict`"；adapter 三层 contract-gate（intent/mp/QA/equivalence）改造为向 `fulfillment_assessments` 注入 assessment 表达，业务检测保留、verdict 真理来源唯一；(d) 列出 issue3-6 待处理范围（attribute/cluster/check/pipeline），不动 mock。不预设具体方案，只汇报进展。
