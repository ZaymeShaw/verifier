# Trace State Machine Protocol

The trace state machine is the generic runtime protocol for a complete trace evaluation. It orchestrates input preparation, mock/input handling, application execution or provided-output capture, evidence collection, judge analysis, attribution analysis, finalization, and incomplete or human-review stops.

Project-specific API fields, prompts, service endpoints, semantic mappings, and business rules must not be encoded in this protocol. Projects provide those through `impl/projects/<project>` configuration, standards, adapters, and hooks.

## State graph

A state graph is a declarative object with:

- `graph_id`: stable graph identifier.
- `version`: graph contract version.
- `initial_state`: first state id.
- `states`: state declarations keyed by id.
- `transitions`: conditional transitions between states.
- `depth_profile`: optional profile such as `fast`, `standard`, or `deep`.
- `limits`: retry, depth, and timeout limits.

Each state declaration defines:

- `state_id`
- `role`
- `executor_refs`
- `required_evidence`
- `gate_refs`
- `merge_policy`
- `on_error`
- `max_retries`

## Default graph

Projects without a custom graph use the default graph:

1. `prepare_trace`
2. `mock_or_input`
3. `execute_or_capture`
4. `collect_evidence`
5. `judge_plan`
6. `judge_compare`
7. `judge_critic`
8. `attribute_plan`
9. `attribute_probe`
10. `attribute_critic`
11. `finalize`
12. `incomplete_or_human_review`

Transitions are conditional. A critique state may return to evidence collection, retry a focused state, continue to finalization, or stop incomplete when configured limits are reached.

## State execution record

Every executed state appends a record to trace state history:

- `state_id`
- `role`
- `status`: `pending`, `running`, `succeeded`, `failed`, `skipped`, or `blocked`
- `attempt`
- `started_at`
- `finished_at`
- `input_summary`
- `outputs`
- `subagent_results`
- `evidence_refs`
- `gate_decisions`
- `transition_decision`
- `errors`

The record must be inspectable by CLI, API, frontend, batch persistence, and check review.

## Transition decision

A transition decision records:

- `from_state`
- `to_state`
- `condition`
- `reason`
- `gate_ids`
- `retry_count`
- `stop_reason`

Generic transition conditions may inspect state status, gate decisions, missing evidence, contradiction flags, retry counts, and adapter hook outcomes. Project-specific meanings remain in project declarations or hooks.

## Stop reasons

Stop reasons are structured values:

- `completed`
- `incomplete_missing_evidence`
- `incomplete_gate_failed`
- `incomplete_retry_limit`
- `human_review_required`
- `execution_error`
- `skipped_by_configuration`

Incomplete stops must preserve the state history and the blocking gate or evidence reason.

## Compatibility

The state machine augments existing trace outputs. Existing `RunTrace`, `JudgeResult`, `AttributeResult`, CLI payloads, API payloads, and frontend summaries should continue exposing their current useful fields while adding state history, gate decisions, transition decisions, and incomplete reasons.
