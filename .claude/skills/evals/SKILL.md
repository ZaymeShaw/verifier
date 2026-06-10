# Evals Skill

Use this skill to build and audit project evaluation pipelines under `impl/`.

## Agent chain

- analysis: read user-owned `projects/<project>` docs and extract project API, business context, mock, judge, and attribution requirements.
- application: start or simulate the project service and document a repeatable run method.
- mock: generate representative inputs and expected intent data from project docs.
- judge: evaluate current `RunTrace` output against the project final-verdict standard.
- attribute: for incorrect or uncertain outputs, locate the likely source through executable trace/code/config evidence.
- check: audit mechanism quality, code quality, protocol consistency, frontend/API/data alignment, standardization risks, and stale or redundant surface area.

## Operating rules

1. User-owned project docs live in `projects/<project>`; AI-generated implementation lives in `impl/projects/<project>`.
2. Generic protocols and core code live under `impl/protocols` and `impl/core` and must not hardcode project-specific fields, cases, ports, prompts, or business rules.
3. Project-specific behavior belongs in project docs, project adapters, project standards, or project frontend extensions.
4. When protocol changes are needed, update the protocol, every affected project implementation, frontend output, batch/CLI/API usage, and check gates together.
5. Avoid parallel orchestration paths: live, mock, batch, frontend, and CLI should reuse the same judge, attribute, cluster, and check mechanisms.
6. After code changes, run compile/API/mock-chain/frontend smoke tests and report the check result.
7. Treat batch, browser persistence, and frontend display as part of the evaluated mechanism: failures there must be isolated and must not hide source pipeline defects.
8. When check finds non-trivial standardization issues, track actionable findings under `search-test-case/issue` if issue tracking is requested.

## Specialized agents

- `agents/specialized/attribute-analyzer.md`: how to produce useful attribution from traceable evidence and avoid overfit attribution.
- `agents/specialized/check.md`: how to audit mechanism quality, standardization, stale code/data/frontend, and generalized fixes.
