# Case Pool Trace Column Design

## Goal

Make `Trace` visibly distinct from evaluated `Output` in the attribution summary case-pool table, while preserving the current table layout and the existing side-by-side comparison of `Output` and `Reference`. Output must render only the project `EXTRACT_OUTPUT_SCHEMA` value and must not render trace summaries or trace envelopes.

## Scope

This change only affects the case-pool candidate table in `impl/frontend/summary.html`.

The current row remains structurally unchanged through the attribution columns:

`Input | Output | Reference | Status | Judge | Attribute`

One final column is appended:

`Input | Output | Reference | Status | Judge | Attribute | Trace`

The following areas are explicitly out of scope:

- Live page layout.
- The single-chain result grid below the case-pool table.
- Judge, Attribute, Cluster, Check, Frontend ViewModel, or Batch protocols.
- Backend schema changes, including changes to `FrontendViewModel` or `RunTrace`.
- Project-specific rendering branches.

## Data Source

The Trace column reads the existing `item.trace` object stored on each case-pool row. No new API field or backend display model is introduced.

When no trace exists, the cell shows the existing empty-state style and does not infer trace data from Output, Judge, Attribute, or `frontend_view.run_trace_summary`.

The Output column reads only `item.output`. Batch result merging assigns the current run's `trace.extracted_output` value to `item.output` once, making the stored Output object the project `EXTRACT_OUTPUT_SCHEMA` value. The Output renderer itself must not read `item.trace`, conversation summaries, Judge actual, table summaries, or any other trace-derived display structure.

Reference continues to use the existing aligned reference resolution, but the displayed value must have the same top-level shape as Output. Output and Reference use the same JSON formatting, truncation limit, height, and width.

## Presentation

The Trace column is the last table column.

Its collapsed cell summary contains only:

- trace ID;
- execution status;
- an expand control.

Expanding the control reveals the complete formatted `item.trace` JSON inside the cell. The Trace column has an independent width of approximately 720–900 pixels rather than reusing the 260–420 pixel summary-column width. The raw JSON uses bounded scrolling so it does not increase the default row height without user action.

`Output` and `Reference` remain adjacent and retain equal width constraints. Their renderers display aligned schema-shaped JSON only. Judge and Attribute remain in the same row and in their current order.

The table keeps its existing horizontal scrolling behavior. The new Trace column receives a bounded width suitable for the compact summary; expanded JSON scrolls within the cell.

## Behavior and Error Handling

- A case with a trace shows its own trace only.
- A case without a trace shows `无 Trace`.
- A case with no `item.output` shows an empty Output state; it must not recover Output from Trace, Judge, or interaction summaries.
- Clearing or invalidating case results continues to clear `item.trace`; the Trace cell therefore returns to the empty state automatically.
- Trace rendering must escape JSON content through the existing HTML escaping path.
- Expanding Trace is presentation-only and does not mutate, persist, rerun, or request data.

## Verification

Tests and review should verify:

1. The header order ends with `Score / Judge | 归因摘要 | Trace`.
2. Output and Reference remain adjacent and use the existing equal-width CSS rules.
3. Output is sourced only from `item.output`, contains the project extracted-output value, and does not fall back to Trace, Judge, or conversation summaries.
4. Reference uses the same display shape and formatting as Output.
5. Trace is sourced from the current row's `item.trace` only.
6. Missing trace renders a compact empty state.
7. Full Trace JSON is escaped, formatted, collapsed by default, locally scrollable, and displayed in a 720–900 pixel column.
8. Existing case selection, filtering, persistence, stale-result clearing, and batch merging behavior is unchanged.
9. No project ID or project-specific output field is hardcoded into the renderer.

## Design Review

The design is intentionally frontend-only and additive. It avoids changing protocol standards merely to expose data already present on each case row, avoids moving existing business columns, and removes display fallbacks that could make trace summaries or stale trace data appear to be the evaluated Output. The output renderer remains generic because it consumes the project schema-shaped object without inspecting project IDs or private fields.
