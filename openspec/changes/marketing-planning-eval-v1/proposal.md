## Why

`marketing-planning` is a multi-turn, stateful, SSE-based business agent, while the current verifier project examples primarily cover single-turn QA and client-search style outputs. The updated `demand.md` requires protocol-driven evaluation, reference/output alignment, independent case contexts, robust batch execution, and check-agent review; this change introduces a v1 integration path without turning project-specific SSE/session behavior into generic core assumptions.

## What Changes

- Add a `marketting-planning` project integration that can run through the existing `mock/live -> RunTrace -> judge -> attribute -> cluster -> check -> frontend/batch` chain.
- Support multi-turn case shapes where a case contains a user intent plus ordered turns, isolated session IDs, expected stage, expected path types, expected cards, and boundary metadata.
- Normalize marketing-planning SSE or provided outputs into a compact, judgeable output summary instead of passing huge raw event/card payloads to judge and frontend storage.
- Add project documents for application, mock, evaluation, attribution, checklist, and boundary behavior, grounded in `projects/marketting-planning/marketplan-demand.md` and the existing issue analysis.
- Keep the first implementation as a minimal v1 that can run mock/provided-output and optionally live SSE when the service is available, without requiring external service startup to pass verifier tests.
- Add check-agent audit coverage and an issue report verifying protocol alignment, batch isolation, output/reference formatting, overfit risk, and storage-size resilience.
- Do not push or modify the external `marketing-planning` business repository.

## Capabilities

### New Capabilities
- `marketing-planning-eval`: Evaluate the marketing-planning agent through project-specific multi-turn/SSE normalization, stage-aware judge context, attribution context, mock cases, batch isolation, and check reporting.

### Modified Capabilities
- `verifier-project-adapter`: Extend the verifier project-adapter contract expectations to cover project-specific multi-turn session inputs, SSE output extraction, compact output/reference summaries, and project-owned boundary decisions while preserving the existing unified core pipeline.
- `verifier-frontend-case-pool`: Ensure summary/live frontend behavior and case-pool persistence continue to support uploaded/generated cases with scenario/output/reference/metadata while avoiding large transient SSE/run artifacts.

## Impact

- Affected verifier code: `impl/projects/marketting-planning/*`, `impl/core/adapter.py`, `impl/core/frontend_view.py`, `impl/frontend/summary.html`, and possibly small generic hooks only where needed for project-neutral multi-turn/SSE support.
- Affected protocols/docs: `impl/protocols/*`, `impl/judge_boundary-template.md`, project docs under `impl/projects/marketting-planning`, and check reports under `search-test-case/issue`.
- Affected APIs: existing generic endpoints (`/api/mock_cases`, `/api/live_run`, `/api/run_chain`, `/api/batch_start`, `/api/batch_status`, `/api/frontend_view`) should be reused; no project-private verifier endpoint should be added for v1.
- Dependencies: no new third-party dependency is required for v1; live SSE should use standard-library HTTP handling if implemented.
