问题：状态值协议不一致(口径分裂)
- normalize.py 定义 FULFILLMENT_STATUSES = {fulfilled, partial, not_fulfilled, not_evaluable}
- 但 state_machine.py / attribute.py / check.py 大量使用 partially_fulfilled 和 contested
- 这两个值不在 normalize 常量里,_normalize_fulfillment_status 也没配别名映射
- VERDICTS 同理:normalize 用 partial,代码用 partially_correct


我需要你通过schema的方式管理它，并设置校验器在相应的地方挂载检查。FULFILLMENT_STATUSES只有3个枚举值(fulfilled，not_fulfilled，not_evaluable).你检查下所有可能涉及的地方，我们尽量减少改动范围，你先探索下





这个问题不只是 normalize.py 常量问题，而是“schema 常量、judge 提示词/派生逻辑、state_machine校验、attribute 归因目标、summary/table 展示统计”五处共同漂移。
    
最小改动范围建议如下：

1. schema 作为唯一口径
- 改 impl/core/schema/normalize.py
- FULFILLMENT_STATUSES 收窄为：
{"fulfilled", "not_fulfilled", "not_evaluable"}
- _normalize_fulfillment_status 加 legacy alias：
    - correct → fulfilled
    - incorrect / failed / partial / partially_fulfilled → not_fulfilled
    - uncertain / contested → not_evaluable
- 在 normalize_judge_result 里补齐 overall_fulfillment.status 的 schema 归一化，现在这里只归一化了
fulfillment_assessments，这是主要漏点。
2. judge 生产侧改成 3 枚举
- 改 impl/core/judge.py
- _FULFILLMENT_STATUS_VOCAB 直接引用 schema 的 FULFILLMENT_STATUSES。
- _derive_overall_status 只返回三值。
- _compute_verdict 不再产生 partially_correct。
- _compute_score 不再按 partially_fulfilled = 0.5 计算，只按 fulfilled / not_fulfilled。
- LLM prompt 和 _JUDGE_OUTPUT_SCHEMA 从 5 值改为 3 值，避免继续生成脏状态。
3. state_machine 只检查三值派生
- 改 impl/core/state_machine.py
- failure 状态集合改为 {"not_fulfilled", "not_evaluable"}。
- 删除 partially_correct / partially_fulfilled 派生分支。
- contested 不作为运行时合法状态，只由 schema 在入口归一化为 not_evaluable。
4. attribute 归因目标收窄
- 改 impl/core/attribute.py
- _derive_overall_status 只返回三值。
- _compute_verdict 不再产生 partially_correct。
- _compute_score 不再按 partially_fulfilled = 0.5 计算，只按 fulfilled / not_fulfilled。
- LLM prompt 和 _JUDGE_OUTPUT_SCHEMA 从 5 值改为 3 值，避免继续生成脏状态。
3. state_machine 只检查三值派生
- 改 impl/core/state_machine.py
- failure 状态集合改为 {"not_fulfilled", "not_evaluable"}。
- 删除 partially_correct / partially_fulfilled 派生分支。
- contested 不作为运行时合法状态，只由 schema 在入口归一化为 not_evaluable。
4. attribute 归因目标收窄
- 改 impl/core/attribute.py
- 输出 schema 文案改为三值。
- _judge_fulfillment_status 按三值派生。
- failing_statuses 改为 {"not_fulfilled", "not_evaluable"}。
- 文案里的 contested 改成 not_evaluable / disputed evidence 的描述，不再作为协议值。
5. 展示/汇总同步减少误统计
- 改 impl/core/summary.py
- 改 impl/core/table_view.py
- 改 impl/core/pipeline.py
- 删除 partially_fulfilled / contested / partially_correct 分支或统计项。
- batch representative 优先级保留：
("not_fulfilled", "not_evaluable")
6. 项目 adapter 暂时不大动
- 目前 impl/projects/*/adapter.py 搜到的硬编码基本已经是三值。
- 只依赖 schema normalize 兜底即可，减少改动范围。

我建议下一步直接按这个最小范围改 6个核心文件：schema/normalize.py、judge.py、state_machine.py、attribute.py、summary.py、table_view.py，外加 pipeline.py的两个小分支。