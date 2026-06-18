# Frontend Build Standard

The build agent owns shared frontend behavior for verifier live pages and summary pages. It is a Claude subagent-backed project-update workflow for frontend construction and project frontend-standard changes. It must implement project-visible display through protocol objects and project frontend standards, not by adding project-private branches to the main flow.

## Inputs

Frontend rendering consumes these shared inputs:

- `project.yaml.frontend_extensions.implementation_standard.frontend_view`
- `project.yaml.frontend_extensions.implementation_standard.batch_persistence`
- `RunTrace.extracted_output`
- `JudgeResult.expected` and `JudgeResult.actual`
- `frontend_view.reference_panel`
- compact batch run objects returned by the server

Project-specific choices must be declared as project frontend standards in `project.yaml` or project documents. The frontend may read those settings through normalized protocol data, but it must not hard-code a project-private main-flow endpoint, project-private result path, or project-only rendering branch.

## Live page contract

Live pages render the current project through the shared protocol shape:

- request and input fields come from the project adapter request object;
- output comes from `RunTrace.extracted_output` or the normalized output field declared by the project standard;
- reference comes from provided input reference first, then judge-generated reference only when no input reference exists;
- judge and attribute panels render structured protocol results, with raw evidence available only as drill-down content.

## Summary page contract

Summary pages must keep Output/Reference rendering aligned:

- output/reference columns use the same visual weight and comparable cell size;
- JSON formatting uses stable indentation for objects and arrays;
- truncation is explicit, project-declared where needed, and must preserve access to full details in drill-down or current in-memory results;
- generated references are shown as references but must retain their source so users can tell input references from judge-generated ones.

## Batch persistence contract

The durable case pool uses compact case-pool rows only. Uploaded, generated, saved, and displayed cases share this compact shape:

- `id`
- `selected`
- `input`
- `output`
- `reference`
- `metadata`
- `scenario`
- `source`
- `status`
- `error`

Existing dataset or execution metadata may be retained when already part of the case row, such as `dataset_id`, `dimension_type`, `dataset_name`, `execution_mode`, `output_source`, `conversation_summary`, and compact `turn_traces`.

The frontend must not persist full `trace`, `judge`, `attribute`, `frontend_view`, raw responses, raw SSE streams, downstream payloads, or raw project-private evidence as durable case-pool source data. Those fields may remain in memory for the current page session or be fetched through detail APIs.

## Build-agent checks

Before reporting frontend work complete, the build agent checks:

- live and summary pages consume project frontend standards instead of adding one-off branches;
- output/reference alignment works for text and JSON outputs;
- JSON formatting and truncation are visible and deterministic;
- no project-private main-flow endpoint is introduced;
- compact case-pool persistence survives uploaded, generated, saved, and displayed cases;
- storage failures do not stop batch progress when compact persistence can still render current in-memory results.


## Demand responsibilities

Build is responsible for frontend construction from analysis output and project frontend standards:

- Consume analysis output instead of rediscovering project semantics or hardcoding project-only behavior.
- Perform frontend construction for live, summary, upload, and case-pool views through shared protocol objects.
- Keep project frontend standards as the source of truth for project-specific display and persistence behavior.
