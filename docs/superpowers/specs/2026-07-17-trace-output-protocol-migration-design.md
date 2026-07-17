# Trace / Output Protocol Migration Design

## Goal

Complete the trace protocol migration without preserving the legacy convention that a multi-turn live output is `{"turns": [...]}`.

After this change:

- `EXTRACT_OUTPUT_SCHEMA` represents one business call's normalized output.
- Every multi-turn output independently conforms to that schema.
- `execute_live()` returns the last valid turn output.
- `RunTrace.turn_records` is the sole owner of the full turn sequence and execution facts.
- Judge evaluates a deterministic projection of the trace rather than reading transport-private data.

## Scope

The migration covers every current `MultiTurnInteractiveLive` project:

- `marketting-planning`
- `deerflow`

It also fixes directly exposed protocol inconsistencies found during the migration review:

- `marketting-planning-intent` request-type mismatch.
- QA provided-output validation accepting an unknown or empty answer as successful.
- Judge evidence exposing successful-turn raw responses through `turn_records`.
- Incomplete `expected_intent` to `user_intent` Judge API migration.

Unrelated working-tree changes and historical context-store data are outside scope.

## Multi-turn Output Contract

### Project schemas

- `marketting-planning.EXTRACT_OUTPUT_SCHEMA` becomes the single-turn marketing-planning output schema.
- `deerflow.EXTRACT_OUTPUT_SCHEMA` becomes the single-turn Deerflow output schema.
- Aggregate wrapper schemas with a top-level `turns` field must not be accepted as live outputs.

If an aggregate model remains useful for a frontend or report, it must be explicitly named as a trace/view model and must not be registered as `EXTRACT_OUTPUT_SCHEMA`.

### Consumers

Consumers use:

- `trace.extracted_output` for the final normalized business output.
- `trace.turn_records` for all turns, requests, statuses, errors, and per-turn outputs.
- `trace.conversation_transcript` for conversational content.
- `trace.application_boundary` for the latest applicable business boundary.

Project code must not reconstruct the execution history from `extracted_output["turns"]`, and no compatibility fallback will silently accept both structures.

## Live Request Contract

Project live extension points receive the project request value that conforms to `REQUEST_SCHEMA`. A project must not assume that this value is the retired `LiveRequest` transport wrapper.

`deliver_real`, `extract_output`, `application_boundary`, `project_fields`, and `build_execution_trace` will use the same request convention. Project-specific execution evidence will derive from the normalized project request, not from `.raw_input` or `.normalized_request` attributes that may not exist.

## Provided-output Validation

Provided-output extraction may normalize explicitly supported aliases, but it must not turn an unknown payload into an empty valid output.

For QA:

- At least one declared answer field must be present.
- The normalized `actual_answer` must be non-empty.
- Unknown-only, empty, or structurally invalid payloads produce an error trace.
- No fallback answer is synthesized to make schema validation pass.

## Judge Evidence Contract

The source of Judge evidence remains `RunTrace`, but the Judge receives a deterministic projection.

For each successful turn, the projection may include:

- turn index
- normalized request or compact request evidence
- extracted output
- call status and error
- validation and execution-trace evidence
- application boundary and project fields where required

It excludes raw response transport payloads. For failed or incomplete execution, a compact and bounded `raw_response_evidence` may be included explicitly. Raw response must not re-enter through nested `turns` records.

## Judge Intent Contract

- The common Judge API parameter is `user_intent`.
- Expected classification labels belong to `trace.reference_contract`, not to `user_intent`.
- Production implementations, enabled drafts, pipeline callers, and tests migrate together.
- A compatibility alias is only acceptable at an external boundary if necessary and must not merge expected labels into user intent. The preferred implementation is a complete internal migration without a permanent dual API.

## Verification

### Unit and protocol tests

- Both multi-turn project schemas accept one turn output and reject `{"turns": [...]}`.
- Multi-turn `execute_live()` returns the last valid turn and retains every turn in `TraceContext` / `RunTrace`.
- Real project extension-point tests exercise request values with the same type used by the protocol.
- QA unknown-only and empty provided outputs produce error traces.
- Judge evidence recursively contains no successful-turn raw response.
- Judge production and draft implementations accept the unified intent API.

### API UAT

Using the API configuration from `impl/config.yaml` and the running UAT service:

- QA valid provided output and invalid provided output.
- QA incorrect-answer `run_chain`, which must remain judgeable as not fulfilled.
- client_search live and run-chain cases, preserving parser/downstream boundary semantics.
- marketting-planning-intent live and run-chain cases.
- marketting-planning explicit `interactive_intent` multi-turn live and run-chain cases.
- Deerflow explicit multi-turn case when its external dependency is available; otherwise verify that the trace records an explicit dependency failure without schema fallback.

## Acceptance Criteria

The change is complete when:

1. No current multi-turn project registers a top-level `turns` aggregate as `EXTRACT_OUTPUT_SCHEMA`.
2. No consumer requires `trace.extracted_output["turns"]` to evaluate a multi-turn run.
3. Project request extension points run without wrapper/dict type mismatches.
4. Invalid provided outputs cannot be recorded as successful completed runs.
5. Successful Judge evidence contains no raw response at any nesting level.
6. The focused unit suite passes and API UAT demonstrates the expected success or explicit failure semantics for every in-scope project.

