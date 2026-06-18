## ADDED Requirements

### Requirement: Trace-level declarative graph
The system SHALL support a declarative state machine that orchestrates a full trace evaluation across mock, application execution, judge, attribute, verification, critique, finalization, and incomplete-stop states.

#### Scenario: Project declares a trace graph
- **WHEN** a project provides a trace state graph declaration
- **THEN** the trace runner uses that graph to choose states, transitions, subagent invocations, quality gates, and stop conditions for the run

#### Scenario: Project omits a trace graph
- **WHEN** a project does not provide a trace state graph declaration
- **THEN** the trace runner uses the default graph while preserving the same trace state record format

### Requirement: Conditional transitions
The system SHALL choose the next state from explicit transition conditions based on state outputs, quality gate decisions, retry counts, evidence coverage, and project hook results.

#### Scenario: Fulfillment critique needs more evidence
- **WHEN** the fulfillment critique state reports missing expectation, boundary, actual-output, or downstream-consumer evidence that can be collected
- **THEN** the state machine transitions back to an evidence collection, expectation construction, or probe state instead of finalizing a fulfillment assessment

#### Scenario: Retry limit is reached
- **WHEN** a state exceeds its configured retry or depth limit
- **THEN** the state machine transitions to an incomplete or human-review stop state with the reason preserved

### Requirement: Inspectable state history
The system SHALL preserve each state execution record, including state id, role, inputs summary, outputs, evidence references, gate decisions, transition decision, retry count, timestamps, and errors.

#### Scenario: Trace completes successfully
- **WHEN** a trace state machine reaches finalization
- **THEN** the final trace result includes the complete state history needed to explain how the recommendation was produced

#### Scenario: Trace stops incomplete
- **WHEN** the state machine cannot satisfy required evidence or quality gates
- **THEN** the final trace result includes the incomplete reason and the state history showing where analysis stopped

### Requirement: Recommended default graph
The system SHALL provide a default trace graph with states for prepare_trace, mock_or_input, execute_or_capture, collect_evidence, build_business_expectations, evaluate_fulfillment, fulfillment_critic, attribute_expectations, run_attribution_probes, attribution_critic, finalize, and incomplete_or_human_review.

#### Scenario: Simple project uses default graph
- **WHEN** a simple project runs a trace without custom graph configuration
- **THEN** the default graph can produce compatible judge, attribute, mock, and final trace outputs

#### Scenario: Complex project extends default graph
- **WHEN** a complex project adds project-specific states or transitions
- **THEN** the runner combines those declarations with the same state execution protocol instead of requiring generic core changes
