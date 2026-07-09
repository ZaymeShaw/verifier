# Tool Protocol

## Purpose

The tool layer provides reusable, project-aware protocol tools that can be used by analysis, application, mock, judge, attribute, and check flows. Tools expose inspectable evidence and structured outputs so agents do not need to reimplement project-specific comparison, boundary, attribution, or check logic in prompts.

## Core objects

- `ToolContext`: runtime context for a tool call. It includes `project_id`, `purpose`, optional `ProjectSpec`, optional `RunTrace`, and extra `inputs`.
- `ToolResult`: structured result from a tool. It includes `tool_id`, `tool_type`, `status`, `outputs`, `evidence`, `missing_evidence`, `boundary_limits`, and `error`.
- `ProtocolTool`: interface with `tool_id`, `tool_type`, and `run(context)`.
- `ToolRegistry`: project-local registry that stores tools, exposes agno `Function`/`Toolkit` wrappers, and runs selected tools by type.
- `ProtocolToolPlanner`: deterministic selection layer that maps purpose/policy/tool_type/tool_ids to tool calls. It is the stable planning boundary; LLM planner variability must be opt-in by protocol policy.

## Tool types

Tool types describe reusable capability, not the caller:

- `document`: reads or validates project documents and standards.
- `application`: inspects application/runtime behavior.
- `trace`: extracts or verifies run trace evidence.
- `intent`: reconstructs current user/downstream intent.
- `boundary`: determines evaluable project/system boundary.
- `comparison`: compares expected-vs-actual business output.
- `attribution`: probes root cause and evidence chain.
- `check`: audits protocol/code/data/frontend consistency.

A project may implement only the tools it needs, under `impl/projects/<project>/tools`.

## Registration

Each `ProjectAdapter` exposes `protocol_tools() -> ToolRegistry`. Project adapters register project-specific tools there. Shared flows call tools through:

```python
adapter.run_protocol_tools(trace, purpose="judge", tool_type="comparison")
```

`purpose` is the agent/runtime purpose (`analysis`, `application`, `mock`, `judge`, `attribute`, `check`). `tool_type` selects reusable capability. A caller should not hard-code project tool classes outside the project adapter.

## Agno integration

The registry creates agno `Function` wrappers for registered tools and can expose an agno `Toolkit`. Deterministic protocol paths should use `run_protocol_tools()` or `run_selected()` for reproducibility. `ProtocolToolPlanner` selects tools from explicit `tool_ids` or `tool_type` policy. Agno planner-based selection may be layered above this registry only when the protocol sets an opt-in policy such as `allow_planner_variability`; stable judge/check paths keep deterministic selection.

## Output requirements

Tool outputs must be evidence-first:

- Do not derive business expectations from verdict labels alone.
- Mark expected source explicitly when a tool uses reference/sample data.
- Keep boundary limitations separate from failures.
- Return enough structured evidence for frontend, check, and attribute flows to audit the claim.

## Retrieval tool budgets

Retrieval tools that return file or document content (e.g. `source_read_functions`, `field_search_definition`) must enforce two caps:

- **Per-call cap**: a single result is bounded by a documented byte cap (current default `MAX_SOURCE_FILE_BYTES = 64000` in `impl/tools/source_retrieval.py`). Content over the cap must be truncated, not paginated.
- **Per-case aggregate cap**: cumulative bytes returned to one agent run are bounded (current default `DEFAULT_AGGREGATE_BYTE_BUDGET = 192_000`). Once exhausted, the tool must return a structured `budget_exhausted` marker so the agent can stop calling and finalise with `incomplete_reason` instead of retrying.

Retrieval providers should narrow the candidate set up-front using current trace signals (failed/suspicious stages, attribution targets) when those signals are available; the aggregate budget is defence-in-depth, not the primary control. Project adapters that build retrieval catalogs (e.g. `build_attribute_context.source_config_paths`) are responsible for the up-front narrowing.

## Client search comparison example

`client_search.condition_compare` is a `comparison` tool. It compares the target customer-search contract against actual structured conditions and returns:

- `expected`: expected query logic and conditions, with `expected_source`.
- `actual`: actual query logic and conditions.
- `wrong`: same field but wrong operator/value/logic.
- `missing`: intent-required condition not output.
- `extra`: actual condition not required by current target population.
- `boundary_limits`: unsupported/out-of-boundary requirements.

Reference answers for client_search are evidence unless the case or project explicitly marks them as current oracle (`is_current_oracle` or equivalent). Current intent/config-derived expectations take priority when available. If neither current intent/config expectations nor an explicit reference oracle exists, the comparison tool must return `evaluable=false`, keep reference conditions as evidence, and avoid producing wrong/missing/extra as if the reference were the oracle.
