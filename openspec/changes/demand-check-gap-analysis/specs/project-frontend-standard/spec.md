## ADDED Requirements

### Requirement: Project frontend uses protocol-driven views
The system SHALL render project live and summary views from shared frontend protocols plus project-level display standards.

#### Scenario: Live request page uses project standard
- **WHEN** a user runs a live request for a project
- **THEN** the page obtains output through the project application path, requests judge and attribution through the unified chain, and displays fields according to the project frontend standard

#### Scenario: Summary page displays aligned output and reference
- **WHEN** a case has output and reference values
- **THEN** the summary view displays them with aligned format, comparable cell size, JSON formatting when applicable, and project-declared truncation or field selection

#### Scenario: Project-specific display does not fork generic APIs
- **WHEN** a project needs custom frontend presentation
- **THEN** it uses shared run, batch, case-pool, judge, attribute, and cluster APIs rather than introducing a project-private frontend endpoint for the main flow

### Requirement: Case-pool frontend supports durable batch workflows
The frontend SHALL support upload, generated datasets, candidate pools, completed pools, retries, skips, and persistence without losing unrelated cases.

#### Scenario: User uploads custom dataset
- **WHEN** the user uploads a dataset file for batch attribution
- **THEN** the frontend normalizes cases into the shared case-pool shape and preserves case identity through run, judge, attribute, cluster, and check results

#### Scenario: One case fails during judge or attribution
- **WHEN** judge or attribution fails for one case in a batch
- **THEN** the frontend and backend mark that case as failed or retryable without aborting completed or unrelated cases

#### Scenario: Persisted data remains compact
- **WHEN** case-pool state is saved for refresh recovery
- **THEN** persisted state stores durable source data and compact summaries, not oversized raw downstream payloads or transient trace blobs
