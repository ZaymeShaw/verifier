# Run Trace Protocol

`RunTrace` is the normalized execution record produced by live or batch runs.

Fields:

- `trace_id`
- `project_id`
- `input`
- `normalized_request`
- `raw_response`
- `extracted_output`
- `project_fields`
- `runtime_logs`
- `evidence_refs`
- `execution_trace`
- `status`
- `error`
- `created_at`

Rules:

- `raw_response` preserves the original project response. When the caller provides an evaluated output in the input, the adapter must convert that provided output into the project-equivalent raw response shape and record it here instead of calling the project service.
- `extracted_output` contains the adapter-normalized output used by judge and frontend summaries.
- `project_fields` may hold project-specific fields, but generic core code must not require their names.
- `execution_trace` records coarse executable stages such as request normalization, project API call or provided-output capture, response capture, and adapter extraction; project adapters may add deeper chain nodes when they can verify existing business code paths.
- Mock and live runs must normalize into semantically equivalent `RunTrace` inputs for judge and attribute. If live traces expose project evidence such as matched fields, retrieved rules, or routing basis, mock traces for the same project should expose equivalent evidence instead of only final outputs.
- Projects decide whether a run should call the business API or evaluate a provided output: if the normalized input does not contain `output`/`response`/`raw_response`, the adapter calls the project API; if it does contain one of those fields, the adapter directly extracts that output into the same `RunTrace` protocol.
- Every judge or attribution result should point back to a `trace_id`.
