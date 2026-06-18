## 1. Protocol Normalization and Compatibility Tests

- [x] 1.1 Add a failing protocol test that a QA case without `interaction` is normalized/executed as `single_run` and still preserves `output=actual_answer` / `reference=golden_answer` semantics.
- [x] 1.2 Add a failing protocol test that a client_search case without `interaction` keeps its existing single-query input shape, stable case id, and candidate-row merge behavior.
- [x] 1.3 Add a failing protocol test that legacy top-level `turns` are accepted as static multi-turn source data without requiring source migration.
- [x] 1.4 Implement the minimal case interaction normalization helper in core pipeline or a focused protocol module: missing `interaction` becomes `single_run`, legacy `turns` becomes internal `static_turns`, explicit `interactive_intent` remains explicit, and adapter-specific fields remain opaque.
- [x] 1.5 Verify the compatibility tests turn GREEN before adding marketing-planning interactive behavior.

## 2. Interactive Dispatch Boundary

- [x] 2.1 Add a failing batch/run_chain test that a case with `interaction.mode = interactive_intent` is not flattened into a normal single request.
- [x] 2.2 Add a failing test that an unsupported project declaring `interactive_intent` returns a bounded `uncertain`/error run for that case and does not abort the rest of the batch.
- [x] 2.3 Add adapter capability hooks for interactive execution detection and execution, with safe default behavior for adapters that do not implement it; core must pass `interaction`, `mock_agent`, and project facts through without interpreting project-specific keys.
- [x] 2.4 Route only explicit `interactive_intent` cases through the adapter interactive hook; keep `single_run` and `static_turns` on existing paths.
- [x] 2.5 Verify mixed batches containing single-run QA/client_search cases and one unsupported interactive case complete without cross-case failure.

## 3. Marketing-Planning Interactive Mock Agent Protocol

- [x] 3.1 Add a failing adapter test that marketing-planning mock cases include at least one case with `user_intent`, `interaction.mode = interactive_intent`, `mock_agent`, and `interaction.turn_expectations`.
- [x] 3.2 Add a failing test that path type choices are represented in `user_intent`/interaction facts instead of only as incidental reference fields.
- [x] 3.3 Update marketing-planning mock case generation to emit the new interactive intent case while keeping existing single-run/static cases valid.
- [x] 3.4 Update project docs/checklist to describe the generic `interaction` envelope and the marketing-planning interactive contract.
- [x] 3.5 Verify mock case generation still covers existing intent, clarification, planning, fallback, non-agent, and streaming scenarios.

## 4. Marketing-Planning Conversation Runner

- [x] 4.1 Add a failing test that the first interactive turn is generated from `user_intent`, not from a pre-flattened request containing all future facts.
- [x] 4.2 Add a failing test that when turn 1 returns clarification feedback with missing `target_value`, the mock agent generates turn 2 using the target value from `user_intent`.
- [x] 4.3 Add a failing test that when later feedback asks for `path_types`, the mock agent generates the path selection from `user_intent.path_type_intent`.
- [x] 4.4 Implement the bounded marketing-planning interactive runner in the adapter: build turn input, call existing live/provided output path per turn, extract compact feedback, generate next turn, stop on terminal condition or max turns.
- [x] 4.5 Ensure each turn records compact evidence only: turn index, user input summary, stage, missing fields, path/card evidence, per-turn verdict, and error summary.
- [x] 4.6 Verify raw SSE payloads, raw cards, raw model text, and raw frontend sections are absent from interactive `turn_traces`.

## 5. Interactive Verdict and Attribution Evidence

- [x] 5.1 Add a failing test that if a turn expectation requires clarification but the system jumps directly to planning, the final interactive verdict is not `correct`.
- [x] 5.2 Add a failing test that if all required turn expectations pass and the stop condition is satisfied, the final interactive verdict can be `correct`.
- [x] 5.3 Implement final conversation verdict derivation from per-turn judge results, turn expectations, stop reason, and terminal stage.
- [x] 5.4 Ensure attribution/check evidence references the current interactive conversation and does not invent failure causes for correct conversations.
- [x] 5.5 Verify max-turn stop returns `uncertain` with a clear stop reason and bounded evidence.

## 6. Frontend Case-Pool Rendering and Persistence

- [x] 6.1 Add a failing summary frontend test that applying an interactive run keeps exactly one candidate row keyed by the original intent case id.
- [x] 6.2 Add a failing frontend test that the row displays intent summary, turn count, final stage, stop reason, and final verdict for an interactive run.
- [x] 6.3 Add a failing frontend persistence test that an interactive case stores only source fields and compact conversation/status summaries, not raw per-turn payloads.
- [x] 6.4 Update `summary.html` row summary/detail rendering to recognize `conversation_summary` and compact `turn_traces` without changing existing single-run rendering.
- [x] 6.5 Verify existing client_search case-pool retention tests and marketing-planning UAT frontend tests still pass.

## 7. End-to-End Verification and Check Report

- [x] 7.1 Run `python -m unittest tests.test_marketting_planning_adapter tests.test_marketting_planning_uat tests.test_summary_case_pool_retention -v`.
- [x] 7.2 Run compatibility checks for QA and client_search single-run behavior, including project listing and representative run_chain/batch cases.
- [x] 7.3 Run `python -m compileall -q impl` and `python -m impl.cli projects`.
- [x] 7.4 Run an API-level marketing-planning interactive batch smoke through `/api/batch_start` and `/api/batch_status`, confirming one intent case produces one completed run with compact conversation summary.
- [ ] 7.5 Manually smoke-test the summary frontend for marketing-planning interactive mock cases: build/generate cases, run batch attribution, confirm one row per intent and expandable per-turn evidence.
- [x] 7.6 Update or create a Chinese `check.md` audit report under `search-test-case/issue` covering protocol extensibility, cross-project compatibility, marketing-planning divergence point 1, frontend behavior, compact persistence, overfit risk, and verification evidence.
- [x] 7.7 Update the previous marketing-planning demand/check report to stop claiming divergence point 1 is complete unless this interactive protocol and frontend flow have passed verification.
