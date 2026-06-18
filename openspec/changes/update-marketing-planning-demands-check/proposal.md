## Why

`demand.md` 和 `projects/marketting-planning/marketplan-demand.md` 的关键更新点是：必须重点核对 `impl/projects/marketting-planning/issue/20260611-marketplan-integration-risks.md` 中记录的分歧点，以及 `reviews-of-propose/20260611-marketplan-integration-risks.md` 给出的处理方案是否真正落到当前实现里。这个变更不是泛泛重做 marketing-planning，而是围绕多轮状态、SSE、阶段化 judge、reference contract、application boundary、fallback、path_types、卡片归一化、mock 覆盖和 split-brain 接口这些分歧点做机制级 check.md 审核与补齐。

## What Changes

- Re-audit the existing `marketting-planning` implementation against the updated global demand, project demand, `check.md`, and the two divergence-point documents.
- For each divergence point, verify both the chosen treatment and the implementation evidence: multi-turn/session isolation, SSE post-processing, workflow-stage judging, non-exact reference contracts, fine-grained application boundary, fallback responsibility, path_types as execution intent, strong card normalization, full-chain mock coverage, and single primary `/stream` path.
- Verify that the integration still uses the unified verifier chain (`mock/live/provided -> RunTrace -> judge -> attribute -> cluster -> check -> frontend/batch`) without adding project-private endpoints.
- Strengthen or adjust project docs, adapter behavior, tests, and check report only where the divergence-point treatment is missing, inconsistent, or only documented but not enforced.
- Preserve historical QA/client_search behavior, especially QA `output=actual_answer` and `reference=golden_answer` semantics.
- Confirm batch/front-end storage remains compact and resilient for SSE/card-heavy marketing-planning output.
- Confirm judge/attribute behavior remains boundary-driven, evidence-grounded, useful to developers, and not overfit to a few sample cases.
- Do not modify or push the external `/Users/xiaozijian/WorkSpace/package/marketing-planning` repository.

## Capabilities

### New Capabilities
- `marketing-planning-demand-sync`: Reconcile marketing-planning evaluation behavior with updated global/project demands and the recorded divergence-point treatment plan, including check-agent audit, boundary consistency, compact SSE handling, and UAT coverage.

### Modified Capabilities
- `marketing-planning-eval`: Tighten existing marketing-planning evaluation requirements where updated demands require stronger evidence, boundary handling, output/reference alignment, or frontend/batch compactness.
- `verifier-check-audit`: Apply updated `check.md` expectations to inspect producing mechanisms, protocol alignment, overfit risk, standardization, and user-facing verification evidence.

## Impact

- Affected verifier code: `impl/projects/marketting-planning/*`, `impl/server.py`, `impl/frontend/summary.html`, and tests under `tests/` if gaps are found.
- Affected docs/reports: project docs under `impl/projects/marketting-planning`, check reports under `search-test-case/issue`, and any relevant skill/check-agent docs only if the audit shows they lag behind the updated demand.
- Affected APIs: existing generic endpoints only (`/api/mock_cases`, `/api/run_chain`, `/api/batch_start`, `/api/batch_status`, `/api/frontend_view`); no new project-private verifier endpoint.
- Dependencies/external systems: no new third-party dependencies; the external marketing-planning repo remains read-only unless the user explicitly requests otherwise.
