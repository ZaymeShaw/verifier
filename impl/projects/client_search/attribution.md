# Attribution

Attribute client_search failures by connecting user intent, expected output, actual output, and available code/config/runtime evidence.

Current project-owned sources:

- `projects/client_search/readme.md` defines the evaluation goal: use config field definitions and prompt rules to decide whether returned conditions can search the correct customers.
- `projects/client_search/config.md` points to authoritative field definition, enum, rule, label, and value-mapping config files in the business project.
- `projects/client_search/prompt.md` defines current parsing rules for valid fields, operators, age handling, unit conversion, AND/OR, and JSON output.
- `projects/client_search/start.md` defines service startup, ES reindex, live request, judge, and attribute verification flow.

Required reasoning chain:

1. Reconstruct the current query intent.
2. Build expected conditions from current prompt/config/business rules.
3. Compare actual response with expected output and separate missing, wrong, and extra conditions.
4. Walk the available `RunTrace.execution_trace` stages and mark each stage as normal, suspicious, failed, or not yet verified.
5. Identify the earliest likely divergence stage: request normalization, client_search API, routing, prompt/rule construction, model parsing, field/config mapping, post-processing, adapter extraction, service/tooling, or evaluation standard.
6. Use current response, logs, project docs, prompt/config snippets, and executable trace nodes when available.
7. If code evidence is available, name the concrete module/function/config and explain expected vs. actual behavior there; if not, explicitly say code-path evidence was not collected.
8. Produce a minimal root-cause hypothesis.
9. Give executable verification steps and a minimal patch direction developers can act on.

Attribution quality bar:

- The conclusion must help a developer know what to verify or change next.
- Do not stop at “a module failed”; connect the gap to the prompt/config/runtime chain when evidence exists.
- Do not bring fields or fixes from unrelated historical cases into the current query.
- Do not propose editing frontend display or one run result as the fix when the source generator is wrong.
- If code evidence was not read, mark suspected locations as hypotheses or leave them empty.
- If the current output is correct, return a no-failure attribution with evidence from judge rather than inventing a failure.
