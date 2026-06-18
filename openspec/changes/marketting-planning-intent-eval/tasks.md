## 1. Project Registration and Single-Turn Boundary Tests

- [x] 1.1 Add a failing project-loader/API test that `marketting-planning-intent` is listed as a separate project without replacing `marketting-planning`.
- [x] 1.2 Add a failing adapter test that `marketting-planning-intent` uses `/api/v1/marketing-planning/intent-recognition` and not `/api/v1/marketing-planning/stream`.
- [x] 1.3 Add a failing mock-case test that generated cases are single-turn and never declare `interaction.mode = interactive_intent`.
- [x] 1.4 Create `impl/projects/marketting-planning-intent/project.yaml` and minimal docs/checklist for the single-turn intent boundary.
- [x] 1.5 Add the minimal adapter skeleton so project loading and mock case generation pass.

## 2. Intent Request and Output Normalization

- [x] 2.1 Add a failing adapter test for building a single-turn intent-recognition request from `query` or `user_text`.
- [x] 2.2 Add failing extraction tests for mock/provided/live-like intent-recognition response shapes, covering intent label, confidence, slots/entities, ambiguity/fallback, and errors.
- [x] 2.3 Implement request construction for the intent-recognition API without turns/session continuation/interactive next-turn behavior.
- [x] 2.4 Implement compact output normalization through one extraction path for mock/provided/live outputs.
- [x] 2.5 Verify normalized outputs do not include raw downstream payloads in compact batch/server/frontend persistence paths.

## 3. Two-Layer Judge and Attribution

- [x] 3.1 Add a failing judge test that expected intent plus required slots passes the deterministic contract gate and can produce `correct` after semantic judge reasoning.
- [x] 3.2 Add a failing judge test that missing required slots/entities fails the deterministic contract gate even when intent label matches.
- [x] 3.3 Add a failing judge test that disallowed fallback/unknown/ambiguous or low-confidence intent fails the deterministic contract gate.
- [x] 3.4 Add a failing judge test that a valid-shaped response can still be non-correct when semantic judge detects user-text/intent mismatch.
- [x] 3.5 Implement deterministic intent-reference contract gate before semantic judge reasoning in the adapter judge hook.
- [x] 3.6 Add attribution tests that correct cases do not invent failure causes and incorrect cases cite current-case evidence such as contract gate failure, semantic mismatch, intent mismatch, missing slot, fallback disallowed, API error, or parse failure.
- [x] 3.7 Implement attribution context/result normalization for the intent project.

## 4. Mock Cases, UAT, and Frontend Integration

- [x] 4.1 Add mock cases covering at least: normal planning intent, missing required slot, ambiguous/unknown intent, fallback/error, and non-target intent.
- [x] 4.2 Add a batch/run_chain UAT test that mock cases complete through the unified pipeline and return one run per original case id.
- [x] 4.3 Add a summary frontend test that completed `marketting-planning-intent` cases display compact intent evidence, judge verdict, and attribution summary without project-specific endpoints.
- [x] 4.4 Verify `QA`, `client_search`, and existing `marketting-planning` representative cases still list and run after adding the new project.

## 5. Live API Smoke and Check Report

- [x] 5.1 Run `python -m unittest` for the new intent adapter/UAT/frontend tests.
- [x] 5.2 Run `python -m compileall -q impl` and `python -m impl.cli projects`.
- [x] 5.3 Execute `projects/marketting-planning-intent/start.md`: confirm business service on 9006, restart verifier 8020 if needed, and smoke `/api/v1/marketing-planning/intent-recognition` through `run_chain -> judge -> attribute`.
- [x] 5.4 Run an API-level batch smoke through `/api/batch_start` and `/api/batch_status` for `marketting-planning-intent`.
- [x] 5.5 Update or create a Chinese check.md audit report under `search-test-case/issue` covering the single-turn boundary, endpoint split from `/stream`, cross-project compatibility, compact persistence, overfit risk, and verification evidence.
