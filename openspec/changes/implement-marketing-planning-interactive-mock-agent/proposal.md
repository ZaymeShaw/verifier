## Why

`marketting-planning` is a multi-turn stateful agent, but the current verifier case protocol only models cases as static single-run inputs or static bundled `turns`. That exposes a generic protocol extensibility gap: the verifier must distinguish case identity/source data from execution interaction mode, while remaining compatible with QA/client_search single-run cases and allowing any future stateful project to provide its own interactive driver.

## What Changes

- Introduce a backward-compatible extensible case protocol for interaction modes across projects.
- Add a generic `interaction` envelope so a case can declare whether it is `single_run`, `static_turns`, or `interactive_intent` without changing existing `input/output/reference` semantics.
- Keep core interpretation project-neutral: core normalizes interaction mode, preserves source fields, dispatches to adapter capability hooks, and never interprets business fields such as marketing target values, path types, cards, or stages.
- Add an adapter-owned interactive driver contract for projects that opt in. Marketing-planning is the first implementation, using `user_intent`, adapter-specific facts, and per-turn expectations to generate user turns from compact system feedback.
- Add a multi-turn runner hook that executes one intent case as one bounded conversation result through existing generic verifier APIs and the project business path.
- Store per-turn compact trace/judge evidence plus final conversation summary as one run keyed by the original case id, without persisting raw SSE/card payloads.
- Update frontend summary case-pool rendering so one interactive case remains one row, with visible intent/final-stage/turn-count summary and expandable compact per-turn evidence.
- Preserve existing single-turn cases and generic APIs; do not add project-private verifier endpoints or modify the external marketing-planning repository.

## Capabilities

### New Capabilities
- `extensible-case-protocol`: Covers backward-compatible case protocol extensions for single-run, static multi-turn, and interactive intent-driven evaluation modes across projects.
- `marketing-planning-interactive-mock-agent`: Covers intent-driven multi-turn mock case protocol, conversation-loop execution, per-turn evidence, and frontend display for stateful marketing-planning evaluation.

### Modified Capabilities
- `marketing-planning-eval`: Strengthens marketing-planning evaluation requirements so multi-turn cases are evaluated as interactive conversations, not static bundled inputs.

## Impact

- Affected code: `impl/projects/marketting-planning/adapter.py`, unified pipeline/batch execution if needed, `impl/frontend/summary.html`, and compacting helpers in `impl/server.py` if multi-turn summaries need additional stripping.
- Affected tests: marketing-planning adapter tests, UAT/frontend summary tests, and regression coverage for the new interactive protocol.
- Affected docs/reports: `impl/projects/marketting-planning` docs and `search-test-case/issue` check report for the divergence-point follow-up.
- APIs: existing generic verifier APIs only (`/api/mock_cases`, `/api/run_chain`, `/api/batch_start`, `/api/batch_status`, `/api/frontend_view`); the business path remains `/api/v1/marketing-planning/stream`.
- External repository: `/Users/xiaozijian/WorkSpace/package/marketing-planning` remains read-only unless explicitly requested.
