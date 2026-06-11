# QA output/reference 标注与 application 协议审核报告

记录时间：2026-06-11

## 审核结论

本次按 `check.md` 审核 QA 项目的 application agent 构建、协议字段、前端展示链路，确认原问题不是 QA judge 单点问题，而是字段语义和前端展示机制之间存在不一致：

- QA 的 `output` 语义应是被评估答案，即 `actual_answer`。
- QA 的 `reference` 语义应是参考答案/标准答案，即 `golden_answer`。
- 不能为了满足通用“reference 与 output 对齐”的展示规则，把 QA 的 golden answer 改标成 actual answer。

因此最终选择保持 QA 项目语义优先：

```json
{
  "output": {"actual_answer": "..."},
  "reference": {"golden_answer": "..."}
}
```

## 发现的问题

### 1. 前端候选区对 flat QA case 的 output 识别不足

flat QA case 常见输入：

```json
{
  "question": "什么是犹豫期？",
  "actual_answer": "...",
  "golden_answer": "..."
}
```

原前端 `caseOutput()` 只读取：

- `item.output`
- `item.input.output`
- `item.trace.extracted_output`

没有读取：

- `item.actual_answer`
- `item.input.actual_answer`

这会导致 batch 运行前，候选区 `Output / 被评估输出` 为空或只能等 trace 生成后才显示。

### 2. 通用 reference shape alignment 会误改 QA 字段名

`impl/core/frontend_view.py::_align_reference_shape()` 的通用逻辑会在 actual 是：

```json
{"actual_answer": "..."}
```

reference 是：

```json
{"golden_answer": "..."}
```

时，把 reference 展示成：

```json
{"actual_answer": "golden text"}
```

这对部分同构 JSON 项目是合理的，但对 QA 项目会造成语义标注错误：reference 本质就是 golden answer，不应该显示成 actual answer。

### 3. QA 协议文档本身是正确方向，应保留

`impl/projects/QA/application.md` 和 `impl/projects/QA/evaluation.md` 已明确：

- `output.actual_answer`: 待评估回答。
- `reference.golden_answer`: 可选参考答案。

本次没有把 QA 协议改成 `reference.actual_answer`，因为这会破坏 QA 项目的业务语义。

## 已做修改

### 1. 修复前端候选区 output/reference 展示

修改文件：`impl/frontend/summary.html`

- `caseOutput()` 增加 flat QA 字段识别：
  - `item.actual_answer`
  - `item.answer`
  - `item.input.actual_answer`
  - `item.input.answer`
- `inputReference()` 保持 QA reference 语义：
  - `golden_answer`
  - `gold_answer`
  - `input.golden_answer`
  - `input.gold_answer`
- 前端候选区现在会显示：

```json
Output / 被评估输出:
{"actual_answer": "..."}

Reference:
{"golden_answer": "..."}
```

### 2. 修复 FrontendView reference panel 的 QA 字段误对齐

修改文件：`impl/core/frontend_view.py`

- `_align_reference_shape()` 遇到 reference 中包含 `golden_answer` 时直接返回原 reference。
- 避免把 QA 的 `reference.golden_answer` 误展示成 `actual_answer`。
- 其他项目仍保留原有 reference/output shape alignment 逻辑。

### 3. 保持 QA adapter/project 协议语义

相关文件已检查并保持一致：

- `impl/projects/QA/adapter.py`
- `impl/projects/QA/application.md`
- `impl/projects/QA/evaluation.md`
- `impl/projects/QA/frontend.md`
- `impl/projects/QA/project.yaml`

最终语义保持：

- `actual_answer` 只表示被评估输出。
- `golden_answer` 只表示 reference 标准答案。
- QA check rule 继续要求 `reference_field: golden_answer`。

## 与 demand.md 的对齐说明

`demand.md` 要求：

1. 输入包含 output 时直接取 output。
2. 输入包含 reference 时直接取 reference。
3. 输入没有 reference 时由 judge 生成 reference。
4. 用例池中 reference 格式尽量与 output 对齐。

QA 项目的特殊性是：output/reference 在结构上不完全同名，但语义上天然成对：

- `actual_answer` vs `golden_answer`

本次按 check.md 的机制审核后，选择不做机械字段同名对齐，而是保留 QA 语义字段，避免把 golden answer 错标为 actual answer。也就是说：

- 对通用项目，仍可执行 reference/output shape alignment。
- 对 QA，`golden_answer` 是项目协议字段，应优先于通用展示对齐规则。

## 验证结果

已执行：

```bash
python -m compileall -q impl
```

已用 flat QA case 验证：

```json
{
  "question": "什么是犹豫期？",
  "actual_answer": "犹豫期通常是投保人收到合同后的一段可无条件退保期限。",
  "golden_answer": "犹豫期是投保人收到保险合同后，在规定天数内可申请解除合同并通常退还已交保费的期限。"
}
```

验证结果：

```text
single_output= {'actual_answer': '...'}
single_reference= {'golden_answer': '...'}
single_view_reference= {'golden_answer': '...'}
batch_output= {'actual_answer': '...'}
batch_reference= {'golden_answer': '...'}
batch_view_reference= {'golden_answer': '...'}
check= True
```

## 最终结论

QA 项目的 application/adapter 主体构建方向是正确的：它评估上传数据中已经产出的 QA 输出，不调用外部 QA 服务。

本次真正的问题在于前端候选区和通用 frontend view 的展示机制没有尊重 QA 的项目语义，导致 `golden_answer` 被错误展示成 `actual_answer`。已修复为：

- Output 永远展示被评估输出 `actual_answer`。
- Reference 永远展示标准答案 `golden_answer`。
- 通用对齐逻辑不再覆盖 QA golden answer 字段。
