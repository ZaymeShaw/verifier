## ADDED Requirements

### Requirement: Skill-local implementation boundary
The system SHALL implement the meta-verifier product capability inside `.claude/skills/meta-verifier/`, not as a primary module under `impl`.

#### Scenario: Store skill artifacts in the skill directory
- **WHEN** the meta-verifier skill is added
- **THEN** its instructions, protocol docs, scripts, routing behavior, checklist behavior, evidence behavior, and report guidance MUST be stored under `.claude/skills/meta-verifier/`

#### Scenario: Reuse across projects
- **WHEN** the skill runs in this repository or a future repository
- **THEN** it MUST adapt to the visible project information available in that environment rather than depending on this verifier project's `impl` package as its own implementation home

#### Scenario: Inspect `impl` as target evidence
- **WHEN** the skill checks this verifier repository
- **THEN** `impl` files MAY be inspected as project artifacts and evidence sources, but MUST NOT be required as the location of the skill's generic meta-verifier implementation

### Requirement: Single-entry skill interface
The system SHALL expose meta-verifier as a single Claude Code skill entrypoint `/meta-verifier [natural language goal]`.

#### Scenario: Run with no explicit target
- **WHEN** the user invokes `/meta-verifier` without arguments
- **THEN** the system MUST infer a broad project verification goal, prioritize demand-side persona critique, generate a project checklist, and collect browser evidence for reachable product surfaces

#### Scenario: Run with a natural-language target
- **WHEN** the user invokes `/meta-verifier` with a natural-language goal, symptom, page, chain, or business question
- **THEN** the system MUST infer the appropriate internal verification routes without requiring the user to choose a mode name

#### Scenario: Hide internal modes from the user
- **WHEN** the system decides whether to perform project exploration, targeted verification, issue reproduction, or persona critique
- **THEN** those route names MUST remain implementation details and MUST NOT be required as user-facing subcommands

### Requirement: Automatic intent routing
The system SHALL route each `/meta-verifier` request to one primary internal route and any supporting routes needed to answer the user’s goal.

#### Scenario: Route broad verification requests
- **WHEN** the request is empty or broadly asks whether the project is reasonable
- **THEN** the primary route MUST be demand-side persona critique with project exploration and browser evidence as supporting routes

#### Scenario: Route page or chain testing requests
- **WHEN** the request mentions testing, verification, pages, buttons, links, core controls, or user chains
- **THEN** the primary route MUST be targeted verification with checklist generation, browser evidence, and persona critique as supporting routes where applicable

#### Scenario: Route issue descriptions
- **WHEN** the request describes a failure, wrong result, error, no response, reproduction need, or localization need
- **THEN** the primary route MUST be issue reproduction with browser evidence and code or artifact localization as supporting routes

#### Scenario: Route business-goal critique
- **WHEN** the request asks whether the system can help a role achieve a business or demand-side goal
- **THEN** the primary route MUST be persona critique with project exploration and output-quality review as supporting routes

#### Scenario: Compose overlapping routes
- **WHEN** a request matches multiple route types
- **THEN** the meta-verifier MUST compose the relevant routes automatically and ask clarification only when the target cannot be inferred

### Requirement: Meta-verifier role
The system SHALL provide a meta-verifier capability that acts as a critical tester of this verifier project, not merely a fixed UAT runner.

#### Scenario: Act as a demanding user
- **WHEN** the meta-verifier runs
- **THEN** it MUST evaluate the system from the perspective of a demand-side user trying to satisfy real project goals

#### Scenario: Report unmet needs
- **WHEN** the simulated demand-side user finds that the system cannot satisfy a need
- **THEN** the meta-verifier MUST record the unmet need, user path, evidence, suspected defect category, and reproduction guidance

### Requirement: Project understanding and checklist generation
The system SHALL inspect project documentation, skills, protocols, implementation files, frontend pages, and common user paths to generate a verification checklist before browser execution.

#### Scenario: Enumerate critical verification targets
- **WHEN** the meta-verifier prepares a run
- **THEN** it MUST identify critical chains, critical functions, critical frontend components, and common user operation paths

#### Scenario: Keep checklist evidence-based
- **WHEN** checklist items are produced
- **THEN** each item MUST reference the observed project artifact, page element, protocol, function, or user path that caused it to be included

### Requirement: Demand-side sub-agent simulation
The system SHALL support starting an independent Claude Code sub-agent or equivalent isolated reviewer process that plays the demand-side user role.

#### Scenario: Launch a user-role reviewer
- **WHEN** advanced meta-verifier mode runs
- **THEN** it MUST obtain user-goal critique from an isolated demand-side reviewer rather than relying only on the same implementation process that wrote the code

#### Scenario: Merge reviewer findings
- **WHEN** the sub-agent returns findings
- **THEN** the meta-verifier MUST merge them into the final report with source attribution and without treating them as automatically verified facts unless evidence is present

### Requirement: Real browser product-surface verification
The system SHALL use Selenium or equivalent browser automation to operate the real product entrypoint at `http://127.0.0.1:8020/frontend/index.html`.

#### Scenario: Start from the real entrypoint
- **WHEN** browser verification begins
- **THEN** it MUST open the index page and navigate through linked project pages rather than only opening toy pages or isolated HTML snippets

#### Scenario: Cover page basics and buttons
- **WHEN** the meta-verifier exercises the frontend
- **THEN** it MUST verify page loading, visible navigation, core buttons, forms, result panels, and primary linked chains

#### Scenario: Preserve browser evidence
- **WHEN** browser operations pass or fail
- **THEN** the meta-verifier MUST capture action trace, page state, screenshots or HTML snapshots, console/error details where available, and the user-visible result at the failure or checkpoint

### Requirement: Meta-verifier finding categories
The system SHALL classify findings into functional implementation defects, algorithm capability problems, system design or architecture defects, and unmet user-need gaps.

#### Scenario: Classify a frontend defect
- **WHEN** a button, form, navigation path, or result panel does not work for a user goal
- **THEN** the finding MUST be classified as a functional implementation defect with browser reproduction evidence

#### Scenario: Classify an algorithm capability problem
- **WHEN** the system runs but produces weak, incorrect, incomplete, or non-actionable AI evaluation output
- **THEN** the finding MUST be classified as an algorithm capability problem with input/output evidence

#### Scenario: Classify a design defect
- **WHEN** the system behavior reveals unclear boundaries, missing protocol responsibilities, brittle workflow design, or insufficient observability
- **THEN** the finding MUST be classified as a system design or architecture defect

### Requirement: Historical UAT-only deprecation
The system SHALL treat the previous UAT-only protocol proposal and implementation as superseded by the meta-verifier demand.

#### Scenario: Remove rigid UAT protocol center
- **WHEN** the change is updated for `impl/demand/meta-verifier.md`
- **THEN** fixed UAT protocol objects and tests that exist only to support the old standalone UAT module MUST be removed or replaced by meta-verifier abstractions

#### Scenario: Preserve browser UAT as a technique
- **WHEN** browser operation is still needed
- **THEN** Selenium-driven page/button UAT MUST remain available as a meta-verifier execution technique, not as the entire product capability

### Requirement: Meta-verifier tests
The system SHALL provide tests under `tests` for checklist generation, report schema, browser evidence capture, and real 8020 entrypoint verification.

#### Scenario: Test meta-verifier preparation
- **WHEN** targeted tests run
- **THEN** they MUST verify that project artifacts can be converted into a checklist of critical links, controls, functions, chains, and expected evidence

#### Scenario: Test real frontend verification boundary
- **WHEN** real Selenium meta-verifier smoke is enabled in a compatible environment
- **THEN** it MUST launch a browser against `http://127.0.0.1:8020/frontend/index.html`, navigate to linked pages, operate core controls, and produce a structured meta-verifier report
