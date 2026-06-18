## ADDED Requirements

### Requirement: Project adapters may own complex interaction shapes
The verifier project-adapter contract SHALL allow project-specific adapters to normalize complex interaction shapes such as multi-turn sessions, event streams, and structured cards without adding those project-specific fields as required core schema fields.

#### Scenario: Project-specific multi-turn input
- **WHEN** a project adapter receives an input containing project-specific multi-turn fields
- **THEN** the adapter normalizes them into `RunTrace.normalized_request`, `RunTrace.project_fields`, and `RunTrace.execution_trace` while keeping the core pipeline unchanged.

#### Scenario: Project-specific event stream output
- **WHEN** a project adapter receives stream-oriented output
- **THEN** the adapter extracts a compact summary into `RunTrace.extracted_output` and records detailed stream evidence only in project-owned fields or raw response.

### Requirement: Project adapters define boundary before judge
The verifier project-adapter contract SHALL support project-owned boundary decisions that are computed before judge and passed into judge and attribution contexts.

#### Scenario: External dependency unavailable
- **WHEN** an adapter detects that an external service, data source, session store, or model dependency is unavailable
- **THEN** it records the boundary and verification status in project fields before judge runs.

#### Scenario: Boundary affects verdict scope
- **WHEN** a project boundary excludes or includes a class of evidence
- **THEN** judge and attribute contexts receive that decision as current-case evidence rather than independently rediscovering or guessing the boundary.

### Requirement: Project adapters preserve unified pipeline semantics
The verifier project-adapter contract SHALL NOT permit project adapters to bypass the shared `live_run`, `judge`, `attribute`, `cluster`, `check`, and `frontend_view` pipeline for normal verifier usage.

#### Scenario: Project-specific behavior is needed
- **WHEN** a project needs special request, output, judge, or attribution behavior
- **THEN** it implements that behavior through adapter hooks and project documents rather than separate backend endpoints or duplicate frontend orchestration.
