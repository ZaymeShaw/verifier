## Why

`projects/marketting-planning-intent` has clarified that the current business boundary is the single-turn `/api/v1/marketing-planning/intent-recognition` interface, with intent-recognition extracted from the broader marketing-planning flow. The verifier needs a focused project integration for this intent-only path instead of continuing to treat the demand as a multi-turn planning/stream evaluation.

## What Changes

- Add a focused verifier project for `marketting-planning-intent` that targets `/api/v1/marketing-planning/intent-recognition` as the primary business API.
- Keep the project single-turn for now; do not implement interactive/multi-turn mock-agent behavior in this change.
- Define intent-recognition input/output/reference contracts, mock cases, judge behavior, attribution evidence, and UAT checks for the extracted intent-recognition capability.
- Keep the existing `marketting-planning` stream/planning project separate so the two evaluation scopes do not share or blur verdict semantics; both verifier projects still target the same external marketing-planning business service.
- Add check.md-style audit evidence covering protocol boundary, cross-project compatibility, overfit risk, and frontend/API behavior.

## Capabilities

### New Capabilities
- `marketing-planning-intent-eval`: Evaluates the single-turn marketing-planning intent-recognition interface, including request construction, output normalization, judge/reference semantics, attribution evidence, mock cases, frontend batch support, and UAT verification.

### Modified Capabilities
- None.

## Impact

- New or updated verifier project files under `impl/projects/marketting-planning-intent/`.
- Demand/start context under `projects/marketting-planning-intent/` becomes the source demand for this focused integration.
- Tests under `tests/` for adapter behavior, UAT, frontend project listing/batch handling, and regression compatibility with QA/client_search/marketting-planning.
- Check report under `search-test-case/issue/` documenting why intent-recognition is single-turn and should not depend on the previous interactive mock-agent protocol.
