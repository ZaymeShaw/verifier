## Context

The verifier currently has a unified project pipeline and two concrete project styles: `QA` for provided answer/reference evaluation, and `client_search` for single-turn query parsing plus project-specific boundary handling. The updated `demand.md` requires the same protocol-driven chain to support more complex projects without creating split-brain flows across mock, live, batch, frontend, judge, attribute, and check.

`marketing-planning` is different from the existing projects in three ways: it is multi-turn and session state matters; its user-facing endpoint returns SSE event streams rather than a single compact JSON response; and correctness is stage-dependent, so a clarification card can be correct for one case while a planning card is required for another. The existing issue analysis already identifies the main risks: case state contamination, large SSE/card payloads, fallback masking real failures, path-type dispatch errors, status-code ambiguity, and insufficient trace detail for attribution.

This design treats those differences as project-owned behavior first. The core pipeline remains the source of truth for orchestration, while `impl/projects/marketting-planning` owns request normalization, session isolation, SSE parsing, compact output summaries, stage-aware judge context, and attribution context.

## Goals / Non-Goals

**Goals:**

- Add a minimal v1 `marketting-planning` project that can run mock/provided-output cases through the existing `run_chain` and batch APIs.
- Normalize multi-turn input and SSE/provided output into stable `RunTrace.extracted_output` and `project_fields` summaries.
- Keep `output` and `reference` aligned in top-level shape so frontend tables remain readable and comparable.
- Isolate session IDs per case, especially in batch, so cases cannot leak state into each other.
- Provide project docs and mock cases for intent recognition, clarification, multi-turn accumulation, execution planning, fallback, non-agent intent, and streaming protocol scenarios.
- Add check-agent audit artifacts that verify mechanism alignment, not just visible outputs.

**Non-Goals:**

- Do not modify or push the external `/Users/xiaozijian/WorkSpace/package/marketing-planning` repository.
- Do not require live external service startup for v1 validation.
- Do not add a parallel verifier API path for this project.
- Do not hardcode historical case answers as generic rules.
- Do not move marketing-specific concepts such as `path_types`, card codes, or SSE event names into required core schema fields.

## Decisions

### 1. Project adapter owns multi-turn and SSE normalization

The `marketting-planning` adapter will accept cases in a generic outer shape with project-specific details inside `input`, for example `user_intent`, `turns`, `session_id`, `scenario`, `expected_stage`, `expected_path_types`, and `boundary`. It will produce a request that can either be mocked/provided or sent to the real stream endpoint when available.

For raw SSE/provided outputs, the adapter will extract a compact summary:

- `stage`: intent, clarification, planning, non_agent, fallback, or unknown.
- `event_summary`: event names, order, counts, final event, and completion flag.
- `card_summary`: path type, card code/style/name, fallback flag, forecast value, achievement rate, and stable card identity.
- `session_summary`: sanitized session ID, required fields, accumulated fields, and missing fields.
- `errors`: sanitized error/fallback indicators.

Raw responses can remain in `RunTrace.raw_response` for current-page drill-down, but frontend persistence and judge context should rely on the compact summary.

Alternative considered: add generic core fields for events/cards/sessions. Rejected for v1 because it would make project-specific concepts appear universal and increase risk to QA/client_search.

### 2. Reference is a conditional contract, not exact text

Marketing-planning references should align to the output summary shape. A case reference may contain expected stage, required events, required path types, required/forbidden cards, fallback allowance, semantic requirements, and expected session fields. The adapter and judge context should preserve this structure instead of converting it into a single golden string.

Alternative considered: make reference a free-form golden answer. Rejected because NBEV planning outputs include open-ended AI analysis text and complex cards where exact matching is brittle.

### 3. v1 supports mock/provided-output first, live SSE second

The first implementation should pass verifier validation with mock/provided cases. Live SSE support can be added in the adapter using standard-library HTTP handling and should be marked unavailable or not_verified when the service cannot be reached. This lets the project enter the verifier without depending on external keys, Doris, or session-store state.

Alternative considered: full UAT before adapter merge. Rejected because external dependencies and secrets make it too easy to block core integration and encourage bypasses.

### 4. Deterministic project checks supplement LLM judge

The generic LLM judge remains in the chain, but the adapter should provide deterministic stage and structure signals in `build_judge_context` and may reconcile or block judge output when local evidence contradicts it. Examples: expected stage mismatch, missing required path type, forbidden planning when clarification is expected, or fallback not allowed by boundary.

Alternative considered: rely entirely on prompt instructions. Rejected because the business app itself uses LLMs, and verifier needs executable evidence to avoid LLM-on-LLM ambiguity.

### 5. Check report audits the producing mechanism

The check artifact should confirm that mock generation, request normalization, output extraction, judge context, attribution context, batch isolation, and frontend persistence all use the unified pipeline. It should also record any remaining UAT limitations, such as live service not started or external data unavailable.

### 6. Frontend should not expose mock/live as a confusing case-pool mode

Mock generation is data generation, not a separate frontend execution lane. The summary page should not make users choose between "Mock 响应" and "真实服务" after building a mock case pool, because that makes the UI imply that mock cases belong to a mock-only path. Case-pool execution should submit the selected cases through the unified batch API; the backend/project adapter should determine the output source from the case data and project execution policy, then expose that source as trace evidence rather than as a user-facing primary switch.

The current summary UI still has a `batchMode` dropdown. That is a known design gap: it allowed the path "构建 Mock 用例池 -> 批量归因" to silently run as live service when the dropdown stayed on its default value, producing all `incorrect` in the frontend while backend mock-mode tests showed all `correct`. The fix should remove or demote this mode switch instead of simply changing the default.

Alternative considered: default the dropdown to `Mock 响应`. Rejected because it preserves the misleading split and does not address the root misunderstanding that mock cases are evaluation data while mock response is only one possible output source.

## Risks / Trade-offs

- [Risk] Mock/provided-output v1 may not prove the real SSE endpoint works. → Mitigation: mark live UAT as a separate verification item and make live failures explicit in trace/check rather than treating mock success as production success.
- [Risk] Compact summaries may omit details needed for attribution. → Mitigation: keep targeted evidence in `project_fields` and `execution_trace`, and keep raw response available for explicit drill-down without persisting it in lightweight case pools.
- [Risk] Stage-aware deterministic checks become overfit rules. → Mitigation: base checks on project docs and reference contracts, not specific historical queries; report overfit risks in check output.
- [Risk] Multi-turn batch can still leak session state if input supplies a reused session ID. → Mitigation: adapter should generate or namespace session IDs per case unless a case explicitly opts into shared-session testing.
- [Risk] Status-code/card-sort ambiguity remains unresolved in the business docs. → Mitigation: encode the current chosen standard in project docs and surface unresolved discrepancies as check warnings rather than silently guessing.

## Migration Plan

1. Add project docs and adapter scaffolding under `impl/projects/marketting-planning`.
2. Add mock cases and provided-output parsing so `/api/mock_cases`, `/api/run_chain`, and `/api/batch_start` work without external services.
3. Add optional live SSE handling with safe unavailable status when the service is not running.
4. Run compile, project listing, mock run_chain, batch run, and check-agent audit.
5. Leave existing QA/client_search behavior unchanged and verify project listing still includes them.

Rollback is local: remove the new project directory and any project-neutral protocol text added for multi-turn/SSE support. Since v1 should not change external services or persisted production state, rollback does not require data migration.

## Open Questions

- Whether live UAT should be required before considering this v1 complete, or whether mock/provided-output verifier coverage is enough for the first implementation.
- Which card sort/status-code standard should be authoritative if business docs and implementation disagree.
- Whether multi-turn shared-session cases should be supported in v1 or deferred until isolated-session cases are stable.
