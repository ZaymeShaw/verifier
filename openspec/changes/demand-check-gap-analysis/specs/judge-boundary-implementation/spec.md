## ADDED Requirements

### Requirement: Judge boundary is derived from project standards
The system SHALL derive judge responsibility boundaries from templates, project documentation, and analysis/application standards before runtime judging.

#### Scenario: Boundary template is filled for a project
- **WHEN** a project provides a judge boundary template or equivalent project standard
- **THEN** the project judge implementation uses those boundary fields as structured evaluation constraints

#### Scenario: Boundary is applied through flow or gate
- **WHEN** judge evaluates an output
- **THEN** boundary constraints are applied through deterministic flow, structured configuration, or project judge code before or alongside semantic LLM reasoning

#### Scenario: Judge does not invent project boundary at runtime
- **WHEN** judge runs on a case
- **THEN** it does not rely only on prompt-time freeform reasoning to decide which parts of the user intent are inside the system responsibility boundary

### Requirement: Reference handling follows project boundary
The system SHALL generate or normalize references according to the declared project responsibility boundary.

#### Scenario: Input provides reference
- **WHEN** a case includes a reference
- **THEN** judge uses it after normalizing format to align with output without changing reference content

#### Scenario: Input lacks reference
- **WHEN** a case lacks a reference
- **THEN** judge generates a reference that states the expected answer within the project responsibility boundary and records enough basis for check to audit it

#### Scenario: External limitation is outside responsibility
- **WHEN** an output cannot satisfy part of user intent because of a documented external system limitation outside project responsibility
- **THEN** judge does not penalize that limitation as a project failure
