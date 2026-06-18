## ADDED Requirements

### Requirement: Agent responsibilities are capability-owned
The system SHALL define agent responsibility boundaries by capability ownership rather than by whether an agent writes code.

#### Scenario: Agent role protocol lists ownership
- **WHEN** the agent role protocol is inspected
- **THEN** it lists analysis, application, build, mock, judge, attribute, and check agents with their owned capability, trigger, inputs, outputs, allowed implementation scope, and handoff expectations

#### Scenario: Agent trigger protocol distinguishes trace phases
- **WHEN** the agent role protocol is inspected
- **THEN** it distinguishes project initialization or information updates, business project updates, prebuilt batch mock generation, trace runtime user simulation, and post-trace judge or attribution analysis

#### Scenario: Capability agents may implement their own capability
- **WHEN** a judge, attribute, mock, application, or build capability requires project-specific code
- **THEN** the protocol allows that agent to implement code within its owned capability boundary

#### Scenario: Cross-capability glue is not owned by one runtime agent
- **WHEN** project registration, protocol field alignment, batch orchestration, or frontend/backend integration spans multiple capabilities
- **THEN** the implementation MUST follow the shared project implementation standard instead of being owned ad hoc by a single runtime agent

### Requirement: Analysis agent produces project standards
The system SHALL treat the analysis agent as the producer of project understanding and standards rather than the default runtime code owner.

#### Scenario: Project is initialized or project information changes
- **WHEN** `projects/<project>` documentation or project requirements are updated
- **THEN** analysis output identifies API information, business background, responsibility boundary, mock strategy, judge standard, attribution trace plan, frontend adaptation needs, and key pipeline/code links

#### Scenario: Analysis output feeds project implementation
- **WHEN** project-specific implementation is generated or updated
- **THEN** it consumes analysis output as source standard and records which standard fields drive application, mock, judge, attribute, and frontend behavior

### Requirement: Application agent owns executable application access
The system SHALL limit the application agent's primary ownership to business service startup, simulated service construction, request execution, and output acquisition.

#### Scenario: Existing business service is available
- **WHEN** a project points to an existing business service
- **THEN** application output documents how to start or verify the service, construct requests, call the API, and obtain normalized output

#### Scenario: No complete business service is available
- **WHEN** a project has no runnable business service
- **THEN** application output defines a simulated API/service/pipeline that can be executed independently and used by the unified verifier chain

#### Scenario: Application does not own judge or attribute semantics
- **WHEN** judge scoring or attribution root-cause logic is required
- **THEN** application output supplies business constraints and execution evidence but does not define final judge verdict logic or attribution conclusion logic

### Requirement: Build agent owns project frontend construction
The system SHALL define a build agent responsibility for constructing project frontend behavior from analysis output and frontend protocol requirements.

#### Scenario: Project frontend is initialized or updated
- **WHEN** a project requires live or summary frontend behavior
- **THEN** build output defines how output, reference, judge result, attribution result, cluster/check state, uploads, and persistence are displayed through the shared frontend protocol

#### Scenario: Frontend behavior remains protocol-driven
- **WHEN** a project needs custom field selection, truncation, JSON formatting, or reference-output format alignment
- **THEN** the customization is declared in project frontend standards rather than hardcoded as a one-off display branch

### Requirement: Check agent audits and corrects after evidence
The system SHALL treat check as a mechanism audit and correction role, not the default implementation owner.

#### Scenario: Check is triggered
- **WHEN** check agent runs after demand, project, code, data, prompt, protocol, or frontend changes
- **THEN** it audits visible results and producing mechanisms for protocol alignment, stale paths, overfit risk, batch resilience, frontend/API consistency, and attribution grounding

#### Scenario: Check finds non-trivial behavior change
- **WHEN** check proposes deletion, protocol change, shared behavior change, or standardization that affects user-visible behavior
- **THEN** it records evidence and proposed fix for user confirmation before modifying shared behavior
