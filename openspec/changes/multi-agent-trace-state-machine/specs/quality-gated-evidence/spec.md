## ADDED Requirements

### Requirement: Quality gates control finalization and transitions
The system SHALL evaluate quality gates after configured states to decide whether analysis may finalize, must collect more evidence, must retry, must transition to another state, or must stop incomplete.

#### Scenario: Gate passes
- **WHEN** all required process and evidence checks pass for a state
- **THEN** the state machine may transition toward the next analysis or finalization state

#### Scenario: Gate fails with recoverable missing evidence
- **WHEN** a gate fails because recoverable evidence is missing
- **THEN** the state machine transitions to a collection, probe, retry, or clarification state rather than fabricating a conclusion

#### Scenario: Gate fails unrecoverably
- **WHEN** a gate fails and no configured transition can recover the missing evidence
- **THEN** the state machine stops as incomplete or human review with the failed gate reasons preserved

### Requirement: Generic evidence sufficiency checks
The system SHALL provide generic gate checks for required evidence presence, business expectation coverage, fulfillment assessment coverage, boundary decision availability, contradiction status, unsupported claims, probe availability, source/probe support for causal claims, and finalization readiness.

#### Scenario: Fulfillment assessment lacks expectation coverage
- **WHEN** a fulfillment state attempts to finalize without reconstructed user intent, downstream consumer contract, business expectations, actual-output evidence, and per-expectation fulfillment assessments
- **THEN** the quality gate blocks a confident fulfillment conclusion and any derived verdict summary

#### Scenario: Attribute lacks expectation-level causal evidence
- **WHEN** an attribute state attempts to finalize a causal attribution without linking it to unmet, partially fulfilled, not-evaluable, or contested business expectations and without earliest divergence evidence or supported suspected locations
- **THEN** the quality gate blocks formal attribution and records the missing evidence

### Requirement: Quality gates are not business correctness rules
The system SHALL keep generic quality gates limited to process completeness and evidence sufficiency, while project-specific correctness rules remain in project specs, state declarations, adapter hooks, or subagent contracts.

#### Scenario: Project-specific semantic rule needed
- **WHEN** a project needs to decide whether two output forms are semantically equivalent
- **THEN** that rule is provided by the project configuration or adapter hook, while the generic gate only checks whether the semantic equivalence decision is evidenced

### Requirement: Demand and check compliance gates
The system SHALL require implementation-time compliance gates that map total demand, project demand, project implementation standards, and check-agent requirements to concrete verification evidence before the change can be treated as complete.

#### Scenario: Demand requirement has no verification evidence
- **WHEN** a demand or check requirement is listed as relevant to the state-machine architecture but has no implemented behavior, test, protocol field, adapter hook, or documented non-goal decision
- **THEN** the compliance gate fails and the implementation cannot be marked complete

#### Scenario: Project-specific demand conflicts with generic protocol
- **WHEN** a project demand requires behavior that does not belong in generic core
- **THEN** the compliance gate requires that behavior to be represented as project configuration, project spec, adapter hook, or explicit deferred decision instead of hardcoding it into the generic runner

#### Scenario: Check-agent standard detects overfit or split flow
- **WHEN** check-agent review finds hardcoded case behavior, display-only fixes, stale generated artifacts, split mock/live/batch paths, or attribution evidence not grounded in the current trace
- **THEN** the compliance gate fails until the producing mechanism is corrected and re-verified

### Requirement: Gate decisions are inspectable
The system SHALL store each gate decision with gate id, checked inputs, pass/fail status, missing evidence, recoverability, recommended transition, and human-readable reason.

#### Scenario: Frontend displays gate history
- **WHEN** a trace result is viewed in live or summary pages
- **THEN** the UI can show which gates passed, which failed, and why the trace finalized or stopped incomplete
