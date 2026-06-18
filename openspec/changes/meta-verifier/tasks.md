## 1. Change Reorientation

- [x] 1.1 Read `impl/demand/meta-verifier.md` and treat it as the source of truth replacing the previous UAT-only demand.
- [x] 1.2 Rewrite the proposal so the top-level capability is meta-verifier, not standalone UAT.
- [x] 1.3 Add meta-verifier specs and update demand specs to describe checklist, demand-side critique, browser evidence, finding categories, and historical UAT deprecation.
- [x] 1.4 Rewrite the design to explain why the historical UAT-only proposal is superseded and how useful browser evidence pieces migrate into meta-verifier.

## 2. Historical UAT Cleanup

- [x] 2.1 Remove or replace `impl/protocols/uat_protocol.md` so it no longer presents standalone UAT as the product capability.
- [x] 2.2 Remove or replace `impl/core/uat.py` fixed UAT-only protocol objects, keeping only browser evidence behavior that belongs inside meta-verifier internals.
- [x] 2.3 Remove or rewrite UAT-only tests that only prove protocol normalization/action translation without meta-verifier checklist/report semantics.
- [x] 2.4 Update project adapter hooks that were added solely for UAT-only extension points.

## 3. Meta-verifier Skill Core

- [x] 3.1 Add `.claude/skills/meta-verifier/` as the home for the meta-verifier skill instructions, protocol docs, scripts, and supporting implementation artifacts.
- [x] 3.2 Add skill-local data structures or schema definitions for `MetaVerifierRun`, `MetaVerifierChecklistItem`, `MetaVerifierFinding`, `MetaVerifierEvidence`, `MetaVerifierReport`, and `MetaVerifierExtension`.
- [x] 3.3 Add skill-local `MetaVerifierIntentRouter` for routing `/meta-verifier [natural language goal]` into internal project exploration, targeted verification, issue reproduction, and persona critique routes.
- [x] 3.4 Implement normalization/serialization for meta-verifier runs, router decisions, checklist items, findings, and reports in the skill support layer.
- [x] 3.5 Implement finding categories for functional defects, reproduction records, algorithm capability problems, system design/architecture defects, and unmet user needs.
- [x] 3.6 Preserve project-specific metadata and evidence references through report output.
- [x] 3.7 Remove the meta-verifier primary implementation from `impl` if it was added there during the superseded direction; `impl` should remain the first target project surface, not the skill home.

## 4. Checklist Generation

- [x] 4.1 Implement skill-local project artifact discovery for frontend pages, protocol docs, demand docs, project config, skills, API routes, and project implementations.
- [x] 4.2 Generate checklist items for critical chains, key functions, key frontend components, and common user operation paths.
- [x] 4.3 Ensure each checklist item records the artifact/page/function/source that justified its inclusion.
- [x] 4.4 Add default checklist coverage for `http://127.0.0.1:8020/frontend/index.html`, `live.html`, and `summary.html`.

## 5. Browser Evidence Execution

- [x] 5.1 Add a skill-local Selenium-backed browser evidence executor that starts from `/frontend/index.html` for this project and navigates through linked pages.
- [x] 5.2 Exercise basic page loading, navigation, forms, core buttons, result panels, and primary 8020 user chains.
- [x] 5.3 Capture action trace, screenshots, HTML snapshots, console logs where available, extracted page state, and user-visible results.
- [x] 5.4 Convert navigation, selector, timeout, driver startup, and browser failures into structured meta-verifier findings and evidence.

## 6. Demand-side Reviewer Integration

- [x] 6.1 Add a single-entry Claude Code skill surface for `/meta-verifier [natural language goal]` under `.claude/skills/meta-verifier/`.
- [x] 6.2 Add a demand-side reviewer abstraction that can launch an independent Claude Code sub-agent or equivalent isolated reviewer.
- [x] 6.3 Provide reviewer prompts/persona inputs for acting as the system's demand-side user.
- [x] 6.4 Merge reviewer findings into the meta-verifier report with source attribution.
- [x] 6.5 Keep unverified reviewer critique separate from confirmed browser/code evidence.

## 7. Report Generation

- [x] 7.1 Generate a structured meta-verifier report with checklist results, browser evidence, reviewer critique, findings, severity, user impact, and reproduction paths.
- [x] 7.2 Include summary sections for functionality defects, algorithm capability issues, design/architecture defects, and unmet user needs.
- [x] 7.3 Ensure report output is useful for deciding what to fix next, not only pass/fail status.

## 8. Tests

- [x] 8.1 Add tests for skill-local meta-verifier object normalization and report schema.
- [x] 8.2 Add tests for skill-local automatic intent routing from empty input, page/button requests, issue descriptions, and business-goal critique requests.
- [x] 8.3 Add tests for checklist generation from frontend pages, protocols, demand docs, and project files.
- [x] 8.4 Add tests for finding classification and evidence attachment.
- [x] 8.5 Add tests for demand-side reviewer merge behavior with source attribution.
- [x] 8.6 Add Selenium-compatible tests against a controlled local page for browser evidence execution.
- [x] 8.7 Add a real Selenium smoke for `http://127.0.0.1:8020/frontend/index.html` that navigates to linked pages and exercises core controls when a compatible browser/driver is available.

## 9. Verification

- [x] 9.1 Run targeted meta-verifier tests and fix failures.
- [x] 9.2 Run relevant existing verifier tests to ensure removing UAT-only implementation does not regress current behavior.
- [x] 9.3 Run or attempt the real browser meta-verifier smoke and record whether browser startup succeeds or returns structured startup-failure evidence.
- [x] 9.4 Review the codebase for stale UAT-only names or docs that conflict with `impl/demand/meta-verifier.md`.
