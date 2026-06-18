## ADDED Requirements

### Requirement: Check produces demand-aligned gap reports
The system SHALL allow check agent to audit the current verifier implementation against the latest `demand.md` and `check.md` and produce actionable Chinese gap reports.

#### Scenario: Demand is updated
- **WHEN** `demand.md` changes
- **THEN** check reconstructs the latest user intent from the current demand and project docs before evaluating implementation state

#### Scenario: Check finds a mechanism gap
- **WHEN** check identifies a protocol mismatch, stale artifact, split-brain flow, overfit rule, frontend/API inconsistency, batch persistence risk, or ungrounded attribution
- **THEN** it records evidence, root cause, blast radius, proposed generalized fix, and verification plan

#### Scenario: Gap becomes implementation work
- **WHEN** the user asks to treat check findings as a change
- **THEN** the findings are converted into OpenSpec proposal, specs, design, and task artifacts that can be implemented later

### Requirement: Check audits producing mechanisms before visible outputs
The system SHALL verify that visible reports, frontend cells, datasets, and attribution summaries are produced by the current source mechanisms.

#### Scenario: Visible output looks correct
- **WHEN** a frontend view or report appears correct
- **THEN** check also verifies that the source pipeline, generator, adapter normalization, judge, attribution, persistence, and rendering paths would reproduce the result for new cases

#### Scenario: Local patch bypasses source mechanism
- **WHEN** an artifact was manually edited while the source generator or protocol still produces stale data
- **THEN** check marks the issue unresolved and recommends fixing the source mechanism

### Requirement: Check includes verification evidence
The system SHALL require check reports to include verification evidence for the claims they make.

#### Scenario: Check says an issue is fixed
- **WHEN** check marks a gap as resolved
- **THEN** the report includes fresh verification commands, browser/API smoke evidence when relevant, and the affected files or mechanisms inspected

#### Scenario: Verification cannot be completed
- **WHEN** a service, browser flow, or external model call cannot be verified
- **THEN** check records the unverified item explicitly instead of claiming completion
