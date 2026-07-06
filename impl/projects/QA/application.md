# QA Application Notes

QA 项目评估已经产出的问答结果，不在第一版中调用外部被测 QA 服务。

## Input semantics

- `input.question`: 用户问题。
- `input.contexts`: 可选证据上下文，属于输入的一部分。
- `output.actual_answer`: 待评估回答，可来自上传数据。
- `reference.actual_answer`: 可选参考答案；与 `output.actual_answer` 同形状，语义上是参考答案，不能与待评估回答混用。上传数据里的 `golden_answer` / `gold_answer` 别名会被归一化到 `reference.actual_answer`。
- `scenario`: adapter 按字段推断或沿用样本显式值。

## RunTrace semantics

`normalized_request` 保存标准化后的 input/reference/metadata/scenario；`raw_response` 表示待评估输出来源；`extracted_output` 表示标准化后的 actual answer。