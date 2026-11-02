# 六轴消费侧：criterion_checks 改动 + 上下文轴真实回放

## 改动

模型只提交 `criterion_checks`（criterion_ref / outcome / observed），单位 outcome、expectation_ids、observed 汇总由程序派生；优先序统一为 `UNIT_OUTCOME_PRIORITY`。旧字段直接拒绝。

- 回归：`tests-after.log`，274 passed（离线，业务/付费端口被屏蔽）。
- 受保护文档哈希无漂移（`protected.json`）。

## 上下文轴真实回放（`replay_context_axis.py`）

复用 `analysis-split-full-live-20261007` 的冻结需求、分析结果与期望投影，只重跑 context_memory；生产 runner，未改校验与重试。

- run_id：`consumer-checks-context-live-20261007`，2 次模型调用，约 170 秒。
- 结果：**failed**（`live-summary.json` / `live-result.json`）。

| 调用 | 结果 |
|---|---|
| 第 1 次 | 通过 schema、`_expand`、bind、证据校验；在最后的承诺覆盖检查被拒：3 条 coverage_required 未核对（模型只用了 `obligation:` 判准） |
| 第 2 次（重试） | 补上了 3 条承诺，但 observed 中出现未转义的双引号，JSON 失效；json_repair 把它拆成 list，schema 拒绝 |

上次运行的"单位 outcome 与逐项检查不一致"在新结构下不再可能出现。**上下文轴仍未通过**，暴露的两个原因与其他轴相同：

1. **承诺期望按整轴分派，而不是按单位挂判准。** 投影只给每条承诺标 axes；`run_process_axis` 把该轴全部承诺按批分派为 coverage_required（上次：规划 48、工具 62、知识 22 条压在 2–8 个单位上）。与 `spec/alg/expectations.md` §6.1“挂判准：条件成立、部件对得上的承诺侧期望挂到单位”不一致。
2. **结构化输出只靠 json_object 模式 + 提示词 + json_repair。** 长中文 observed 引用原文时写出未转义引号；第 1 次被 json_repair 悄悄修好，第 2 次被修成 list。上次工具执行轴的“非约定字段”是同一机制。

代码只在本目录新增脚本与产物，未改其他源码与配置。
