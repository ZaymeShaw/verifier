# Cluster Protocol

`ClusterSummary` groups multiple attribution results into actionable issue clusters.

Fields:

- `clusters`
- `representative_cases`
- `common_root_cause`
- `impact`
- `priority`
- `next_actions`

Rules:

- Clustering must use attributed cases, not raw unjudged inputs.
- A cluster should preserve representative evidence, trace ids, and affected generic case ids when they are available.
- v1 may use a simple local grouping by failure category and root-cause text; future versions can use LLM summarization.
