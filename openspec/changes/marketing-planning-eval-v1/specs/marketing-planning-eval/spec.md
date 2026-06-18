## ADDED Requirements

### Requirement: Marketing-planning project integration
The system SHALL provide a `marketting-planning` project integration that runs through the existing verifier pipeline without project-private orchestration endpoints.

#### Scenario: Project is listed
- **WHEN** the user lists verifier projects
- **THEN** the result includes `marketting-planning` alongside existing projects.

#### Scenario: Unified chain execution
- **WHEN** a marketing-planning case is submitted to the generic `/api/run_chain` endpoint
- **THEN** the system produces a `RunTrace`, `JudgeResult`, `AttributeResult`, `ClusterSummary`, `CheckReport`, and `FrontendViewModel` using the same core pipeline as other projects.

### Requirement: Multi-turn case normalization
The system SHALL accept marketing-planning cases that describe user intent, ordered turns, scenario, expected stage, expected path types, expected cards, reference contract, output, metadata, and boundary information.

#### Scenario: Single-turn case
- **WHEN** a case contains a single user query and scenario metadata
- **THEN** the adapter normalizes it into a project request with a stable case identity and an isolated session identity.

#### Scenario: Multi-turn case
- **WHEN** a case contains ordered turns
- **THEN** the adapter preserves turn order, current-turn context, accumulated session expectations, and expected stage evidence in the normalized request.

#### Scenario: Batch case isolation
- **WHEN** multiple marketing-planning cases run in a batch
- **THEN** each case uses an isolated session identity unless the case explicitly declares a shared-session scenario.

### Requirement: SSE and card output summary
The system SHALL normalize marketing-planning SSE streams, provided outputs, or mock outputs into a compact output summary suitable for judge, attribute, frontend display, and batch persistence.

#### Scenario: SSE output is provided
- **WHEN** raw output contains SSE-style events
- **THEN** the adapter extracts event order, event counts, final completion state, card summaries, session summary, fallback markers, and sanitized errors into `RunTrace.extracted_output` and `project_fields`.

#### Scenario: Card payload is large
- **WHEN** raw card data contains large nested tables or AI analysis text
- **THEN** the persisted case-pool and compact batch status exclude oversized raw payloads while preserving compact evidence needed for judging.

#### Scenario: Provided output is not SSE
- **WHEN** a case provides a compact output object directly
- **THEN** the adapter accepts it and aligns it into the same summary shape as SSE-derived output.

### Requirement: Conditional reference contract
The system SHALL use a marketing-planning reference contract aligned to the output summary shape rather than requiring an exact golden answer string.

#### Scenario: Reference is provided
- **WHEN** a case provides expected stage, events, path types, cards, fallback allowance, session fields, or semantic requirements
- **THEN** the judge receives those expectations as structured reference evidence aligned to the extracted output shape.

#### Scenario: Reference is missing
- **WHEN** a case has no reference
- **THEN** the judge may generate a reference contract from the current input and project standards, and the frontend marks the reference source as judge-generated.

### Requirement: Stage-aware judgement and attribution context
The system SHALL supply judge and attribute contexts that make marketing-planning stage, boundary, session, path dispatch, fallback, and SSE evidence explicit.

#### Scenario: Clarification expected
- **WHEN** the reference expects clarification
- **THEN** planning cards are treated as suspicious or wrong evidence unless the boundary explicitly permits planning.

#### Scenario: Planning expected
- **WHEN** the reference expects planning for selected path types
- **THEN** missing selected paths, extra unselected paths, wrong card identities, or disallowed fallback are exposed as judge evidence.

#### Scenario: Attribution on failure
- **WHEN** judge finds a marketing-planning failure
- **THEN** attribution evidence identifies the earliest observable failing stage among request normalization, intent recognition, field clarification, session merge, path dispatch, planning function, result assembly, SSE generation, or adapter extraction.

### Requirement: Marketing-planning mock cases
The system SHALL provide mock cases covering the main marketing-planning evaluation scenarios without relying on external service availability.

#### Scenario: Mock case generation
- **WHEN** the user requests mock cases for `marketting-planning`
- **THEN** cases cover intent recognition, clarification, multi-turn field accumulation, execution planning, fallback/data unavailable, non-agent intent, and streaming protocol behavior.

#### Scenario: Mock cases run in batch
- **WHEN** generated marketing-planning mock cases are run through batch execution
- **THEN** individual failures are isolated and do not stop unrelated cases.

### Requirement: Check-agent audit report
The system SHALL produce a check-agent audit report for the marketing-planning integration.

#### Scenario: Check report is generated
- **WHEN** the integration is implemented
- **THEN** a report under `search-test-case/issue` records protocol alignment, mechanism evidence, overfit risks, batch/session isolation, frontend persistence behavior, live-UAT limitations, and verification results.
