# Run Trace Protocol

`RunTrace` is the normalized execution record produced by live or batch runs.

Fields:

- `trace_id`: trace identity shared by judge, attribution, check, and frontend projections.
- `project_id`: project implementation that produced the trace.
- `case_id`: original case/sample identity when available.
- `input`: original case or live input as received by the adapter.
- `normalized_request`: adapter-normalized request, including metadata/data-quality flags that downstream logic may consume.
- `raw_response`: original service response or provided output converted into the project-equivalent response shape.
- `extracted_output`: adapter-normalized evaluated output and project-owned runtime evidence that judge/attribute/check may consume.
- `live_result`: optional original `LiveExecutionResult` fact record.
- `execution_mode`: how the trace was produced, such as `live`, `provided`, or `interactive_intent`.
- `output_source`: where the evaluated output came from, such as `live_service`, `provided_output`, or `interactive_adapter`.
- `scenario`: canonical sample/run scenario used by judge, report grouping, and frontend filters.
- `reference_contract`: canonical expected/reference contract for the current trace.
- `application_boundary`: canonical scope and external dependency boundary for the current execution.
- `project_fields`: adapter-private extension/debug/display details only.
- `runtime_logs`
- `evidence_refs`
- `execution_trace`: executable stage evidence.
- `status`
- `error`
- `created_at`
- `state_history`
- `gate_decisions`
- `transition_decisions`
- `stop_reason`
- `interaction_mode`: `single_turn`, `static_turns`, or `interactive_intent`.
- `session_id`
- `turn_index`
- `conversation_transcript`: structured multi-turn conversation turns.
- `conversation_summary`: typed multi-turn summary for judge/frontend/report consumption.
- `multi_turn_input`: original multi-turn intent/policy/input bundle when needed for replay or debugging.
- `fallbacks`: structured fallback decisions.

Rules:

- `raw_response` preserves the original project response. When the caller provides an evaluated output in the input, the adapter must convert that provided output into the project-equivalent raw response shape and record it here instead of calling the project service.
- `extracted_output` contains the adapter-normalized output used by judge, attribute, check, and frontend summaries. Project-owned runtime evidence may live here when downstream logic consumes it as part of the evaluated output contract.
- `reference_contract`, `scenario`, `execution_mode`, `output_source`, and `application_boundary` are canonical top-level fields. They must not be sourced from `project_fields`.
- `project_fields` holds project-specific adapter extras only. It is surfaced externally as `schema_protocol_extensions` for display/debug use and must not become the source of shared protocol facts.
- `conversation_transcript` stores turn-level facts. `conversation_summary` stores the typed summary used by judge/frontend/reporting. `multi_turn_input` stores the original intent/policy bundle and may duplicate human-readable context for replay only; consumers should prefer `conversation_summary` for summary semantics.
- `execution_mode` describes the run path. `output_source` describes the origin of the evaluated output. For example, an interactive adapter run may have `execution_mode=interactive_intent` and `output_source=interactive_adapter`.
- `execution_trace` records coarse executable stages such as request normalization, project API call or provided-output capture, response capture, and adapter extraction; project adapters may add deeper chain nodes when they can verify existing business code paths.
- Mock and live runs must normalize into semantically equivalent `RunTrace` inputs for judge and attribute. If live traces expose project evidence such as matched fields, retrieved rules, or routing basis, mock traces for the same project should expose equivalent evidence instead of only final outputs.
- Projects decide whether a run should call the business API or evaluate a provided output: if the normalized input does not contain `output`/`response`/`raw_response`, the adapter calls the project API; if it does contain one of those fields, the adapter directly extracts that output into the same `RunTrace` protocol.
- Every judge or attribution result should point back to a `trace_id`.
