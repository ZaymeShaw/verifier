## MODIFIED Requirements

### Requirement: Check audit inspects producing mechanisms and user-visible behavior
The system SHALL apply `check.md` audit criteria to both generated artifacts and the mechanisms that produce them, including code paths, protocol alignment, frontend/API consistency, tests, and verification reports.

#### Scenario: Updated marketing-planning audit runs
- **WHEN** the updated demand sync is completed
- **THEN** the check report covers request normalization, mock generation, output/reference shaping, judge boundary input, attribution evidence, batch isolation, frontend persistence, and verification results

#### Scenario: Divergence-point handling is reported
- **WHEN** the marketing-planning check report is written
- **THEN** it includes a Chinese checklist or matrix for multi-turn state, SSE post-processing, workflow-stage judge, non-exact reference, fine-grained application boundary, fallback responsibility, `path_types`, card normalization, full-chain mock coverage, and single primary `/stream` path

#### Scenario: Divergence treatment evidence is explicit
- **WHEN** a divergence point is marked handled
- **THEN** the report names the producing mechanism and verification evidence rather than only saying the final result looks correct

#### Scenario: Overfit risk is reviewed
- **WHEN** adapter or judge/attribute logic is changed
- **THEN** the audit checks whether the logic is based on project contracts and current-case evidence rather than hardcoded sample query text

#### Scenario: Report is written for user review
- **WHEN** check audit findings are available
- **THEN** a Chinese report is written under `search-test-case/issue` with checklist results, known limits, and recommended follow-up if any

### Requirement: Verification follows implementation risk
The system SHALL run targeted automated checks for changed behavior and SHALL not claim live or browser UAT coverage that was not actually performed.

#### Scenario: Behavior change is implemented
- **WHEN** code behavior changes during this update
- **THEN** a failing test is created first, RED is observed, the minimal fix is implemented, and GREEN is verified

#### Scenario: Live service is unavailable or not started
- **WHEN** marketing-planning live service is not available during verification
- **THEN** the check report states that live business output was not verified and limits claims to mock/provided/API/source verification
