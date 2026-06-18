# Agent Role Protocol

Agent ownership is capability-owned, not code-writing-owned. Analysis, application, build, mock, judge, attribute, and check agents may write or update project-specific code only inside their owned capability boundary. Shared registration, protocol field alignment, batch orchestration, frontend/backend integration, and cross-capability glue must follow project implementation standards instead of being owned ad hoc by one runtime agent.

## Required trigger phases

- project initialization
- project information update
- business project update
- prebuilt batch mock generation
- trace runtime
- post-trace analysis

`trace runtime` means the business system is executing a complete chain and may call mock to simulate user behavior. `post-trace analysis` means a completed trace is inspected by judge or attribute.

## analysis agent

- execution backend: Claude subagent for project initialization and information-update workflows; it is not invoked inside a per-case trace runtime.
- owned capability: project understanding and project standard production.
- trigger: project initialization, project information update, or new project requirement material.
- inputs: `demand.md`, project docs under `projects/<project>`, filled boundary templates, existing project config, and available business code or API docs.
- outputs: project API understanding, API document shape, API call chain, business background, responsibility boundary, mock strategy, frontend architecture, judge standard, attribution trace plan, frontend adaptation needs, and key pipeline/key code links for `impl/projects/<project>`.
- allowed implementation scope: project standards, project docs, protocol-aligned config, and analysis artifacts. It does not own runtime judge verdict logic, attribution conclusions, or frontend rendering implementation beyond the standards that drive them.
- handoff: supplies standard fields consumed by application, build, mock, judge, attribute, and check.

## application agent

- execution backend: Claude subagent when business service startup/API shape changes require project update work; the resulting adapter/runtime code is later called by the normal pipeline.
- owned capability: executable application access and output acquisition.
- trigger: business project update, service startup/change, API shape change, or runtime execution need during trace runtime.
- inputs: analysis output, project API standard, context-independent environment requirements, service startup instructions, request construction rules, and current case input.
- outputs: application folder startup/run standard, application start/run guidance, health checks, self verification evidence, normalized request construction, API call execution, raw response capture, extracted output, execution trace, and application boundary evidence.
- allowed implementation scope: project adapter execution, existing service startup scripts, generated service/simulated service or pipeline when no complete service exists, request builders, output extractors, and application boundary probes.
- handoff: emits `RunTrace` and boundary/runtime evidence for judge, attribute, frontend, batch, and check.

## build agent

- execution backend: Claude subagent for frontend construction or project frontend-standard updates; browser/API verification remains required before reporting user-visible completion.
- owned capability: project frontend construction from project standards and frontend protocol.
- trigger: project initialization, project information update, frontend standard update, or user-visible live/summary behavior change.
- inputs: analysis output, frontend protocol, project frontend view settings, output/reference handling rules, judge/attribute/cluster/check protocol shapes, and case-pool persistence standards.
- outputs: frontend construction, project frontend standards, live request page behavior, summary/attribution page behavior, upload/case-pool views, protocol-shaped rendering, frontend view normalization, and persistence display rules.
- allowed implementation scope: shared frontend components and project frontend configuration needed to render protocol objects. It may not hardcode project-private main-flow endpoints or bypass project standards.
- handoff: consumes application, judge, attribute, cluster, and check outputs through `FrontendViewModel` and reports display/persistence gaps back to analysis or check.

## mock agent

- execution backend: runtime script agent, invoked by dataset-generation or trace-runtime code rather than by Claude subagent for every case.
- owned capability: simulated evaluation inputs, user intents, and optional user behavior during trace runtime.
- trigger: prebuilt batch mock generation or trace runtime user simulation.
- inputs: analysis mock strategy, project mock docs, case-pool schema, current scenario constraints, and optional interaction context.
- outputs: generic case objects, simulated intents, optional references or expected intents, scenario metadata, and traceable generation basis.
- allowed implementation scope: project mock generators, mock endpoints, case normalization, seed datasets, and runtime user-simulation logic inside the mock capability.
- handoff: generated cases enter the same application -> judge -> attribute -> cluster -> check pipeline as uploaded or live cases.

## judge agent

- execution backend: runtime script agent, invoked after a `RunTrace` exists by the evaluation pipeline rather than by Claude subagent during project setup.
- owned capability: verdict, score, expected-vs-actual comparison, and responsibility-boundary reconciliation.
- trigger: post-trace analysis after a current `RunTrace` exists and evaluation is requested.
- inputs: current `RunTrace`, analysis evaluation standard, project judge boundary, optional reference or expected intent, application boundary evidence, and project judge docs.
- outputs: `JudgeResult` with verdict, score, confidence, reconstructed intent, expected, actual, condition assessments, boundary decision, verdict derivation, evidence, and quality flags.
- allowed implementation scope: project judge code, boundary gate/reconciliation logic, semantic equivalence rules, reference generation/alignment, and judge result normalization.
- handoff: provides evidence-backed expected-vs-actual gaps and boundary decisions to attribute, cluster, frontend, and check.

## attribute agent

- execution backend: runtime script agent, invoked after judge produces an attribution-worthy result by the evaluation pipeline rather than by Claude subagent during project setup.
- owned capability: current-case root-cause attribution and next verification guidance.
- trigger: post-trace analysis after judge finds an incorrect, uncertain, suspicious, or otherwise attribution-worthy trace.
- inputs: current `RunTrace`, `JudgeResult`, analysis attribution trace plan, project docs, code/config/prompt/log evidence, and local verification results.
- outputs: `AttributeResult` with evidence chain, trace analysis, chain nodes, local verifications, earliest divergence, evidence coverage, suspected locations, root-cause hypothesis, verification steps, patch direction, incomplete reason, and quality flags.
- allowed implementation scope: project attribution analyzers, evidence collectors, trace-node mappers, local verification probes, and attribution result normalization.
- handoff: sends supported root causes, insufficient evidence, or next verification steps to cluster, frontend, check, and developers.

## check agent

- execution backend: Claude subagent for independent mechanism audit and review-driven implementation checks; it may write audit helpers/reports but does not replace runtime mock/judge/attribute scripts.
- owned capability: mechanism audit, protocol consistency review, and evidence-backed correction recommendations.
- trigger: after demand, project docs, code, data, prompt, protocol, frontend, judge, attribution, batch, or persistence changes; also when the user requests current-state review.
- inputs: current `demand.md`, check rules, OpenSpec artifacts, protocols, project standards, implementation code, generated outputs, frontend/API behavior, persisted data, and verification results.
- outputs: check report with passed items, failed items, evidence locations, root causes, blast radius, protocol gaps, overfit risks, stale artifacts, proposed fixes, and verification status.
- allowed implementation scope: check helpers, audit tests, reports, and narrowly scoped corrective changes after evidence. Non-trivial shared behavior changes, deletions, or user-visible protocol changes require user confirmation unless already authorized.
- handoff: reports gaps to the owning capability agent or shared project implementation standard instead of silently absorbing all implementation ownership.

## Cross-capability handoff rules

- Analysis, application, build, and check are Claude subagent-backed project-update workflows: they inspect or change standards, service access, frontend construction, and audit evidence outside an individual case trace.
- Mock, judge, and attribute are runtime script agents: they are called by verifier code during prebuilt dataset generation, trace runtime, or post-trace analysis and must not require a Claude Code subagent per case.
- Analysis produces standards; runtime agents implement only their capability-specific code from those standards.
- Application owns trace runtime service access and output extraction, not judge semantics or attribution conclusions.
- Build owns frontend behavior, but rendering choices must come from project frontend standards and protocol objects.
- Mock may operate before runtime for datasets or during trace runtime for user simulation; both outputs must remain valid for the unified pipeline.
- Judge and attribute both may write project-specific code, but judge owns verdict/boundary comparison while attribute owns evidence-backed root-cause localization.
- Check audits the mechanism and may propose corrections, but it is not the default owner for every implementation gap.
- When a change spans multiple capabilities, the shared project implementation standard is the contract and check verifies alignment against it.
