## Context

The summary frontend keeps a `casePool` for generated, uploaded, saved, and manually edited cases. Batch attribution updates that pool from `/api/batch_start` and `/api/batch_status` events. Recent marketing-planning work already established two relevant constraints: frontend persistence must be lightweight, and visible rows must be populated from the same backend run that produced trace/judge/attribute/frontend_view.

The client_search disappearance report points to a similar consistency gap in the batch result merge path: after attribution finishes, the candidate area can become empty even though backend evidence exists in `impl/data/case_pools.json` and the batch run completed per case. The fix must preserve visible candidates while still avoiding browser quota failures from very large client_search traces, especially `matched_patterns` and raw model output.

## Goals / Non-Goals

**Goals:**

- Reproduce the client_search summary flow where candidate rows disappear after attribution.
- Preserve candidate rows after batch progress events, final status payloads, per-case errors, and storage quota failures.
- Ensure completed row fields (`status`, `trace`, `judge`, `attribute`, `frontend_view`, `execution_mode`, `output_source`, `error`) come from the corresponding backend run without losing source fields (`id`, `input`, `reference`, `metadata`, `scenario`, `dataset_id`, `dimension_type`, `selected`, `source`).
- Persist only lightweight case-pool state; full raw traces and large client_search evidence must remain out of browser storage.
- Add regression tests that model the exact disappearance mechanism rather than only asserting a happy-path batch response.

**Non-Goals:**

- Do not modify the external client_search business service or downstream search service.
- Do not change client_search business judge semantics such as whether `plantypedesc MATCH 年金` is correct; this change is about retaining frontend candidate rows after attribution.
- Do not reintroduce separate mock execution modes.

## Decisions

1. Treat `casePool` as durable source rows plus ephemeral run overlays.
   - The row merge must start from the existing case by `id/case_id`, then overlay compact run result fields.
   - It must not replace the whole pool with `result.runs` unless those runs have been explicitly converted back into full candidate rows.
   - Alternative rejected: reload candidate rows from storage after batch completion. That reintroduces quota sensitivity and can discard the just-completed in-memory results.

2. Keep storage writes best-effort and lightweight.
   - Persist source fields and compact status/error summaries only.
   - Do not persist full `trace.project_fields.matched_patterns`, downstream payloads, raw judge model output, raw streams, or full frontend views.
   - Alternative rejected: disable persistence entirely during batch. That would prevent quota failures but makes refresh/navigation lose the candidate pool.

3. Make regression tests operate on the frontend row-merge contract.
   - Tests should build representative client_search case rows and compact backend runs, then assert rows remain visible after applying final runs.
   - Include an uncertain/error run so fallback status does not filter or erase the row.
   - Alternative rejected: only testing backend `batch_run`; the reported symptom is frontend candidate disappearance after backend completion.

4. Add diagnostic evidence at the boundary where disappearance can happen.
   - If a batch status payload has no runs, malformed case identity, or storage failure, the UI should continue rendering the existing pool and surface a bounded warning.
   - This avoids silent empty-state transitions.

## Risks / Trade-offs

- Risk: keeping full run overlays in memory can still be large for client_search. → Mitigation: persist compact source rows only, and rely on backend compact status to strip raw model output and large traces.
- Risk: preserving rows after malformed status may hide a backend bug. → Mitigation: keep visible rows but show bounded diagnostic status/error so the user knows the batch result was incomplete.
- Risk: row identity mismatch can merge a run into the wrong case. → Mitigation: require exact `case_id`/`id` matching and keep unmatched runs as diagnostic rows only if they carry a stable identity.
