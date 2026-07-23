# Project Implementation Standard Template

Each `impl/projects/<project>` must expose a minimal, auditable implementation standard through typed fields owned by the runtime or verifier object they describe. `documents.implementation_standard` may explain the contract, but it is not a runtime source.

## Required project.yaml fields

```yaml
runtime:
  mode: <existing_service_required | existing_service_optional | uploaded_output_evaluation>
  application:
    interface:
      shape: <request/response or uploaded-output interface shape>
      source: <adapter or approved application source>
    start_run: <how to start, reuse, or bypass the business application>
    boundary: <which application responsibilities are evaluated>
  adapter:
    request_construction:
      builder: <adapter function, service contract, or uploaded output rule>
      required_inputs: []
    output_extraction:
      extractor: <adapter function or source field rule>
      normalized_output: <RunTrace.extracted_output shape>
    reference_handling:
      source_priority: []
      alignment: <how reference is aligned to output shape>
  batch_persistence:
    case_shape: <compact durable case shape>
    transient_results: <what must not be persisted as durable case data>
verifier:
  judge:
    boundary:
      document: <documents.judge_boundary key or path>
      gate: <how boundary is applied before verdict reconciliation>
  attribution:
    trace:
      document: <documents.attribution key or path>
      trace_nodes: []
  presentation:
    frontend_view:
      live: <live page display rule>
      summary: <summary page display rule>
  check_rules:
    evidence:
      documents: []
      tests: []
```

## Required semantics

- `runtime.application.interface` declares the evaluated interface, including uploaded-output projects that do not call a service.
- `runtime.application.start_run/boundary` declares how the business application is started or bypassed and which responsibilities are evaluated.
- `request_construction` identifies where project input becomes an executable request or evaluation object.
- `output_extraction` identifies where raw service/uploaded output becomes `RunTrace.extracted_output`.
- `reference_handling` defines priority and shape alignment for input references, judge-generated references, or missing references.
- `judge_boundary` points to the project responsibility boundary and states how it gates final verdict reconciliation.
- `attribution_trace` defines major trace nodes and evidence sources for root-cause analysis.
- `frontend_view` states how live and summary pages consume protocol fields without project-private rendering branches.
- `batch_persistence` states the compact durable case shape and excludes large transient trace/judge/attribute payloads from case-pool persistence.
- `check_evidence` lists documents and focused tests that prove the project standard remains current.
