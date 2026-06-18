## 1. Project Adapter and Protocol Alignment

- [ ] 1.1 Add `marketting-planning` project registration so project listing includes it without removing existing projects.
- [ ] 1.2 Create project docs under `impl/projects/marketting-planning` for application boundary, mock behavior, judge context, attribution context, checklist, and evaluation contract.
- [ ] 1.3 Implement the project adapter scaffold through the existing `ProjectAdapter` hooks without adding project-private backend endpoints.
- [ ] 1.4 Normalize single-turn and multi-turn inputs into stable requests with per-case isolated session identity unless a shared-session scenario is explicitly declared.
- [ ] 1.5 Record project-owned boundary and verification status in `RunTrace.project_fields` before judge runs.

## 2. Output, Reference, and SSE Normalization

- [ ] 2.1 Implement provided-output and mock-output handling for compact marketing-planning output summaries.
- [ ] 2.2 Parse SSE-style raw output into compact event, card, session, fallback, completion, and sanitized error summaries.
- [ ] 2.3 Ensure large raw SSE/card payloads remain out of persisted case-pool and compact batch status data.
- [ ] 2.4 Align provided references and judge-generated reference contracts to the same top-level summary shape as output.
- [ ] 2.5 Mark judge-generated references explicitly for frontend display when input has no reference.

## 3. Judge, Attribution, and Mock Cases

- [ ] 3.1 Build marketing-planning judge context with explicit stage, boundary, session, path dispatch, fallback, SSE, output, and reference evidence.
- [ ] 3.2 Reconcile judge results with deterministic project evidence for stage mismatch, missing required path types, forbidden planning, and disallowed fallback.
- [ ] 3.3 Build attribution context that identifies the earliest observable failing stage across normalization, intent recognition, clarification, session merge, path dispatch, planning, assembly, SSE generation, and adapter extraction.
- [ ] 3.4 Add mock cases covering intent recognition, clarification, multi-turn accumulation, execution planning, fallback/data unavailable, non-agent intent, and streaming protocol behavior.
- [ ] 3.5 Ensure generated mock cases run through `run_chain` and batch APIs with isolated per-case failures.

## 4. Frontend and Batch Behavior

- [ ] 4.1 Update summary-page case-pool persistence to store only durable lightweight case source fields, not full traces, raw streams, full card payloads, judge raw output, or complete frontend views.
- [ ] 4.2 Guard browser storage writes so quota failures do not abort batch polling, completed case rendering, or unrelated cases.
- [ ] 4.3 Render structured output and reference as formatted comparable JSON in table and details views with matching visual treatment.
- [ ] 4.4 Confirm generated, uploaded, saved, and manually edited cases all submit through the generic batch APIs.
- [ ] 4.5 Remove the explicit mock-output execution mode from frontend, API, CLI, and core pipeline. Mock cases/datasets are simulated evaluation data and may carry provided `output`; after case construction, execution must go through the unified live/provided-output batch API with `output_source` recorded as run evidence.

## 5. Verification and Check Report

- [ ] 5.1 Run Python compile validation for `impl` and confirm project listing includes `marketting-planning` alongside existing projects.
- [ ] 5.2 Verify `marketting-planning` mock cases through `/api/mock_cases`, `/api/run_chain`, `/api/batch_start`, and `/api/batch_status` without requiring external service startup.
- [ ] 5.3 Smoke-test the frontend summary flow for mock case generation, batch attribution, output/reference display, and storage quota resilience.
- [ ] 5.4 Produce a check-agent audit report under `search-test-case/issue` covering protocol alignment, mechanism evidence, overfit risks, batch/session isolation, frontend persistence behavior, live-UAT limitations, and verification results.
- [ ] 5.5 Confirm no external `/Users/xiaozijian/WorkSpace/package/marketing-planning` code was modified or pushed.
