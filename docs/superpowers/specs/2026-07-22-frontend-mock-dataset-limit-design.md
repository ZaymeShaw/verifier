# Frontend Mock Dataset Default Limit

## Objective

Make the summary frontend's `加载 Mock 数据集` action load only the first three
persisted Mock cases by default.

## Design

Change only the frontend request from:

```javascript
post('/api/mock_datasets', {project: project(), count: 500})
```

to `count: 3`.

The backend API, persisted fixture file and explicit callers remain unchanged.
For DeerFlow, current file order means the frontend loads:

1. `single_turn_planning`
2. `multi_turn_dimension_accumulation`
3. `clarification`

It does not load `authorization_boundary`, `non_agent_intent` or
`service_unavailable` through this default button action.

## Verification

- Assert the frontend posts `count: 3`.
- Assert it no longer posts `count: 500`.
- Call the persisted dataset path with `count=3` and verify exactly the first
  three scenarios are returned.

## Non-goals

- No backend default change.
- No fixture deletion or reordering.
- No LLM call or dynamic generation.
- No new scenario filtering rule.
