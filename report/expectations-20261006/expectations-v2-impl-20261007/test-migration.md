# 测试迁移

仅修改授权的五个测试/fixture 文件；不改生产代码、其他测试或实施文档。无 live 调用。

## 已迁移

- `tests/test_expectations.py`：E 仅用户需求，数据需要为 external/none/unknown，候选办法引用工具原文；保留运行隔离、历史指代、条件保留、漏查询跨轴、整段 JSON 与调用输入成员等反例。跨轴脚本复用另一代理提供的 `payload(axis, instance=run)`。
- `tests/test_process_prompt_contract.py`：共享 AxisJudgment 与实际 prompt/schema 检验，删除承诺全局映射用例，替换为设计原文块覆盖、逐字引文、多处条件、版本/调用归属、缺判准及同材料纠错用例。
- `tests/support/unit_reply.py`：每块默认 unknown 并给理由；无判准给 missing_criterion；行动必要性未配置时显式 unknown + 缺证，不把脚本默认 pass 当作语义结论；可按单位配置 necessity/blocks/rules/missing_criterion，保留正反例构造能力。
- `tests/support/expectations.py`：移除 contracts。
- `tests/fixtures/expectations_gold.json`：仅 want/history/background；保留并列、条件、用户格式、历史指代/省略及歧义反例；设计侧样例移至原文判准测试，增加场景判准及背景不能独立产需求的样例。

## 集成过程发现的问题

1. **已由共享实现维护方修复、保留原断言重跑通过**：`process_output.UnitJudgment.matched` 默认为空且 prompt 明确允许留空，但生成 schema 原为 `minLength: 1`。现 schema 与默认值一致；未让 helper 回避空值。
2. **已由共享实现维护方修复、保留正例重跑通过**：`expectation_projection.bind_results` 原拒绝 `discharged=True`、checks=[] 的 satisfied 候选。现有效缓存正例通过，未填造 pass checks。
3. **仍可复现，超出本代理所有权**：`tests/test_process_axis_investigation.py::test_unselected_model_call_cannot_disappear_from_obligation_scope` 在 `process_output.build_units` 计算 candidates 时对 `link['turn']=None` 调 `.replace()` 抛 AttributeError，尚未进入脚本 helper。需要共享实现正确处理无轮次环节；不得删除“未选模型调用仍须进入覆盖”的断言。当前无轮次代码位于 `process_output.py:134–136`。

## 验证（离线）

解释器：`/Users/xiaozijian/miniconda3/envs/agno/bin/python`，全部通过现有 `report/expectations-20261006/expectations-v2-impl-20261007/offline_tests.py`，屏蔽外网及本地业务/付费端口。

- 两个自有测试文件：**74 passed，0.42s**，日志 `/tmp/expectations-v2-owned-final.log`。包含 `methods` 的可选 JSON pointer、含引号/换行的逐字摘录、错误 pointer 不得借其他位置的规则，以及设计规则 `/content` 引用的正反例。
- 扩展回归：**148 passed，1 failed，3.36s**，日志 `/tmp/expectations-v2-consumers-final.log`；唯一失败为上述无轮次 AttributeError。范围：`test_llmtracing_tool_loop.py`、`test_process_loop.py`、`test_process_v2_entrypoints.py`、`test_process_axis_investigation.py`、`test_process_axes_facts.py`、`test_axis_materials.py`、`test_expectations_v2_need_judge.py`、`test_process_main_judge.py`。
- 旧协议符号检索：五个自有文件中无 `ProcessAssessment/_expand/ContractBinding/contracts/attach_criteria/tool_expectation_ids/OUTPUT_SPEC/_pending` 引用；未加兼容层。
- Python AST 与 JSON 均可解析；gold 为 8 个案例、14 条需求；`git diff --check` 对自有路径无报错。

复现自有测试：

```bash
/Users/xiaozijian/miniconda3/envs/agno/bin/python \
  report/expectations-20261006/expectations-v2-impl-20261007/offline_tests.py \
  -q tests/test_expectations.py tests/test_process_prompt_contract.py
```

复现扩展回归：

```bash
/Users/xiaozijian/miniconda3/envs/agno/bin/python \
  report/expectations-20261006/expectations-v2-impl-20261007/offline_tests.py -q \
  tests/test_llmtracing_tool_loop.py tests/test_process_loop.py \
  tests/test_process_v2_entrypoints.py tests/test_process_axis_investigation.py \
  tests/test_process_axes_facts.py tests/test_axis_materials.py \
  tests/test_expectations_v2_need_judge.py tests/test_process_main_judge.py
```

本报告不声称全仓通过（全仓集成由主协调方执行），也不声称真实模型语义召回或 live 运行已验证。全部正反例为离线脚本或冻结证据检查；没有修改生产共享文件、其他代理的测试或实施文档，没有提交 git。
