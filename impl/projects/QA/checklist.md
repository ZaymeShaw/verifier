# QA Checklist

- scenario 推断要和样本字段一致。
- 无 golden answer 的样本不得计入 accuracy。
- `verdict_derivation.score_dimensions` 中所有 score 必须在 0-1。
- `causal_category` 必须来自 QA taxonomy 或通用归因分类。
- RAG/context 场景必须有非空 contexts。
- weak-quality 场景必须标记为质量估计，不声称准确率。
- 低置信度、严重错误、边界分数和弱证据要能进入 human review。