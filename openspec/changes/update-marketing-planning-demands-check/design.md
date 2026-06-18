## Context

The verifier already has a first `marketting-planning` integration with project docs, adapter hooks, mock cases, compact SSE/card summaries, frontend defaults, and check reporting. The updated demand points specifically back to the divergence analysis in `impl/projects/marketting-planning/issue/20260611-marketplan-integration-risks.md` and the treatment notes in `reviews-of-propose/20260611-marketplan-integration-risks.md`: multi-turn state, SSE output, workflow-stage judge, non-exact reference, fine-grained application boundary, fallback ambiguity, `path_types` as execution graph selection, card normalization, insufficient full-chain test data, and split-brain risk across full/split/internal APIs.

The existing implementation must therefore be audited divergence-by-divergence, not only demand-by-demand. The implementation phase should prove each chosen treatment is enforced by adapter/docs/tests/check output, or add the smallest missing mechanism. Historical QA/client_search behavior is part of the acceptance surface and must not be changed incidentally.

## Goals / Non-Goals

**Goals:**

- Reconcile updated demand files with the existing marketing-planning verifier integration.
- Treat the recorded divergence points as the primary audit checklist and verify their actual handling in code/docs/tests/report.
- Preserve the unified core pipeline and existing generic APIs.
- Audit the producing mechanisms: request normalization, boundary construction, mock data generation, output/reference shaping, judge context, attribute evidence, batch isolation, frontend persistence, and check reporting.
- Add or update tests using TDD for any behavior change.
- Produce a Chinese check report that records requirements, gaps, fixes, verification, and live/UAT limits.

**Non-Goals:**

- Do not rewrite the current verifier architecture.
- Do not introduce project-private backend endpoints for marketing-planning.
- Do not modify or push `/Users/xiaozijian/WorkSpace/package/marketing-planning`.
- Do not solve overfitting with hardcoded query-specific rules.
- Do not change QA `actual_answer`/`golden_answer` semantics or client_search behavior unless a regression is discovered and explicitly scoped.

## Decisions

### 1. Divergence-point matrix is the primary acceptance artifact

This change treats `impl/projects/marketting-planning/issue/20260611-marketplan-integration-risks.md` and `reviews-of-propose/20260611-marketplan-integration-risks.md` as the audit backbone. Each recorded divergence point must be mapped to: treatment decision, current implementation evidence, test/check evidence, and remaining limit if any.

Alternative considered: audit only against the latest demand files. Rejected because the user's correction makes the divergence handling itself the core acceptance surface.

### 2. Treat this as demand synchronization plus audit, not a second integration

The first integration already added the project structure and core behavior. This change should first diff requirements against current implementation and only then adjust the smallest set of project-owned code/docs/tests.

Alternative considered: create a new parallel marketing-planning adapter or endpoint. Rejected because it would violate the demand for protocol reuse and create split-brain behavior.

### 3. Multi-turn and `path_types` remain request/mock intent contracts

The treatment notes say multi-turn cases should be driven by a single user intent that unfolds across turns, and `path_types` are part of execution intent rather than ordinary output fields. The audit should verify mock cases, request normalization, session isolation, and reference contracts express those intent/path requirements before runtime judging.

Alternative considered: judge `path_types` only after the fact as generic fields. Rejected because it would miss execution-graph selection failures.

### 4. SSE is post-processed into compact evidence, not displayed or persisted raw

The primary business output is SSE, but the treatment decision is to post-process it into readable summaries. Adapter extraction, frontend view, and batch status should expose compact event/card/session/fallback/error summaries and avoid persisting raw SSE/card payloads.

Alternative considered: keep full raw SSE in frontend/batch payloads for debugging. Rejected because it reintroduces storage quota and user readability problems.

### 5. Judge boundary remains adapter-produced mechanism, not prompt-only policy

Updated demand emphasizes that boundary construction must come from application/project analysis and flow design, not a judge agent guessing at runtime. The implementation should verify `application_boundary` is populated before judge and that judge/attribute consume current-case boundary evidence, including fallback responsibility and expected workflow stage.

Alternative considered: add stronger prompt text only. Rejected because prompt-only fixes are not stable or auditable enough for `check.md`.

### 6. Reference is a structured contract, not exact text

Marketing-planning expected output is conditional: stage, events, allowed fallback, required/forbidden path types, cards, and session requirements matter more than exact wording. The adapter/judge must compare output summaries to reference contracts and record missing/conflicting evidence instead of silently accepting an LLM verdict.

Alternative considered: use a single golden free-form answer. Rejected because the divergence notes explicitly say this project has no unique exact answer.

### 7. Attribute usefulness is judged by evidence chain quality

For incorrect/uncertain results, attribution must identify useful failure locations with current-case trace evidence and actionable remediation. For correct results, it must not fabricate a failure. Any improvement should target trace/evidence construction rather than hardcoded failure summaries.

Alternative considered: map a few known scenarios to canned root causes. Rejected as overfit and contrary to the updated demand.

### 8. Check report must include historical regression evidence

The check report should explicitly record that QA/client_search were inspected for regression risk and that marketing-planning did not alter their semantics. This is part of the user's stated concern about historical requirements.

Alternative considered: report only marketing-planning verification. Rejected because the updated demand says to preserve historical information and not exceed scope.

## Risks / Trade-offs

- [Risk] Demand wording may imply broad protocol redesign. → Mitigation: limit implementation to gaps proven by the divergence-point matrix and record deferred protocol questions in the check report.
- [Risk] Multi-turn mock generation could become an overfit script. → Mitigation: model stable user intent, turns, session requirements, and path intent contracts rather than hardcoded query text.
- [Risk] Live marketing-planning service may not be available. → Mitigation: verify mock/provided-output paths and clearly state live UAT limits; do not claim live business correctness without the service.
- [Risk] Fallback may be treated as universally correct or universally incorrect. → Mitigation: judge fallback against current-case boundary/reference responsibility and record missing evidence when responsibility is unclear.
- [Risk] Tests that call full LLM judge/attribute can be slow. → Mitigation: use narrow deterministic unit/UAT tests for changed behavior and keep full batch verification as explicit acceptance when needed.
- [Risk] Removing raw data too aggressively could reduce debugability. → Mitigation: remove raw only from compact/persisted frontend paths while preserving compact evidence in trace/project_fields/execution_trace.

## Migration Plan

1. Re-read updated demands, divergence analysis, treatment notes, existing marketing-planning docs/adapter/frontend/server/tests, and prior check report.
2. Build a divergence-point matrix covering multi-turn state, SSE output, workflow-stage judge, non-exact reference, fine-grained boundary, fallback, `path_types`, card normalization, full-chain mock coverage, and split-brain API risk.
3. For each divergence point, identify current implementation evidence and whether the treatment is enforced by adapter/docs/tests/check output.
4. For each behavior gap, write a failing test first, verify RED, implement the minimum project-owned or generic source fix, and verify GREEN.
5. Run regression checks for marketing-planning plus project listing and historical QA/client_search smoke coverage where relevant.
6. Update or create the check report under `search-test-case/issue` with the divergence matrix, implemented fixes, no-change decisions, verification, and live/browser UAT limits.

Rollback is local: revert the OpenSpec change artifacts and any implementation/test/report edits from this change. No external repository or persistent production data is modified.

## Open Questions

- Whether the next implementation should run a browser-driven UAT, or whether automated API/unit UAT plus source inspection is sufficient until the external service is available.
- Whether updated demands require deeper protocol-template changes beyond marketing-planning, which would need a broader change and explicit confirmation.
