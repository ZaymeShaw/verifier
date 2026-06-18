## 1. Reproduction and Evidence

- [x] 1.1 Reproduce the client_search summary flow where batch attribution completion makes the case-pool candidate area empty or lose completed rows.
- [x] 1.2 Identify the exact boundary that drops rows: batch status response shape, progress event handling, final run merge, filtering, render path, or storage persistence.
- [x] 1.3 Capture a representative failing fixture for `client_search_value_service_100-006` including source row identity and compact run result.

## 2. Regression Coverage

- [x] 2.1 Add a frontend/UAT regression test that applies a completed client_search run to an existing candidate row and asserts the row remains visible with source fields preserved.
- [x] 2.2 Add a regression test for uncertain/error client_search runs so they update row status/evidence without removing the row.
- [x] 2.3 Add a regression test for quota/storage write failure during batch polling so rendering and later case updates continue.
- [x] 2.4 Add a regression test for malformed or empty final batch status so the existing candidate pool is not replaced by an empty pool.

## 3. Frontend Case-Pool Retention Fix

- [x] 3.1 Update `impl/frontend/summary.html` batch run/event application to merge run overlays into existing rows by stable `id`/`case_id` instead of replacing the candidate pool with raw runs.
- [x] 3.2 Preserve source fields (`id`, `input`, `reference`, `metadata`, `scenario`, `dataset_id`, `dimension_type`, `selected`, `source`) when applying run fields.
- [x] 3.3 Keep uncertain, incorrect, and error rows renderable; do not filter them out after batch completion.
- [x] 3.4 Add bounded diagnostics when final batch status has no mergeable runs or a run lacks stable identity.

## 4. Persistence and Compact Payload Safety

- [x] 4.1 Ensure case-pool persistence stores only lightweight source/status fields and never full client_search `matched_patterns`, raw judge model output, downstream payloads, or full frontend views.
- [x] 4.2 Ensure storage write failures are caught and surfaced as bounded diagnostics without aborting polling or clearing in-memory rows.
- [x] 4.3 Confirm backend compact run/status output remains sufficient for frontend row rendering without forcing full raw traces into polling responses.

## 5. Verification and Report

- [x] 5.1 Run targeted client_search case-pool retention tests and existing marketing-planning UAT tests to ensure the previous fix is not regressed.
- [x] 5.2 Run `python -m compileall -q impl` and relevant CLI/API smoke checks.
- [x] 5.3 Manually smoke-test summary frontend/API flow: load/generate client_search cases, run batch attribution, confirm candidate rows remain visible after completion.
- [x] 5.4 Produce a check-agent report under `search-test-case/issue` covering reproduction evidence, root cause, row-retention mechanism, persistence safety, and verification results.
