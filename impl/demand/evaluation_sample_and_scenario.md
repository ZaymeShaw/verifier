# Impl Demand: Multi-project Evaluation Sample and Scenario

## Generic direction

The evaluation system should remain protocol-driven and project-agnostic. `client_search` and `QA` must share the same execution concepts where possible, while project-specific behavior is implemented through adapters, project standards, and frontend extensions.

## EvaluationSample protocol direction

Introduce a generic sample concept for cases whose evaluated output may come from either a live API call or an uploaded dataset.

Recommended shape:

```json
{
  "id": "sample-id",
  "input": {},
  "output": {},
  "reference": {},
  "metadata": {},
  "scenario": "optional_project_specific_scenario"
}
```

Semantics:

- `input`: user request and context needed to evaluate the output.
- `output`: the actual system output being evaluated. For API projects this can come from the API response; for uploaded QA datasets it can come directly from the file.
- `reference`: golden answer, expected intent, expected structured result, or other evaluation reference.
- `metadata`: category, model name, latency, token usage, cost, source dataset, or row index.
- `scenario`: optional project-specific evaluation scenario selected or inferred by the project adapter.

Existing generic case pools should normalize uploaded/generated data into this sample/case shape before batch execution.

## RunTrace semantic alignment

Keep the existing `RunTrace` shape, but document broader semantics:

- `normalized_request`: normalized evaluation input, including any context/reference needed before output evaluation.
- `raw_response`: raw evaluated output source. This may be a live API response or an uploaded dataset's actual output.
- `extracted_output`: normalized evaluated output extracted by the adapter.
- `project_fields`: project-specific fields, including inferred scenario and sample normalization details when useful.

This keeps `client_search` valid while allowing QA datasets where no live API is called.

## Frontend requirements

- Project selection in live and summary pages should be an enumerable dropdown loaded from a unified API such as `/projects`; it should not be a free-text field.
- Switching project should keep one unified page flow, but project-local UI/session state should be isolated by project id.
- Rename generic frontend wording away from API-only language:
  - prefer `Input`, `Output`, `Reference`, `Evaluated output`, `RunTrace`;
  - avoid using `API output` for all projects.
- Summary/case-pool pages should display optional `scenario` and support filtering/grouping by it when the selected project exposes scenarios.
- A single batch action should remain the entry point. Scenario-specific logic belongs in project adapter/judge/attribute standards, not in separate frontend buttons.

## Scenario extension rule

Scenario is a project-specific extension allowed by the generic protocol. The generic system should not require every project to have scenarios, but it should preserve and display scenario values when a project uses them.

For QA, scenario should be a sample-level attribute, not a separate project and not a separate page.

## Judge protocol direction

Generic judge output should remain unified but support multidimensional scoring:

```json
{
  "score": 0.0,
  "confidence": 0.0,
  "verdict": "correct|incorrect|uncertain|...",
  "score_details": [
    {"name": "dimension_name", "score": 0.0, "weight": 0.0, "reason": "..."}
  ]
}
```

Rules:

- `score` is the normalized overall score used for sorting and aggregate views.
- `score_details` is optional and project/scenario-specific.
- Scores should be normalized to 0-1.
- Multidimensional score definitions belong in project standards or project frontend extensions.

## Attribution and cluster protocol direction

Generic attribution should support structured error classification without hardcoding one project's taxonomy:

- `primary_error_type`
- `error_types`
- `severity`
- `needs_human_review`

Project standards define allowed error types and severity meanings. Cluster/report should be able to group by scenario, primary error type, severity, and review flag when available.

## Check requirements

Generic check should validate protocol invariants:

- project-specific fields do not pollute generic core unless promoted as generic protocol fields;
- score and score detail values are within 0-1;
- structured error classification is internally consistent when present;
- aggregate metrics do not mix incompatible scenarios or metric meanings.

Project-specific check may add taxonomy and scenario checks.
