## ADDED Requirements

### Requirement: Project implementation standard is explicit
Each verifier project SHALL provide a project implementation standard that makes API, application, mock, judge, attribution, frontend, batch, and persistence behavior inspectable.

#### Scenario: Project standard can be audited
- **WHEN** a check audits `impl/projects/<project>`
- **THEN** it can identify the source standard for API shape, request construction, output extraction, reference handling, judge boundary, attribution trace, frontend view, and batch persistence

#### Scenario: Project implementation follows generic protocols
- **WHEN** project-specific behavior is implemented
- **THEN** generic orchestration remains in shared protocols/core and only project-specific business behavior lives under `impl/projects/<project>`

#### Scenario: Missing project standard is reported
- **WHEN** a project lacks required implementation-standard fields
- **THEN** check reports the missing fields as a project readiness issue rather than silently relying on adapter defaults

### Requirement: Project source artifacts remain consistent
The system SHALL keep generated project docs, project config, adapter behavior, and frontend views aligned with the newest project standard.

#### Scenario: Generated artifact is stale
- **WHEN** a generated project doc, checklist, frontend view, or mock dataset conflicts with the current project standard
- **THEN** check identifies the producing mechanism and recommends fixing the source mechanism instead of editing the stale artifact alone

#### Scenario: Cross-project compatibility is preserved
- **WHEN** the project implementation standard is applied to a new or existing project
- **THEN** representative QA, client_search, marketting-planning, and marketting-planning-intent runs remain listed and executable through the unified pipeline
