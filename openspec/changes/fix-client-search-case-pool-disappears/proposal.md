## Why

Running client_search attribution from the summary case-pool flow can leave the candidate area empty or missing the completed rows, making users lose the very cases they just evaluated. This blocks UAT because the frontend result no longer matches the backend batch evidence and users cannot inspect the incorrect/uncertain rows after attribution completes.

## What Changes

- Preserve client_search case-pool candidate rows across batch attribution completion, polling, errors, and storage quota failures.
- Ensure completed run fields update the visible row without replacing the whole candidate pool with an empty or malformed batch result.
- Keep persistence lightweight: do not store full raw traces, large matched-pattern payloads, judge raw model output, or full frontend views in browser storage.
- Add regression coverage for client_search batch attribution so candidate rows remain visible after completed, incorrect, uncertain, and per-case error runs.
- Add diagnostic evidence for the specific disappearance path so future failures show whether the loss came from API shape, event handling, row merge, filtering, or storage write failure.

## Capabilities

### New Capabilities
- `summary-case-pool-retention`: The summary frontend preserves selected/generated/uploaded case-pool candidates while applying batch attribution results and compact persistence.

### Modified Capabilities

## Impact

- Affected frontend: `impl/frontend/summary.html` case-pool state, batch polling, row merge, filtering, rendering, and storage persistence.
- Affected backend if needed: compact batch status shape in `impl/server.py` and batch run identity fields in `impl/core/pipeline.py`.
- Affected tests: UAT/regression tests for summary candidate row construction and client_search batch status handling.
- No external client_search business service or external repository should be modified by this verifier change.
