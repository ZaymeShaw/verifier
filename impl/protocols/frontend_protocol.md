# Frontend Protocol

`FrontendViewModel` is the only structure generic frontend pages should render.

Fields:

- `project_info`
- `run_trace_summary`
- `raw_sections`
- `reference_panel`
- `judge_panel`
- `attribute_panel`
- `fulfillment_panel`
- `expectation_attribution_panel`
- `cluster_panel`
- `check_panel`
- `project_extensions`
- Optional page-level panels for `ProjectAnalysis` and `BatchRunResult`, rendered from their protocol outputs.
- Summary pages should provide protocol-shaped sections for single-chain review, mock dataset construction, case-pool management, batch attribution, cluster summary, and check results without depending on project-private fields.

Rules:

- Build owns project frontend behavior and may implement shared frontend rendering or project frontend configuration, but project-specific display choices must be declared through project frontend standards rather than one-off rendering branches.
- Project selection on live and summary pages must be an enumerable dropdown loaded from the unified projects API; free-text project inputs are not the generic UX.
- Page-local state such as last chain, case pools, selected filters, and uploaded dataset text should be scoped by project id so switching projects does not contaminate another project.
- Persisted or session case-pool rows must not reuse stale trace/judge/attribute results when the stored result input no longer matches the row input. Frontend should clear stale result fields and rerun through the unified batch pipeline.
- Loading a saved single-chain result must apply the same input-matching rule before rendering `RunTrace`, `JudgeResult`, or `AttributeResult`; stale last-chain data must be cleared or blocked rather than shown beside the current input.
- Generic labels should use Input, Output / Evaluated output, Reference, Scenario, Score details; do not use API output as the universal label.
- `reference_panel` should expose the reference shown by the frontend. If input/case data provides a reference, source is `input`; if no reference is provided and judge reconstructs one, source is `judge_generated` and the value is `JudgeResult.expected`; otherwise source is `missing`. The exposed reference must be normalized to the same top-level shape as the evaluated output; if the aligned value is still hard to summarize or is JSON/object-shaped, case-pool tables should render formatted JSON with line breaks rather than comma-joined key snippets, and Output/Reference table cells should use the same visual size for side-by-side comparison.
- Summary/case-pool pages should preserve optional `scenario`, `output`, `reference`, and `metadata` fields and display/filter by scenario when present.
- Project-specific fields are displayed only in `project_extensions` or raw sections.
- Frontend pages must not require one project's private response fields.
- Pages should show whether data came from the latest live run, judge, attribute, cluster, or check step.
- Live and summary pages must render the same protocol objects for Judge and Attribute. They may use different layouts, but they must not omit core `JudgeResult`/`AttributeResult` fields or invent a separate judge display shape that makes the same run look different across pages.
- Summary pages should mirror the single-chain order `RunTrace -> Judge -> Attribute -> Cluster -> Check`, then expose batch/case-pool views as aggregate protocol outputs rather than as separate one-off result shapes.
- Summary pages should make the case pool a first-class workspace: visible stats, named saved pools, candidate table, selection controls, status filter, batch progress, per-case API output, per-case judge/attribute summaries, and cluster overview should be shown before raw JSON drill-downs.
- Case-pool UI state must remain a list of generic case objects with `id`, `input`, optional `expected_intent`, `source`, and `status`; project semantics stay inside `input` or project documents.
- Saved case-pool libraries should store named snapshots of generic case objects in a backend project-scoped store so completed pools can be reloaded after page refresh or later sessions while a new candidate pool is analyzed.
- Uploaded or generated datasets must be converted into the same batch input shape used by `/api/batch_start` + `/api/batch_status`; file upload should parse JSON locally, show the normalized candidate pool, and still submit through the unified async batch job API.
- Summary pages should call generic mock and batch APIs rather than duplicating mock case lists or per-case judge/attribute/cluster/check orchestration in page JavaScript.
- Summary pages should expose batch execution as one unified action with an execution mode (live service or mock response), concurrency, visible loading state, per-case progress from the batch job/status wrapper, and returned batch/cluster/check outputs. Candidate rows must show or drill down to the execution mode/output source used by the same run that produced the displayed Output, Reference, status, Judge, and Attribute fields.
- Live pages should present business request, judge, and attribute outputs as readable collapsible step panels with compact human summaries visible by default and raw JSON available in each panel's details area, not as one growing JSON blob or crowded always-expanded cards.
- Project extension fields must be rendered as compact collapsible drill-down sections with counts or short summaries visible by default; large project-specific JSON must not be dumped inline into the main live summary.
- Summary pages should avoid rendering large persisted chains, raw batch results, or unbounded case tables during initial page load; load heavy raw JSON only on user action or show compact summaries by default.
- Case-pool tables should cap or paginate visible rows while preserving full selected-case execution semantics.
