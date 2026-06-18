## Context

`projects/marketting-planning-intent/marketplan-demand.md` clarifies that the current evaluation target is the extracted, single-turn `/api/v1/marketing-planning/intent-recognition` business API. Earlier `marketting-planning` work focused on the broader `/stream` planning flow and then explored interactive multi-turn mock-agent behavior; this new project must not inherit that scope. The goal is a separate verifier project whose semantics match intent recognition only.

The external business repository remains `/Users/xiaozijian/WorkSpace/package/marketing-planning`. `marketting-planning` and `marketting-planning-intent` share this same business service and local runtime on `127.0.0.1:9006`; they are separate verifier projects because they evaluate different business boundaries. The verifier may call the local service, but must not modify or push changes to that external repository unless the user explicitly asks.

## Goals / Non-Goals

**Goals:**

- Register a separate `marketting-planning-intent` verifier project.
- Use `/api/v1/marketing-planning/intent-recognition` as the project primary API.
- Treat each evaluation case as a single-turn intent-recognition request.
- Normalize the business response into compact intent evidence suitable for judge, attribution, frontend display, and persisted case pool state.
- Provide mock cases and UAT cases that exercise intent categories, required extracted fields, ambiguous/unknown intent behavior, and business error/fallback behavior.
- Preserve QA, client_search, and existing marketting-planning behavior.

**Non-Goals:**

- Do not implement multi-turn or interactive mock-agent behavior for this project.
- Do not evaluate the broader planning execution graph, streaming SSE cards, path execution cards, or terminal planning stages.
- Do not add a project-private verifier endpoint; use existing verifier APIs such as `/api/run_chain`, `/api/batch_start`, `/api/batch_status`, and summary frontend.
- Do not modify the external marketing-planning repository.

## Decisions

### Decision 1: Separate project id instead of overloading `marketting-planning`

Create `impl/projects/marketting-planning-intent/` rather than changing `marketting-planning` in place. The two projects evaluate different business boundaries: `marketting-planning` covers the broader planning stream, while `marketting-planning-intent` covers single-turn intent recognition. Separating them prevents judge/reference semantics from drifting between intent classification and planning execution.

Alternative considered: reuse `marketting-planning` with a scenario switch. That would make frontend/project selection ambiguous and could reintroduce split-brain behavior inside one adapter.

### Decision 2: Single-turn protocol only

The adapter will accept a single user query or user_text, construct the intent-recognition request, and evaluate one response. It will ignore interactive `turn_expectations` and will not call `run_interactive` for this project.

Alternative considered: keep the generic interactive protocol available. That remains available in core for future stateful projects, but it is not part of this demand because `/intent-recognition` is single-turn.

### Decision 3: Compact intent output contract

`extract_output()` should normalize live/provided/mock outputs into fields such as intent label, confidence, extracted slots/entities, ambiguity/fallback indicators, and raw-error summary. The exact field names may follow the business response, but persisted/frontend output must remain compact and must not store raw downstream payloads.

Alternative considered: persist the full intent-recognition JSON. That would make frontend batch runs easier to inspect initially, but repeats the large-payload persistence risk already found in previous case-pool work.

### Decision 4: Two-layer judging with contract gate before semantic judge

References should describe expected intent, required slots/entities, optional forbidden intents, fallback allowance, and confidence threshold when applicable. Judge reconciliation first runs a deterministic contract gate over the compact intent evidence; if expected intent, required slots, fallback allowance, parse status, or confidence constraints fail, the final verdict is non-correct with explicit failure evidence. Only cases that pass this gate proceed to semantic LLM judge reasoning, which explains whether the user text and extracted intent are business-semantically aligned.

Alternative considered: rely only on LLM judge over natural language output. That would be fragile and could pass cases where the interface contract is wrong. Another alternative was contract-only judging; that is useful for smoke tests but can miss cases where the interface shape is correct while the recognized business intent is semantically wrong.

## Risks / Trade-offs

- Wrong request schema for `/intent-recognition` → add RED adapter tests for normalized request shape and verify against local service through UAT.
- Response schema differs between mock/provided/live → normalize through one extraction path and test all three shapes before live UAT.
- Confusion with previous multi-turn design → document this project as single-turn and add regression tests that mock cases do not declare `interactive_intent`.
- Overfitting to one intent example → create mock cases covering multiple intent classes, ambiguous input, missing required slot, and fallback/error cases.
- Frontend invisibility → ensure summary output includes compact intent label, confidence, slots, verdict, and attribution summary in existing table/detail views.
