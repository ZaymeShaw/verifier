## ADDED Requirements

### Requirement: Mock cases are full-pipeline evaluation data
The system SHALL treat generated mock cases as simulated `case/input/reference` data for full-pipeline evaluation. A mock case MUST be valid input to the same batch pipeline as live or uploaded cases, and its reference MUST remain the evaluation target for the actual output produced by that run.

#### Scenario: Generated mock case enters unified batch pipeline
- **WHEN** a user builds a mock case pool and starts batch attribution for selected cases
- **THEN** each selected case MUST execute through the unified run, judge, attribute, cluster, check, and frontend-view chain

#### Scenario: Reference evaluates the run output
- **WHEN** a mock-generated case is run in live, mock-response, or provided-output mode
- **THEN** the case reference MUST be used to evaluate the output produced in that same run

### Requirement: Execution mode only selects output source
The system SHALL use execution mode only to identify how actual output is produced. Execution mode MUST NOT change the downstream judge, attribute, cluster, check, or frontend-view semantics.

#### Scenario: Mock response mode shares downstream semantics
- **WHEN** a batch run is started with mock-response mode
- **THEN** only the run output source MAY use the project adapter's mock response path, while judge, attribute, cluster, check, and frontend-view behavior MUST remain shared with live mode

#### Scenario: Live mode on mock-generated data remains valid
- **WHEN** a batch run is started with live mode for mock-generated cases
- **THEN** the system MUST call or prepare the live project output path and evaluate the resulting output against each case reference

#### Scenario: Service fallback is visible as output-source evidence
- **WHEN** a live service call fails and the system records a fallback output
- **THEN** the run result MUST preserve visible status or trace evidence that the output did not come from a successful live service response

### Requirement: Frontend candidate rows reflect the executed run
The summary frontend SHALL render candidate-pool row fields from the same run result that backend batch execution returned for that case. User-visible input, output, reference, status, judge, attribution summary, case id, and execution-mode evidence MUST be traceable to one executed run.

#### Scenario: Candidate row uses backend batch result fields
- **WHEN** batch status returns a completed run for a case in the summary frontend
- **THEN** that case's candidate row MUST display output, reference, status, judge, and attribution summary derived from that completed run result

#### Scenario: Candidate row exposes run identity evidence
- **WHEN** a user reviews a candidate row after batch attribution
- **THEN** the row or its details MUST expose enough evidence to identify the case id and execution mode for the run that produced the displayed result

#### Scenario: Candidate row does not mix stale run data
- **WHEN** the same case pool is rerun with a different execution mode or new batch result
- **THEN** the visible row fields MUST not combine output, reference, status, judge, or attribution data from different runs

### Requirement: Tests assert page-equivalent candidate semantics
Regression and UAT tests SHALL verify the same candidate-pool fields that users see in the summary frontend, not only backend batch JSON. Tests MUST cover the mapping from mock case pool to batch result to candidate row state.

#### Scenario: UAT covers mock pool batch attribution as user sees it
- **WHEN** a test simulates clearing the candidate pool, building mock cases, and running batch attribution
- **THEN** the test MUST assert the resulting candidate state for user-visible output, reference, status, judge, attribution summary, case id, and execution mode

#### Scenario: Backend and frontend assertions compare the same run
- **WHEN** a test compares backend batch results with frontend candidate state
- **THEN** the asserted fields MUST come from the same case id and same execution mode

### Requirement: Stale or unused code is check-audited before cleanup
The system SHALL classify suspected unused, stale, or misleading functions before modifying or deleting them. The audit MUST distinguish framework reflection hooks, adapter extension points, protocol entry points, and true dead code.

#### Scenario: Framework-called methods are not removed by text count
- **WHEN** static scanning reports no direct textual callers for server handler methods or adapter hooks
- **THEN** the audit MUST check whether they are invoked by framework reflection, polymorphism, or protocol extension before recommending deletion

#### Scenario: Dead code cleanup preserves historical project behavior
- **WHEN** a function is classified as true dead or stale code and is cleaned up
- **THEN** QA, client_search, and marketting-planning regression coverage MUST remain consistent with their project-specific output and reference semantics
