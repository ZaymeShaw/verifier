# 交接：实施 axe-v5（ES 知识源 · 可选依赖 · 真实性轴）

你接手的是 `llm_probe` 扩展评估轴体系的下一阶段。先读这三份，按顺序：

1. `AGENTS.md`（仓库工程原则，必须遵守）
2. `spec/adapter/axe-v4.md`（已实现的现状与协议；§0 决定表、§5 运行器、§6 结果、§7 校验、§8 触点）
3. `spec/adapter/axe-v5.md`（本次要实现的增量；§0 决定表 D13–D18 是边界）

## 现有代码地图

- 扩展轴包：`impl/projects/llm_probe/eval_axes/`（`types.py` `registry.py` `validate.py` `runner.py` `llm.py` `adapters/{fulfillment,carryability}.py`），入口 `__init__.py::run_for_trace / build_report`
- core 侧钩子：`impl/core/eval_axes.py`（声明式装载，不 import 项目代码）
- 现有资料工具箱（文件数据源，**只读不改**）：`impl/projects/llm_probe/material_tools.py`
- 配置合同：`impl/config.yaml` + `impl/core/config_schema.py` + `impl/core/config.py`；`.env` 变量必须先在 `config.yaml` 的 `environment.variables` 注册，`required_when` 可做条件必填；`eval_axes.model_policy` 是上一轮加的同类字段，照它的模式加
- 测试：`tests/test_llm_probe_eval_axes.py`（32 个，全绿；含假 LLM `FakeLlm`、假路由 `_fake_router`、`_install_fake_llm` 夹具）；运行方式 `bash run.sh python -m pytest tests/test_llm_probe_eval_axes.py -q -p no:cacheprovider`

## 硬规则（违反即返工）

- **生产轴1/轴2一行不改**：`impl/core/judge.py` `judge_protocol.py` `judge_execution.py` `capability_carrier.py` `capability_structured.py`、`impl/projects/llm_probe/{judge,text_carrier,live,capability,material_tools}.py`、`project.yaml`。改前 `git diff --stat HEAD -- <这些文件>` 必须为空，改后也必须为空。
- **不新增 Python 依赖**（D14）：ES 用标准库 `urllib` 直接调 REST，不装 `elasticsearch`。
- `.env` 变量不得 `os.getenv` 直读，必须走 `config.yaml` 注册 + resolver（`get_runtime_config()`）。
- 扩展轴新建的 LLM 客户端统一经 `eval_axes/llm.py::axis_llm`（记账 + 模型策略），不要直接 `project_llm_client`。
- 每个 adapter 的 `run()` 必须返回带 `summary`（`text` 非空 + 逐格 `items`）的 `RunOutcome`，否则运行器判 `failed`。
- 没有真实性框时，fulfillment 发给模型的 system/user 材料必须与生产逐字相同——现有测试 `test_fulfillment_context_is_byte_identical_to_production_build_context` 钉着，不许改弱。
- 不提交 git。不改 `tmp/` 下的对照脚本。

## 任务（按 v5 §5 顺序，每步单测绿了再下一步）

1. **可选依赖**（v5 §2）：`types.py` 加 `Dependency(type_id, optional=False)`，`AxisType.depend_on` 接受 `Dependency | str`；可选上游对应的 `Input` 必须 `required=False`（构造期校验）；`runner.py` 第 2 步按 §2.2 改；`validate.py` 按 §2.3 改；`trigger_when` 不得引用可选上游；`registry.py` 的静态校验同步。单测覆盖：可选上游缺席时下游正常跑、上游存在时等待并注入、上游 failed 时下游照跑且 summary 追加说明、`trigger_when` 引用可选上游被拒。
2. **ES 数据源**（v5 §1）：`eval_axes/sources/{__init__,es_client,es_tools}.py`；`{es://<index>}` 记号在 `capability_store.validate_entry` 只校格式不连网（给 `{es://}` 单独加分支，不动 `{material://}` 分支）；`validate.py` 在 `eval_axes.es.enabled=false` 时对 `{es://}` 报错；目录条目按 `source` 分发到 material 或 es 工具；`es_outline / es_search / es_read` + `verify_quote`；配置节 `eval_axes.es.*` 与 4 个变量（`EVAL_AXES_ES_URL` 用 `required_when: eval_axes.es.enabled == true`）。`BoxBoundaryCarrier` 改走 `sources.build_tools`，material 条目原样交给旧 `build_material_tools`。单测用 stdlib `http.server` 起假 ES（`_mapping` / `_count` / `_search` / `_doc`），覆盖三个工具、回执、范围守卫、回读核验、未启用时的加载期报错。
3. **`truthfulness` 类型**（v5 §3）：三阶段 `run()`（提取断言 → 逐条核验 → 确定性汇总），每阶段输入隔离；断言逐字来自 `output_text` 且机械核验；`refuted`/`verified` 必带引用并回读核验、不过打回重试 ≤3；`errors` 非空 → failed；无断言 → `claims=[]` 且 `succeeded`。注册进 `registry.py`。单测用假 LLM + 假 ES。
4. **fulfillment 消费真实性**（v5 §3.3）：可选依赖 + 可选输入 `truth`；有值时按 §3.3 注入 `user_prompt_extras["truthfulness"]` 与一段 system extra；无值时 prompt 逐字不变（现有逐字相等测试必须继续通过，并新增"有 truth 时多且只多那两段"的测试）。
5. 全部完成后：跑 `tests/test_llm_probe_eval_axes.py`、`tests/test_config_contract.py`、`tests/test_llm_probe_text_carrier.py`、`tests/test_llm_probe.py`、`tests/test_capability_carrier.py`、`tests/test_active_artifacts.py`、`tests/test_summary_trace_column.py`、`tests/test_case_pool_export.py`；再跑全量 `tests`，把失败清单与 HEAD 上既有失败对比（已知既有失败：`test_deerflow_attribute_evidence` 6 个、`test_project_live_smoke::test_marketting_planning_live_run_smoke`、`test_schema_validator` 2 个、`test_summary_trace_column` 的 `test_output_and_reference_share_json_formatting` / `test_output_cell_renders_only_schema_shaped_item_output`、`test_config_contract::test_repository_public_config_contract_has_no_consumer_bypass`）。新增失败必须归零。
6. 在 `spec/adapter/axe-v5.md` 末尾追加「实施记录」：改了哪些文件、与设计稿的偏差及原因、测试结果。

## 不要做

- 不接真实 ES（第 5 步"接真实索引"由人来做）。
- 不做向量检索、不做场景级依赖编辑、不让轴2消费真实性轴（v5 §6）。
- 不改 `summary.html` / `live.html`（第 14 列按 items 渲染，真实性轴自动能显示；只读区显示"可选依赖"的 `materials.html` 小改可做，非必需）。

## 完成标准

上面 1–4 的单测全绿、5 的回归无新增失败、6 的记录写完。最后用一段话说明：做了什么、哪里和设计稿不一致、什么没做。
