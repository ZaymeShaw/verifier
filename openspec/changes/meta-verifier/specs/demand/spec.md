## MODIFIED Requirements

### Requirement: Skill-scoped meta-verifier implementation
The system SHALL implement meta-verifier as a reusable Claude Code skill under `.claude/skills/meta-verifier/`, with the skill directory owning the user-facing instructions, implementation protocol, scripts, and operational docs.

#### Scenario: Add meta-verifier as a Claude skill
- **WHEN** the meta-verifier capability is implemented
- **THEN** `.claude/skills/meta-verifier/` MUST contain the skill entrypoint instructions and necessary supporting protocol, script, and documentation artifacts

#### Scenario: Keep meta-verifier outside project `impl`
- **WHEN** shared meta-verifier routing, checklist generation, evidence collection, reviewer orchestration, and report semantics are added
- **THEN** they MUST live in the skill directory rather than under `impl`, because the skill is intended for reuse across different projects

#### Scenario: Treat current verifier implementation as the first target
- **WHEN** the skill verifies this repository
- **THEN** `impl`, `impl/frontend`, `impl/protocols`, and `impl/projects` MUST be inspected as target project artifacts, not treated as the home of the meta-verifier product implementation

#### Scenario: Keep browser UAT subordinate
- **WHEN** browser automation is implemented for this skill
- **THEN** it MUST serve the broader meta-verifier workflow and avoid becoming a rigid standalone protocol that cannot express demand-side critique, algorithm capability review, or architecture findings

### Requirement: Project-extensible verifier workflow
The system SHALL support verifier workflows whose generic core defines stable boundaries while project implementations provide project-specific pages, selectors, setup, business semantics, acceptance standards, and critique rules through explicit extensions.

#### Scenario: Extend meta-verifier for different projects
- **WHEN** two projects require different pages, login flows, selectors, business assertions, algorithms, or demand-side acceptance criteria
- **THEN** both projects MUST be able to implement those differences through project meta-verifier extensions while sharing the same generic checklist, browser-evidence, finding, and report model

#### Scenario: Avoid implementation-first verifier design
- **WHEN** a new verifier capability is designed
- **THEN** it MUST define generic scope, inputs, outputs, extension points, evidence, critique categories, and constraints before choosing or reusing a concrete execution path
