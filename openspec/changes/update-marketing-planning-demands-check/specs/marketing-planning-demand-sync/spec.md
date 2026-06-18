## ADDED Requirements

### Requirement: Recorded divergence points drive the audit
The system SHALL treat `impl/projects/marketting-planning/issue/20260611-marketplan-integration-risks.md` and `reviews-of-propose/20260611-marketplan-integration-risks.md` as the primary checklist for this change.

#### Scenario: Divergence matrix is created
- **WHEN** implementation begins for this change
- **THEN** the audit maps each recorded divergence point to the selected treatment, implementation evidence, test or verification evidence, and any remaining limit

#### Scenario: Divergence treatment is missing
- **WHEN** a recorded treatment is only documented but not enforced by adapter behavior, tests, frontend/server behavior, or check output
- **THEN** the implementation adds the smallest missing mechanism using TDD for behavior changes

#### Scenario: Divergence point needs no code change
- **WHEN** current implementation already enforces a divergence treatment
- **THEN** the check report records the no-change decision with source evidence instead of rewriting the area

### Requirement: Updated marketing-planning demands are reconciled with current implementation
The system SHALL compare the latest `demand.md` and `projects/marketting-planning/marketplan-demand.md` requirements against the current `marketting-planning` verifier implementation before applying code changes.

#### Scenario: Demand sync starts from current state
- **WHEN** implementation begins for this change
- **THEN** the current project docs, adapter, frontend/server compacting behavior, tests, and prior check report are inspected against the updated demand files

#### Scenario: Scope is limited to proven gaps
- **WHEN** the demand sync finds no behavior gap in an area
- **THEN** the implementation does not rewrite that area only for cleanup or preference

### Requirement: Historical project semantics are preserved
The system SHALL preserve existing QA and client_search behavior while updating marketing-planning demand handling.

#### Scenario: QA reference semantics remain stable
- **WHEN** QA cases include `actual_answer` and `golden_answer`
- **THEN** the verifier continues treating output as `actual_answer` and reference as `golden_answer`

#### Scenario: Existing projects remain registered
- **WHEN** project listing is checked after the change
- **THEN** `QA`, `client_search`, and `marketting-planning` are all present

### Requirement: External marketing-planning repository remains read-only
The system MUST NOT modify or push the external `/Users/xiaozijian/WorkSpace/package/marketing-planning` repository unless the user explicitly requests it.

#### Scenario: Demand sync completes
- **WHEN** verification is reported
- **THEN** the report states whether the external marketing-planning repository was left unmodified
