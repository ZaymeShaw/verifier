# QA Project Frontend Notes

## Goal

QA should use the shared live and summary pages, with project/scenario-aware rendering. Do not create separate frontend flows for each QA scenario.

## Project selection

- Replace free-text project inputs with an enumerable project dropdown loaded from the unified projects API.
- The dropdown should include `client_search` and `QA` when both projects exist.
- Session state such as case pools, last chain, selected filters, and uploaded dataset text should be scoped by project id to avoid cross-project contamination.

## Scenario handling

Scenario is a sample-level QA extension.

Frontend behavior:

- Show a `Scenario` column when cases include scenario values.
- Add a scenario filter when the selected project exposes scenarios.
- Show scenario distribution in summary cards.
- Keep batch evaluation as a single button.
- Do not create separate buttons like `Gold QA batch`, `RAG batch`, or `Weak QA batch`.

## Case table columns

Prefer generic columns:

- Select
- ID
- Source
- Scenario
- Input
- Output
- Reference
- Status
- Score / Verdict
- Attribution summary

Project-specific details can appear in collapsible raw/details sections.

## Upload/import

The QA first version expects JSON. Supported shapes:

```json
[
  {
    "question": "...",
    "actual_answer": "...",
    "actual_answer": "...",
    "reference_answer": "..."
  }
]
```

or protocol-shaped samples:

```json
[
  {
    "input": {"question": "...", "contexts": []},
    "output": {"actual_answer": "..."},
    "reference": {"actual_answer": "..."},
    "metadata": {"category": "..."}
  }
]
```

Frontend may parse JSON locally for preview/import, but final normalization and scenario inference should be project adapter logic so QA-specific rules do not spread across generic page JavaScript.

## Wording

Use generic wording:

- `Input` / `输入`
- `Output` / `被评估输出`
- `Reference` / `参考答案`
- `Scenario` / `评估场景`
- `Score details` / `多维评分`

Avoid using `API 输出` as a universal label.
