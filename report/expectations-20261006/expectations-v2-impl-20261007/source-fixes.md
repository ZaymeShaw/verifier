# R4 / R5 / R7 source fixes

2026-10-07。只处理独立评审 R4/R5/R7。**已实现并通过局部离线反例验证；不声称全仓或 live 验收通过。**

## 修改范围

- `impl/projects/llm_probe/business_trace/expectation_material.py`
- `impl/projects/llm_probe/business_trace/providers/llmtracing_transcript.py`
- `impl/projects/llm_probe/business_trace/providers/llmtracing_evidence.py`
- `impl/core/capability_store.py`：**仅在 `validate_entry()` 的 `clean` 初始化之后插入 14 行**，保存/校验 criterion、description 和可选 downstream；未改已有其他 worker 的路径、business_trace、axes、process_obligations 等逻辑。
- `tests/test_expectations_v2_need_judge.py`：把历史 fixture 的来源补到独立外层请求，而非从首个模型调用猜历史。
- 新增 `tests/test_need_source_boundaries.py`：46 项参数化离线测试。

没有修改 `test_expectations.py`、`test_design_rule_blocks.py`、共享输出/投影/design_rules、`need_judge.py` 或公共 `JudgeResult`。没有修改任何 demand/spec 文档、迁移数据、添加依赖、保留旧模型消息 fallback 或提交 git。`demand/expectations.md`、两个 alg 协议和 `spec/implementation/process-axes.md` 的开始/结束 SHA 一致；`impl/core/schema/judge.py` 无 diff。

## 已解决的发现

### R4 — 原话与历史必须有独立来源

`expectation_material.py:11–94`：

1. 原话来自外层 request / 已记录的 mock_message；识别业务 body 中的原话字段，以及外层 messages 中的当前 user。**首个模型请求的 user 角色和先后位置不再作为原始来源证明。**
2. 已知外层原话时，即使首个模型 user 是 Direct/预处理结果或生成指令，仍只投影外层原话。不把内部改写文本放进 history。
3. 没有外层原话时，只有注册的 `provider=agno` 快照可提供独立 `run.run_input`，包含 Agno `input_content` 封装；不取 run.content。失败快照或已知 run_id 不匹配不能供给原话。llmtracing/未知 provider 不因拥有 run 形状就获此权限。
4. 历史只取外层请求中当前 user 之前的 user/assistant，或 Agno adapter 已标明 `ordering=trace_timestamps/created_at_plus_duration` 且 run_id 不同的 history_runs。不同 run_id 本身不能证明过去；当前输出、工具返回、内部 assistant 和后续调用不作历史。
5. 模型消息只用于**原文相等后的关联**，保留真实下标 trace_ref；最后一条内部 user 不会替换更早已匹配的独立原话。
6. 原话不可用时保留 `用户原文未独立记录`，不从首个模型调用补造。Agno run_input 可用时不错误报缺料。capability 未拆分继续 partial，downstream 继续不消费。

覆盖测试（新文件，名称均为 `test_` 前缀）：
- `outer_request_wins_over_first_model_user_and_fake_history`（4 种外层形状）；`model_role_cannot_supply_unrecorded_original_or_history`（3 provider）。
- `outer_message_history_is_preserved_but_current_outputs_are_not`；`turn_records_use_each_outer_original_and_mock_source_not_model_content`。
- `registered_agno_run_input_is_a_legitimate_original`（字符串原样保留及 input_content）；`other_providers_cannot_invent_raw_original_from_run_shape`；`outer_original_precedes_agno_run_input`。
- `failed_or_mismatched_agno_association_does_not_supply_original`；`matching_original_before_generated_last_user_is_not_replaced_or_history`。
- `agno_history_requires_adapter_ordering_not_just_a_different_run_id`：实际调用既有 Agno `_history()` 产生已定序 fixture，再验证没有定序证明/当前 run 被排除。

### R5 — 消息身份与实际输入正文闭环

`llmtracing_transcript.py:108–111,153–160`：先枚举**原始 messages 下标**，再区分 system/body。`.mN` 不再用 `len(system)+body_index` 猜编号；忽略非消息项也不重编号。沿用精确内容前缀去重，只把实际重放的旧条目列入当前 input_refs。

`llmtracing_evidence.py:235–254`：删除 `source.trace_refs ∩ input_refs` 命中即通过的捷径。对每条需求出处都用已有 `source_in_inputs()` 核对本次实际输入正文（原始 message.content、system 消息正文、实际 tools/params）。调用元信息、渲染文本或错误旧 ref 不构成送达证明。

覆盖测试：
- `transcript_message_ids_use_original_indices_and_replay_only_actual_content`：评审交错 user/system 原例，m1 是旧 query，m3 才是当前原文；c2 只继承旧 query。
- `nonmessage_slots_do_not_renumber_original_input_positions`。
- **完整 `TranscriptEvaluation._submitter()` 入口**：`full_submitter_checks_original_arrival_not_previous_query`。真实计算 E/projection hash、完成原文读取与批次回执后，c1 接受，只有旧 query 的 c2 拒绝（`出处未证实进入本次输入`），重新实际收到当前原文的 c3 接受。不靠全局共享 validator 放松通过。
- `even_matching_trace_ref_requires_actual_source_content`（3 变体）：错误 ref 命中旧 query；调用元信息伪含当前原文；渲染文本伪含当前原文，均拒绝。

### R7 — 普通保存不再静默删除场景材料

`capability_store.py:61–74`：criterion/description 配置时必须为字符串，沿用 `MAX_CAPABILITY_CHARS` 上限；**保存原文，包括空白/换行，不转换为 str、不 trim、不合成缺省字段**。可选 downstream 必须是 `list[str]` 并原样保存，仅占位，不进入 y_need。

`save_preserves_need_fields_through_active_artifact_and_projection` 使用临时仓库根目录，经过**真实 `save_capability → validate_entry → active artifact writer → load_capability_map → 再保存 → project_requirements`**；没有替换保存器/校验器。criterion 作为 want，description 作为 background，capability 未拆分仍 partial，downstream 不被读取。另有类型错误、超长、缺省与空值形状的正反例。

## 离线验证与剩余失败

解释器：`/Users/xiaozijian/miniconda3/envs/agno/bin/python`。所有 pytest 通过既有 `offline_tests.py`，禁用 plugin autoload 和 pytest cache；该守护阻断外部/业务/付费端口，允许本地假服务器。两份本 worker 测试还逐例禁止 socket connect/connect_ex。**没有发起真实模型或业务调用。**

| 组 | 结果 | 证据 |
|---|---|---|
| 新 R4/R5/R7 反例初始红灯 | 39 failed / 3 passed；实现前 | 初始执行 `/tmp/source-fixes-red.log`；之后增加 4 项边界反例 |
| 本 worker 两份测试，最终 | **63 passed，0.80s**（新文件 46 + need_judge 17） | [source-fixes-tests.log](source-fixes-tests.log) |
| 首轮相邻回归，12 文件 | 538 passed / 50 failed，5.88s | [source-fixes-first-regression.log](source-fixes-first-regression.log) |
| 最终相邻回归，20 文件 | **745 passed / 42 failed，12.04s** | [source-fixes-regression.log](source-fixes-regression.log)，末尾列出所有精确失败 node ID |
| 全仓 `tests` | **未完成：工具等待 300 秒后超时终止**，日志停在约 17–20% 进度；没有 pytest 总结，不能报全仓通过或剩余失败总数 | [source-fixes-full-tests.log](source-fixes-full-tests.log) |

最终 42 项均是其他 worker 范围内的 **R6 指纹 fixture 未更新/更新后未重算**：

| 文件 | 数量 / 精确接缝 |
|---|---|
| `tests/test_process_v2_rules.py` | **40** 项，均在 `candidate_case():74 → required_units → validate_projection → validate_expectations` 进入业务断言前失败；fixture 没有真实 E SHA。精确参数化 node ID 见最终日志 `1323–1362` 行。 |
| `tests/test_process_unit_output.py` | **1**：`test_off_map_link_without_turn_can_satisfy_a_should_happen_unit`；自造 E/projection 无真实 SHA。 |
| `tests/test_process_prompt_contract.py` | **1**：`test_transcript_prompt_maps_source_id_to_readable_evidence_id`；修改 E 的 source_refs 后未重算 E/projection SHA。 |

均报 `冻结需求 E 的 sha256 与实际内容不一致`，**没有改这些测试，也没有放松校验**。

首轮另有 **9 项 R4 旧 fixture 失败**，来自 `test_expectations.py`：`test_projection_excludes_outputs_runtime_system_tools_and_caller_ability`、`test_history_resolves_reference_but_current_assistant_is_not_input_to_e`、`test_agno_original_run_input_and_definition_provenance`、`test_retired_design_gold_cases_are_original_sources_not_demands` 的 2 参数、`test_frozen_b_projection_separates_design_format_from_user_demands`、`test_agno_history_is_context_only_and_current_output_excluded`、`test_tool_absence_does_not_make_demand_material_partial` 的 2 参数。需分别补独立外层原话、Agno provider/ordering，或对确实没有原话的冻结样本断言 partial。**其他 worker 已在并发更新这些 fixture；最终回归这 9 项均通过，不归功于本 worker。** 冻结 B.trace.json 只记录 capability_ref，没有外层 query，不能从内部模型 user 补造；冻结文件未修改。

最终 `test_design_rule_blocks.py`、llmtracing 两条证据/ToolLoop测试、入口测试和 capability 消费相关测试在上述范围内没有失败。各组有重叠，不把通过数相加宣称独立总覆盖。

### 重跑命令

```bash
export PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
PY=/Users/xiaozijian/miniconda3/envs/agno/bin/python
RUNNER=report/expectations-20261006/expectations-v2-impl-20261007/offline_tests.py
$PY "$RUNNER" -q -p no:cacheprovider \
  tests/test_need_source_boundaries.py tests/test_expectations_v2_need_judge.py

$PY "$RUNNER" -q -p no:cacheprovider \
  tests/test_business_trace_llmtracing.py tests/test_llmtracing_tool_loop.py \
  tests/test_transcript_evidence_boundary.py tests/test_process_v2_entrypoints.py \
  tests/test_process_v2_rules.py tests/test_process_unit_output.py \
  tests/test_process_criterion_checks.py tests/test_expectations.py \
  tests/test_design_rule_blocks.py tests/test_capability_provider_binding.py \
  tests/test_capability_carrier.py tests/test_capability_claims_stamps.py \
  tests/test_llm_probe_business_trace.py tests/test_llm_probe_eval_axes.py \
  tests/test_llm_probe_text_carrier.py tests/test_llm_probe_material_tools.py \
  tests/test_process_axes_facts.py tests/test_process_prompt_contract.py \
  tests/test_axis_materials.py tests/test_process_main_judge.py
```

## 边界与交接

- 不修 R1/R2/R3/R6；引用其并发改动引发的失败仅为交接信息。没有改共享输出、投影或 design_rules。
- 无原话的历史 gateway-only trace 现在会 partial；这是来源契约修复，不加兼容恢复、不改冻结样本。若要 complete，须由已有真实外层请求记录提供来源。
- 内容匹配只证明原文出现在实际输入，不能证明模型理解、需求提取准确或语义规则核验完整。
- 用户提供的状态为 live1 已在 projection 失败、live2 尚未运行；本 worker **没有启动、重跑或独立验收任何 live**，不把离线通过改写成 live 成功。
- 全仓超时未完成；不能据此确认“只剩既有 14 项失败”或全仓无新增回归。

### 本 worker 收尾源码 SHA-256

| 文件 | SHA-256 |
|---|---|
| `business_trace/expectation_material.py` | `c4907502fc8bbbd33c2e8cb2fb28d5278461e860b35dc1b5b7a6636d53e49a0e` |
| `business_trace/providers/llmtracing_transcript.py` | `588b20b9b3f3442ba4af672f37c66c4a6526ab6aefa13ab8f4638190ae9c65d4` |
| `business_trace/providers/llmtracing_evidence.py` | `251e2bd9fe250192fc5879144b7bbbaf65610307b96f3fcf5d2fc1e392b87129` |
| `impl/core/capability_store.py` | `afba7143b9af1807b0f1d5ff3afab69d258ec40c842b7e0156417a30a2f38e52` |
| `tests/test_expectations_v2_need_judge.py` | `3cbda0dbbd1ec5194574b40177f8b40f1c91c120a5abf2572af6a7b19dc5180a` |
| `tests/test_need_source_boundaries.py` | `1a49e4c3bce8854b77e82dd1172e799831d1f23ee908907a15f0e06d9bbe8f83` |

前三个路径相对 `impl/projects/llm_probe/`。工作区其他文件持续由其他 worker 更新；这些结论只覆盖本报告列明的运行快照。
