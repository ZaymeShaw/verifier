# QA Project Evaluation Scenario Notes

## Project positioning

QA is one evaluation project with optional sample-level scenarios. It should not be split into multiple projects such as `QA_gold`, `QA_rag`, or `QA_weak`.

The project evaluates already-produced QA outputs. A sample can provide the user input, the evaluated answer, and optional references/context. The system should normalize these fields, build a trace, then judge and attribute independently.

## Canonical sample shape

QA datasets should be normalized into:

```json
{
  "id": "qa-sample-id",
  "input": {
    "question": "...",
    "contexts": []
  },
  "output": {
    "actual_answer": "..."
  },
  "reference": {
    "actual_answer": "..."
  },
  "metadata": {
    "category": "...",
    "model_name": "...",
    "row_index": 1
  },
  "scenario": "qa_gold_answer"
}
```

For flat uploaded JSON, accept standard field names and normalize them:

- `question` -> `input.question`
- `contexts` -> `input.contexts`
- `actual_answer` / `answer` -> `output.actual_answer`
- `golden_answer` / `gold_answer` -> `reference.actual_answer`（输入别名，归一化到与 output 同形状）
- `category`, `model_name`, `latency_ms`, `token_usage`, `cost` -> `metadata`

The first version assumes JSON input. Other formats can be converted to JSON before upload.

## Scenario design

Scenario is a QA project extension carried on each sample.

Recommended scenarios:

1. `qa_gold_answer`
   - Required fields: `question`, `actual_answer`, reference answer (provided as `actual_answer` in reference, or uploaded via `golden_answer` / `gold_answer` alias).
   - Contexts may exist but are auxiliary unless the judge standard says otherwise.
   - Metrics: correctness, completeness, key point coverage, contradiction control, clarity.

2. `qa_context_faithfulness`
   - Required fields: `question`, `actual_answer`, `contexts`.
   - Used when no golden answer exists but evidence/context exists.
   - Metrics: faithfulness, relevance, evidence support, hallucination risk, context usage.

3. `qa_weak_quality`
   - Required fields: `question`, `actual_answer`.
   - Used when neither golden answer nor contexts are available.
   - Metrics: relevance, usefulness, coherence, risk control, clarity.

Default inference:

```text
has golden_answer/gold_answer (alias) -> qa_gold_answer
else has non-empty contexts -> qa_context_faithfulness
else has question + actual_answer -> qa_weak_quality
else invalid_sample
```

A dataset may contain mixed scenarios, but reports must group metrics by scenario. Do not mix weak-quality samples into accuracy.

## RunTrace semantics for QA

QA does not need to call a tested QA service during evaluation if the dataset already contains the evaluated output.

For QA:

- `normalized_request`: normalized `input`, `reference`, `metadata`, `data_quality_flags`, and inferred `scenario`.
- `raw_response`: original `output.actual_answer` or the original uploaded sample output section.
- `extracted_output`: normalized output, usually `{ "actual_answer": "..." }`.
- `reference_contract`: canonical QA reference such as `actual_answer` and scenario-specific expected evidence.
- `scenario`: canonical scenario selected from normalized sample fields.
- `schema_protocol_extensions`: QA-private display/debug details only; shared facts must not be sourced from extensions.

## Judge requirements

QA judge should output fulfillment-first generic fields plus multidimensional details:

- `business_expectations`
- `fulfillment_assessments`
- `overall_fulfillment`
- `verdict`
- `score`
- `confidence`
- `reasoning_summary`
- `verdict_derivation.score_dimensions`
- `needs_human_review`
- scenario-specific evidence fields when useful

All scores are 0-1. Scenario dimensions live under `verdict_derivation.score_dimensions` when present.

Gold answer metrics should not be applied to context-only or weak samples. Weak samples should not be reported as accuracy.

## Attribution requirements

QA attribution should use structured error types. Initial taxonomy:

- `answer_incorrect`
- `answer_incomplete`
- `question_misunderstood`
- `irrelevant_answer`
- `unsupported_claim`
- `hallucination`
- `context_not_used`
- `insufficient_context`
- `context_noise`
- `over_refusal`
- `format_error`
- `too_vague`
- `contradiction`
- `needs_human_review`

Each failed or risky sample should have:

- `causal_category`
- `expectation_attributions`
- `earliest_divergence`
- `chain_nodes`
- `probe_results`
- `evidence_coverage`
- `needs_human_review`
- actionable reason and suggested fix

## Cluster and summary requirements

QA cluster/report should group by:

- scenario
- causal category
- needs human review
- category/model metadata when available

Metrics must be separated:

- `qa_gold_answer`: accuracy, average correctness, average completeness.
- `qa_context_faithfulness`: faithful rate, hallucination risk rate, insufficient evidence rate.
- `qa_weak_quality`: usable rate, human-review rate, high-risk rate.

A combined score may be shown only as `综合质量估计分`.

## Frontend expectations

The generic frontend should support QA through protocol fields rather than hardcoded QA-only pages:

- Project dropdown includes `QA` and `client_search` from the project list API.
- Upload/import area accepts JSON and normalizes into case pool samples.
- Case table displays `Input`, `Output`, `Reference`, and optional `Scenario`.
- Scenario filters and scenario summary cards appear when the project exposes scenarios.
- Batch evaluation remains one action; scenario-specific judge behavior is backend/project logic.

Do not label QA output as generic `API 输出`; use `Output` or `被评估输出`.

## QA check requirements

QA-specific check should verify:

- scenario inference is consistent with sample fields;
- samples without golden answer are not included in accuracy;
- `verdict_derivation.score_dimensions` scores are 0-1 and match scenario dimensions;
- `causal_category` comes from the QA taxonomy or generic attribution categories;
- RAG/context scenario has non-empty contexts;
- weak-quality scenario conclusions are marked as estimates, not accuracy;
- human-review queue can be derived from confidence, boundary scores, evidence coverage, and `needs_human_review`.
