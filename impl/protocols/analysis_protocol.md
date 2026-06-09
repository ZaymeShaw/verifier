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

- Analysis reads project-owned documents and config; it must not infer project-specific fields into generic core.
- Missing application, mock, evaluation, or attribution guidance is reported through `quality_flags` instead of hidden defaults.
- Frontend and CLI should consume the same `ProjectAnalysis` output instead of inventing separate project metadata structures.
