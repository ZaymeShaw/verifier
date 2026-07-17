# Case Pool Trace Column Design

## Goal

Make `Trace` visibly distinct from evaluated `Output` in the attribution summary case-pool table, while preserving the current table layout and the existing side-by-side comparison of `Output` and `Reference`.

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

## Presentation

The Trace column is the last table column.

Its collapsed cell summary contains only:

- trace ID;
- execution status;
- an expand control.

Expanding the control reveals the complete formatted `item.trace` JSON inside the cell. The raw JSON uses the table's existing formatted JSON and bounded scrolling conventions so it does not increase the default row height.

`Output` and `Reference` remain adjacent, retain equal width constraints, and continue using their existing renderers. Judge and Attribute remain in the same row and in their current order.

The table keeps its existing horizontal scrolling behavior. The new Trace column receives a bounded width suitable for the compact summary; expanded JSON scrolls within the cell.

## Behavior and Error Handling

- A case with a trace shows its own trace only.
- A case without a trace shows `无 Trace`.
- Clearing or invalidating case results continues to clear `item.trace`; the Trace cell therefore returns to the empty state automatically.
- Trace rendering must escape JSON content through the existing HTML escaping path.
- Expanding Trace is presentation-only and does not mutate, persist, rerun, or request data.

## Verification

Tests and review should verify:

1. The header order ends with `Score / Judge | 归因摘要 | Trace`.
2. Output and Reference remain adjacent and use the existing equal-width CSS rules.
3. Trace is sourced from the current row's `item.trace` only.
4. Missing trace renders a compact empty state.
5. Full Trace JSON is escaped, formatted, collapsed by default, and locally scrollable.
6. Existing case selection, filtering, persistence, stale-result clearing, and batch merging behavior is unchanged.
7. No project ID or project-specific output field is hardcoded into the renderer.

## Design Review

The design is intentionally frontend-only and additive. It avoids changing protocol standards merely to expose data already present on each case row, avoids moving existing business columns, and does not add fallback data that could make stale or unrelated trace information appear valid.
