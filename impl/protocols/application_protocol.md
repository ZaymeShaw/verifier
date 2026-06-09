# Application Protocol

`ApplicationSpec` describes how the evaluated business application is started or connected.

Fields:

- `mode`: `existing_service`, `generated_service`, `script`, or `manual`.
- `startup_steps`: ordered human-readable steps.
- `health_checks`: URLs, commands, or manual checks.
- `api_base`: default API base URL.
- `dependencies`: local or external dependencies.
- `known_external_services`: databases, search services, queues, model services, or other dependencies.

Rules:

- Startup details are project implementation, not generic core logic.
- A manual startup spec is valid for v1 if the service cannot be safely started automatically.
- Health passing only means the service is reachable; judge still determines output correctness.
