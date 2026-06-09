# Project Protocol

`ProjectSpec` is the entry point for a project under evaluation.

Required fields:

- `project_id`: stable identifier.
- `name`: display name.
- `description`: what this project evaluates.
- `adapter`: Python adapter path relative to the project directory.
- `capabilities`: supported steps such as `live_run`, `judge`, `attribute`, `cluster`, `check`.
- `documents`: project-specific specs used by agents.

Optional fields:

- `application`: startup and health-check information.
- `api`: default API base, endpoint, method, headers, and request template.
- `frontend_extensions`: project-specific display metadata.

Rules:

- Project-specific business fields must not become required core fields.
- If the core cannot classify an item as generic or project-specific, keep it in the project spec and surface it for user review.
