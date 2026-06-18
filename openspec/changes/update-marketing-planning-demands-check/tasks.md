## 1. Divergence-Point Demand and Current-State Audit

- [x] 1.1 Re-read updated `demand.md`, `projects/marketting-planning/marketplan-demand.md`, `check.md`, `impl/projects/marketting-planning/issue/20260611-marketplan-integration-risks.md`, `reviews-of-propose/20260611-marketplan-integration-risks.md`, and existing `impl/projects/marketting-planning` docs.
- [x] 1.2 Build a divergence-point matrix for multi-turn state, SSE output, workflow-stage judge, non-exact reference, fine-grained application boundary, fallback ambiguity, `path_types`, card normalization, full-chain mock coverage, and full/split/internal API split-brain risk.
- [x] 1.3 Compare each divergence treatment against current adapter/server/frontend/test/check behavior and record concrete implementation evidence.
- [x] 1.4 Mark areas with no required change explicitly, with evidence, to avoid unnecessary rewrites.
- [x] 1.5 Confirm the external `/Users/xiaozijian/WorkSpace/package/marketing-planning` repository is not modified.

## 2. TDD-Driven Implementation Updates

- [x] 2.1 For each discovered behavior gap, add a focused failing test first and verify the RED result.
- [x] 2.2 Apply the minimal implementation update in project-owned code or generic compacting code as required by the proven gap.
- [x] 2.3 Verify the new test turns GREEN and existing marketing-planning adapter/UAT tests still pass.
- [x] 2.4 Avoid query-specific hardcoded rules; base any judge/attribute reconciliation changes on reference contracts, boundary fields, and current-case evidence.

## 3. Divergence Treatment Verification

- [x] 3.1 Verify multi-turn mock/provided cases preserve user intent, turns, and per-case session isolation.
- [x] 3.2 Verify SSE/provided raw output is post-processed into compact event/card/session/fallback/error summaries.
- [x] 3.3 Verify judge uses workflow stage, structured reference contract, application boundary, fallback responsibility, and required/forbidden evidence before accepting verdicts.
- [x] 3.4 Verify `path_types` are treated as execution-graph intent/reference evidence, not as incidental display fields.
- [x] 3.5 Verify card extraction normalizes complex/delta/snapshot card structures and avoids duplicate card evidence.
- [x] 3.6 Verify mock data covers more than intent-only cases, including clarification, multi-turn, planning, fallback, non-agent, and streaming scenarios.
- [x] 3.7 Verify marketing-planning still uses the primary `/api/v1/marketing-planning/stream` business path and generic verifier APIs (`/api/mock_cases`, `/api/run_chain`, `/api/batch_start`, `/api/batch_status`, `/api/frontend_view`) without project-private verifier endpoints.
- [x] 3.8 Verify compact batch events/results exclude raw SSE/card payloads, `trace.raw_response`, and `frontend_view.raw_sections` from persisted frontend paths.
- [x] 3.9 Verify QA `actual_answer`/`golden_answer` semantics and client_search project registration are not regressed.

## 4. Verification and Check Report

- [x] 4.1 Run `python -m unittest tests.test_marketting_planning_adapter tests.test_marketting_planning_uat`.
- [x] 4.2 Run `python -m compileall -q impl` and `python -m impl.cli projects`.
- [x] 4.3 Run or document mock/provided marketing-planning chain checks through the unified API/pipeline; state any live service limitations separately.
- [x] 4.4 Update or create a Chinese `check.md` audit report under `search-test-case/issue` covering the divergence-point matrix, mechanism evidence, protocol consistency, overfit risk, historical regression checks, verification results, and remaining limits.
- [x] 4.5 Summarize what changed, what was intentionally left unchanged, and what requires future live/browser UAT.
