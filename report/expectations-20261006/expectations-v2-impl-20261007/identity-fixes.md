# R6 identity 修复

状态：指定范围的实现与离线测试完成；全仓仍有范围外 fixture / 其他并行修复待协调。未发起 live。

## 协调方接缝

`impl/projects/llm_probe/process_loop/expectation_projection.py` 已提供：

- `validate_expectations(e) -> str`：用与需求轴、主判相同的 `json.dumps(e['expectations'], ensure_ascii=False, sort_keys=True)` UTF-8 SHA-256 校验 E 的真实内容与 `sha256`，同时拒绝重复 E ID；返回核验后的真实 hash。协调方可在共享 `process_output` 为单位附上该值。
- `validate_projection(e, projection) -> str`：先校验 E，再核验 `expectations_sha256` 相等和 `data_needs` 精确唯一覆盖 E ID。只核验消费身份，不把 prepare 后已绑定 `ref` / 绝对路径的内部 methods 重新送进模型 schema。
- `required_units` 每次消费都执行上述身份门禁；两个 ToolLoop 构造器在分析/取证/loop 构造前核验，保存自有 E / projection 副本；每轴 `view.expectations_sha256` 是经校验的实际消费指纹，存在的 `design_sha256` 一并保留。
- `prepare` 在任何模型调用前校验 E，保留 B 短编号和 ref / 绝对路径回填。未知块错误保留“原文位置”并提示使用 B 短编号。

本 worker 不修改 common/output/protocol/main judge，也不修改 `coalesce` 的 R1 聚合逻辑。

## 范围外 fixture 待协调方更新

全仓离线实测中，前四项共引起 **43 项失败**（本 worker 不修改这些文件）：

1. `tests/test_process_axes_protocol.py::test_missing_required_exercise_is_enumerated_with_evidence_and_cannot_be_na`：E 缺 hash；投影缺 identity，仍有旧 `need='tool' / tool_expectation_ids`，应改当前 external/methods 协议。
2. `tests/test_process_unit_output.py::test_off_map_link_without_turn_can_satisfy_a_should_happen_unit`：非空 E / projection 都缺 hash。
3. `tests/test_process_v2_rules.py::candidate_case`：非空 E / projection 都缺 hash；`case` 等只传 `{'expectations': []}` 的共享 validator fixture，若协调方新增单位回执也须改真实 identity。
4. `tests/test_process_prompt_contract.py::test_transcript_prompt_maps_source_id_to_readable_evidence_id`：修改 frozen E 的 `source_refs` 后须重算 E `sha256`，并同步 projection 的 `expectations_sha256`。
5. `tests/test_process_criterion_checks.py::submit`：共享 validator 只传 expectations 列表，若新增单位回执须补真实 hash。

可复用 `tests/support/expectations.py::content_sha256(value)`；空 E 常量 `E` / `PROJECTION` 已改真实确定性指纹。不能加占位 hash、兼容别名或跳过空 E 校验。

## 本范围测试与 fixture 更新

- `tests/support/expectations.py`：空 E 与空需求材料使用确定性真实 SHA-256，新增测试用 `content_sha256`，没有 fake hash / 兼容别名。
- `tests/test_expectations.py`：非空 fixture 改真实内容 hash；模型原始投影与带 identity 的内部投影分开使用；覆盖六轴入口的 stale E、缺 hash、同 ID 内容变化后的旧投影、缺/重复/额外/未知 data_need、重复 E ID、空 E 校验、字典键序不改变 identity。
- preparer 测试使用真实 `dossier_blocks` 生成的长 design ID / fields wrappers。模型接收 B1 和相对 `/description/value`，输出回填为原 ID、原 ref、`/fields/description/value`；最终路径反向解析原 record，保留英文引号和换行。验证内部带 ref 的 methods 可通过 consumer identity 校验，不重新套模型 schema。
- preparer 正反例覆盖错误长 ID、未知块、绝对路径冒充相对路径、错误字段、改写引文、缺需求；正确纠错一次可通过，两次错误仍失败。stale E 在任何调用前拒绝。
- `tests/test_process_v2_entrypoints.py`：两构造器在有轴 / 无启用轴时均拒绝 stale / 缺 identity / 覆盖错误，且尚未创建分析或取证工具、未调用客户端。
- `tests/test_process_loop.py`、`tests/test_llmtracing_tool_loop.py`：非空 E 的完整脚本六轴流程验证每轴 `view.expectations_sha256`，有/无 design hash 两种情况；模型不回显 identity，调用方构造后修改原对象不影响 evaluator 消费快照。失败仍不补业务结论。
- 随并行 R4/R5 来源修复，同步本范围 fixture 的显式外层用户原话、历史来源、Agno provider / association / ordering 元数据。**没有改变 E 原文引用、条件或 expected 拼接语义。**
- 历史 `report/llmtracing-calibration-draft/frozen-inputs/B.trace.json` 没有独立外层请求，本 worker 不修改历史文件。测试明确断言用户原文缺料，仍检查设计格式原文保存；不为得到非空 E 把 gateway user 内容冒充原话。

## 离线验证

解释器：`/Users/xiaozijian/miniconda3/envs/agno/bin/python`。使用既有 `offline_tests.py` 禁止外部/业务/付费端口；真实 SDK 测试只连本机临时 FakeOpenAI。均设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`。

| 范围 | 结果 | 证据 |
|---|---|---|
| 所有本 worker 负责的 4 个测试文件，收尾复跑 | **234 passed，4.92s** | `identity-tests-post-integration.log` |
| 9 个相关范围外测试文件，首次接缝检查 | 285 passed / 43 failed，1.15s；失败均为上述未更新 identity fixture | `identity-integration-first.log` |
| 全仓 `tests` | **2352 passed / 60 failed / 5 skipped，451.09s** | `identity-full-tests.log` |
| 8 个指定 Python 文件 | 语法与行尾空白检查通过 | 本轮离线 compile / whitespace 检查 |

完整回归期间并行 R1/R4/R5/R7 仍在更新；全仓数字是该次运行快照，不代表最终集成验收。全仓失败分组：

- **43 项** R6 范围外 identity fixture：`test_process_v2_rules.py` 40 项、`test_process_axes_protocol.py` / `test_process_unit_output.py` / `test_process_prompt_contract.py` 各 1 项。
- **2 项** R1 接缝：`test_process_criterion_checks.py::test_aggregate_is_derived_without_overwriting_any_atomic_judgment` 的两种 input_invalid 组合未给上游问题，被并行新增校验拒绝。由协调方更新，不放松校验。
- **1 项**其他 worker 新测试：`test_need_source_boundaries.py::test_save_preserves_need_fields_through_active_artifact_and_projection` 报 `PATH_ACTIVE_UNKNOWN`，临时目录的 active artifact 路径不匹配；由来源 worker / 协调方处理。
- **14 项**既有同名基线类别：config_contract 1、deerflow_attribute_evidence 6、llm_probe 缺 case 2、schema_validator 2、tool_loop_lab 1、tool_loop_lab_frontend 1、tool_loop_package implementation_files 1。本 worker 未修改这些文件。

重跑本范围命令：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /Users/xiaozijian/miniconda3/envs/agno/bin/python \
  report/expectations-20261006/expectations-v2-impl-20261007/offline_tests.py -q \
  tests/test_expectations.py tests/test_process_loop.py \
  tests/test_llmtracing_tool_loop.py tests/test_process_v2_entrypoints.py
```

未发起或核验 live，不将 live1 历史失败改写为通过；不声称全仓已绿、语义已验收或性能改善。没有修改 common/output/protocol/main judge、其他 worker 的测试、需求/规格文件，也没有提交 git。

## 收尾源码指纹

相对 `impl/projects/llm_probe/process_loop/`：

| 文件 | SHA-256 |
|---|---|
| `expectation_projection.py` | `858b9473b5035e9b9adcaaa4c6879dff9c28eabf35998049f3d0b5e8811d609d` |
| `evaluation.py` | `b8a9977f58f9f3e5d9ced2d53387959a323aad8544bea4faf026b5876aba5e17` |
| `llmtracing.py` | `0e7847eab9efa7167597c41005f8083beebb93ca2a4ab68398fa93c3602124c3` |

R1 的 `coalesce` 顶层 upstream 条件仍未由本 worker 改动；共享单位回执也由协调方添加。本报告不宣称这两处 R1 接缝已经完成。
