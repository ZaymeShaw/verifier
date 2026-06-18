## Context

`marketting-planning` is a stateful conversation agent. The current verifier can store `turns`, `session_id`, and `user_intent`, but it still treats a case as one static input passed through one `run_chain`. That is not enough for divergence point 1 in `reviews-of-propose/20260611-marketplan-integration-risks.md`: the mock agent should start from one user intent, observe each system response, and generate the next user message until the intent is resolved or no further useful turn is needed.

The root problem is not only a marketing-planning project gap. The current case protocol is not extensible enough: it conflates “case identity/source fields” with “single request input” and has no first-class way to declare interaction mode, per-turn expectations, or conversation summaries. The new design should extend the generic case protocol while keeping the existing single-run shape valid.

The existing generic verifier protocol is used by QA, client_search, and marketting-planning. QA and client_search are still single-run projects and must not be forced into an interactive protocol. The extension therefore needs to be additive and mode-discriminated: old cases remain valid, while multi-turn cases can declare interaction metadata explicitly.

## Goals / Non-Goals

**Goals:**

- Define a backward-compatible case protocol extension for interaction modes: single-run, static multi-turn, and adapter-driven interactive cases.
- Keep the protocol generic: core owns mode normalization, case identity, dispatch, bounded result shape, and compact persistence; adapters own project-specific intent facts, feedback interpretation, next-turn generation, and stop policy.
- Represent marketing-planning multi-turn mock cases as the first concrete use of that extension: `user_intent`, `interaction`, adapter-owned `mock_agent`, and per-turn `turn_expectations`.
- Execute interactive cases as a bounded conversation loop over the existing unified chain while preserving generic verifier APIs.
- Keep raw SSE/card payloads out of persisted case pools and compact batch status.
- Keep QA/client_search and existing single-turn marketing-planning cases working without protocol migration.

**Non-Goals:**

- Do not modify the external `/Users/xiaozijian/WorkSpace/package/marketing-planning` repository.
- Do not add a project-private verifier endpoint.
- Do not build a general autonomous LLM simulator for every project in this change.
- Do not replace the existing single-run input protocol for projects that do not opt into interactive evaluation.

## Decisions

### 1. Extend the generic case protocol with an additive interaction envelope

A case can keep the current shape (`id`, `input`, `output`, `reference`, `metadata`, `scenario`) or add an `interaction` envelope:

```json
{
  "interaction": {
    "mode": "single_run | static_turns | interactive_intent",
    "turns": [],
    "turn_expectations": [],
    "conversation_expectation": {},
    "policy": {
      "max_turns": 4,
      "stop_when": ["adapter_defined_condition"]
    }
  },
  "mock_agent": {
    "driver": "adapter",
    "facts": {}
  }
}
```

Generic fields mean:

- `interaction.mode`: the only core-dispatched mode discriminator.
- `interaction.turns`: static source turns when the case is replay-style, not a signal to enter a live interactive loop.
- `interaction.turn_expectations`: project-defined expectation objects consumed by adapter/judge hooks, not interpreted by core.
- `interaction.conversation_expectation`: project-defined final conversation contract.
- `interaction.policy.max_turns`: a generic safety bound used by core/adapter dispatch.
- `interaction.policy.stop_when`: opaque condition names interpreted by the adapter.
- `mock_agent`: optional adapter contract for simulated user behavior; core only passes it through.

If `interaction` is missing, the case is treated as `single_run`. Existing top-level `turns` remain accepted as legacy/static multi-turn input and can be normalized into `interaction.mode = "static_turns"` internally without changing stored source cases.

Rationale: the old protocol was not extensible enough, but replacing it globally would risk QA `actual_answer/golden_answer` semantics and client_search query parsing. A mode-discriminated envelope lets new multi-turn scenarios exist beside old cases.

Alternative considered: keep this as only a marketing-planning adapter marker. Rejected because the underlying problem is a generic case protocol gap; future stateful agents should not need another project-specific ad hoc field.

### 2. Keep interactive behavior in adapter capabilities, not protocol fields

The generic pipeline should only normalize the mode, enforce generic safety bounds, preserve case identity, and call an adapter-provided hook when `interaction.mode = interactive_intent`. The hook owns:

- how to generate the first user message from project-specific intent/source facts;
- how to interpret system output summaries;
- how to choose the next user message from project-specific feedback;
- how to evaluate project-defined turn expectations;
- when adapter-defined stop conditions are satisfied.

For marketing-planning, those facts include `user_intent`, target values, path type choices, workflow stages, and clarification cards. For another future project, the same generic envelope could carry different adapter-owned facts without changing core dispatch.

Rationale: “what should the next user say?” is project behavior, not generic verifier behavior. Keeping it in the adapter avoids coupling QA/client_search or future projects to marketing-planning fields such as `target_value`, `path_types`, and clarification cards.

Alternative considered: implement a generic `MockAgent` in core. Rejected for this change because it would either be too abstract to verify or would leak marketing-planning assumptions into core.

### 3. Store a compact conversation trace as the single run result

An interactive case still returns one batch run with the original `case_id`. Its `trace.project_fields` contains compact conversation evidence such as:

```json
{
  "interaction_mode": "interactive_intent",
  "conversation_summary": {
    "turn_count": 3,
    "final_stage": "planning",
    "stop_reason": "intent_resolved"
  },
  "turn_traces": [
    {
      "turn_index": 1,
      "user_input": {"user_text": "帮我做NBEV规划"},
      "stage": "clarification",
      "missing_fields": ["target_value", "path_types"],
      "judge_verdict": "correct"
    }
  ]
}
```

Full raw SSE, raw cards, raw model text, and raw frontend sections stay out of `turn_traces` and persisted case-pool data.

Rationale: the frontend and batch status need one row per user intent, not one row per turn. Compact per-turn evidence is enough to audit the mechanism without exploding browser storage.

Alternative considered: return each turn as a separate batch run. Rejected because it fragments one user intent across multiple candidate rows and makes clustering/check summaries harder to interpret.

### 4. Judge per turn first, then summarize the conversation verdict

The runner should evaluate each turn against the corresponding `turn_expectations` when provided. The final case verdict is derived from the turn verdicts and final stop reason:

- `incorrect` if any required turn expectation is violated;
- `uncertain` if the runner stops because of max turns, missing evidence, or service failure;
- `correct` if all required expectations pass and the stop condition is satisfied.

Rationale: multi-turn correctness cannot be judged only from the final message. A system that jumps directly to planning when it should clarify is wrong even if a later card looks plausible.

Alternative considered: judge only final output. Rejected because it loses the workflow-stage correctness requirement from the divergence document.

### 5. Frontend adapts display without changing generic APIs

`summary.html` should recognize compact interaction metadata on a run/case and render:

- a stable row keyed by the intent case id;
- intent summary from `user_intent.goal` or case input summary;
- `turn_count`, `final_stage`, and `stop_reason` in visible fields;
- expandable JSON/details containing compact `turn_traces`.

The frontend should preserve the existing table for single-run cases. No new endpoint is required: `/api/mock_cases`, `/api/run_chain`, `/api/batch_start`, `/api/batch_status`, and `/api/frontend_view` remain the only verifier APIs.

Rationale: the conflict risk is mostly frontend assuming every row has one `input -> output`. Rendering interactive metadata as an extension avoids breaking other projects.

### 6. Add regression tests for cross-project compatibility

Implementation must include tests proving:

- QA still treats `output` as `actual_answer` and `reference` as `golden_answer`;
- client_search still accepts single query cases and stable `case_id` candidate rows;
- marketing-planning single-turn cases still run through the old path;
- only cases with the interactive marker enter the new loop.

Rationale: protocol changes are high-risk. Compatibility tests prevent the marketing-planning fix from becoming a global input-shape regression.

## Risks / Trade-offs

- Interactive loop can hang or overrun cost/time → bound with `max_turns`, explicit stop conditions, and per-turn error handling.
- Mock agent policy can become hardcoded to sample text → base next-turn generation on intent facts, missing fields, path type intent, and compact system feedback, not query string matching.
- Conversation summaries may still get too large → store only compact fields in `turn_traces`; backend compacting strips raw payloads before batch status.
- Frontend could accidentally persist full turn traces with raw outputs → extend existing lightweight case persistence tests for interactive rows.
- Generic pipeline hook can leak project assumptions → core should call adapter hooks by capability marker and keep field interpretation inside the adapter.
- Existing project behavior can regress → require targeted QA, client_search, marketing-planning single-run, and interactive marketing-planning tests before completion.

## Migration Plan

1. Add failing tests for interactive case detection and cross-project non-interference.
2. Add adapter capability/hook for marketing-planning interactive cases.
3. Add bounded conversation runner that returns one compact run per intent case.
4. Update marketing-planning mock cases/datasets to include at least one interactive intent case.
5. Update frontend rendering and persistence for interactive summaries.
6. Run adapter/UAT/frontend regression tests plus compile and project smoke checks.
7. Update the check report to mark divergence point 1 as actually implemented, including remaining limitations.

Rollback is straightforward: remove the interactive marker from mock cases and the generic pipeline will use the existing single-run path. Existing single-run project cases remain unchanged throughout the migration.
