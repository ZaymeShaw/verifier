# QA Mock Notes

QA mock cases 覆盖三个 scenario：

- `qa_gold_answer`: question + actual_answer + reference.actual_answer。
- `qa_context_faithfulness`: question + actual_answer + contexts。
- `qa_weak_quality`: question + actual_answer。

Mock 数据集保持 JSON case pool 形态，仍通过统一 batch pipeline 执行。