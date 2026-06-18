## Context

`impl/demand/meta-verifier.md` replaces the previous UAT-only demand. The new requirement has two levels: basic page function/button UAT, and an advanced role that acts as a critical tester / meta verifier. The advanced role must use this system like a real demand-side user, discover places where the product cannot satisfy the user’s goals, and classify problems across implementation defects, algorithm capability issues, and system design/architecture defects.

The historical UAT protocol proposal should be considered superseded. It produced useful browser-operation pieces, but its center of gravity was a fixed UAT protocol (`UATCase`, browser actions, assertions). That is too narrow for the advanced demand: a meta verifier must first understand the project, generate a checklist, use real browser operation as evidence collection, and incorporate independent demand-side critique.

## Goals / Non-Goals

**Goals:**
- Build meta-verifier as a reusable Claude Code skill under `.claude/skills/meta-verifier/`, not as a verifier-project-only module under `impl`.
- Put the user-facing skill instructions, implementation protocol, scripts, and operational docs inside the skill directory so the capability can be reused by other projects.
- Start from project understanding: docs, skills, protocols, implementation files, frontend pages, and common user paths.
- Generate an evidence-backed checklist of critical chains, key functions, frontend components, and user operations.
- Use Selenium or equivalent browser automation to operate `http://127.0.0.1:8020/frontend/index.html` and linked pages for the current verifier project.
- Support an independent Claude Code sub-agent / reviewer process that plays the demand-side user role.
- Produce structured findings for functional defects, algorithm capability problems, design/architecture defects, and unmet user needs.
- Retain page/button UAT as a technique inside meta-verifier.
- Remove or replace the historical UAT-only implementation that no longer matches the demand.

**Non-Goals:**
- Keeping UAT as a standalone product capability centered on fixed browser-action protocol objects.
- Implementing the meta-verifier primary capability under `impl/`; `impl` is a project surface to inspect, not the cross-project skill home.
- Treating Selenium smoke tests as sufficient meta-verification.
- Treating a sub-agent’s opinion as verified without browser, code, or artifact evidence.
- Testing only `live.html` or `summary.html` while skipping the real `index.html` entrypoint.

## Decisions

1. **Meta-verifier, not UAT, is the top-level capability.**
   - The system first builds a model of what should be checked, then executes browser operations and critique flows.
   - Rationale: the demand asks for a tester that can judge whether the project satisfies user needs, not only whether predefined UI operations pass.
   - Historical alternative: standalone UAT protocol. Rejected because it is too rigid and misses algorithm/design critique.

2. **Checklist generation precedes browser execution.**
   - Inputs include project docs, skills, protocol docs, frontend pages, API routes, implementation entrypoints, and project extensions.
   - Output is a checklist with target type, source artifact, user path, expected evidence, and priority.
   - Rationale: a meta verifier must decide what matters before running browser actions.

3. **Browser automation is an evidence collector.**
   - Selenium remains the first concrete mechanism for real browser operation.
   - Browser traces, screenshots, HTML snapshots, console logs, page state, and visible results attach to checklist items and findings.
   - Rationale: real browser behavior catches UI failures, while the meta-verifier report decides whether failures matter.

4. **Demand-side critique is isolated.**
   - Advanced mode can launch a Claude Code sub-agent or equivalent isolated reviewer that plays the demand-side user.
   - Its output is merged as findings only when tied to evidence or marked as reviewer critique.
   - Rationale: a separate reviewer reduces self-confirmation by the implementation process.

5. **Findings use explicit categories.**
   - `functional_defect`: page, button, API, state, navigation, or result panel failure.
   - `algorithm_capability_problem`: output is weak, wrong, incomplete, non-actionable, or fails the business goal despite successful execution.
   - `design_architecture_defect`: unclear boundaries, brittle flow, missing protocol responsibility, missing observability, or hard-to-extend structure.
   - `unmet_user_need`: user goal cannot be achieved with the current system.
   - Rationale: meta-verifier must be useful for product and architecture improvement, not only pass/fail testing.

6. **Historical UAT-only implementation should be removed or replaced.**
   - Existing UAT-only protocol docs, fixed UAT dataclasses, UAT-specific tests, and OpenSpec wording should be deleted or rewritten as meta-verifier artifacts.
   - Browser-operation helpers may be reintroduced only if they are framed as meta-verifier browser execution internals.
   - Rationale: leaving old UAT as the main capability will mislead future implementation and violate the updated demand.

7. **The user-facing skill is a single natural-language entrypoint.**
   - Users invoke `/meta-verifier [natural language goal]`; they do not select `explore`, `test`, `reproduce`, or `critique` modes.
   - The meta-verifier routes internally based on the request: empty or broad requests start with persona critique plus project exploration; page/button/link requests trigger targeted verification; bug/problem descriptions trigger issue reproduction and localization; business-goal questions trigger persona critique.
   - If several routes match, the system composes them without asking the user. It asks a clarification question only when the target is not inferable.
   - Rationale: the skill should behave like an intelligent verifier, not expose an implementation menu to the user.

8. **Internal routes are implementation details.**
   - `project_exploration` discovers artifacts and produces checklist items.
   - `targeted_verification` validates a named page, button, chain, API, function, or capability.
   - `issue_reproduction` reproduces a described symptom and records shortest steps plus suspected areas.
   - `persona_critique` evaluates whether the system satisfies the inferred demand-side user goal.
   - `browser_evidence` is a cross-cutting evidence collector used by the routes, not a user-facing route.

9. **The implementation boundary is the skill directory.**
   - `.claude/skills/meta-verifier/` owns the skill instructions, protocol docs, scripts, router, checklist generator, browser evidence executor, reviewer prompts, and report writer.
   - The current verifier repository is the first target the skill verifies; its `impl/` modules, frontend files, protocols, and project configs are inputs to inspect rather than the place where the meta-verifier product lives.
   - Rationale: the demand explicitly requires a reusable Claude skill that can later run in other projects with different visibility, not a verifier-project implementation module.

## Proposed Skill Components

All primary meta-verifier implementation artifacts live under `.claude/skills/meta-verifier/`:

- `SKILL.md`: Claude Code skill instructions for `/meta-verifier [natural language goal]`, including persona-first behavior, routing policy, evidence requirements, and report format.
- Protocol docs: skill-local documentation for run, route decision, checklist item, evidence, finding, extension, and report semantics.
- Scripts or modules: skill-local implementation support for intent routing, artifact discovery, checklist generation, browser evidence execution, reviewer prompt construction, finding classification, and report generation.
- Browser assets/config: Selenium helpers and target discovery defaults that can start from `http://127.0.0.1:8020/frontend/index.html` for this project without hardcoding that URL as the only supported project.

Conceptual objects owned by the skill:

- `MetaVerifierRun`: run id, raw user request, inferred route, target URL, project scope, persona configuration, checklist, browser plan, findings, evidence, and final summary.
- `MetaVerifierIntentRouter`: maps `/meta-verifier [natural language goal]` into a primary internal route, supporting routes, target scope, inferred persona, and confidence.
- `MetaVerifierChecklistItem`: target type, artifact source, user path, priority, expected observation, browser action hints, and acceptance question.
- `MetaVerifierFinding`: category, severity, user impact, source checklist item, evidence references, reproduction path, and suggested next investigation.
- `MetaVerifierEvidence`: browser action trace, screenshots, HTML snapshots, console logs, page state, artifact references, sub-agent critique, and timing.
- `MetaVerifierExtension`: project-specific discovery hints, selector aliases, persona prompts, business goals, algorithm acceptance criteria, and custom finding classifiers.
- `BrowserEvidenceExecutor`: Selenium-backed browser operation layer used by meta-verifier, not exposed as the product-level protocol.
- `DemandSideReviewer`: wrapper for launching or simulating an independent demand-side reviewer and merging its critique.

## Historical proposal and implementation to deprecate

The following historical direction should be explicitly deprecated:
- OpenSpec capability `uat-module` as the main capability.
- `impl/protocols/uat_protocol.md` as the primary protocol document.
- Fixed protocol objects whose only purpose is standalone UAT (`UATCase`, `BrowserSession`, `BrowserAction`, `BrowserAssertion`, `UATResult`, `ProjectUATExtension`).
- Tests that only prove protocol normalization or browser-action translation without meta-verifier checklist/report semantics.

The useful historical pieces are:
- Selenium can start a real browser.
- Browser action trace, assertion trace, screenshot, HTML snapshot, and page-state evidence are valuable.
- 8020 page/button coverage remains the basic requirement.

These pieces should be migrated into meta-verifier as implementation details.

## Risks / Trade-offs

- [Risk] Meta-verifier becomes too subjective → Mitigation: every finding must carry evidence or be labeled as reviewer critique.
- [Risk] Sub-agent critique is noisy → Mitigation: merge with source attribution and do not mark unverified critique as a confirmed defect.
- [Risk] Browser tests are slow and environment-sensitive → Mitigation: keep fast checklist/report unit tests separate from real Selenium smoke and report driver startup failures structurally.
- [Risk] Scope expands to “test everything” → Mitigation: checklist generation prioritizes critical chains, key controls, and user-common paths first.
- [Risk] Old UAT code creates duplicate abstractions → Mitigation: delete or replace old UAT-only files during implementation.

## Migration Plan

1. Rename the OpenSpec change direction from UAT-only to meta-verifier in proposal/spec/design/tasks.
2. Add `meta-verifier` specs and update demand specs to use `impl/demand/meta-verifier.md` as source of truth.
3. Implement meta-verifier skill artifacts under `.claude/skills/meta-verifier/`, including instructions, protocol docs, and support scripts/modules for run, checklist item, finding, evidence, and report semantics.
4. Implement project artifact discovery and checklist generation for docs, protocols, frontend pages, API routes, skills, and project implementations as skill-local behavior.
5. Implement Selenium-backed browser evidence executor in the skill support layer, starting at `/frontend/index.html` for this project and navigating linked pages.
6. Implement demand-side reviewer integration using a sub-agent boundary or testable abstraction from the skill.
7. Implement report generation and finding classification in the skill support layer.
8. Migrate useful browser evidence behavior from historical UAT code into skill-local meta-verifier internals.
9. Implement the `/meta-verifier [natural language goal]` skill entrypoint and intent router so users never need to choose internal modes.
10. Delete deprecated UAT-only protocol docs, code, and tests or rewrite them as meta-verifier skill tests.
11. Add tests for intent routing, checklist generation, finding classification, report schema, browser evidence capture, and real 8020 entrypoint smoke.

## Open Questions

- Should advanced sub-agent execution be mandatory in normal test runs, or mocked in unit tests and enabled only by an environment flag for real meta-verifier runs?
