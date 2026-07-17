# VNext Case Protocol Hard Cutover Design

## Goal

Complete the repository-wide VNext case protocol migration so stored and transported cases have one shape, runtime cases have one shape, and project request semantics never leak into frontend result association.

The migration covers core code, APIs, frontend state, project adapters, mock data, evaluation datasets, schema fixtures, test fixtures, and batch execution. Historical context-store records remain immutable evidence.

## Authoritative Baseline

The migration uses the current working-tree VNext schema direction as its baseline:

- `MockCase` is the only persisted and transported case format.
- `SingleTurnCase` and `MultiTurnCase` are internal runtime values only.
- `MockCase.live_request` exactly conforms to the project `REQUEST_SCHEMA`.
- `RunTrace` is the complete execution fact record.
- `RunTrace.extracted_output` is one project `EXTRACT_OUTPUT_SCHEMA` value.
- Multi-turn history belongs to `RunTrace.turn_records`, not to project output.
- `ProjectAdapter` is a role loader; project behavior remains in project role implementations.
- `project.yaml` and project `live_schema.py` remain the project-specific sources of truth.

Historical `bak` or `old` specifications are not normative. The earlier frontend canonical-input merge guard is superseded by protocol-level request identity and must not be retained as the result-association mechanism.

## Architecture

```text
verifier/data/**/*
impl/data/*/mock_cases.json
schema/test fixtures
frontend import and Mock APIs
            |
            v
         MockCase
            |
            | one protocol-boundary conversion
            v
   SingleTurnCase / MultiTurnCase
            |
            v
         pipeline
            |
            v
         RunTrace
            |
            v
   BatchResult / frontend display
```

No consumer may persist a runtime case. No pipeline entry point may receive a storage MockCase without first converting it at the designated protocol boundary.

## Canonical Case Contracts

### MockCase

Every persisted or transported case has these fields:

- `id`
- `project_id`
- `scenario`
- `intent`
- `live_request`
- `output`
- `reference`

`intent` preserves user semantics independently of API request shape. `live_request` contains only the project request. `output` and `reference` are governed by the ready contract and remain explicitly `null` when absent.

### Runtime cases

`SingleTurnCase` and `MultiTurnCase` exist only inside Python execution. A single shared converter transforms MockCase into the appropriate runtime case exactly once. Internal code must not reconstruct MockCase semantics heuristically.

### RunTrace

- `input` is the actual project request used for execution.
- `normalized_request` is the project-normalized request.
- `extracted_output` is the final valid business output.
- `turn_records` owns per-turn requests, outputs, statuses, errors, and execution facts.
- `conversation_transcript`, `completion_status`, and `stop_reason` remain trace facts.
- A complete MockCase must never appear in `RunTrace.input`.

## Protocol and Project Responsibilities

The protocol layer owns:

- MockCase validation and conversion;
- API request and response schemas;
- batch submission identity and result association;
- trace construction invariants;
- persistence format validation;
- explicit errors for obsolete formats.

The project layer owns:

- `REQUEST_SCHEMA` and `EXTRACT_OUTPUT_SCHEMA`;
- request normalization and delivery;
- output extraction;
- project-specific execution evidence;
- business judging and attribution extensions.

The frontend owns only import/export, selection, execution controls, persistence of MockCase values, and result presentation. It must not infer whether project fields such as `trace_id`, `thread_id`, `history`, or `messages` are semantically significant.

## Batch Identity

Each submitted item receives an immutable protocol `request_key`. Batch events and final runs carry:

- `job_id`
- `request_index`
- `request_key`
- `request_case_id`
- `status`
- `run`

The frontend merges exclusively by this submission identity. It does not compare `RunTrace.input` with project request data. The pipeline verifies that a result remains bound to the submitted request identity and emits `protocol_identity_mismatch` on violation.

The active `job_id` and submitted case snapshot are recoverable after page reload. Running rows show `running`; failed rows show the protocol stage, case identity, and concrete error.

## Data Migration Scope

### Migrated

- `verifier/data/**/*` evaluation datasets;
- `impl/data/*/mock_cases.json` project fixtures;
- `impl/data/case_pools.json`;
- `impl/core/schema/fixture/**/*`;
- test fixture files and embedded fixture objects;
- API examples and CLI payload fixtures;
- frontend import/export persistence.

Dataset envelopes and indexes remain dataset metadata, while every contained case becomes MockCase.

Migration preserves IDs, requests, outputs, references, and authoritative business metadata. It must not regenerate business content. Records that cannot be mapped deterministically are written to a quarantine report and excluded from runnable datasets until reviewed.

### Preserved read-only

- `impl/data/context_store/**/*` historical RunTrace, Judge, and Attribute artifacts;
- source review files such as spreadsheets unless a loader explicitly materializes MockCase values from them;
- dataset provenance records such as upload-batch indexes.

Historical records are not rewritten because doing so would falsify the format and facts produced at their original execution time.

## Hard-Cutover Behavior

After migration:

- storage and transport boundaries reject legacy `input` case objects;
- pipeline boundaries reject raw MockCase values that bypass conversion;
- no permanent dual-format fallback remains;
- project adapters do not add compatibility branches;
- frontend import reports obsolete-format errors rather than silently wrapping data;
- migration tooling is explicit and one-shot, not used as a runtime fallback.

## Error Handling

Errors identify the violated boundary and record path:

- `mock_case_schema_invalid`
- `runtime_case_boundary_violation`
- `request_schema_invalid`
- `protocol_identity_mismatch`
- `legacy_case_format_rejected`
- `case_migration_quarantined`

Errors must remain visible through batch events, final results, CLI output, and frontend rows. Sanitization or persistence must not reset a real error to `pending`.

## Migration Sequence

1. Freeze canonical schemas and add contract tests.
2. Implement the single MockCase-to-runtime conversion boundary.
3. Align API, CLI, persistence, and batch envelopes.
4. Align trace construction and remove obsolete aggregate aliases.
5. Migrate project mock fixtures and schema fixtures.
6. Migrate `verifier/data` evaluation datasets and indexes.
7. Migrate case pools, frontend import/export, and batch recovery.
8. Remove legacy compatibility paths.
9. Run focused and full regression gates.
10. Perform browser UAT on the actual summary page.

Each phase must preserve unrelated working-tree changes and must not rewrite historical context-store evidence.

## Verification Gates

### Schema and static gates

- adapter compliance for every project;
- protocol compliance for every project;
- schema hook fixtures;
- no runtime persistence of SingleTurnCase or MultiTurnCase;
- no project-specific merge logic in the frontend;
- no live output schema with a top-level aggregate `turns` field.

### Data gates

- every project mock fixture is valid MockCase;
- every case under `verifier/data` is valid MockCase;
- dataset index counts match migrated case counts;
- IDs, request content, outputs, and references match the pre-migration source;
- quarantine count is zero or explicitly reviewed;
- context-store files have no migration diff.

### Runtime gates

- MockCase converts exactly once to a runtime case;
- `RunTrace.input` equals the delivered request shape;
- `RunTrace.extracted_output` conforms to project output schema;
- multi-turn facts remain in `turn_records`;
- concurrent batch events retain request identity;
- deliberately swapped A/B results produce `protocol_identity_mismatch`;
- page reload resumes the active batch and repopulates completed rows.

### Project and UAT gates

Run adapter compliance, protocol compliance, mock-check, and run-chain for:

- QA
- client_search
- deerflow
- marketting-planning
- marketting-planning-intent

Browser UAT verifies the existing one-row layout, adjacent Output and Reference, final wide Trace column, live partial result updates, explicit row errors, and reload recovery on `http://127.0.0.1:8021/frontend/summary.html`.

## Acceptance Criteria

The migration is complete when:

1. Every non-historical stored or transported case is MockCase.
2. Runtime case types never cross storage or API boundaries.
3. Every project receives only its declared request shape.
4. A complete MockCase never appears in `RunTrace.input`.
5. Batch results associate by protocol request identity without frontend semantic comparison.
6. All project code, project fixtures, core fixtures, test fixtures, `impl/data`, and `verifier/data` pass VNext validation.
7. Historical context-store evidence remains unchanged.
8. Focused tests, full regressions, and actual browser UAT pass without legacy-format fallbacks.
