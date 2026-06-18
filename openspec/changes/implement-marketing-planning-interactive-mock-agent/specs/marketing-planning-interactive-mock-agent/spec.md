## ADDED Requirements

### Requirement: Marketing-planning mock cases use intent-driven interactive contracts
Marketing-planning mock cases for stateful scenarios SHALL model a single user intent, an interaction contract, mock-agent behavior, and per-turn expectations instead of relying on a pre-flattened static input.

#### Scenario: Multi-turn mock case declares intent and interaction contract
- **WHEN** marketing-planning mock cases are generated for field clarification or planning scenarios
- **THEN** at least one case includes `user_intent`, `interaction.mode = interactive_intent`, `mock_agent`, and `interaction.turn_expectations`

#### Scenario: Path type intent is part of the user intent
- **WHEN** a mock case expects the user to choose team/customer/product planning paths
- **THEN** the case expresses the desired path choices in `user_intent` or interaction facts so the mock agent can generate path-type answers as part of the conversation

### Requirement: Marketing-planning interactive runner generates turns from system feedback
The marketing-planning adapter SHALL support interactive execution by generating each next user message from the original user intent and the compact system feedback from prior turns.

#### Scenario: First turn is generated from user intent
- **WHEN** an interactive marketing-planning case starts
- **THEN** the runner generates the first user input from `user_intent` rather than replaying a fixed full request containing all future facts

#### Scenario: Next turn responds to clarification feedback
- **WHEN** a prior turn output indicates missing fields such as `target_value` or `path_types`
- **THEN** the mock agent generates the next user input using the corresponding facts from `user_intent`

#### Scenario: Runner stops when the intent is resolved
- **WHEN** the conversation reaches the expected planning/non-agent/fallback terminal stage or another declared stop condition
- **THEN** the runner stops and records `conversation_summary.stop_reason`

#### Scenario: Runner is bounded
- **WHEN** an interactive conversation does not reach a terminal stage before `mock_agent.max_turns`
- **THEN** the runner stops with an `uncertain` result and records the max-turn stop reason

### Requirement: Marketing-planning interactive verdict uses per-turn expectations
The marketing-planning interactive result SHALL judge the conversation by per-turn workflow expectations and final stop condition, not only by the final output.

#### Scenario: Wrong early stage makes case incorrect
- **WHEN** a turn expectation requires clarification but the system jumps directly to planning
- **THEN** the final interactive case verdict is not marked correct even if the final card output appears plausible

#### Scenario: All required turns pass
- **WHEN** every required turn expectation passes and the declared stop condition is satisfied
- **THEN** the final interactive case verdict can be marked correct with compact per-turn evidence

### Requirement: Marketing-planning frontend displays one interactive intent row
The summary frontend SHALL render an interactive marketing-planning case as one candidate row with compact conversation summary and expandable per-turn evidence.

#### Scenario: Candidate row shows conversation summary
- **WHEN** an interactive marketing-planning run is applied to the case pool
- **THEN** the row remains keyed by the original case id and shows intent summary, turn count, final stage, stop reason, and final verdict

#### Scenario: Details expose compact turns
- **WHEN** the user opens the row details or JSON evidence for an interactive case
- **THEN** the frontend includes compact `turn_traces` with user input summary, stage, missing fields, cards/path evidence, and per-turn verdicts

#### Scenario: Frontend persistence remains lightweight
- **WHEN** an interactive case is saved to browser storage
- **THEN** the persisted case-pool entry keeps source fields and compact status summaries without raw per-turn SSE/card payloads
