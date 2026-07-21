# marketting-planning attribution

归因必须从当前 case 的 `RunTrace.execution_trace`、每轮/最终 `extracted_output`、`RunTrace.application_boundary`、reference contract 和业务文档出发，不能复用历史 case 字段或硬编码个别 query。

## 阶段顺序

1. request_normalization
2. intent_recognition
3. field_clarification
4. session_merge
5. path_dispatch
6. planning_function
7. result_assembly
8. sse_generation
9. adapter_extraction

attribute agent 应基于 Finalization 重新加载的 ContextUnit，定位能够解释当前 not_fulfilled gap 的真实缺陷，并按缺陷组织 findings。如果 `overall_fulfillment.status` 是 `fulfilled`，则不做失败归因；如果证据不足或 judge 不可用，则 findings 为空并在一个 `unresolved_reason` 中说明阻塞，而不是伪造根因。
