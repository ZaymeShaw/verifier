# QA Attribution Notes

QA attribution 使用结构化错误类型，优先帮助定位回答质量问题而不是代码路径。

## Error taxonomy

- answer_incorrect
- answer_incomplete
- question_misunderstood
- irrelevant_answer
- unsupported_claim
- hallucination
- context_not_used
- insufficient_context
- context_noise
- over_refusal
- format_error
- too_vague
- contradiction
- needs_human_review
- none

## Output requirements

AttributeResult 应输出 `causal_category`、`expectation_attributions`、`earliest_divergence`、`chain_nodes`、`probe_results`、`evidence_coverage`、`needs_human_review` 和 `scenario`。失败或高风险样本要给出可执行的原因、验证方式和建议修复方向。