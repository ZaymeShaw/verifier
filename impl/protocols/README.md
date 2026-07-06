# Protocols

This directory defines the generic evaluation chain used by `impl`.

Agent responsibility boundaries are defined in `agent_role_protocol.md`: ownership follows capabilities, not whether an agent writes code. Capability agents may implement project-specific code inside their own boundary, while shared cross-capability glue must follow project implementation standards.

```text
ProjectSpec / MockCase
  -> LiveRequest
  -> LiveExecutionResult
  -> RunTrace
  -> JudgeResult
  -> AttributeResult
  -> CheckReport / ClusterSummary
  -> FrontendViewModel / CasePoolTable / TraceTableRow
```

The core system only depends on these protocols. Project-specific API formats, business fields, ports, prompts, and code paths belong in `impl/projects/<project>` and are adapted into the shared carriers above.

`project_fields` is not a second protocol. It may carry adapter-private debug/display details that are surfaced as `schema_protocol_extensions`, but shared facts must use typed protocol fields:

- reference or expected contract: `RunTrace.reference_contract` and normalized request/reference fields
- scenario: `RunTrace.scenario`
- execution mode: `LiveRequest.execution_mode` / `RunTrace.execution_mode`
- output source: `LiveExecutionResult.output_source` / `RunTrace.output_source`
- application boundary: `LiveExecutionResult.application_boundary` / `RunTrace.application_boundary` / judge boundary fields
- case identity: `case_id` / `trace_id`
- multi-turn transcript and summary: `conversation_transcript`, `conversation_summary`, `multi_turn_input`
- data quality and metadata: `normalized_request`

Some project standards use copyable templates outside this directory, such as `impl/judge_boundary-template.md`. These templates are user-facing standards, not generic execution protocols; the generic protocol only defines how filled standards are consumed and how outputs such as `JudgeResult` are structured.

Simple projects may implement only ProjectSpec, ProjectAnalysis, RunTrace, and JudgeResult. Complex projects can add application startup, mock generation, attribution, clustering, batch runs, code evidence, and project-specific frontend extensions.
