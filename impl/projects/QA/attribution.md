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

AttributeResult 应输出 `expectation_attributions`、`suspected_locations`、`root_cause_hypothesis`、`evidence` 和 `evidence_strength`。失败或高风险样本要基于当前 question/reference/actual/judge evidence 给出可解释的回答质量根因；证据不足时将 `evidence_strength` 设为 `none` 或 `weak`，并在 `root_cause_hypothesis` 中说明缺失证据。