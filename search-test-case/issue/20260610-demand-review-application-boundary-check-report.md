# 2026-06-10 demand/review application-boundary check report

## 审核范围

- 最新 `demand.md` / `review.md` 中的四类问题：
  - 前端批量归因不能再因 browser storage quota 中断整批。
  - QA 批量不应大量落到不稳定的 `uncertain`。
  - judge/attribute 必须区分当前评价边界，不能把 `CONTAINS` / `MATCH` 等可等价语义机械判错。
  - `client_search` 下游结果集不可用时，application/project adapter 先确定边界，judge/attribute 聚焦边界内 parser 条件语义，不反复把外部依赖不可用当作主结论。
- 按 `.claude/skills/evals/agents/specialized/check.md` 审查产生机制，而不是只看当前输出。

## 发现与修复

### 1. QA 批量 `uncertain` 来源不稳定

- 证据：QA 场景本身已有 `qa_gold_answer`、`qa_context_faithfulness`、`qa_weak_quality` 的可确定项目证据，但此前只有 LLM 失败时才进入 deterministic fallback，批量时会受 LLM 输出波动影响。
- 根因：项目已知 QA 场景的评价机制没有优先使用项目确定性标准。
- 修复：`impl/projects/QA/adapter.py` 中 `normalize_judge_result()` 对已知 QA scenario 统一使用 `_fallback_judge()` 生成 `qa_project_deterministic_judge`，保留原始 LLM raw output 作为辅助信息。
- 验证：`batch_run('QA', mock_cases('QA')[:3], mock=True)` 返回 3 条 `correct`，check passed，issues 为空。

### 2. client_search 边界由 judge 反复重判

- 证据：review 要求 application/project 先确定下游当前可用性；judge/attribute 只消费当前边界。旧 judge 文档仍要求 judge 每次检查 `project_fields.downstream_search` 并容易重复输出下游不可用叙述。
- 根因：应用运行能力边界没有被明确作为 `application_boundary` 传入并被 check/protocol 固化。
- 修复：
  - `impl/projects/client_search/adapter.py` 增加/使用 `application_boundary`：下游不可用时设置 `judge_scope=parser_condition_semantics_only`、`result_set_verified=false`。
  - `reconcile_judge_result()` 清理 downstream/result-set 类质量标记，统一暴露 `application_boundary_parser_only`，避免输出重复外部依赖失败标签。
  - `impl/projects/client_search/judge.md` 改为要求 judge 消费 `application_boundary`，而不是把下游不可用作为每次判定主因。
  - `impl/core/check.py` 检查下游不可用时 `boundary_decision.application_boundary.judge_scope == parser_condition_semantics_only`。
- 验证：`client_search` mock batch 3 条均 `correct`，check passed，quality flags 均为 `application_boundary_parser_only`，`reasoning_summary` 不含重复“下游客户搜索”短语。

### 3. 协议与 check 对齐

- 证据：demand 要求 application boundary 在 judge/attribute 前确定；protocol 需要表达这个机制，否则后续实现容易回退成 judge 内部自行重判边界。
- 修复：
  - `impl/protocols/application_protocol.md` 增加 `application_boundary` 字段说明。
  - `impl/protocols/judge_protocol.md` 要求 judge 消费 adapter 提供的 `application_boundary`。
  - `impl/protocols/attribute_protocol.md` 要求 attribution 使用已有 application/project boundary，边界排除结果集验证时聚焦 parser/model/config/code 证据链。
- 验证：`python -m compileall -q impl` 通过；`python -m impl.cli projects` 返回 `QA`、`client_search`。

### 4. 前端批量 quota 风险复核

- 证据：`impl/frontend/summary.html` 已使用轻量 case pool 持久化：只保存 durable source fields，不把完整 `trace/judge/attribute/frontend_view` 写入 `sessionStorage`；`safeSetSessionJson()` 捕获 storage 写入失败并跳过持久化，不中断渲染/轮询。
- 结论：本轮未发现回退到完整结果持久化的路径；符合 check.md 对 batch resilience 和 persisted case-pool 最小化的要求。

## 验证命令

- `python -m compileall -q impl`
- `python -m impl.cli projects`
- QA mock batch：3/3 correct，check passed，issues=[]，judge_method=`qa_project_deterministic_judge`
- client_search mock batch：3/3 correct，check passed，issues=[]，quality_flags=`application_boundary_parser_only`

## check.md 结论

- 协议一致性：通过。application/judge/attribute/check 都已表达并消费 `application_boundary`。
- 机制源头：通过。QA 修在 adapter judge normalization；client_search 修在 project adapter/context/reconcile 和 project judge doc；不是只改前端展示或静态结果。
- 批量容错：通过。QA/client_search mock batch 复用统一 `batch_run -> run_chain -> judge -> attribute -> check` 链路。
- 前端持久化：通过复核。case pool 持久化为轻量数据，storage 失败不会中断整批。
- 过拟合风险：未发现新增历史 case 硬编码；本轮变更基于 scenario 机制、application boundary 和协议字段。
- 剩余外部限制：本地 8081 下游结果集仍不可用时不能声称 result-set verified；当前实现通过 `application_boundary_parser_only` 明确约束评价范围。
