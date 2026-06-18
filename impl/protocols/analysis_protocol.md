# Analysis Protocol

`ProjectAnalysis` summarizes project information loaded from `impl/projects/<project>` before runtime execution.

Fields:

- `project_id`
- `api`
- `application`
- `capabilities`
- `documents`
- `mock_guidance`
- `evaluation_guidance`
- `attribution_guidance`
- `quality_flags`

Rules:

- Analysis is a Claude subagent-backed project-update workflow: it runs when a project is initialized or its information changes, and it produces standards for later runtime agents instead of running inside every case trace.
- Analysis reads project-owned documents and config; it must not infer project-specific fields into generic core.
- Analysis produces the project standards consumed by application, build, mock, judge, attribute, and check, but it does not become the default owner of all runtime implementation code.
- Missing application, mock, evaluation, or attribution guidance is reported through `quality_flags` instead of hidden defaults.
- Frontend and CLI should consume the same `ProjectAnalysis` output instead of inventing separate project metadata structures.


## Demand responsibilities

Analysis is responsible for extracting and standardizing these project facts before runtime agents execute:

- API document shape and API call chain, including request/response format and important service boundaries.
- Mock strategy, including how user intent and next-turn user input should be generated for the project.
- Frontend architecture and frontend adaptation needs consumed later by build.
- Judge standard and evaluation guidance used to create project-specific judge behavior.
- Attribution trace plan, including key pipeline links and key code paths needed for useful root-cause analysis.
