## ADDED Requirements

### Requirement: State invokes focused subagents
The system SHALL allow each state to invoke one or more focused subagents, local probes, deterministic normalizers, or adapter hooks with explicit role, input contract, output contract, and evidence contribution.

#### Scenario: State has multiple subagents
- **WHEN** a state declares multiple subagent invocations
- **THEN** the runner executes them according to the declared sequence or parallel policy and stores each subagent output separately

#### Scenario: State uses adapter hook
- **WHEN** a state declares a project adapter hook as an executor
- **THEN** the runner calls the hook and records its structured result as state evidence or state output

### Requirement: Subagent merge policy
The system SHALL require a merge policy when a state has multiple outputs that need to become one state result.

#### Scenario: Subagents agree
- **WHEN** multiple subagents return compatible findings
- **THEN** the merge policy combines them into the state result and preserves individual evidence references

#### Scenario: Subagents conflict
- **WHEN** multiple subagents return contradictory findings
- **THEN** the merge policy records the contradiction and the state machine routes to critique, retry, evidence collection, or human review according to transition conditions

### Requirement: Role-specific subagent contracts
The system SHALL support role-specific contracts for common trace analysis work such as user-intent reconstruction, consumer contract extraction, business expectation construction, boundary evaluation, fulfillment assessment, fulfillment critique, expectation attribution planning, probe execution, earliest-divergence analysis, causal category review, improvement recommendation, and final synthesis.

#### Scenario: Fulfillment state uses specialized roles
- **WHEN** the fulfillment assessment phase is executed
- **THEN** the graph can split work across user-intent reconstruction, consumer contract extraction, business expectation construction, boundary evaluation, fulfillment assessment, and fulfillment critique subagents without requiring one prompt to perform all tasks

#### Scenario: Attribute state uses specialized roles
- **WHEN** the attribute phase is executed for unmet, partially fulfilled, not-evaluable, or contested business expectations
- **THEN** the graph can split work across expectation attribution planning, probe execution, earliest divergence analysis, causal category review, and improvement recommendation subagents

### Requirement: Project-defined subagent extensions
The system SHALL allow projects to declare additional subagent roles and bind them to project-specific prompts, tools, probes, or adapter hooks while preserving the generic state execution record format.

#### Scenario: Project adds domain verifier
- **WHEN** a project declares a custom domain verifier subagent for one state
- **THEN** the state machine can invoke that subagent and use its result in gates and transitions without generic core knowing project-specific fields
