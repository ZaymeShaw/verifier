## ADDED Requirements

### Requirement: Case protocol supports interaction modes without breaking single-run cases
The verifier case protocol SHALL support an additive, project-neutral `interaction` envelope that distinguishes `single_run`, `static_turns`, and `interactive_intent` cases while preserving the existing `id`, `input`, `output`, `reference`, `metadata`, and `scenario` shape. Core protocol handling SHALL treat project-specific intent facts, turn expectations, stop conditions, and mock-agent details as adapter-owned data unless explicitly defined as generic fields.

#### Scenario: Existing single-run case remains valid
- **WHEN** a QA or client_search case has no `interaction` field and uses the existing `input/output/reference/metadata/scenario` fields
- **THEN** the verifier treats it as `interaction.mode = single_run` internally and preserves the existing run_chain and batch behavior

#### Scenario: Legacy static turns are normalized without source migration
- **WHEN** a case includes legacy top-level `turns` but no `interaction` envelope
- **THEN** the verifier MAY normalize it internally as `interaction.mode = static_turns` while keeping the original case source shape accepted

#### Scenario: Interactive intent case is explicitly marked
- **WHEN** a case declares `interaction.mode = interactive_intent`
- **THEN** the verifier routes the case through an adapter interactive execution hook instead of flattening all turns into one static request, and treats adapter-specific mock-agent/fact fields as opaque data

### Requirement: Interaction protocol keeps project-specific behavior out of core fields
The protocol SHALL define generic interaction structure but MUST keep project-specific next-turn policy and business field interpretation in the project adapter.

#### Scenario: Core detects mode but does not interpret project fields
- **WHEN** the core pipeline sees `interaction.mode = interactive_intent`
- **THEN** it delegates message generation, feedback interpretation, turn expectation evaluation, and stop-condition evaluation to adapter hooks instead of interpreting project-specific fields such as marketing `target_value`, `path_types`, workflow stages, or clarification cards

#### Scenario: Generic safety fields stay project-neutral
- **WHEN** an interactive case declares bounds such as `interaction.policy.max_turns`
- **THEN** the verifier may enforce those generic bounds without interpreting adapter-defined stop condition names or business facts

#### Scenario: Unsupported interactive project fails safely
- **WHEN** a project case declares `interaction.mode = interactive_intent` but its adapter does not support interactive execution
- **THEN** the verifier returns a bounded error/uncertain run for that case without changing behavior for other cases in the batch

### Requirement: Conversation results remain one case result with compact evidence
The protocol SHALL represent an interactive conversation as one case result keyed by the source case id, with compact per-turn evidence and a final conversation summary.

#### Scenario: Interactive batch result keeps one row per intent case
- **WHEN** an interactive case completes multiple turns during batch attribution
- **THEN** batch status returns one run for the original `case_id` with `conversation_summary` and compact `turn_traces`, not one run per turn

#### Scenario: Raw turn payloads are not persisted
- **WHEN** an interactive run includes per-turn evidence
- **THEN** persisted frontend case-pool data and compact batch status exclude raw SSE payloads, raw cards, raw model text, and `frontend_view.raw_sections`

### Requirement: Protocol changes are regression-tested across existing projects
The verifier SHALL include compatibility tests proving that the interaction protocol extension does not alter existing single-run project semantics.

#### Scenario: QA output/reference semantics remain stable
- **WHEN** QA cases include `actual_answer` and `golden_answer`
- **THEN** the verifier continues treating output as `actual_answer` and reference as `golden_answer`

#### Scenario: client_search query cases remain stable
- **WHEN** client_search cases use existing single-query input and stable case ids
- **THEN** the verifier continues running and rendering them without requiring interaction metadata
