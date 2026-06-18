## ADDED Requirements

### Requirement: Single-turn intent project registration
The system SHALL register `marketting-planning-intent` as a separate verifier project for the single-turn marketing-planning intent-recognition capability.

#### Scenario: Project is listed separately
- **WHEN** the verifier lists available projects
- **THEN** `marketting-planning-intent` is present alongside existing projects without replacing `marketting-planning`

#### Scenario: Project does not declare interactive cases
- **WHEN** mock cases are generated for `marketting-planning-intent`
- **THEN** no case declares `interaction.mode = interactive_intent`

### Requirement: Intent-recognition primary API
The system SHALL use `/api/v1/marketing-planning/intent-recognition` as the primary business API for `marketting-planning-intent` live runs while sharing the same external marketing-planning service runtime used by `marketting-planning`.

#### Scenario: Live request targets intent-recognition
- **WHEN** a `marketting-planning-intent` live run is executed
- **THEN** the adapter sends the request to the configured intent-recognition endpoint rather than the broader `/stream` endpoint

#### Scenario: Request is single-turn
- **WHEN** a case contains a query or user_text
- **THEN** the adapter builds one intent-recognition request for that input without requiring turns, session continuation, or interactive next-turn generation

### Requirement: Compact intent output normalization
The system SHALL normalize intent-recognition responses into compact intent evidence for trace, judge, attribution, frontend display, and persistence.

#### Scenario: Successful intent response is compacted
- **WHEN** the business API returns an intent-recognition response
- **THEN** the trace extracted output contains compact fields for intent, confidence, slots/entities, ambiguity/fallback indicators, and error summary if present

#### Scenario: Raw downstream payloads are not persisted
- **WHEN** a batch result is compacted or saved into the frontend case pool
- **THEN** raw downstream payloads, raw model text, and large response bodies are absent from persisted case data

### Requirement: Two-layer intent judging
The system SHALL judge intent-recognition outputs with a deterministic contract gate before semantic LLM judge reasoning.

#### Scenario: Expected intent matches
- **WHEN** the extracted intent matches the reference expected intent, required slots are present, fallback is allowed or absent, and confidence constraints pass
- **THEN** the deterministic contract gate passes and the final judge verdict can be `correct` after semantic judge reasoning

#### Scenario: Required slot is missing
- **WHEN** the extracted intent matches but a reference-required slot/entity is missing
- **THEN** the deterministic contract gate fails and the final verdict is non-correct with current-case missing-slot evidence

#### Scenario: Fallback is disallowed
- **WHEN** the output indicates fallback, unknown, ambiguous, or low-confidence intent and the reference does not allow fallback
- **THEN** the deterministic contract gate fails and the final verdict is non-correct with current-case fallback or confidence evidence

#### Scenario: Semantic intent is wrong despite valid shape
- **WHEN** the deterministic contract gate passes but the semantic judge finds the user text does not match the extracted business intent
- **THEN** the final verdict is non-correct with semantic mismatch evidence from the current case

### Requirement: Current-case attribution evidence
The system SHALL build attribution for `marketting-planning-intent` from the current case trace, reference contract, extracted intent evidence, and judge result.

#### Scenario: Correct intent has no invented failure
- **WHEN** the judge verdict is `correct`
- **THEN** attribution reports no failure category and does not invent a root cause

#### Scenario: Incorrect intent identifies earliest divergence
- **WHEN** the judge verdict is non-correct
- **THEN** attribution references the current case evidence such as intent mismatch, missing slot, fallback disallowed, API error, or parse failure

### Requirement: Frontend and batch compatibility
The system SHALL support `marketting-planning-intent` through existing generic verifier APIs and summary frontend behavior.

#### Scenario: Batch run completes through generic API
- **WHEN** selected `marketting-planning-intent` cases are submitted through `/api/batch_start`
- **THEN** `/api/batch_status` returns one run per original case id with judge and attribution results

#### Scenario: Summary frontend displays intent evidence
- **WHEN** a completed `marketting-planning-intent` case is rendered in the summary frontend
- **THEN** the row displays compact intent output, judge verdict, and attribution summary without requiring project-specific frontend endpoints

### Requirement: Cross-project compatibility
The system SHALL preserve existing QA, client_search, and marketting-planning behavior while adding `marketting-planning-intent`.

#### Scenario: Existing projects still list and run
- **WHEN** compatibility checks run after adding `marketting-planning-intent`
- **THEN** QA, client_search, and marketting-planning still list and representative single-run/batch cases remain valid
