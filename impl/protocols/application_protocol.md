# Application Protocol

`ApplicationSpec` describes how the evaluated business application is started or connected.

Fields:

- `mode`: `existing_service`, `generated_service`, `script`, or `manual`.
- `startup_steps`: ordered human-readable steps.
- `health_checks`: URLs, commands, or manual checks.
- `api_base`: default API base URL.
- `dependencies`: local or external dependencies.
- `known_external_services`: databases, search services, queues, model services, or other dependencies.
- `application_boundary`: current runtime capability boundary discovered before judge/attribute, such as whether downstream result-set verification is available and which judge scope should be used.

Rules:

- Application is a Claude subagent-backed project-update workflow when service startup, API shape, or adapter execution standards need to be built or revised; the runtime pipeline later calls the produced adapter/request/output code directly.
- Startup details are project implementation, not generic core logic.
- Application owns service access, request construction, output extraction, and runtime boundary evidence; it does not own judge verdict semantics or attribution conclusions.
- A manual startup spec is valid for v1 if the service cannot be safely started automatically.
- Health passing only means the service is reachable; judge still determines output correctness.


## Demand responsibilities

Application is responsible for making the evaluated business service executable through a standardized access layer:

- Define a context-independent environment for running or connecting to the business capability under evaluation.
- Support existing service startup when a real project/API is available.
- Support generated service, simulated service, script, or pipeline execution when no complete service exists.
- Land startup/run usage as an application folder standard or equivalent project application document.
- Record self verification through health checks, smoke calls, or other evidence that the standardized usage works.
