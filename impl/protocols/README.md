# Protocols

This directory defines the generic evaluation chain used by `impl`.

Agent responsibility boundaries are defined in `agent_role_protocol.md`: ownership follows capabilities, not whether an agent writes code. Capability agents may implement project-specific code inside their own boundary, while shared cross-capability glue must follow project implementation standards.

```text
ProjectSpec -> ProjectAnalysis -> ApplicationSpec -> MockSpec/LiveInput -> RunTrace -> JudgeResult -> AttributeResult -> ClusterSummary -> FrontendViewModel -> CheckReport
```

The core system only depends on these protocols. Project-specific API formats, business fields, ports, prompts, and code paths belong in `impl/projects/<project>` and are exposed through adapters as `raw_response`, `project_fields`, or frontend extensions.

Some project standards use copyable templates outside this directory, such as `impl/judge_boundary-template.md`. These templates are user-facing standards, not generic execution protocols; the generic protocol only defines how filled standards are consumed and how outputs such as `JudgeResult` are structured.

Simple projects may implement only ProjectSpec, ProjectAnalysis, RunTrace, and JudgeResult. Complex projects can add application startup, mock generation, attribution, clustering, batch runs, code evidence, and project-specific frontend extensions.
