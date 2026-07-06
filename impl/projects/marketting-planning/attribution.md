# marketting-planning attribution

归因必须从当前 case 的 `execution_trace`、`extracted_output`、`LiveExecutionResult.application_boundary`、reference contract 和业务文档出发，不能复用历史 case 字段或硬编码个别 query。

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

attribute agent 应定位最早可观察 divergence。如果 judge verdict 是 correct，则不做失败归因。如果 evidence 不足或 judge 不可用，则输出 incomplete，而不是伪造根因。
