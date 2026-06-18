# Demand Compliance Harness Design

This document defines how `openspec/changes/multi-agent-trace-state-machine` prevents total demand, project demand, project implementation standards, and check-agent requirements from being forgotten during implementation.

## Purpose

The state-machine change must not rely on informal reminders such as “remember to satisfy demand.md”. The harness makes those requirements explicit, traceable, and blocking.

Implementation is not complete unless every relevant requirement from the harness has either:

- an implementation artifact,
- verification evidence, and
- status `satisfied`,

or a clearly justified `deferred` / `non-goal` decision.

## Source set

The harness source set is defined in `constraints.md` and includes:

- total demand: `demand/demand.md`
- check-agent standard: `.claude/skills/evals/agents/specialized/check.md`
- project standards: `impl/project_implementation_standard-template.md`, `impl/projects/*/implementation_standard.md`, `impl/projects/*/project.yaml`
- project demands: `projects/QA/QA-demand.md`, `projects/marketting-planning/marketplan-demand.md`, `projects/marketting-planning-intent/marketplan-demand.md`
- future discovered project demand files matching `projects/*/demand.md`, `projects/*/*demand*.md`, or `impl/projects/*/demand.md`

If a source is missing or moved, implementation must record the discovery command and fallback source in `compliance-matrix.md` before coding continues.

## Artifacts

### `constraints.md`

`constraints.md` is the human-readable guardrail. It records:

1. the required source documents,
2. explicit source-derived requirements,
3. non-negotiable architectural constraints,
4. completion evidence requirements, and
5. the required workflow for future implementation agents.

It is the first file future agents must read before applying this change.

### `compliance-matrix.md`

`compliance-matrix.md` is the acceptance ledger. Every relevant requirement must have a row with:

- source document and line or section,
- requirement summary,
- scope,
- implementation artifact,
- verification evidence,
- status.

A row cannot be marked `satisfied` until the implementation artifact exists and verification evidence is recorded.

## Enforcement model

The harness uses three layers of enforcement.

### 1. Pre-coding gate

Before implementation starts, the agent must:

1. read `constraints.md`,
2. refresh source discovery for project demand and implementation-standard files,
3. update `compliance-matrix.md` for any newly discovered source, and
4. keep unresolved rows as `pending`.

### 2. Implementation alignment gate

During implementation, each change must be mapped to the matrix by source of truth:

- generic protocol,
- core runner,
- project adapter,
- project configuration,
- pipeline,
- backend endpoint,
- frontend component,
- persisted case pool,
- test or check report.

Generic requirements must stay in protocols/core. Project-specific endpoints, fields, prompts, semantic rules, service boundaries, and probes must stay in project specs, project configs, adapters, or hooks.

### 3. Completion gate

The change cannot be called complete unless the matrix records evidence for:

- graph loading, transition selection, fulfillment gate evaluation, attribution gate evaluation, merge policy, and stop-condition tests,
- at least one simple default-graph end-to-end trace that produces business expectations and fulfillment assessments,
- at least one complex project deep-graph trace using project hooks/probes for expectation-level attribution,
- mock-generated cases entering the same full pipeline,
- batch isolation across cases,
- frontend/API smoke coverage for state history, gate display, fulfillment matrix, and expectation attribution display,
- check-style review covering protocol alignment, anti-overfit behavior, source-mechanism correctness, batch resilience, fulfillment grounding, and attribution grounding.

## Project-demand coverage

Project demand must be first-class, not folded into generic demand.

### QA

QA requirements are represented by `QA-*` rows in `compliance-matrix.md`. They cover provided input/output/reference datasets, no required tested-service call, reference/golden-answer scoring, multidimensional scoring/taxonomy extension, JSON-compatible upload conversion, project selector behavior, RunTrace flexibility, per-row isolation, contexts/scenario input, and QA-specific check coverage.

### marketing-planning

Marketing-planning requirements are represented by `MP-*` rows. They cover the external business repository boundary, no unauthorized remote mutation, standardized service startup/application usage, and integration-risk documents as source constraints for states/hooks/probes.

### marketing-planning-intent

Intent requirements are represented by `MPI-*` rows. They cover the shared marketing-planning service boundary, separate evaluation boundary, `/api/v1/marketing-planning/intent-recognition`, single-turn scope, and integration-risk coverage.

## Design decision

The selected approach is **constraints file + compliance matrix + completion gate**.

This is stronger than only writing reminders in `design.md` or `tasks.md`, because future implementation agents must update requirement rows with artifacts and evidence. It is lighter than building an automatic checker now, because this change is still at the OpenSpec/design stage; an automatic checker can be added later if implementation shows the manual matrix is not strict enough.

## Self-review

- No placeholders remain.
- The design is scoped only to the harness mechanism, not the full state-machine implementation.
- The project-demand omission is addressed through explicit `QA-*`, `MP-*`, and `MPI-*` matrix rows.
- The harness now treats business expectation fulfillment and expectation-level attribution as blocking evidence surfaces, not optional wording in design docs.
- The design does not move project-specific business rules into generic core.
- Completion depends on evidence, not claims.
