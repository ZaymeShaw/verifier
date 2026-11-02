# Meta-verifier Protocol

Meta-verifier is a verifier-of-verifier capability. It does not expose standalone UAT modes as the product surface. Browser operation is an evidence collection technique inside a broader process that understands the project, infers the user goal, generates source-backed checks, audits coverage, and reports actionable findings.

## Skill entrypoint

```text
/meta-verifier [natural language goal]
```

Users do not choose modes such as `explore`, `test`, `reproduce`, or `critique`. The meta-verifier routes internally from the natural-language request.

## Internal route decision

```text
raw_user_request -> MetaVerifierIntentRouter -> MetaVerifierRouteDecision
```

Internal routes:

- `project_exploration`: discover project docs, skills, protocols, frontend pages, API routes, project config, and implementation entrypoints.
- `targeted_verification`: verify a named page, button, chain, API, function, or capability.
- `issue_reproduction`: reproduce a described failure and record shortest reproduction steps plus suspected areas.
- `persona_critique`: act as the inferred demand-side user and judge whether the system satisfies the user goal.
- `browser_evidence`: collect browser action trace, screenshots, HTML snapshots, console logs, page state, and user-visible output for other routes.
- `code_localization`: connect reproduced behavior to visible code/API/protocol mechanisms.
- `output_quality_review`: judge whether generated outputs are grounded, actionable, and sufficient for the business goal.

## Core object graph

```text
MetaVerifierRun
  -> MetaVerifierRouteDecision
  -> MetaVerifierGoalRequirement[]
  -> MetaVerifierLayerCoverage
  -> MetaVerifierChecklistItem[]
  -> MetaVerifierEvidence[]
  -> MetaVerifierFinding[]
  -> MetaVerifierAuditResult[]
  -> MetaVerifierReport
```

- `MetaVerifierGoalRequirement`: decomposed requirement with user outcome, acceptance question, required layers, browser-evidence obligation, and higher-level-probe obligation.
- `MetaVerifierLayerCoverage`: visible layers, invisible layers, visibility scope, and confidence impact for unavailable layers.
- `MetaVerifierChecklistItem`: target, target type, source artifact, source kind, requirement link, visible layers, evidence rule, expected evidence, user path, browser hints, acceptance question, and project metadata.
- `MetaVerifierEvidence`: browser/code/artifact/run/reviewer evidence with covered layers, action trace, page state, snapshots, console logs, artifact references, timing, and error message.
- `MetaVerifierFinding`: category, severity, user impact, source checklist item, evidence references, reproduction steps, suspected areas, recommendation, evidence status, and project metadata.
- `MetaVerifierAuditResult`: planned/completed-run gate result with status, category, severity, message, and related requirement/checklist/evidence id.
- `MetaVerifierExtension`: project-specific discovery hints, selector aliases, persona prompts, business goals, algorithm acceptance criteria, custom finding classifiers, and project metadata.
- `MetaVerifierReport`: requirements, layer coverage, checklist, evidence, confirmed findings, separate persona critiques, audit summary, confidence impact, unverified areas, higher-level probes, biggest risks, and next investigations.

## Enforced planning mechanism

Before execution, the run must be made auditable:

1. `MetaVerifierVisibilityScopeDetector.detect(...)` maps visible/invisible layers: `frontend`, `browser`, `api`, `code`, `skill`, `protocol`, `demand_doc`, `data`, and `generated_output`.
2. `MetaVerifierGoalDecomposer.decompose(...)` turns the natural-language goal into concrete requirements with user outcomes and acceptance questions.
3. `MetaVerifierProjectDiscovery.generate_checklist(...)` creates source-backed checklist items. When requirements are provided, checklist items carry `requirement_id`, `layers`, `source_kind`, and evidence rules such as `browser_required`.
4. Broad/business/persona routes must include at least one `higher_level_probe` checklist item so the run cannot stop at page-load reassurance.
5. `MetaVerifierDemandCoverageAuditor.audit_planned_run(...)` flags missing goal decomposition, missing layer mapping, missing checklist sources, missing requirement links, missing browser evidence plans, and missing higher-level probes.

## Completed-run evidence gates

`MetaVerifierDemandCoverageAuditor.audit_completed_run(...)` and `MetaVerifierFindingValidator` enforce:

- Confirmed findings must resolve every `evidence_ref` to actual evidence in the run.
- Browser-required checklist items and findings must have browser evidence or evidence whose `covered_layers` includes `browser`.
- Reviewer-only critique cannot satisfy confirmed-finding evidence; it stays separate as `unverified_reviewer_critique` unless independently supported.
- No-finding reports for broad/business routes are flagged as `pass_theater_risk` unless higher-level demand-side probe evidence was executed.
- Invisible layers must appear in confidence impact rather than being silently skipped.

## Finding categories

- `functional_defect`: page, button, API, state, navigation, or result panel failure.
- `reproduction_record`: a user-reported problem has been reproduced or could not be reproduced, with steps and evidence.
- `algorithm_capability_problem`: output is weak, wrong, incomplete, non-actionable, or fails the business goal despite successful execution.
- `design_architecture_defect`: unclear boundaries, missing protocol responsibilities, brittle workflow design, insufficient observability, or hard-to-extend structure.
- `unmet_user_need`: the user goal cannot be achieved with the current system.

## Browser execution boundary

When a browser-reachable frontend exists, browser execution must start at the discovered entrypoint, navigate linked pages, operate core controls and primary chains, and convert browser startup/navigation/selector/timeouts into structured meta-verifier evidence and findings. Entrypoints are discovered dynamically from project artifacts — no URL or port is hardcoded.

On first browser-evidence use in an environment, inspect available Chrome/Chromium and ChromeDriver. Prefer a compatible local driver. If none matches and network/download is allowed, let Selenium Manager or an explicit download resolve the matching driver. If download is unavailable or blocked, ask the user to specify a driver path.
