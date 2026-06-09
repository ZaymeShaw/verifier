# Batch Protocol

`BatchRunResult` groups multiple single-chain runs for cluster and check summaries.

Fields:

- `project_id`
- `total`
- `runs`
- `cluster`
- `check`

Rules:

- Batch execution reuses the same single-chain protocol for every input; it must not introduce a second run result shape.
- Batch execution may run cases concurrently, but results must remain traceable to the original generic case identity and should be returned in input order when possible.
- Mock batch and live batch are the same batch pipeline. The execution mode only changes the run stage (`mock_response` vs real service call); judge, attribute, cluster, and check must be shared.
- Batch endpoints, CLI, and summary pages should call the same batch pipeline rather than reimplementing per-case judge, attribute, cluster, or check orchestration in the frontend.
- Long-running frontend batch actions should use a job/status wrapper around the same batch pipeline so users can see progress; the wrapper must not introduce a separate judge, attribute, cluster, or check implementation.
- Batch inputs should come from the same case-pool shape used by the summary frontend, then map each case's `input` into a single-chain run. EvaluationSample-shaped cases may additionally carry `output`, `reference`, `metadata`, and `scenario`; those fields must be preserved into the adapter input rather than being dropped by generic batch orchestration. Cases with provided `output`/`response`/`raw_response` must follow the provided-output trace path instead of forcing a project API call.
- Generated mock datasets and uploaded custom JSON files must be normalized into the same case-pool shape before batch execution; dataset metadata such as `dataset_id` and `dimension_type` may travel on the case object but must not change the run-chain protocol.
- Batch results should preserve case identity when the caller provides it, so uploaded datasets, generated mock cases, saved pools, and cluster representatives remain traceable.
- Cluster is meaningful at batch or summary level. Live pages should not expose it as a single-case operation.
- Cluster should group actionable failure attributions; correct/no-failure results must not create `none` clusters that inflate the cluster count.
- Batch check should audit the latest representative run plus aggregate cluster output, and must preserve the individual run outputs for traceability.
- Batch job status APIs may return compact run summaries for frontend progress and table rendering; full raw runs should remain available inside the backend job/pipeline result or explicit debug paths rather than being forced into every polling response.
- Batch progress events should be bounded so long-running or large-batch jobs do not make the frontend progressively slower.
