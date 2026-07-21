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

AttributeResult 只输出按真实缺陷合并的 `findings`、一个整体 `unresolved_reason` 和协议派生的 `summary`。每个 finding 必须引用 Finalization 重新加载的 ContextUnit；证据不足时不提供根因猜测，只在 `unresolved_reason` 说明当前阻塞。
