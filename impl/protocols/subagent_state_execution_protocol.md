# Subagent State Execution Protocol

Subagent state execution defines how a trace state invokes focused LLM subagents, deterministic functions, project adapter hooks, local probes, or normalizers.

The protocol is generic. Project-specific subagent prompts, tools, probes, endpoints, and evidence fields belong in project configuration, project standards, adapters, or hook implementations.

## Executor reference

Each executor reference declares:

- `executor_id`
- `executor_type`: `llm_subagent`, `deterministic`, `adapter_hook`, `local_probe`, or `normalizer`
- `role`
- `input_contract`
- `output_contract`
- `evidence_contract`
- `run_policy`: `single`, `sequential`, or `parallel`
- `timeout`
- `required`

## Common roles

Generic role names are reusable labels, not business rules:

- `intent_reconstructor`
- `boundary_evaluator`
- `semantic_comparator`
- `verdict_critic`
- `trace_planner`
- `probe_runner`
- `earliest_divergence_finder`
- `root_cause_reviewer`
- `fix_reviewer`
- `final_synthesizer`

Projects may add roles when those roles emit the same structured state execution records.

## Subagent result

Each executor emits a result with:

- `executor_id`
- `executor_type`
- `role`
- `status`
- `output`
- `evidence_refs`
- `claims`
- `contradictions`
- `missing_evidence`
- `error`

Claims that affect judge, attribution, finalization, or patch direction must be tied to evidence references or marked incomplete.

## Merge policies

When a state has multiple executor outputs, the state declaration must choose a merge policy:

- `single_output`: use one required executor result.
- `sequential_accumulation`: later executors receive previous structured outputs.
- `parallel_agreement`: combine compatible results and record disagreements.
- `contradiction_record`: preserve conflicts and route through critique or human review.

A merge policy must preserve individual executor outputs even when it produces a compact state result.

## Project hooks

Adapter hooks may implement project-specific work such as request normalization, evidence collection, local verification, probe execution, semantic equivalence checks, boundary reconciliation, or result normalization.

Hooks must return structured data that can be stored as subagent results, evidence records, gate inputs, or state outputs. Generic core must not interpret project-private fields except through declared gate or transition inputs.
