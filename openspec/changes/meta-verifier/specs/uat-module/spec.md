## REMOVED Requirements

### Requirement: Standalone UAT Protocol Objects
The previous standalone UAT protocol centered on fixed `UATCase`, `BrowserSession`, `BrowserAction`, `BrowserAssertion`, `UATEvidence`, `UATResult`, and `ProjectUATExtension` objects is superseded by the meta-verifier demand.

#### Scenario: Deprecate UAT as the top-level capability
- **WHEN** the change is updated from `impl/demand/uat.md` to `impl/demand/meta-verifier.md`
- **THEN** the system MUST NOT treat standalone UAT protocol objects as the main product capability

#### Scenario: Remove rigid protocol-only implementation
- **WHEN** implementation proceeds
- **THEN** UAT-only public objects, docs, and tests MUST be removed or rewritten as meta-verifier internals if they only exist for the historical standalone UAT module

### Requirement: Standalone Browser Action and Assertion Protocol
The previous generic browser action/assertion protocol as an independent UAT module is removed as a product-level requirement.

#### Scenario: Keep browser operation as an implementation technique
- **WHEN** browser automation is needed by the meta-verifier
- **THEN** Selenium browser actions, page assertions, and evidence capture MAY be reused internally as browser evidence execution, but MUST be driven by meta-verifier checklist and report semantics

### Requirement: Standalone Project UAT Extension Protocol
The previous project UAT extension contract is removed as the main project extension surface.

#### Scenario: Replace UAT extensions with meta-verifier extensions
- **WHEN** a project needs custom pages, selectors, business goals, persona prompts, algorithm criteria, or finding classifiers
- **THEN** it MUST express those through a meta-verifier extension rather than a UAT-only extension

### Requirement: Standalone 8020 Frontend Business UAT
The previous 8020 UAT coverage remains valuable but is no longer sufficient by itself.

#### Scenario: Upgrade 8020 UAT into meta-verifier coverage
- **WHEN** the verifier frontend is checked
- **THEN** the run MUST start at `http://127.0.0.1:8020/frontend/index.html`, generate checklist-driven coverage for linked pages, operate core controls, and produce meta-verifier findings and evidence rather than only pass/fail UAT assertions

### Requirement: Standalone UAT Tests
The previous UAT-only tests are superseded by meta-verifier tests.

#### Scenario: Replace UAT tests
- **WHEN** tests are updated for the new demand
- **THEN** tests that only validate UAT protocol normalization or browser-action translation MUST be deleted or rewritten to validate meta-verifier checklist generation, evidence capture, finding classification, reviewer merge behavior, and report output
