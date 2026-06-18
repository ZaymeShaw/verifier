## 1. Demand and Current-State Audit

- [x] 1.1 Add a failing check test that detects when the agent role protocol does not include analysis, application, build, mock, judge, attribute, and check ownership boundaries.
- [x] 1.2 Add a failing check test that detects when a project lacks an auditable implementation-standard checklist for API, application, mock, judge, attribute, frontend, batch, and persistence behavior.
- [x] 1.3 Add a failing check test that reports stale or missing project artifacts by comparing `demand.md`, `impl/protocols`, and `impl/projects/*` standards.
- [x] 1.4 Produce an initial Chinese gap report under `search-test-case/issue` that records current missing mechanisms, evidence, root cause, blast radius, proposed fix, and verification plan.

## 2. Agent Role Protocol

- [x] 2.1 Create or update `impl/protocols/agent_role_protocol.md` with capability-owned boundaries for analysis, application, build, mock, judge, attribute, and check.
- [x] 2.2 Define each agent's trigger, input standards, output artifacts, allowed code-writing scope, and handoff expectations, including trace runtime versus post-trace judge/attribute triggers.
- [x] 2.3 Update relevant agent docs so judge/attribute/mock/application/build can write capability-specific project code without owning cross-capability orchestration.
- [x] 2.4 Add protocol validation tests that fail if required agent roles or handoff fields are missing.

## 3. Project Implementation Standard

- [x] 3.1 Create or update a project implementation standard template under `impl` for `impl/projects/<project>` readiness.
- [x] 3.2 Add required fields for API shape, application start/run, request construction, output extraction, reference handling, judge boundary, attribution trace, frontend view, batch behavior, persistence, and check evidence.
- [x] 3.3 Update existing QA, client_search, marketting-planning, and marketting-planning-intent project docs/configs to satisfy the minimal standard without changing their business behavior.
- [x] 3.4 Add project-loader/check tests that surface missing required project-standard fields as readiness issues.

## 4. Frontend and Build Agent Standard

- [x] 4.1 Add a frontend/build standard that describes how project live pages and summary pages consume project frontend view settings.
- [x] 4.2 Add failing frontend tests for aligned output/reference rendering, JSON formatting, project-declared truncation, and no project-private main-flow endpoint.
- [x] 4.3 Implement or adjust shared frontend view normalization so project-specific display choices come from project standards rather than one-off branches.
- [x] 4.4 Add upload/case-pool persistence tests that verify uploaded, generated, saved, and displayed cases share the same compact case-pool shape.

## 5. Judge Boundary Implementation

- [x] 5.1 Add failing judge-boundary tests showing project boundary fields are loaded from template/project standard and applied before final verdict reconciliation.
- [x] 5.2 Update `impl/judge_boundary-template.md` and judge protocol docs so boundary fields are minimal, fillable, and focused on responsibility-boundary distinctions.
- [x] 5.3 Implement structured boundary loading and gate/reconciliation hooks for project judges without relying only on prompt-time freeform boundary judgment.
- [x] 5.4 Add tests for ideal-boundary evaluation versus system-responsibility-boundary evaluation, including external limitation cases that should not be penalized.

## 6. Attribute Trace Implementation

- [x] 6.1 Add failing attribution tests that reject vague module-only root causes when no current-case evidence supports them.
- [x] 6.2 Define an attribute trace standard for project API flow, major trace nodes, local chain-test evidence, suspected location, expected behavior, actual behavior, and patch direction.
- [x] 6.3 Implement attribution result normalization that can return supported root cause, insufficient evidence, or next-verification-step statuses.
- [x] 6.4 Add mapping-grounding tests for field/config/enum/label attribution evidence to prevent incorrect mapping assumptions.

## 7. Check-Driven Gap Reporting

- [x] 7.1 Implement check logic that reconstructs current intent from `demand.md` and project docs before auditing generated artifacts.
- [x] 7.2 Implement check categories for protocol mismatch, stale artifact, split-brain flow, overfit rule, frontend/API inconsistency, batch persistence risk, and ungrounded attribution.
- [x] 7.3 Generate an updated Chinese check report under `search-test-case/issue` after implementation, including passed items, failed items, evidence locations, root causes, fixes, and verification results.
- [x] 7.4 Ensure non-trivial shared protocol or user-visible behavior changes are reported for user confirmation instead of silently applied by check.

## 8. Cross-Project Verification

- [x] 8.1 Run focused unit tests for agent role protocol, project implementation standard, frontend view standard, judge boundary, attribute trace, and check reporting.
- [x] 8.2 Run representative mock/run_chain/batch tests for QA, client_search, marketting-planning, and marketting-planning-intent.
- [x] 8.3 Run `python -m compileall -q impl` and `python -m impl.cli projects`.
- [x] 8.4 Restart verifier frontend/backend if changed and smoke live/summary pages through HTTP or browser, explicitly noting any unverified browser steps.
- [x] 8.5 Update this OpenSpec task list as tasks are completed and leave unresolved items unchecked.
