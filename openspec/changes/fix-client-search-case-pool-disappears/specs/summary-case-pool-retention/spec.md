## ADDED Requirements

### Requirement: Preserve candidate rows after batch attribution
The summary case-pool UI SHALL preserve candidate rows after batch attribution starts, reports progress, completes, or reports per-case failures. Applying a batch run SHALL merge run fields into the matching existing candidate row by stable case identity without dropping source case fields.

#### Scenario: Completed client_search run updates visible row
- **WHEN** a selected client_search candidate with id `client_search_value_service_100-006` receives a completed batch run with the same `case_id`
- **THEN** the candidate area still contains that row with its original `id`, `input`, `dataset_id`, `dimension_type`, `selected`, and `source` fields
- **AND** the row displays the completed run `status`, `trace`, `judge`, `attribute`, `frontend_view`, `execution_mode`, `output_source`, and `error` fields from that run

#### Scenario: Uncertain or error run does not remove row
- **WHEN** a batch run for an existing candidate has status `uncertain` or carries an `error`
- **THEN** the candidate area still contains the original candidate row
- **AND** the row displays the uncertain/error evidence instead of disappearing or being filtered out

### Requirement: Keep case-pool persistence lightweight and non-blocking
The summary UI SHALL persist only durable lightweight case source fields and bounded status/error summaries for case-pool restoration. Browser storage write failures MUST NOT abort batch polling, row rendering, or application of later case results.

#### Scenario: Storage quota failure during batch polling
- **WHEN** writing the case pool to browser storage throws a quota error while batch polling is applying client_search results
- **THEN** the current in-memory candidate rows remain visible
- **AND** batch polling continues for unrelated and later cases
- **AND** raw traces, large matched-pattern payloads, raw model output, and full frontend views are not written into storage

### Requirement: Do not replace candidate pool with malformed batch status
The summary UI SHALL treat empty or malformed batch status payloads as diagnostics, not as authoritative replacement case pools.

#### Scenario: Final status has no runs
- **WHEN** a batch status response reports completion but has no `runs` array or an empty malformed `runs` array
- **THEN** the existing candidate pool remains visible
- **AND** the UI records a bounded diagnostic message explaining that no mergeable runs were returned

#### Scenario: Run identity is missing
- **WHEN** a batch run has no stable `case_id` or matching `id`
- **THEN** the UI does not clear the existing case pool
- **AND** the unmatched run is either ignored with a diagnostic message or displayed separately without replacing existing candidates
