# Mock Protocol

`MockSpec` describes how test inputs, user intents, or session data are built.

Fields:

- `input_modes`: supported modes such as `single_turn`, `multi_turn`, `batch`.
- `case_sources`: user-written cases, generated cases, uploaded files, or historical regressions.
- `intent_generation_guidance`: how to create realistic intents for this project.
- `expected_intent_format`: how expected output should be described for judge.

Rules:

- Mock data should exercise business semantics, not only API schemas.
- Mock outputs must satisfy the same normalized `RunTrace` judge-input contract as live outputs for that project, including equivalent routing, field-match, or source evidence when live traces provide it.
- Generated cases must remain traceable to their generation guidance.
- Mock agents may return a dataset proposal as generic case objects: `id`, `input`, optional `expected_intent`, `source`, and `status`.
- Mock case construction should be exposed through a project adapter or generic mock endpoint so live pages, summary pages, CLI, and batch flows reuse one source of generated cases.
- Project docs may provide seed cases, but generic UI should treat them as editable case-pool entries before batch execution.
- Project-specific intent fields stay in project specs or case data.
