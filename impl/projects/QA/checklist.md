# QA Checklist

- scenario 推断要和样本字段一致。
- 无 golden answer 的样本不得计入 accuracy。
- QA 私有质量维度分数必须在 0-1，并只能作为 fulfillment evidence 或项目扩展展示。
- AttributeResult 的 findings 必须来自当前 QA taxonomy 相关事实或当前样本语义材料，并通过 Finalization 重载的 ContextUnit EvidenceRef 证明；证据不足时只写 `unresolved_reason`。
- RAG/context 场景必须有非空 contexts。
- weak-quality 场景必须标记为质量估计，不声称准确率。
- 低置信度、严重错误、边界分数和弱证据要能进入人工复核队列。
