# Marketing Planning Divergence Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the `update-marketing-planning-demands-check` change by auditing every recorded marketing-planning divergence point, adding missing regression coverage, and updating the Chinese check report with mechanism-level evidence.

**Architecture:** Keep the existing unified verifier pipeline unchanged. All marketing-planning specificity stays in `impl/projects/marketting-planning/adapter.py`, project docs, tests, and the check report; generic server/frontend code is touched only if audit evidence proves a compacting or API consistency gap. The implementation is mostly audit/report work plus focused characterization tests for existing divergence treatments; any behavior gap discovered during execution must follow RED → GREEN before production edits.

**Tech Stack:** Python `unittest`, existing verifier modules under `impl/`, OpenSpec artifacts under `openspec/changes/update-marketing-planning-demands-check`, Markdown check report under `search-test-case/issue`.

---

## File Structure

- Modify: `tests/test_marketting_planning_adapter.py`
  - Responsibility: focused regression tests for project adapter mechanisms that enforce divergence treatments.
  - Add tests for multi-turn/session isolation, fallback boundary rejection, mock scenario coverage, and primary stream path configuration.

- Modify: `search-test-case/issue/20260611-marketting-planning-check-report.md`
  - Responsibility: Chinese user-facing `check.md` audit report.
  - Add a divergence-point matrix that maps each recorded divergence to treatment, mechanism evidence, verification evidence, and remaining limit.

- Read-only verification: `impl/projects/marketting-planning/adapter.py`
  - Responsibility: project-specific request normalization, SSE/card extraction, judge normalization, attribution context, and mock cases.
  - Do not change unless a new failing test exposes a real behavior gap.

- Read-only verification: `impl/projects/marketting-planning/project.yaml`
  - Responsibility: project registration and external business endpoint configuration.
  - Confirm primary path remains `/api/v1/marketing-planning/stream`.

- Read-only verification: `impl/server.py` and `impl/frontend/summary.html`
  - Responsibility: generic APIs and compact frontend/batch persistence.
  - Do not change unless compacting regressions are found.

- Read-only verification: `openspec/changes/update-marketing-planning-demands-check/*`
  - Responsibility: accepted scope and checklist for this implementation.
  - Do not rewrite during execution unless implementation finds a spec inconsistency.

---

### Task 1: Add adapter divergence regression coverage

**Files:**
- Modify: `tests/test_marketting_planning_adapter.py`
- Read: `impl/projects/marketting-planning/adapter.py`
- Read: `impl/projects/marketting-planning/project.yaml`

- [ ] **Step 1: Add focused regression tests**

Append these methods inside `class MarketingPlanningAdapterTest(unittest.TestCase):` after the existing `test_card_extraction_deduplicates_same_card_from_snapshot_and_sse_delta` method.

```python
    def test_multiturn_session_is_isolated_by_default_and_shared_only_when_declared(self):
        subject = adapter()

        isolated = subject.build_request(
            {
                "case_id": "mp-session-isolated",
                "session_id": "external-session",
                "turns": [
                    {"role": "user", "content": "帮我规划NBEV目标"},
                    {"role": "assistant", "content": "请补充目标年份和目标值"},
                    {"role": "user", "content": "明年120亿"},
                ],
            }
        )
        shared = subject.build_request(
            {
                "case_id": "mp-session-shared",
                "session_id": "external-session",
                "shared_session": True,
                "turns": [{"role": "user", "content": "继续刚才的规划"}],
            }
        )

        self.assertEqual(isolated["session_id"], "eval-mp-session-isolated")
        self.assertFalse(isolated["shared_session"])
        self.assertEqual(isolated["user_intent"], "帮我规划NBEV目标")
        self.assertEqual(shared["session_id"], "external-session")
        self.assertTrue(shared["shared_session"])

    def test_disallowed_fallback_overrides_correct_llm_verdict(self):
        subject = adapter()
        trace = RunTrace(
            trace_id="trace-disallowed-fallback",
            project_id="marketting-planning",
            input={"query": "规划保费增长路径"},
            normalized_request={},
            extracted_output={
                "stage": "planning",
                "event_summary": {"names": ["intent_detected", "fallback", "done"], "completed": True},
                "card_summary": [{"path_type": "premium_growth", "fallback": True}],
                "fallback": {"used": True, "allowed": False, "reason": "dependency unavailable"},
            },
            project_fields={
                "reference": {"expected_stage": "planning", "required_path_types": ["premium_growth"], "allow_fallback": False},
                "expected_stage": "planning",
                "expected_path_types": ["premium_growth"],
                "application_boundary": {"allow_fallback": False, "dependency_status": "available"},
            },
        )
        judge = JudgeResult(trace_id=trace.trace_id, project_id="marketting-planning", verdict="correct", score=1, quality_flags=[])

        result = subject.normalize_judge_result(trace, judge)

        self.assertEqual(result.verdict, "incorrect")
        self.assertIn(
            {"requirement": "allow_fallback", "expected_fragment": False, "actual_fragment": {"used": True, "allowed": False, "reason": "dependency unavailable"}, "status": "wrong", "evidence": ["fallback used but reference/boundary does not allow it"]},
            result.wrong,
        )

    def test_mock_cases_cover_full_chain_divergence_scenarios(self):
        subject = adapter()

        cases = subject.build_mock_cases()
        case_ids = {case["id"] for case in cases}
        scenarios = {case["scenario"] for case in cases}

        self.assertEqual(len(cases), 7)
        self.assertEqual(
            case_ids,
            {
                "mp-intent-1",
                "mp-clarify-1",
                "mp-multiturn-1",
                "mp-planning-1",
                "mp-fallback-1",
                "mp-non-agent-1",
                "mp-stream-1",
            },
        )
        self.assertEqual(
            scenarios,
            {
                "intent_recognition",
                "clarification",
                "multi_turn_field_accumulation",
                "execution_planning",
                "fallback_data_unavailable",
                "non_agent_intent",
                "streaming_protocol",
            },
        )

    def test_live_configuration_uses_primary_stream_path(self):
        project = load_project("marketting-planning")

        self.assertEqual(project.api.get("endpoint"), "/api/v1/marketing-planning/stream")
        self.assertEqual(project.application.get("primary_path"), "/api/v1/marketing-planning/stream")
        self.assertFalse(project.application.get("modify_external_repo"))
```

- [ ] **Step 2: Run the focused adapter tests**

Run:

```bash
python -m unittest tests.test_marketting_planning_adapter
```

Expected: PASS. These are characterization/regression tests for already-implemented divergence treatments; if any test fails, stop and treat the failure as a discovered behavior gap.

- [ ] **Step 3: If a test fails, follow TDD for the failing behavior**

Use this rule for the exact failing test only:

```text
1. Keep the failing test unchanged.
2. Confirm the failure is about the intended divergence treatment, not a typo in the test.
3. Make the smallest edit in `impl/projects/marketting-planning/adapter.py` or `impl/projects/marketting-planning/project.yaml` to satisfy the test.
4. Re-run `python -m unittest tests.test_marketting_planning_adapter` until it passes.
```

Expected if implementation is already correct: no production edit is needed.

- [ ] **Step 4: Commit the adapter test coverage**

If this repository is under git in the execution environment, run:

```bash
git add tests/test_marketting_planning_adapter.py
git commit -m "test: cover marketing planning divergence handling"
```

Expected: one commit containing only the adapter regression tests. If the execution environment is not a git repository, record this in the final summary and do not create a commit.

---

### Task 2: Update the Chinese check report with the divergence-point matrix

**Files:**
- Modify: `search-test-case/issue/20260611-marketting-planning-check-report.md`
- Read: `openspec/changes/update-marketing-planning-demands-check/design.md`
- Read: `openspec/changes/update-marketing-planning-demands-check/tasks.md`
- Read: `impl/projects/marketting-planning/issue/20260611-marketplan-integration-risks.md`
- Read: `reviews-of-propose/20260611-marketplan-integration-risks.md`

- [ ] **Step 1: Insert the divergence matrix after the `## 背景` section**

Add this section after the existing background paragraph and before `## 已执行修改`.

```markdown
## 分歧点处理矩阵

| 分歧点 | 处理方案 | 机制证据 | 验证证据 | 剩余限制 |
| --- | --- | --- | --- | --- |
| 多轮状态型 agent，不是单轮无状态接口 | 以 `user_intent`、`turns`、`session_id` 表达同一意图下的多轮交互；默认按 case 隔离 session，只有显式 `shared_session` 才复用 | `adapter.build_request()` 归一化 turns/user_intent，并生成 `eval-<case_id>`；`project_fields` 输出 session/shared_session | `test_multiturn_session_is_isolated_by_default_and_shared_only_when_declared`；mock case `mp-multiturn-1` | 实时 mock agent 边对话边生成暂未实现，本轮先覆盖静态多轮 contract |
| 主输出是 SSE 事件序列，不是单个 JSON 答案 | 不直接持久化/展示 raw SSE，而是后处理为 compact summary | `extract_output()` 产出 `event_summary/card_summary/session_summary/fallback/errors`；`_compact_run()` 移除 `trace.raw_response` 与 `frontend_view.raw_sections` | `test_provided_sse_raw_preserves_request_context_in_output_summary`；`test_batch_compact_run_removes_raw_frontend_sections_before_case_pool_persistence` | live SSE 字段差异需等外部服务可用后补 UAT |
| judge 必须按 workflow 阶段判断 | reference 和 `project_fields.expected_stage` 驱动阶段判断，stage mismatch 会覆盖 LLM correct verdict | `normalize_judge_result()` 检查 `expected_stage` vs extracted `stage`；`build_judge_context()` 暴露 stage rules | adapter 行为测试覆盖 required event 和 fallback；check 报告记录阶段机制 | 可继续补单独 stage mismatch 测试，但当前机制已存在 |
| reference 不能是唯一标准答案 | reference 使用结构化 contract，不使用唯一 golden free-form 文本 | `_normalize_reference()` 保留 expected_stage、required/forbidden path_types、required_events、allow_fallback、session_requirements | `test_missing_required_event_makes_judge_incorrect`；mock cases 的 reference 字段 | 业务语义类 `semantic_requirements` 的 live 覆盖依赖真实服务输出 |
| application boundary 需要比 client_search 更细 | adapter 在 judge 前构造当前 case 的边界，包含依赖状态、fallback 权限、排除证据 | `project_fields.application_boundary` 与 `_application_boundary()`；`build_attribute_context()` 使用当前 RunTrace boundary | check checklist 的边界机制项；fallback regression test | 边界内容目前来自 case/reference，不读取外部服务运行时依赖拓扑 |
| fallback 既可能正确也可能掩盖错误 | 用 reference/boundary 的 `allow_fallback` 判断，不做全局正确/错误规则 | `normalize_judge_result()` 在 fallback used 且不允许时标记 wrong；`_mock_fallback()` 根据 boundary 构造 mock | `test_disallowed_fallback_overrides_correct_llm_verdict`；mock case `mp-fallback-1` | 真实依赖不可用时是否属于系统责任仍需 live/UAT 证据 |
| `path_types` 是执行图选择，不是普通字段 | 将 `path_types` 作为意图和 reference contract 的执行路径要求 | `build_request()` 写入 `expected_path_types`；`normalize_judge_result()` 检查 required/forbidden path types；execution_trace 的 `path_dispatch` 节点记录 evidence | `test_mock_cases_cover_full_chain_divergence_scenarios`；既有 card/path 测试 | 未对 path 顺序/card_sort 做业务级断言，保留为 live 后续项 |
| 卡片结构复杂，adapter 需要强归一化 | 对 cards snapshot 与 SSE card_delta 做统一 compact card summary，并按 card identity 去重 | `_extract_cards()` 兼容 `cards/card_summary/planning_cards/data.cards` 和 event card_delta；同 card marker 去重 | `test_card_extraction_deduplicates_same_card_from_snapshot_and_sse_delta` | 真实业务新增 card 字段时需扩展 compact summary schema |
| 已有测试数据主要覆盖 intent，不足以覆盖全链路 | mock case 覆盖 intent、clarification、multi-turn、planning、fallback、non-agent、streaming protocol | `build_mock_cases()` 生成 7 条场景样例；`build_mock_datasets()` 汇总 dataset | `test_mock_cases_cover_full_chain_divergence_scenarios`；mock batch 7/7 完成 | 仍不是业务全量黄金集，后续应接入真实样例和 live UAT |
| 全流程/拆分/内部接口容易 split-brain | verifier 只配置业务主路径 `/api/v1/marketing-planning/stream`，不新增项目私有 verifier endpoint | `project.yaml` 的 `api.endpoint` 和 `application.primary_path`；server 继续复用 generic APIs | `test_live_configuration_uses_primary_stream_path`；`python -m impl.cli projects` | 不验证外部仓库内部拆分接口实现，只保证 verifier 不分裂 |
```

- [ ] **Step 2: Update the existing checklist to reference the matrix**

In `## check.md 审核 checklist`, add this item after the heading and before the existing first checklist item.

```markdown
- [x] 分歧点主线：已按 `issue/20260611-marketplan-integration-risks.md` 与 `reviews-of-propose/20260611-marketplan-integration-risks.md` 建立逐项矩阵，记录处理方案、机制证据、验证证据和剩余限制。
```

- [ ] **Step 3: Update verification results with the new tests**

Replace this existing verification bullet:

```markdown
- `python -m unittest tests.test_marketting_planning_adapter`：通过 3 条 adapter 行为测试；其中 required SSE event 缺失用例先按 TDD RED 失败，再补最小实现转为 GREEN。
```

with:

```markdown
- `python -m unittest tests.test_marketting_planning_adapter`：通过 7 条 adapter 行为/回归测试；覆盖 required SSE event 缺失、多轮 session 隔离、fallback 边界拒绝、卡片去重、mock 全链路场景和主 `/stream` 配置。其中新增 4 条为当前分歧点处理的 characterization/regression coverage；如未来失败，应按 TDD RED→GREEN 修复对应机制。
```

- [ ] **Step 4: Commit the report update**

If this repository is under git in the execution environment, run:

```bash
git add search-test-case/issue/20260611-marketting-planning-check-report.md
git commit -m "docs: add marketing planning divergence audit matrix"
```

Expected: one commit containing only the report update. If the execution environment is not a git repository, record this in the final summary and do not create a commit.

---

### Task 3: Run required verification commands

**Files:**
- Read-only verification across `tests/`, `impl/`, and OpenSpec artifacts.

- [ ] **Step 1: Run marketing-planning tests**

Run:

```bash
python -m unittest tests.test_marketting_planning_adapter tests.test_marketting_planning_uat
```

Expected output includes:

```text
Ran 8 tests
OK
```

If the exact runtime count differs because additional tests were added during execution, expected result is still `OK` with no failures or errors.

- [ ] **Step 2: Run Python compile verification**

Run:

```bash
python -m compileall -q impl
```

Expected: command exits `0` with no output.

- [ ] **Step 3: Verify project registration**

Run:

```bash
python -m impl.cli projects
```

Expected output includes all three project IDs:

```json
{
  "projects": [
    "QA",
    "client_search",
    "marketting-planning"
  ]
}
```

The order may match the example. If output order differs, all three IDs must still be present.

- [ ] **Step 4: Verify OpenSpec artifacts remain complete**

Run:

```bash
openspec status --change "update-marketing-planning-demands-check"
```

Expected output includes:

```text
Progress: 4/4 artifacts complete

[x] proposal
[x] design
[x] specs
[x] tasks

All artifacts complete!
```

---

### Task 4: Final consistency check and handoff summary

**Files:**
- Read: `tests/test_marketting_planning_adapter.py`
- Read: `search-test-case/issue/20260611-marketting-planning-check-report.md`
- Read: `openspec/changes/update-marketing-planning-demands-check/tasks.md`

- [ ] **Step 1: Check that each OpenSpec divergence verification task has evidence**

Use this mapping while reviewing the test file and report:

```text
3.1 multi-turn/session isolation -> test_multiturn_session_is_isolated_by_default_and_shared_only_when_declared + matrix row 1
3.2 SSE compact summary -> test_provided_sse_raw_preserves_request_context_in_output_summary + UAT compact test + matrix row 2
3.3 stage/reference/boundary/fallback judge -> test_missing_required_event_makes_judge_incorrect + test_disallowed_fallback_overrides_correct_llm_verdict + matrix rows 3-6
3.4 path_types as execution intent -> test_mock_cases_cover_full_chain_divergence_scenarios + matrix row 7
3.5 card normalization -> test_card_extraction_deduplicates_same_card_from_snapshot_and_sse_delta + matrix row 8
3.6 full-chain mock coverage -> test_mock_cases_cover_full_chain_divergence_scenarios + matrix row 9
3.7 primary stream/generic APIs -> test_live_configuration_uses_primary_stream_path + project listing verification + matrix row 10
3.8 compact persisted frontend paths -> test_batch_compact_run_removes_raw_frontend_sections_before_case_pool_persistence + matrix row 2
3.9 QA/client_search regression -> python -m impl.cli projects + existing report historical checklist
```

Expected: every item has at least one concrete source/test/report evidence entry.

- [ ] **Step 2: Confirm no external marketing-planning repository was modified**

Run:

```bash
git -C "/Users/xiaozijian/WorkSpace/package/marketing-planning" status --short
```

Expected: no output, or only pre-existing changes that are not produced by this plan. If output exists, do not modify it; report it as external repo state observed during verification.

- [ ] **Step 3: Prepare final response**

Use this structure:

```markdown
已完成分歧点处理计划的执行：
- 新增 adapter 回归覆盖：多轮/session、fallback boundary、mock 场景、主 stream 配置。
- check 报告已补充分歧点矩阵，逐项记录处理方案、机制证据、验证证据和剩余限制。
- 验证：`python -m unittest tests.test_marketting_planning_adapter tests.test_marketting_planning_uat`、`python -m compileall -q impl`、`python -m impl.cli projects`、`openspec status --change update-marketing-planning-demands-check` 均通过。
- 外部 `/Users/xiaozijian/WorkSpace/package/marketing-planning` 未修改。
```

If any verification command fails, do not use the success summary. Instead report the exact failing command and the smallest next action.
