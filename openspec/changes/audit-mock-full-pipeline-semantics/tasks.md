## 1. System Audit and Baseline Evidence

- [x] 1.1 Audit `impl/protocols/mock_protocol.md`, `impl/protocols/batch_protocol.md`, `impl/protocols/run_trace_protocol.md`, and `impl/protocols/frontend_protocol.md` for wording that could imply mock cases are mock-response-only fixtures.
- [x] 1.2 Audit `impl/core/pipeline.py`, `impl/core/adapter.py`, `impl/server.py`, and `impl/frontend/summary.html` to document the current mock case pool to batch to candidate-row data path.
- [x] 1.3 Reproduce the marketting-planning summary-page-equivalent flow with mock case generation and batch attribution, recording whether the frontend-visible candidate fields match the backend batch run fields.
- [x] 1.4 Classify suspected unused or stale functions from the check audit as framework hooks, adapter extension points, protocol entry points, stale-but-used code, or true dead code.

## 2. Red Tests for User-Visible Consistency

- [x] 2.1 Add a failing regression test that simulates `mock_cases -> batch_run -> summary candidate mapping` and asserts visible output, reference, status, judge, attribution summary, case id, and execution mode come from the same run.
- [x] 2.2 Add a failing regression test for rerunning the same case pool with a different execution mode to prove stale output, reference, status, judge, or attribution data is not mixed across runs.
- [x] 2.3 Add or extend a marketting-planning UAT test that runs generated mock cases through the full pipeline path and asserts the candidate-visible fields rather than only backend JSON totals.
- [x] 2.4 Verify each new test fails for the expected reason before changing production implementation.

## 3. Protocol and Implementation Alignment

- [x] 3.1 Update protocol wording so mock case pool semantics clearly mean simulated case/input/reference data for full-pipeline evaluation, while execution mode only marks output source.
- [x] 3.2 Preserve or add run identity evidence in batch results, including case id and execution mode or output-source marker available to the frontend candidate row or details.
- [x] 3.3 Update summary frontend candidate mapping so visible input, output, reference, status, judge, attribution summary, case id, and execution-mode evidence are derived from one backend run result.
- [x] 3.4 Ensure reruns replace prior run-specific fields for each case instead of combining stale and current run data.
- [ ] 3.5 Align marketting-planning mock references and live/mock trace normalization only where needed so generated cases can be evaluated through the unified full pipeline without weakening references or hiding incorrect results.

## 4. Dead/Stale Code Handling

- [ ] 4.1 Remove true dead code only after classification confirms it is not a framework hook, adapter hook, project extension point, or protocol entry point.
- [ ] 4.2 For stale-but-meaningful functions or wording, update them to match the current protocol instead of deleting them.
- [ ] 4.3 Run QA, client_search, and marketting-planning focused regression tests to verify historical output/reference semantics remain intact.

## 5. Verification and Check Report

- [x] 5.1 Run Python compile/static smoke checks for `impl`.
- [x] 5.2 Run the new frontend-summary-equivalent regression tests and focused project UAT tests.
- [x] 5.3 Perform browser or page-equivalent UAT for `summary.html`: clear candidate pool, build mock cases, run batch attribution, and verify the visible candidate rows match test assertions.
- [x] 5.4 Write a Chinese check report under `search-test-case/issue/` covering root mechanism, protocol/frontend/test consistency, unused-function classification, overfit risks, and verification evidence.
- [x] 5.5 Re-run `openspec status --change "audit-mock-full-pipeline-semantics" --json` and confirm the change is ready for apply/archive workflow.
