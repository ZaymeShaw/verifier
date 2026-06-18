# Project Implementation Standard Template

Each `impl/projects/<project>` must expose a minimal, auditable implementation standard. The standard can live in `project.yaml` under `frontend_extensions.implementation_standard` and may link to detailed project documents through `documents.implementation_standard`.

## Required project.yaml fields

```yaml
api:
  base_url: <service base URL or evaluation-only marker>
  endpoint: <main endpoint or evaluation-only marker>
  method: <HTTP method or evaluation-only marker>
  timeout: <seconds>
application:
  mode: <existing_service | existing_service_optional | uploaded_output_evaluation | generated_service | manual>
frontend_extensions:
  implementation_standard:
    api:
      shape: <request/response API shape or evaluation-only shape>
      source: <document or adapter source>
    application:
      start_run: <how to start, verify, or bypass runtime application>
      boundary: <what runtime evidence is available>
    request_construction:
      builder: <adapter function, service contract, or uploaded output rule>
      required_inputs: []
    output_extraction:
      extractor: <adapter function or source field rule>
      normalized_output: <RunTrace.extracted_output shape>
    reference_handling:
      source_priority: []
      alignment: <how reference is aligned to output shape>
    judge_boundary:
      document: <documents.judge_boundary key or path>
      gate: <how boundary is applied before verdict reconciliation>
    attribution_trace:
      document: <documents.attribution key or path>
      trace_nodes: []
    frontend_view:
      live: <live page display rule>
      summary: <summary page display rule>
    batch_persistence:
      case_shape: <compact durable case shape>
      transient_results: <what must not be persisted as durable case data>
    check_evidence:
      documents: []
      tests: []
```

## Required semantics

- `api` declares the evaluated interface. Projects that evaluate uploaded outputs instead of calling a service must explicitly say so instead of omitting API shape.
- `application` declares how the business service is started, verified, simulated, or intentionally bypassed.
- `request_construction` identifies where project input becomes an executable request or evaluation object.
- `output_extraction` identifies where raw service/uploaded output becomes `RunTrace.extracted_output`.
- `reference_handling` defines priority and shape alignment for input references, judge-generated references, or missing references.
- `judge_boundary` points to the project responsibility boundary and states how it gates final verdict reconciliation.
- `attribution_trace` defines major trace nodes and evidence sources for root-cause analysis.
- `frontend_view` states how live and summary pages consume protocol fields without project-private rendering branches.
- `batch_persistence` states the compact durable case shape and excludes large transient trace/judge/attribute payloads from case-pool persistence.
- `check_evidence` lists documents and focused tests that prove the project standard remains current.
