# 评测轴任务化（axis loop）实施记录

> 更新：2026-10-21。本文持续维护实施步骤、状态、验证证据和未决事项。
> 当前阶段：§8 重构 R1–R8 完成。准确率、误放行、重跑一致持平；耗时（中位 300s vs 169s）与 token（输入中位 2.4 倍）两条门槛没过，见 `report/axis-loop-20261021/RESULT.md` R8 节。待用户定下一步。

## 1. 三类文档的分工

| 文档 | 回答的问题 | 入口 |
|---|---|---|
| 需求 | 要解决什么、要什么、不做什么、怎么验收 | [评测轴任务化需求](../../demand/axis_loop.md) |
| 方案 | 怎么分工、结构与规则 | [评测轴任务化方案](../alg/axis_loop.md) |
| 实施 | 改哪里、按什么顺序、做到哪、验证证据 | 本文 |

三者冲突时，在本文 §6 记下差异，再回对应文档修订；不在实施里偷改口径。"代码存在""离线测试通过""真实运行通过"三件事分开记录，不互相替代。

## 2. 实施约束

- **在哪里做**：本目录（`verifier`，main 分支，含 10-20 主轴改版的未提交改动）。新项目是纯新增，对 llm_probe 只改 §3.1 列出的分发点。⟡ 如果要求单独开分支或 worktree，需要在 P1 之前说。
- **实验隔离**（记忆 experiment-isolation）：工作流路线的基线在隔离副本里跑（P0），评测进行中不改它会读到的文件。`report/eval-main-axis/run_eval.py` 默认读 `verifier-integrate`，新旧对照时用 `EVAL_CODE` 指定代码目录。
- **环境**：只用 `.env` 里的 `PYTHON_EXECUTABLE`（agno 环境）。要用的 `jsonschema 4.26.0`、`mcp 1.12.4` 都已安装，**本期不加新包**。
- **不保留兼容**（AGENTS.md）：llm_probe_loop 里不带旧的 `eval_axes`；ES 直连、`verify_quote` 回读、receipts 核验直接删；`knowledge_sources.json` 改名为 `sources.json`，不写 migration。
- **不碰**：`impl/core/tool_loop` 的接口；llm_probe 的评测逻辑；其他项目。
- **提交**：等用户说了再提交。

## 3. 设计落点（对应方案）

### 3.1 新项目与分发点（方案 §2）

```text
impl/projects/llm_probe_loop/      ← cp -R impl/projects/llm_probe
  删除  eval_axes/  knowledge_loop/  process_loop/
  新增  axis_loop.py               项目接入（§3.6）
        materials.py              内置材料取值函数（§3.3）
        mcp_servers/es/           ES 包装成 MCP server（§3.5）
  改    judge.py                  _main_axis_result / ProcessJudgeExecution → 调用 axis_loop.build_report
        project.yaml              project.id = llm_probe_loop
  批量  91 处 impl.projects.llm_probe → impl.projects.llm_probe_loop（26 个文件）；3 处项目 id 字面量
impl/data/llm_probe_loop/          ← 拷贝 llm_probe 的 capability_map.json、knowledge_sources.json（改名 sources.json）
```

分发点：llm_probe 只改这些地方，行为不变。

| 文件 | 现在 | 改成 |
|---|---|---|
| `impl/server/service.py` | 12 处 `project == "llm_probe"` / `from ..projects.llm_probe.xxx` | `project in EVAL_AXES_PROJECTS`；`importlib.import_module(f"impl.projects.{project}.xxx")` |
| `impl/core/table_view.py:209-211` | 硬 import `llm_probe.business_trace.dossier`、`llm_probe.eval_axes.registry` | 按 trace 的 project_id 取模块；llm_probe_loop 提供同名接口（§3.6） |
| 前端 13 处 | `'llm_probe'` 常量 | `EVAL_AXES_PROJECTS` 数组 |

llm_probe_loop 对外提供与 llm_probe 同名的入口：`eval_axes.run_for_trace` / `build_report`，以及 `describe_axis_types`。core 的 `eval_axes.py` 按项目名找 `impl.projects.<id>.eval_axes`，所以新项目里保留一个只做转发的 `eval_axes.py`，转到 `axis_loop`。

### 3.2 `impl/core/axis_loop/` 模块（方案 §3–§7）

| 模块 | 职责 | 对应方案 |
|---|---|---|
| `definitions.py` | `AxisDef` / `SubloopDef` dataclass；读写 `axis_definitions.json`（复用 `capability_store` 的存储读写）；output 字段表 → JSON Schema；加载期校验（方案 §3.4 全部条目） | §3 |
| `materials.py` | `MaterialRegistry`（标准名 → schema、description、load）；白名单解析（`名.路径.{字段}`）；路径对 schema 的静态检查；按白名单取值、投影；呈现（标题 + 文本 / 稳定的 JSON） | §4 |
| `view.py` | `TaskView`、`CallView`；按白名单裁剪 | §7.1 |
| `checks.py` | 标准校验 `covers`、`refs_in`、`quote_in_material`、`quote_in_call`、`searched`、`from_call`；参数校验；路径求值（复用 runner 的 `_item_values` 写法） | §7.2 |
| `acceptance.py` | 验收流水线 1–5；用户代码加载与签名检查（`check(view)` / `synthesize(view)`） | §5.3 |
| `ledger.py` | 台账：状态机（未出现 / 已出现 / 已完成 / 作废 / 撤下 / 不出现）、作废的传递、触发重算、程序任务合成、推送文本、事件记录 | §5.4、§11.2 |
| `gate.py` | 工具门禁 Hook（类别、子 loop 所属轴是否已出现）；`StampCallId` 搬过来作为 post_tool | §5.1 |
| `subloop.py` | 子 loop：独立 ToolLoop + `as_tool(render=按白名单拼材料与参数)`；返回 `{text, structured}`；失败时中止父 loop | §6 |
| `context.py` | token 估算、80% 归档、`recall` 工具 | §9 |
| `loop.py` | `AxisLoop`：组装 ToolLoop（固定工具列表、hooks、completion_hook=台账、BudgetStop）；`run(case) -> LoopReport` | §1、§5、§10 |
| `report.py` | LoopReport → `build_report` 同形的 dict | §11.1 |

依赖方向：`loop → ledger / gate / subloop / acceptance / context → checks / view / materials / definitions`。不 import 任何项目代码。

### 3.3 内置材料（方案 §4.1）

`llm_probe_loop/materials.py` 登记 11 个取值函数，从 RunTrace 和 capability_map 里取：

| 标准名 | 取值来源（现有代码） |
|---|---|
| `case.user_turns` / `case.requests` / `case.deliveries` | `business_trace/expectation_material.py` 现有的按轮拆分；`judge._request_payload` |
| `case.business_status` | `core.live_protocol.business_call_failure` |
| `scenario.capability` / `criterion` / `description` / `downstream` / `process_obligations` | `load_capability_map(...)[scenario]`；description 经 `expand_material_uris` 展开 |
| `scenario.boundary` | `sources.expand_boundary` |
| `axis.note` | 场景 `axes[]` 中当前轴的 description |

业务调用失败时（`case.business_status.ok = false`），AxisLoop 不启动，照现有口径出结论（兑现 = not_fulfilled），并在 loop 记录里写明。

### 3.4 第一期的轴定义（方案 §12.1）

写进 `impl/data/llm_probe_loop/axis_definitions.json`。说明正文从现有 prompt 迁移，去掉格式话术：

| 轴 / 子 loop | 说明的来源 | 现有校验 → 新写法 |
|---|---|---|
| `expectations` | `expectations.py` 的 `SYSTEM` | 形状、id 唯一、source_refs → schema + `refs_in`；"必须引本轮用户原话""歧义组 ≥2""有要求不可空集" → `checks.py` |
| `claims` | `knowledge_loop/extract.py` 的 `EXTRACT_SYSTEM` | span 逐字 → `quote_in_material(case.deliveries)`；context 逐字、qualifies 指向、context 不夹带别条 → `checks.py` |
| `truthfulness` | `truthfulness.py` 的 `_JUDGE_SYSTEM` | verdict / gap 的 if/then → schema；basis 必须是检索得到的引文 → `from_call(search_knowledge)` + `refs_in`；轴级 verdict → `synth.py` |
| `fulfillment` | `fulfillment.py` 的 `DELIVERY_SYSTEM` | 逐条覆盖 → `covers`；claim_refs 存在 → `refs_in`；"引了被否定的说法必须判没给到""有核事实时 fulfilled 必须引 verified" → `checks.py`（即 `check_assessments`）；blocking、not_fulfilled 列表、整体状态 → `synth.py`（复用 `_derive_overall_status`） |
| └ `judge_blocking` | `fulfillment.py` 的 `BLOCKING_SYSTEM` | `covers` 全部期望 |
| `carryability` | `carryability.py` 的 `_SYSTEM` | 覆盖 → `covers`；做不了 / 做错了必须有依据 → schema if/then；依据引自责任范围 → `quote_in_material(scenario.boundary)`；依据引自知识 → `from_call(search_knowledge)`；轴级 verdict → `synth.py` |
| `main_verdict`（程序） | — | `synth.py` 调用现有的 `main_verdict()`（从 llm_probe 复制过来，不改） |
| `search_knowledge`（共享子 loop） | `knowledge_loop/loop.py` 的 `SYSTEM` | 现有 `Checklist` 全部改写为 schema + `searched` + `refs_in` + `quote_in_call`，不写代码 |

### 3.5 MCP（方案 §8）

- `core/axis_loop` 不管 MCP。MCP 客户端放在 `llm_probe_loop/sources/`，由现有 `mcp_tools.py` 改写：用官方 `mcp` SDK 的 `stdio_client` + `ClientSession`；返回统一成 `{content, structuredContent?, isError}`；对外只给 `mcp_call / mcp_read / mcp_find` 三个通用工具，各实例的工具清单作为推送文本。
- `sources.json`：`{name: {category, command, args, env, tools?, max_chars, notes}}`。场景条目新增 `sources: [{instance, params}]`，轴框里可以加 `sources: [实例名]`。
- `mcp_servers/es/server.py`：用 `mcp` SDK 的 FastMCP 暴露 `es_outline`、`es_search`、`es_read`，内部直接调用搬过来的 `es_client` + `es_tools` 逻辑，检索语义不变。现有 ES 登记迁成 `command: python -m impl.projects.llm_probe_loop.mcp_servers.es --source <名>`。

### 3.6 项目接入（方案 §2.3、§11）

`llm_probe_loop/axis_loop.py`：

```text
build_case(spec, trace) -> Case                  RunTrace + 场景 → case（含业务调用状态）
build_report(spec, trace, run_id="") -> dict     加载定义 → 校验 → AxisLoop(...).run(case) → report.py 组装
describe_axis_types() -> list                    给前端：轴定义列表（替代 registry.describe_axis_types）
```

- 模型客户端：沿用 `eval_axes/llm.py` 里 `axis_llm` 的记账和模型策略，搬到 `llm_probe_loop/llm.py`，角色名 `axis_loop`。
- trace_id、stage：`AxisLoop` 用 `LoopContext(trace_id=run_id, stage="axis_loop")`；子 loop 继承前缀（ToolLoop 的既有行为）。

## 4. 实施步骤与状态

| 步 | 内容 | 完成标准 | 状态 |
|---|---|---|---|
| P0 | 基线：在隔离副本里，用 llm_probe 的工作流路线在 dev 43 条上跑 3 次，记录一致率、误放行、重跑一致率、token、耗时 | `report/axis-loop-20261021/baseline/` 下有结果 + RESULT.md；可以复算 | 完成：128/129 成功，一致 89.8%、误放行 9/65、三次一致 41/42、耗时中位 169s |
| P1 | 新项目骨架：复制、改名、拷数据、分发点（§3.1） | llm_probe_loop 能被 project_loader 加载；llm_probe 的现有测试全部通过；其他项目测试不受影响 | 完成 |
| P2 | 定义与材料：`definitions.py`、`materials.py`、加载期校验 | 单测：方案 §3.4 每个报错条目各有一个反例；白名单投影与路径检查 | 完成 |
| P3 | 视图、标准校验、验收流水线 | 单测：每个标准校验正反例；流水线 1–5；合成出错时中止；同一视图连续跑两次结果相同 | 完成 |
| P4 | 台账、门禁、子 loop、AxisLoop 组装 | 用脚本化的 StepClient 跑通：出现 / 作废传递 / 撤下 / 程序任务重算 / 门禁拒绝 / 子 loop 隔离（消息里不出现交付）/ 子 loop 失败即中止 / completion | 完成 |
| P5 | MCP：SDK 客户端、`isError`、ES MCP server、`sources.json` | 单测：ES server 与旧 `es_tools` 在同一组查询上返回逐字一致（用录下来的查询）；MCP 翻页、搜索 | 完成 |
| P6 | 项目接入 + 第一期 6 个轴和 2 个子 loop 的定义、checks、synth（§3.4） | 离线：报告与 `build_report` 同形；`main_verdict` 在同一组合成结果上与 llm_probe 一致；防污染测试（方案 §13） | 完成（carryability 未定义，见 §6.16） |
| P7 | 真实运行：单条 case 跑通；然后 dev 43 条 × 3 次 | 指标按需求 §9 与 P0 对比，写 RESULT.md；判错 case 能从 events 里定位 | 完成：dev 128/129 成功，见 RESULT.md |
| P8 | 调优：只在 dev 上调，直到过硬门槛 | 硬门槛全部满足；每次调整都记录在 §5 | 未开始 |
| P9 | holdout 19 条跑一次 | 结果写进 RESULT.md，不再回头调 | 未开始 |
| P10a | 页面第一步（方案 §2.4）：轴类型接口同形、信息源页登记 / 测试 trace 源、场景页选 trace 源 + 绑定、"添加全部轴"、新实例拷出厂数据 | 新开端口、空实例：只用页面登记 agno 源、建场景、选轴，live 页统一全链路真调业务 18066 跑出结论，trace 采到；Playwright 脚本可复跑；llm_probe 页面行为不变 | 完成（10-27，见 §9.1 "P10a"）；live 页单条看不到各轴明细、分两步跑拿不到 trace 两项待定 |
| P10b | 场景对轴的描述（方案 §2.5）：① `expectation_material.project_requirements` 去掉 criterion 一项，`Case.requirements()` 不再读 `notes["expectations"]`；需求轴分发脚本（`axis_code/loops/expectations/dispatch.py`）注释不再提判准；② `axis_definitions.json`：需求轴说明里讲"场景判准（component=criterion）"的段落改讲本轴描述，兑现轴说明加"本轴描述与期望一起判，不替代期望"，6 个本应轴白名单删 `scenario.process_obligations`、说明里过程职责改指本轴描述；③ `materials.py` 删 `scenario.boundary`、`scenario.process_obligations`；④ `eval_axes/validate.py` 场景带 `process_obligations` 报错（`boundary` 随承载性迁入再加）；⑤ `eval_axes/registry.py` 的 `scenario_fields` 改成"非程序执行的轴都给"，删 `uses_sources` 判断；⑥ `materials.html` 删过程职责输入框及读写；⑦ 仓库样例 `insurance-agno-e2e` 的 `process_obligations` 迁进 `planning_routing_expected` 的框；⑧ 单测：`test_llm_probe_loop_project.py` 分发用例去掉 `scenario.criterion`，加"需求侧材料里没有判准""带 process_obligations 保存报错""描述框按执行者给"三条；`test_axis_loop_core.py` 里的 `scenario.criterion` 是框架单测的假材料名，不动 | 单测与全量回归（已知失败清单之外不新增）；8036 页面新建场景：18 个模型执行的轴都有描述框、主轴结论没有、没有过程职责输入框；一条 case 的事件记录里，需求轴各份任务文本含【axis.note】且只一次、材料里没有 criterion | 完成（10-27，见 §9.1 "P10b"） |
| P10c | 承载性（方案 §12.3）：① `axis_definitions.json` 加轴 `carryability`（loop `carryability` ready、依赖 expectations / fulfillment 硬、`trigger: {axis: fulfillment, verdict_in: [not_fulfilled]}`、材料 `result.fulfillment.not_fulfilled[]` 与 `result.expectations.expectations[].{expectation_id, about, condition}`、工具 `search_knowledge`、`submit: per_item`、`item_key: expectation_id`、输出逐条 `{expectation_id, carry, reason, basis[{ref, quote}], gap_kind, missing_material}` + 程序填的 `verdict` / `placements[]`；说明取旧 `_SYSTEM`，依据改指本轴描述、删"背景"段）；加 loop `carryability`；`main_verdict` 依赖加 carryability（软）、材料加 `result.carryability.placements[].{expectation_id, placement}`；② `axis_code/carryability/checks.py`：`basis.ref` 只能是 `axis.note`（quote 逐字在本轴描述里）或本轴的 `search_knowledge` call_id（那次取证有这一条且非 not_found、quote 逐字在返回里），yes / no 至少一条 basis，undecidable 时 gap_kind / missing_material 必填、basis 为空；收尾 `covers` not_fulfilled；`synth.py`：carry → placement，整体 verdict 按条（同旧轴 `item_path`）；③ 框架：`TaskView.materials` 现在只含白名单里的材料，校验代码看不到本轴描述（10-27 查，`impl/core/axis_loop/loop.py:236`）；`view()` 照任务文本的做法补上 `axis.note`（`loop.py:305`），对齐需求 §3.6.4"校验、合成、分发代码读的范围与所属的轴相同"；③b 框架：轴定义加 `optional_tools`（`definitions.py`）；`check_scenario` 只对必需工具报缺信息源；`AxisLoop.withheld` 记下缺必需信息源的可选工具，不提供、任务文本写明不可用（方案 §6.3）；承载性 `optional_tools: [search_knowledge]`；④ `eval_axes/validate.py` 场景带 `boundary` 报错；⑤ 单测：checks 正反例（引框内原文过、引框外文字拒、引 not_found 那次拒、yes 无 basis 拒）、synth 映射、`main_verdict` 读到做不了 / 做错了；"带 boundary 报错"；类型接口里 carryability 有描述框 | 单测与全量回归（已知失败清单外不新增）；8036 上一条没做成的 case，场景开承载性、框里写一条与之相关的责任范围，真跑：承载性出现、逐条有 placement、引用回读通过，主轴结论按 placement 合成；兑现做成时承载性不出现 | 完成（10-27，见 §9.1 "P10c"）；依据回读只在单测里验过，真实 case 待接知识源时验 |
| P10 | 页面：轴定义页（配置表单、说明、上传代码）；场景页轴框选实例；信息源页通用化 | 用页面新建一个测试轴，不改代码就能跑出结果（需求 §6 的验收） | 未开始 |
| P11 | 判胜负，删输的那一方：项目目录、`EVAL_AXES_PROJECTS` 里的那一项、前端里的那一项 | 用户拍板 | 未开始 |

- P10 放在 P7–P9 之后：先用手写的 `axis_definitions.json` 跑通端到端，再上页面（AGENTS.md："先跑通最小端到端"）。页面编辑的是同一份存储，不会出现两套定义。
- 每一步结束都更新本表和 §5。

## 5. 验证证据

- **P1**：`llm_probe_loop` 能被 project_loader 加载；全量测试 2017 passed / 27 failed，其中 26 个失败与本次改动无关（工作区原有未提交改动与测试不一致：需求材料改成 `{query}`、`build_tools` 加了 `recorder` 等），1 个（`test_project_config_contract` 写死项目列表）已随新项目更新，通过。
- **P2–P4**：`tests/test_axis_loop_core.py`（26）、`tests/test_axis_loop_run.py`（10）全部通过：定义加载期报错逐条反例、路径与投影、标准校验正反例、验收流水线、出现 / 作废 / 撤下 / 程序任务 / 门禁 / 子 loop 隔离（子 loop 消息里不出现交付）/ 子 loop 失败即整案失败 / 合成出错即失败 / 上下文归档与超限失败。
- **P5**：`tests/test_llm_probe_loop_es_mcp.py`（3）通过：ES 经本地 MCP server 的检索、回读结果与直连 `EsTools` 逐字一致；报错带 `isError`；未选用的索引被拒。
- **P6**：轴定义存储 `impl/data/llm_probe_loop/axis_definitions.json` 加载期校验无报错（曾查出 truthfulness 的 claims 缺元素 schema，已补）；llm_probe_loop 全部模块可导入。
- **P7 dev**：`report/axis-loop-20261021/RESULT.md`。127 次配对：一致 115 vs 基线 114，误放行 9/64 vs 9/64，三次一致 42/42 vs 41/42；耗时中位 330s vs 168s，请求均值 22.2 vs 20.3；token 未测。
- **P7 单条**：`F-annual-ok`（hr-handbook-qa，gold=fulfilled）→ 五个轴全部完成，兑现 fulfilled，主轴「做成了」；153 s、16 次模型请求、16 次工具调用；`claims` 出现前主上下文里没有交付文本；兑现第一次提交被拒（"有核事实结果时，fulfilled 必须引用至少一条 verified 的 claim"），改后接受。同一条在工作流路线冒烟耗时 99.7 s。

## 6. 与方案 / 需求的差异

待回方案文档修订的（标 ★ 的是新增机制，需用户确认）：

1. **复制时先连 eval_axes 一起复制**，P6 再删 adapters/runner/types/knowledge_loop/process_loop：非评测模块（need_judge、capability、judge）引用了它们，先保证 P1 能加载。现已删净。
2. **table_view 按 trace.project_id 动态取模块**（`impl.projects.<id>.business_trace.dossier` / `.eval_axes.registry`），llm_probe 不改；llm_probe_loop 的 `eval_axes/registry.py` 提供同名 `AXIS_TYPES`。
3. **main 目录 `.env` 有两行过时变量**（`EVAL_AXES_ES_ENABLED/URL`，verifier-integrate 早已删），导致配置加载直接报错、测试跑不起来；已按 integrate 删掉，备份 `.env.bak-axisloop-*`。
4. **知识路由**要求仓库根目录 `projects/<id>/project.yaml`，已为 llm_probe_loop 加一份（复制 llm_probe 的、改 id）。
5. **视图里的材料按标准名给完整值**（方案 §7.1 写的是按白名单条目）：投影只决定放进上下文给模型看多少；代码不是模型，给完整值不构成污染，且 `of` 路径可直接写 `<标准名>.<路径>`。
6. ★ **带参数的内置材料**：材料可声明参数（如 `case.turn_requirements` 的 `turn`），只有参数里含这些名字的子 loop 能读，加载期检查。起因：需求按轮写、每轮看不到后面的轮（spec/alg/expectations.md §2.1；后一轮常是对上一轮交付的反应，等于漏交付），这是"任务里一部分不能看"，按需求 §3.2.3 要用子 loop，而子 loop 要按轮取材料。
7. ★ **需求轴 = 主 loop 里的编排任务 + 每轮一个子 loop `turn_expectations`**：主任务只看 `case.turns`（轮次编号，不含原话），对每一轮调一次子 loop，期望由程序从调用结果里取（全部程序填）。
8. **合成程序只返回程序填的字段**，由程序合并进模型填的部分（方案 §5.3 写的是返回完整结果）：模型填的字段不让代码改。
9. **分条交时同一分项再交是替换**（方案 §5.3 写的是重复交被拒）：改错只重交那一条；替换后收尾要重交。
10. **标准校验加 `on: item | final`**，分条交时逐项校验与收尾校验分开声明；**定义加 `item_key`**（分项编号写进哪个字段）。
11. **信息源工具按实例暴露**（`<实例>__<工具>`，现有 MCP 工具名与 schema 原样），不用通用 `mcp_call(source, tool, args)`：工具列表仍是一开始就固定（场景选用的实例在 loop 开始前已知），模型还能拿到每个工具真实的参数说明。MCP 客户端沿用项目已有的 fastmcp；ES 的本地 MCP server 用官方 `mcp` SDK 的 FastMCP。
12. **知识源登记没有改名为 `sources.json`**，ES 条目仍是 `type: es`（连接信息），由评测器自动拉起本地 ES MCP server 访问；场景选用沿用轴框描述里的 `{es://…}`、`{mcp://…}`、`{material://…}` 引用，不加新的 `sources` 字段（页面现成支持）。
13. **归档策略**：接近上限时归档最早的工具返回（最近一批除外），不按"已完成任务"挑：工具调用不归属任务。
14. **ES 字段骨架**（scenario.knowledge 材料）经 ES 的 MCP server 取，不直连。
15. **预算是模块常量**（`eval_axes/__init__.py: SETTINGS`），还没进配置。
16. **承载性没有定义进第一期存储**：评测集场景都没开承载性（工作流基线也不跑它），先不迁；主轴结论对承载性是软依赖，没开照常出结论。
17. **业务 trace 场景**：llm_probe_loop 的判官不接过程六轴（第二期），`requires_business_trace` 全为 False。
18. **需求轴的判准**取场景里需求轴框的描述；场景预设迁移时把原兑现框描述（场景判准原文）填进需求轴框，同现方案"兑现自推期望"读的材料一致。说法只抽最后一轮交付（`case.final_output`），同现方案。

## 7. 未决事项

- ⟡ 在本目录做，还是单独开分支或 worktree（§2）。
- ⟡ 必须隔离的子 loop 不给参数够不够用：P7 试运行后定（方案 §15）。
- ⟡ 预算系数与上下文上限的初值：P4 先取现有各轴 `ExecutionLimits` 的总和，P7 后回填。
- 风险：单 case 一个 loop，所有轴在一个上下文里，可能比现方案更不稳定（记忆 langfuse-provider：主判官重跑不稳）。P7 的重跑一致率是第一道关。

## 8. 重构计划（2026-10-22 grill 定，需求 / 方案已同步修订）

起因（`report/axis-loop-20261021/RESULT.md` 补充一节与查因记录）：去掉端点故障后仍约 2 倍耗时。主要是真实性取证结果（每 case 12–21 万字证据原文）回到主 loop 公共上下文、之后每轮都带着；其次是固定编排开销（需求、blocking 要主 loop 模型调度）。

| 步 | 内容 | 完成标准 | 状态 |
|---|---|---|---|
| R1 | 框架：`run_mode: isolated`（台账启动独立子 loop，结果即轴结果，作废重跑）；去掉"轴自带子 loop" | 单测：出现即自动跑、结果写入、上游改动重跑、失败即整案失败、主 loop 看不到其过程 | 完成 |
| R2 | 框架：`dispatch.py` 插口 + 白名单元素筛选 `[字段=值,…]` + `view.parts`；撤掉带参数的内置材料 | 单测：分发多份、每份只见自己的选择、选择越界即失败、合并走 synth | 完成 |
| R3 | 框架：公共 loop 工具（`shared_tools`，原 `shared_subloops`），独立运行的轴里可调一层；子 loop 开归档 | 单测：嵌套一层可用、两层被拒、归档在子 loop 生效 | 完成 |
| R4 | 框架：预算进全局运行配置 `axis_loop.*`；loop 失败时各轴不留半截输出（A1） | 配置可改、测试覆盖 | 完成 |
| R5 | 项目：`case.requirements` 内置材料（不带参数）；删 `case.turns` / `case.turn_requirements`；返回命中场景预先维护的错误码 → 运行失败（不启动 loop），没命中的照常进 loop，没配错误码就不判失败；`role` 进定义；信息源类别按登记判断；删 `requires_business_trace` | 单测 + 加载期校验 | 完成 |
| R6 | 配置：需求（isolated + dispatch 按轮）、blocking 独立成轴、真实性（isolated + search_knowledge，可补查）、兑现读 `result.blocking`；迁移场景预设 | 加载期校验无报错；防污染测试（§13 方案） | 完成 |
| R7 | 检视 C1–C5 收尾（重复逻辑、私有调用、死代码、知识源目录建两次） | 全部测试通过 | 完成 |
| R8 | 重测：调大上下文记录保留上限，两条路线各 dev 1 轮测 token 与耗时；loop 再跑 dev × 3 看一致率与稳定性 | RESULT.md 新增一节 | 完成：准确率、误放行、稳定性持平；耗时中位 300s vs 169s、输入 token 中位 2.4 倍，两条门槛没过（RESULT.md R8 节） |

R1–R7 验证：`tests/test_axis_loop_core.py`（31）、`tests/test_axis_loop_run.py`（9：分发每份只见自己那一轮、blocking 看不到交付、取证原文只在真实性子 loop 里、主 loop 只推 main 轴、独立运行失败即整案失败、分发选择越界即失败、上游修改让独立运行的下游自动重跑、合成出错即失败、上下文超限）、`tests/test_llm_probe_loop_project.py`（6：定义加载、可见性、按轮分发、硬依赖、错误码只认登记的）、ES MCP（3）、项目契约（27），共 75 passed。真实单条 `F-annual-ok`：结论对，14 次请求（重构前 16），主 loop 上下文合计 7.5k 字（只有说法抽取与兑现两个任务）。
实现细节：预算键名用现有 `eval_axes` 节下的 `loop_*`；分发出去的每份子 loop 只交模型填的字段、不合成，各份收齐后由轴的 synth 一次合成完整结果；事件里 `subloop` 是一次子 loop 运行，`isolated` 是这个轴完成。

§6 偏差中已回填进方案的：5（视图材料按标准名）、10（`on` / `item_key`）、11（工具按信息源暴露）、12（沿用登记与引用写法）、15（预算进配置）、17（trace 第二期）；被这次重构取代的：6、7（带参数材料、需求轴编排）。

## 9. 第二期：trace 与过程六轴（2026-10-25 起）

依据：需求 `demand/axis_loop.md`、`main_axis.md`、`expectations.md`、`process_axes.md`、`claims.md`、`information_sources.md`（2026-10-25 修订，记录 `demand/draft-20261025/README.md`）；方案 `spec/alg/axis_loop.md` §3.3、§4.4、§6、§8、§12.2，`spec/alg/fulfilled.md` §2.1，`spec/alg/expectations.md` §2.2。llm_probe（8031 那条路线）不动。

| 步 | 内容 | 完成标准 | 状态 |
|---|---|---|---|
| S1 | 框架：loop 定义。轴定义存储改为 `axes` + `loops`；轴字段 `loop` 取代 `run_mode`；`loops[].start` = case / ready / tool；`dispatch.py` 挂到 loop；`shared_tools` 并进 `loops`（`start: tool`）；台账按\"它等的任务全齐\"一个一个起 loop、被改则整个作废重起；加载期校验（loop 图无环、恰一个 case loop、tool loop 不放轴等）。第一期定义迁移 | 第一期 75 条测试改写后全过；新增：loop 图成环报错、全齐才起、上游改动整个 loop 重起、跨 loop 读结果；`F-annual-ok` 真实单条结论不变 | 完成 |
| S2 | 框架：大材料。`eval_axes.loop_material_inline_chars`；超限材料推送只放目录；内置工具 `read_material`（按编号、结构图下钻、full）、`search_material`（关键词）；读取范围 = 本 loop 已出现任务白名单合集；读回的正文按 §9 归档 | 单测：白名单没选的字段读不到；结构图下钻；搜索命中只返回范围内的；归档后 recall 可读 | 完成 |
| S3 | 框架：信息源。登记可选 `check_tool`，loop 起前对必需实例调一次，`isError` → 运行失败，工具不暴露给模型；内置材料取不到 → 运行失败；轴与信息源对不上：跑不了报错、会系统性不确定的写 `warnings` | 单测：检查报错即失败；检查工具不在工具列表；取值函数报取不到即失败；四种对不上各一例 | 完成 |
| S4 | trace 进 case。trace 源 MCP 服务 `mcp_servers/trace_agno/`、`trace_langfuse/`（包现有 provider 的采集，提供采集工具）；`knowledge_sources.json` 加 `type: agno / langfuse` 登记；场景 `business_trace: {source, bindings}`；live 在\"有启用任务的白名单选了 `case.trace`\"时调采集工具存档；内置材料 `case.trace`（`build_dossier` + `build_links`，目录带轮次与顺序） | 对 verify33 的 22 条存档：`case.trace` 的目录与环节表和现方案案卷一致；MCP 采集与直连 provider 在 18066 上同一轮取回逐字一致；采集失败 / 缺整轮 → 运行失败 | 完成（真实一轮的对照待业务系统恢复） |
| S5 | 过程轴定义。`trace_analysis`（说明取自现有整理员提示词，去掉行动路线与覆盖说明；checks；synth 出 links / leads / views / why）；6 个 `<轴>_expected`（分析轴，loop `process_expected`）；6 个 `<轴>`（loop `process`）；说明取自各轴 adapter 的子能力、本轴不判、通用职责与现有本应 / 实际任务文本；checks / synth 搬现有 `check_actual`、`settle`、`aggregate`、`issues_of` | 加载期校验无报错；防污染测试：`process_expected` 的请求里没有输出端字段、读工具读不到输出端；侦探引用编号都读过 | 完成 |
| S6 | 主轴证据组。需求轴每条加 `needs`（说明 + checks）；兑现模型只填 `delivered` / 引用，`process_refs` 与检查，synth 按证据组派生 status / 档位 / 缺的组；`main_verdict` 组成带档位；判官没开兑现 → 运行失败（删单次判官退路） | 单测：证据组各分支（空、无可用组、知识过 / 不过 / 判不了、trace 过 / 不过 / 判不了、两组都配时蒙对与被证伪）；本应标了本条的过程条目漏引被拒 | 完成 |
| S7 | 场景配置（llm_probe_loop 实例）：verify-insurance-agno / langfuse 开主轴各轴 + 侦探 + 12 个过程轴、选 trace 源；轮一不选知识源，轮二选 `insurance-tools` 并开核事实；mcp 场景补 `needs` 生效后的回归 | 加载无报错；警告符合 S3 | 未开始 |
| S8 | 验收：22 条 × 两轮，对照现方案（verify33 `new.jsonl` 的 llm_probe 路线结果）比主结论命中 / 误放行、六轴轴级值逐轴、调用 / token / 耗时；dev 43 条回归；gold 按新口径重核并列出变化给用户 | `report/axis-loop-phase2/RESULT.md`；gold 变化清单经用户核 | 未开始 |

- 每步结束更新本表与 §5；与方案的偏差记到 §6。
- 实验在隔离副本上跑（记忆 experiment-isolation），不碰正在跑的东西。

### 9.1 验证与偏差

- **S1（10-25）**：`tests/test_axis_loop_core.py`、`test_axis_loop_run.py`、`test_llm_probe_loop_project.py`、ES MCP、项目契约共 79 passed（新增：dispatch 挂 loop 时成员要有 synth、存储形状报错、ready loop 卡死两种情况报错与 case 往返不报）。真实单条 `F-annual-ok`（实例 inst-f105511930554648）：结论 fulfilled / 做成了，13 次请求（R8 后 14），176 s。两个实例的旧定义备份在 scratchpad `loop-instance-bak-20261025`、`loop-evalinst-bak-20261025`。
- 偏差 1：方案 §3.4 原写"loop 当节点无环"，第一期配置本身就有 case → 核事实 → case 的往返（说法抽取 → 核事实 → 兑现），不会卡死却会被判成环。改为只拦真会卡死的两种（ready loop 互相等；等的任务又依赖本 loop 的任务），方案与需求措辞已同步。
- 偏差 2：ready loop 用与 case loop 同一份 system（方案 §6.1），不再用第一期子 loop 的"独立上下文完成一件任务"那段；首条 user 是 case 头，任务靠推送进来。
- 报告新增 `loops`：每个 ready loop 一条（id、status、reason、调用、耗时）。
- **S2（10-25）**：`impl/core/axis_loop/reader.py`（`summarize`、`Reader.read` / `search`）；推送时超过 `eval_axes.loop_material_inline_chars`（缺省 20000）的材料只放目录或预览；每个 loop 固定带 `read_material`、`search_material`，能读的范围 = 本 loop 已出现任务白名单条目的合集（取值已按白名单投影）。测试 80 passed（新增：目录 / 预览、按编号取、结构图与下钻、搜索只给编号与片段、白名单只选输入端时读不到输出端）。
- 偏差 3：方案写"材料声明哪个字段是目录"；实现改为按形状认：`{catalog?, records: [{id…}]}`、一列带 id 的记录、或只含一个记录库的列表（按白名单投影后常是后两种），没有 catalog 时目录就是编号列表。不需要在注册表里另加声明。
- **S3（10-25）**：`Sources.check(instance)`（可选）；`AxisLoop.check_sources` 在 case loop 起前、每个 ready loop 起前，对本 loop 轴（及它们选用的被调用 loop）声明为必需的实例各查一次，报错即运行失败；`preflight` 起任何 loop 前先取一遍内置材料，取值函数抛 `MaterialUnavailable` 即运行失败、0 次模型调用；`scenario_warnings`（场景选了某类信息源而没有启用的轴用它）进报告 `warnings`，选用看全部框（含没启用的）。项目侧：MCP 登记加 `check_tool`（不许同时列在 `tools` 里，不暴露给模型），`ProbeSources.check` 调它。测试 87 passed。
- 偏差 4：方案 §12.2.3 写的警告对象是"选了知识源没开核事实、选了 trace 源没开过程轴"；实现成通用规则"选了某类信息源、没有启用的轴声明用这一类"，覆盖这两种，不点名轴。
- **S4（10-25）**：trace 源 MCP server `impl/projects/llm_probe_loop/mcp_servers/trace/`（工具 `collect`：登记的连接 + 场景绑定 → provider 原样快照；采集失败也是一份 status=failed 的快照）；`business_trace/__init__.py` 改为 `validate_selection` / `collect`（经 MCP）/ `open_reader`，删掉旧信封的 `validate_business_trace` / `prepare` 与 live 里的关联头（agno、langfuse 都不需要 prepare；llmtracing 不在第二期）；登记加 `type: agno / langfuse`（`config` 不含 bindings）；场景写 `business_trace: {source, bindings}`（core 的 `validate_entry` 认两种写法：llm_probe 的 `{provider, config}`、llm_probe_loop 的 `{source, bindings}`，分出胜负后删输的那种）；采集条件改为"启用的轴白名单读 case.trace"；内置材料 `case.trace`（`build_dossier` + `build_links` + `build_catalog`，记录正文同 `record_body`；整轮采集失败或无记录 → `MaterialUnavailable`）。
  - 22 条冻结 trace 全部建得出 `case.trace`，环节数与 llm_probe 现码逐条一致；目录 6.8k–36k 字，展开正文 5 万–340 万字。
  - MCP 采集 vs 直连 provider：业务系统 18066 已停、启动脚本已被清（/private/tmp），只验了失败路径：两边快照除 captured_at 外完全一致（含错误文本）。真实一轮的对照待业务系统恢复。
  - eval 实例登记新增 `agno-insurance`、`langfuse-local`（取自原场景配置，去掉 bindings），原登记备份在 scratchpad。
  - 全量测试：2080 passed / 27 failed；27 条在干净 HEAD 工作树上 26 条同样失败，余下 1 条是计时测试 flaky（当前树重跑 3 次 1 败 2 过，tool_loop 未改）。
  - 未做：资料管理页的场景 trace 配置还是旧写法的表单（页面属 P10），llm_probe_loop 场景先改 JSON。
- **S5（10-25）**：`impl/projects/llm_probe_loop/process_axes.py` 收现方案的程序部分（`merge_suspects`、表外环节并入、`input_view`、引文核对、`check_actual`、锁"必须独立查证"、轴级五值与组成、问题记录、通用职责按轮取值），12 + 1 个轴的 `checks.py` / `synth.py` 只调它；`case.trace` 加 `dossier`、`program_suspects`；新内置材料 `scenario.process_obligations`；轴定义 13 个（侦探 1、本应 6、实际 6）由脚本从现方案的轴说明、子能力、通用职责与本应 / 实际任务文本生成进 `axis_definitions.json`（去掉"批次""same_as"等字样，加读工具用法）。加载期校验无报错。`tests/test_llm_probe_loop_process.py`（3，真实存档 + 脚本模型）：侦探 → 本应 → 实际跑通、六轴 sound；逐轴防污染（本轴输出端正文不出现在本轴本应上下文、出现在实际上下文）；没达到无引文被拒；本应引用不存在的期望编号被拒。
- 偏差 5（需用户知悉）：原定"6 个本应共用一个 process_expected loop"会互相看到输出（一个轴的输出是另一个轴的输入），防污染测试在真实存档上抓到；改为本应各自一个 loop，实际仍共用 `process`。框架不改，只改配置。
- 偏差 6：12 个过程轴插口不自包含，都 import 项目模块 `process_axes.py`（第一期插口都是自包含的）。同一段判法给 6 个轴用，抄 6 份更糟；插口仍只做"读视图 → 算 → 返回"，确定性、不调模型。
- 测试夹具 `tests/fixtures/loop_trace_case.json`（41KB）是 verify-insurance-agno neg-unknown 那一轮的真实存档（含被测系统的提示词与工具返回，测试身份数据）。
- **S6（10-25）**：需求轴每条期望加 `needs`（说明 + 校验组内 / 组间不重复）；新内置材料 `scenario.evidence`（选了知识源 / 选了 trace 源）；兑现模型改交 `delivered`（给了 / 没给 / 交付不可读）、`claim_refs`、`process_refs`（`<轴>.<条目id>`），软依赖 6 个实际轴；`checks.py` 要求本应 `expectations` 写了这条的过程条目全部引上；`synth.py` 按 `spec/alg/fulfilled.md` §2.1 派生每条 status、`evidence_tier`、`missing_evidence`；`main_verdict` 组成带档位与缺的组；llm_probe_loop 判官没开兑现 → 运行失败，删掉退回单次判官。测试 101 passed（新增证据组 5 条：只凭交付 / 缺证、只有知识、只有 trace、两样都配两样都要过、过程条目漏引被拒）。真实单条 `F-annual-ok`：做成了，两条期望分别是 knowledge 档（c1）与 delivery 档（"只回答天数"），12 次请求，188 s。
- **卡死检查改为等待图（10-25 用户定）**：S1 时换上的"两条卡死规则"漏掉了经过 case loop 的链（A 等 X、X 要 B 里的 Y、B 等 Z、Z 要 A 里的 a），已用反例验证漏报。改为一张图查圈：任务当节点，边 = 任务的依赖 + ready loop 等齐才起带来的被迫等；取代"依赖成环"与两条规则。运行时兜底：loop 无可交任务、起不了别的 loop、仍有任务未完成 → 当场运行失败，写明谁在等谁。测试 100 passed（反例、case 来回不误报、运行时卡住即失败）。
- **S8 第一轮暴露的 bug：锁"必须独立查证"锁错方向（10-25 修）**：本应标"必须独立查证"的条目，程序原把达到、没达到一律锁成无法核，实际轴提示词也叫模型照写无法核；trace 里看得到工具把对象查回来了，也被判核不了，再经兑现 trace 组拖成"不确定"（第一轮 13 条不确定都引了这样的 knowledge_data 条目）。这个标记的本意（`spec/alg/process-axes.md` §2 第一步第 3 点）是 trace 证明不了"没做是错的"，改为只把没达到锁成无法核，达到照留；6 个实际轴提示词同步、两个实例已同步。llm_probe 现码（`adapters/process_expected.py`）是同一个锁，没改。agno-bizno 重跑：knowledge_data E1 达到，兑现 trace 档，做成了（686 s）。
- **第一轮重跑 r1b-t（10-25）**：命中 gold 15/18（修锁前 6/18，基线 17/18）。langfuse-G01 不确定：langfuse 埋点把工具返回记在子步骤 `backend.policy.detail` 上，工具步骤本身空；侦探找到了它，但按环节类型只分给了 tool_execution，knowledge_data 看不到 → 无法核。改：侦探每条发现交 `axes`（可能用得上的轴，多选偏召回），程序并上环节类型对应的轴（`merge_suspects`）。
- **读材料太慢（agno-F01 超时，10-25 查）**：0 次打回，时间全在一步一步读材料（侦探 38 步、本应·模型能力 11 步没写完）。原因：单次读取上限 8000 字（推送是 2 万），刚超一点就只给结构图要再读；被测系统每次调模型的请求带着完整累积对话，同一段系统提示词、工具返回在多条记录里反复出现；提示词没教一次取齐。改（用户定，本应 loop 仍排队）：读取上限统一用 `loop_material_inline_chars`；读工具按 loop 记住已给过的长段，别的记录里再出现只给指向；SYSTEM 规则 8 加"一次取齐"与指向的读法。
- **实际逐条加"不适用"（10-25 用户定）**：agno / langfuse 伏云平两条走直达工具没调大模型，模型能力的本应（"模型输出不得编造"）只能判无法核，把兑现拖成不确定。实际轴结果加"不适用"：须引原文说明实际走的路（`check_actual`），程序移出逐条结果、列进组成 `not_applicable`、引文全丢降无法核（`actual_result`）；兑现、主轴不动（兑现只读逐条结果）。轴级五值不变。
- **伏云平 / F01 复测（10-25）**：agno 伏云平做成了（本应只写 1 条、判达到，没用到不适用）；langfuse 伏云平仍不确定——没调模型，模型能力的材料里一条记录都没有，拿不出"实际走了哪条路"的原文，只能判无法核。改：侦探提示词加"某类环节这次没出现时，说明实际路径的记录也分给那类轴"。F01：侦探 38 → 21 步，本应·模型能力写完了（24 步），仍在实际阶段超时；慢在模型调用记录 3.8–4.3 万字超限只给结构图，按消息一条条下钻。改（用户定）：读工具超限时长段换预览（开头 + 字数 + 读全文的 path），其余照给全文。
- **隐性期望 + blocking 待定（10-25 用户定）**：需求轴提示词每轮加 `t<n>.implicit_correct`"回答里的事实都对、不误导"；blocking 输出 true / false / null（null = 挡不挡看这次错成什么样）；`main_verdict.py` 删掉"claim refuted → 没做成""claim 核实不了 → 不确定"两条，blocking 为 null 的期望不决定结论、没达到列进 `pending_unmet` 并写进 basis；兑现不动。验收脚本 compare.py：有 pending_unmet 时做成 / 没做成都算命中。
- **统一重跑 r1c-t（10-26）**：22 条全跑完，命中 gold 17/18（r1b-t 16/18，基线 18/18）；平均 850s / 条，LLM 调用平均 36.6 次（r1b-t 49.2）。langfuse-G01 修好（做成了）；agno-F01 仍超时（1522s，本应六个 loop 串行合计约 650s、侦探 363s、实际 463s 时没写完模型能力）。查出两个 bug，已修：
  - 侦探点名给某轴、但挂在别轴环节上的记录，只进了该轴的 `leads`，没进它的实际材料（`material_view` 只收本轴环节上的可疑记录）——伏云平两条模型能力轴材料仍是 0 条，判不出"不适用"。`process_axes.analysis_result` 把这类记录作 `extra_refs` 放进本轴 `full`；`input`（本应材料）不变。
  - 隐性期望提示词写了 `t<轮次>.implicit_correct`，模型照着给所有期望都加了 `t1.` 前缀，`expectations/synth.py` 再加一次轮次 → `t1.t1.…`。提示词改为只写 `implicit_correct`、不要自己加轮次前缀。
- **本应分组同做（10-26 用户定，`spec/alg/axis_loop.md` §6.2、§12.2.2）**：六个 `process_expected_<轴>` loop 合成一个 `process_expected`，挂 `axis_code/loops/process_expected/dispatch.py`。
  - 框架（`loop.py`）：分发的一份可写 `tasks`（按先后）、`materials` 可省；`_plan` 校验（任务属于本 loop、不重复、每个任务至少在一份里）；排在前面的任务作为后面任务的依赖（复用台账的"依赖齐了才出现"）；`_LoopGate._submit` 加锁（后一个已出现就拒）；分发视图 `params.tasks` = 本 loop 启用的任务。
  - 侦探合成（`process_axes.feeds`）：`from` 轴的输出端 `(ref, field)`（field 为空即整条）出现在 `to` 轴本应材料的记录字段里。
  - `dispatch.py`：穷举分法取组数最少、每组无环，组内拓扑序。六个 `_expected/synth.py` 改为从 `view.parts` 取 `expected`、`not_covered`。
  - 测试：按先后出现 + 锁 + 另一份另一个上下文（`test_axis_loop_run.py`）；每个任务交之前的请求里没有本轴输出端正文（反序分发时会被抓到，已验）；分组算法（成环拆开、组内先后）。80 passed。
- **试跑 r1d-t（F01、B02，10-26）**：F01 跑完了（1275s、61 次，之前超时）；B02 本应 26→19 次、476→337s，分 2 组。F01 的 feeds 是满的 30 条，六个轴各自一组，本应没省（33→28 次是波动）。顺着 F01 查出**隔离漏洞（S5 起就有）**：侦探补的表外环节端点不写字段（整条记录），`input_view` 只摘字段名对得上的输出端，整条记录原样留在本应材料里——r1c-t / r1d-t 共 23 份报告里 16 份有，例：langfuse-D16 意图轴的本应看得到 `turn1.delivered_output`。已修：端点不写字段按整条处理（输出端整条摘掉，同时是本轴输入端的照给）；补测试。
- **统一重跑 r1f-t / r2f-tk（10-26）**：只 trace 命中 gold 18/18，平均 747s、32.9 次（本应阶段合计 8082→5873s、373→285 次，平均 3.2 组）；知识 + trace 16/18（两条 F01 在 truthfulness 阶段撞 1500s），平均 1027s、44.2 次（r2-tk 4/18、58.2 次）。另修 `context_store._record_paths_for_project`：并发落档时列出后被别的线程裁掉的文件跳过，不再报"调用记录落档失败"。
- **大材料推送丢了记录库旁的字段（S2 起就有，10-26 修）**：逐次看 r2f-tk 的调用，10 条 langfuse 的侦探全都先猜 `ids=["links","program_suspects","gaps"]`（没有这个编号）、再搜 links / suspect（0 命中），每条白花 3–4 次调用约 40s；E01 偶然用 `path="links", full=true` 才读到。原因：`reader.summarize` 对超限的记录库只回 `{说明, catalog, records: 条数}`，`case.trace` 的环节表、可疑环节、缺口一起丢了，侦探说明却写"你拿到的是…环节表…"。之前各轮侦探都是在没有环节表的情况下做的。改：只把记录正文换成目录，旁边的字段照推，单个超限的给开头 + `path` 读法（`spec/alg/axis_loop.md` §4.4 同步）。按 22 条存档实算，侦探推送 12k–62k 字，环节表除 agno-F01（超限给预览）外都整份推到。
- **同批工具并发执行（10-26 用户定）**：r2f-tk 里模型一次回复会发 3–4 个知识查询，但 `_run_batch` 逐个执行，核事实阶段每条约 21s 花在等 MCP（读材料是内存操作，三个阶段合计每条 2–4s）。工具协议 `VerifiableTool` 加 `concurrent`（只读、不调模型、等外部 I/O）；`tool_loop/runtime._run_batch`：pre_tool 按原顺序过，放行的 concurrent 调用同时执行（`copy_context` 带上 step ctx），其余照旧顺序执行，post_tool 与回放按原顺序。标 concurrent 的：MCP 知识源工具（含 ES）、`mcp_read`、`mcp_find`；`McpTools` 的翻页句柄改成加锁发号（原来按回执条数数，并发会重号）。读材料（read_material / search_material / recall）不标：内存操作省不出时间，且共用"已给过的正文"状态，并发后指向谁不确定。submit、search_knowledge（调模型）不标。测试 `tests/test_tool_loop_concurrent.py`。`test_tool_loop.py` 的慢工具超时用例、两条 tool_loop_lab 用例在改前的 runtime 上同样失败（前者时好时坏），与本改动无关。
- **组内只排真实先后（10-26 用户定）**：原来分发的一份按 `tasks` 列表顺序整串排队，组内互不相干的轴也要等前一个交完，模型只能一个一个交。改为先后对：一份写 `{"id", "tasks"?, "after"?: [[前, 后]], "materials"?}`，`loop._plan` 校验先后对属于本份、不成环（`_pairs`），只给这些对加依赖；锁改为一对里后一个出现后锁前一个（`_LoopGate.after`）。`process_expected/dispatch.py`：组数最少，同组数取轮数之和最少，`after` = 组内的 feeds。按 r1f-t 22 条实算，本应要排的轮数 132 → 94（加上"同组数取轮数最少"，只排真实先后是 108）。测试：先后对放出 + 锁、没先后的一次交齐、先后成环报错、分组取轮数最少。85 passed。实例 axis_code 已同步。
- **读材料少走冤枉路（10-26 用户定）**：r1h-t（组内只排真实先后后）B02、E01 本应阶段交结果少 1 次、省 30–45s，但读材料从 6–7 次涨到 16–18 次（按 path 下钻走不通 13 次、搜索 11 次；另有 16 次碰 6 万字单次上限，复核在侦探阶段，不在本应——当时统计没按阶段筛，误记到本应）。读回内容 81 条约 19 万字，无损压缩（去空格、去字段包装与空字段、提常量）只能压到 78%，大头是真正文；读回的记录 53–70% 用进了提交。改两项不改变模型可见信息的：`reader.search` 逐个字段找（JSON 文本解开），返回编号 + path + 可读片段；`reader.drill` 遇 JSON 文本先解开、走不通报这一层有哪些字段。单次读取上限不动（用户定）；推送"目录 + 预览"、去字段包装可能影响判定，暂不做。测试 86 passed。
  - 验证 r1i-t（B02 / E01 / D16，只 trace）：主结论 3 条不变；整条 794 / 1019 / 569s（r1h-t 1075 / 1238 / 654，r1g-t 869 / 1040 / —）；本应阶段读材料 B02 16→8 次、E01 18→14 次，path 走不通 B02 10→6。六轴每轮都有 2–3 处翻转（B02 工具执行 sound→not_evaluable、E01 知识数据 problematic→not_evaluable 等），连续几轮之间同样在翻，看不出和本改动有关；六轴的跑间稳定性是待查问题。
- **页面实测（10-27）**：8033 新开空实例（仓库 `impl/data/llm_probe_loop` 手拷进去才有轴定义；空实例直接报"没有轴定义存储"），Playwright 驱动资料管理页从零配 llm_probe_loop 场景，三处卡住：① 知识源类型只有 es / mcp，登记不了 agno / langfuse；② 轴框 19 种全显示"(undefined)"、只能加 1 个框、保存报 `axes[0].type 必须是…`——页面取 `type_id`，llm_probe_loop 的类型接口给的是 `type`，也没有 `summary` / `scenario_fields`；③ 业务 trace 还是旧的 provider + config 表单，测试连接后端报"business_trace 写成 {source, bindings}"。另：信息源"测试连接"对 trace 源会落进 MCP 分支。范围见方案 §2.4，步骤 P10a。业务环境：网关 4202、Langfuse 3300、业务 18066（`scripts/insurance_validation_app.py`，按 10-18 会话记录恢复的启动脚本）。
- **P10a（10-27）**：
  - 轴类型接口：llm_probe_loop 按 llm_probe 同形返回（`type_id`、`summary`、`verdict_scope`、`inputs`、`scenario_fields`、`requires_business_trace`…，删 `type`）；描述框给读 `axis.note` 或自己 / 调用的 loop 用信息源的轴（现定义下只有真实性）。
  - trace 源：provider 拆 `validate_connection`（登记）与 `validate_config`（登记 + 场景绑定），`describe()` 的 `default_config` 拆成 `default_connection` / `default_bindings`；登记保存时校连接形状；trace MCP 服务加 `check` 工具，登记页"测试连接"（`check_source`）与场景页"测试 Trace 连接"（`check_connection`）都经它，不再直连 provider；场景保存时校 trace 选用（登记在、绑定合法）。
  - `/api/knowledge_sources` 带 `types`（两个项目都带）；`/api/capability/save` 带 `warnings`（llm_probe_loop；空时按对外输出规则省略）。
  - 页面（`materials.html`）：类型下拉按 `types`；trace 类型模板只有连接；场景业务 trace 在"登记里有 trace 类型"时改为选登记名 + 写绑定，存 `{source, bindings}`；"添加全部轴"；过程职责输入框（有轴读 `scenario.process_obligations` 时显示）；保存结果显示警告（原来保存后 `selectCap` 会把提示清掉，一并改了顺序）。
  - 新实例：`instances.resolve_instance` 第一次绑端口时拷仓库 `impl/data/<项目>/`（不拷 `__pycache__`、`*.bak*`、运行期产物）。
  - 仓库 llm_probe_loop 样例数据：`insurance-agno-e2e` 改成 `{source: insurance-agno-local, bindings}` 并登记该 trace 源；删 `insurance-llmtracing`（第二期不支持）。原写法场景里有本机绝对路径，场景存储的可移植检查（`portable_artifact`）会拒掉整份写入。
  - 另修：`table_view` 收引用按 issue 实有的字段（llm_probe_loop 的过程轴 issue 只有 `output_refs`，原来 `KeyError: 'source_refs'`，统一全链路跑完评测在组装展示时 500）；主轴结论不再重复一行。
  - 测试：新增 `tests/test_llm_probe_loop_trace_sources.py`（5）、`test_instances` 拷出厂数据（1）。
  - UAT（`report/axis-loop-phase2/uat/`，Playwright + 本机 Chrome）：8036 新端口新实例，只用资料管理页登记 `ui-agno`（测试连接经 MCP 通过）、建场景 `ui-verify-agno`（添加全部轴；开着真实性没选知识源时保存被拦，关掉后保存成功；存下的启用轴、能力、边界、service、mock_body、过程职责与 `verify-insurance-agno` 逐项相同），live 页统一全链路真调 18066 跑 D16：839s、fulfilled、页面无报错。8032 上同入口真调：D16（agno）686s 做成了，侦探 24 个环节；B02（langfuse）501s 没做成，侦探 15 个环节——两种 trace 都经 MCP 采到。
  - 待定：① live 页单条结果只显示总结论，各轴明细要么再点"扩展评估轴"整条重跑、要么批量跑后在用例表看；② 分两步跑（先请求业务、再请求 Judge）和 live 页"扩展评估轴"按钮：`project_fields` 被对外输出去掉、浏览器交回的结果没有 trace（按代码判断，未实测；批量、补跑、统一全链路都在服务器上跑完，不受影响）。量过 22 条存档：整条结果中位约 650KB、最大约 7.8MB（trace 快照存了两份）；sessionStorage 刷新不清、约 5MB 上限，live 页写存储没有出错处理。两种改法：A 不去掉 `project_fields` + live 页存储不带 trace / 加出错处理；B trace 留服务器、按 trace_id 取。用户 10-27 定先不管；③ llm_probe 自身的场景写法允许本机绝对路径、场景存储又禁止，有这条场景的实例在页面上存不了任何 llm_probe 场景（8021 原本就这样；新实例拷了仓库样例后也会这样）。

- **资料管理页"知识源"一栏改名"信息源"（10-27 用户定）**：登记里已同时有知识源（es / mcp）与 trace 源（agno / langfuse），页面标题、按钮、编辑框、提示与状态文字改成"信息源"；指知识源本身的地方（引用下拉"MCP 知识源 / ES 知识源"、轴描述占位）不变。只改显示，数据与接口不动。
- **Mock 数据集（10-27）**：`impl/data/llm_probe_loop/mock_cases.json` 是 P1 从 llm_probe 原样拷的，87 条 `project_id` 全是 `llm_probe`，归因总结页"加载 Mock 数据集"报项目不一致。改成 `llm_probe_loop`，删 32 条 `insurance-llmtracing`（场景已删）；剩 55 条，同步到 8036 实例。剩下的场景里 policy_search、marketting-planning-intent、dashscope-qa、insurance-agno-e2e 在 llm_probe_loop 一个轴都没开（共 44 条），跑会报"没有启用的评测轴"；能直接跑的只有 client_search 6 条、policy-clause-qa 5 条。待用户定。
- **P10b（10-27）**：按方案 §2.5 改完。全量回归 26 failed / 2116 passed，失败全在已知清单内（新增 3 条单测）。8036 重启后：轴类型接口 19 个轴 18 个有描述框、`main_verdict` 没有；Playwright 新建场景"添加全部轴"同上、过程职责输入框已删；`ui-verify-agno` 的过程职责迁进 `planning_routing_expected` 的框，页面保存通过。数据：仓库样例 `insurance-agno-e2e` 与 8036 实例的两个场景迁了过程职责，8036 实例同步了轴定义与需求分发脚本（改前副本在会话 scratchpad `8036-before/`）；实验实例 f1055 未动。live 页统一全链路真跑 1 条（严言琳 / 严言雅，728 s，fulfilled）：需求轴任务文本【axis.note】一次，没有 criterion。页面另有一处没改：新建兑现轴框时预填 `capability` 原文（`legacyDescriptionFor`，两个项目共用），在 llm_probe_loop 下会把场景总述带进兑现轴的框，配场景时要手动改。
- **P10c（10-27）**：按方案 §12.3、§6.3 改完。真实运行发现一处漏改：可选工具被扣下后，轴所在 loop 的工具表仍按 `axis.tools` 建（`loop.py` `_LoopGate.__init__`），报 `KeyError 'search_knowledge'`；已过滤并补单测（建出的 loop 工具表里没有被扣下的工具）。全量回归 27 failed / 2123 passed：比 P10b 多出的 `test_tool_loop.py::test_slow_tool_does_not_count_against_request_timeout[stream]` 是计时用例，当时与 8036 真跑并行，单独重跑 3 次都通过（stream 变体单跑时 skipped），本步没改 tool_loop。8036 真跑 1 条（"P260922000099999的被保人是谁？"，`ui-verify-agno`，承载性框只写"仅提供办理说明，不实际提交退保或保全申请。"，未选知识源，455 s）：兑现 not_fulfilled → 承载性出现，任务文本里 `search_knowledge` 标"本场景不可用"，模型交 undecidable（空间未受治理，缺保单查询的责任范围或数据源）；主轴按规则应为"没做成，能不能做没分清"（live 页不显示各轴明细，没在页面上核）。页面上带 `boundary` 保存报"责任范围写进承载性的描述框"，清空后保存通过；"添加全部轴"给承载性框预填整段 `boundary`（392 字，含系统自述），同兑现预填，先不管。改前副本在会话 scratchpad `8036-before-p10c/`。
- **按标准配场景（10-27）**：实验实例的 verify-insurance-agno / -langfuse / -mcp 迁进仓库默认数据（脚本在会话 scratchpad `build_verify.py`，原话不改只按句分框）：能力说明与能力边界按句分到场景总述、需求轴框（交付形式）、兑现轴框（怎样算交付到位）、承载性框（只留"仅提供办理说明，不实际提交退保或保全申请。"）、agno 的侦探框（"Agno 持久化消息……"一句，langfuse 不放）、规划与路由本应轴框（过程职责）；三个场景都开承载性。删 `insurance-agno-e2e`（连 18062）及其 32 条用例、只给它用的 trace 源 `insurance-agno-local`；加 trace 源 agno-insurance、langfuse-local 与 insurance-tools。`verify33/old.jsonl` 33 条样本转成用例（每场景 11 条，6 条多轮走 seed replay；langfuse 请求带 `{request_id}`）。-tk 两个场景不迁（10-27 用户定）。同脚本同步 8036（改前副本 `8036-before-verify/`）。
- **删 llm_probe_loop 的判后轴2（10-27）**：summary 页"承载性"列显示"说不清：缺能力边界描述（请在 capability 预设中填写 boundary 字段）"——`project.yaml` 还开着 `capability_carrier` scope，核心 pipeline 判后再跑一遍从 llm_probe 拷来的 TextCarrier（读已禁用的 `boundary`）。改成 `enabled_scopes: []`，删 `live.capability_provider`、`text_carrier.py`、`capability.boundary_text / resolve_boundary`；llm_probe 不动。
- **summary 页实测（10-27，8036，各 1 条、并发 1）**：① verify-insurance-mcp "P260922000099999的被保人是谁？"：258 s，主轴做不了；承载性调 `search_knowledge` 一次，引"未查询到该保单"的返回原文交 no，回读通过（P10c 未在真实 case 验过的依据回读在此验到）；承载性列不再出现旧轴2 文字。② verify-insurance-agno "P260922000005855是谁的保单？……"：588 s，主轴做成了；兑现 fulfilled → 承载性 not_applicable（不出现）；侦探 complete，六轴 5 个 sound、context_memory problematic。全量回归 27 failed / 2123 passed，较 P10b 多的仍是计时用例 `test_slow_tool_does_not_count_against_request_timeout[stream]`（与 8036 真跑并行）。
- **被测服务没开时（10-27 查）**：`live.py` 连接失败分支用了未定义的 `ref`（llm_probe 在 `deliver_real` 里定义了，llm_probe_loop 拷过来时丢了），报 `name 'ref' is not defined` 盖住真实原因；已补。现在旧场景（服务 8000 / 8050 / 9006 / 18090 都没开）跑 run_chain：业务调用即失败，trace error "llm_probe target unavailable: Connection refused；<start_hint>"，不进 judge、不调模型。服务起来以后：client_search / policy_search / marketting 因带 `boundary` 加载时报错；dashscope-qa 没开轴报"没有启用的评测轴"；policy-clause-qa / hr-handbook-qa 可跑。
- **summary 页跑批时"理由"点开就收起（10-27）**：`pollBatch` 每 1.2 s 取进度，进度事件带回已完成用例的 `run`，`applyBatchEvents` 见 `run` 就算变化 → 每次轮询整表 `innerHTML` 重画，展开的折叠块被收回。改：已合并过（`caseResults` 有）且状态没变的不算变化；`renderCasePool` 重画前记下展开的 `details.axes-detail`（按 `request_key`），重画后恢复。8036 浏览器模拟（同一结果连回 3 次：重画 0 次、保持展开；另一条状态变化触发重画：仍展开），无页面报错。未在真跑批量中核。
- **summary 页明细轴标题显示结论（10-27）**：明细里每轴标题旁原先放运行状态，几乎全是 succeeded，没信息量。改成放 `axis.verdict`（复用 `axisValuePill` 上色），运行状态只在不是 succeeded 时显示；顺序不动（保持判定先后，本应与实际相邻）。llm_probe_loop 各轴 `summary.items` 与 `usage` 仍写死为空（`eval_axes/__init__.py` `_result`），逐条明细、模型名、耗时留待以后。8036 浏览器核：33 条 495 个轴标题无 succeeded，无页面报错。
- **轴定义加 `display`（10-27，用户定）**：结果页明细分两块：`display=expanded` 的轴按原顺序放上面、进令牌行；`collapsed` 的收进"其余分析（n 个）"折叠块、不进令牌行；不是 succeeded 的不管设置都放上面。不写按 `role` 取默认（评测轴展开、分析轴收起）；需求分析、blocking 投影、说法抽取写 `expanded`（blocking 理由以后要写清楚，用户提）。改动：`definitions.py` `AxisDef.display`；`eval_axes/__init__.py` `_result` 改收 `AxisDef` 并带 `display`；`table_view.py` 每行带 `display`（主轴行、整体失败伪行为空 = 展开；llm_probe 不带也按展开）；`summary.html` 分块，跑批重画时"其余分析"的展开状态一并恢复。8036 同步轴定义（改前副本 `8036-before-display/`）并重启。浏览器核：一条 agno 用例上面 12 轴、其余分析 7 个（侦探 + 6 个本应）；把侦探改成 failed 后它回到上面、其余剩 6 个；无页面报错。8036 上已有 33 条结果是旧格式（不带 `display`），全部按展开显示，重跑后才分块。
- **过程轴达到也要引文、评测不再看用例名（10-27）**：盘 agno `smoke-neg-unknown-policy` 发现：① 主 loop 开场写着用例名（`case llm-probe-…-neg-unknown-policy`），知识与数据据此写"库中不存在……符合负向用例的业务期望"判达到；trace 里后端只记了 outcome ok、HTTP 200、130 字节，没有返回内容。② 过程轴"达到的行引文可选"，工具执行 E2"返回与请求一致、未混淆对象"也无引文判达到；`needs_external=是` 的锁只管没达到。改：`eval_axes/__init__.py` 开场只写场景与轮数；`process_axes.py` 达到 / 没达到 / 不适用都必须有引文（`QUOTED`），提交检查退回没引的，合成时引文丢光的降无法核（原先没达到丢光不降，与 spec 不符，一并修）；6 个过程轴说明的引文规则同步；`spec/alg/process-axes.md` §3.2 与引文规则同步。测试：`test_llm_probe_loop_process.py` 脚本模型的达到改为从侦探给的记录里摘引文，样本里工具执行（程序环节表没列后端调用）和模型能力（没调大模型）拿不到记录 → not_evaluable；新增达到没引 / 引错降无法核的单测。相关 204 测试通过。8036 同步轴定义（改前副本 `8036-before-quotes/`）并重启。未真跑验证；预计过程轴 sound 会变少、not_evaluable 变多。llm_probe 的 `process_expected.py` 同句未动。
- **trace_id 误判与写死的 session_id（10-27 查、用户定）**：① 被测系统返回的 `trace_id` 按接口定义"原值回显请求 trace_id；省略或 null 时为 null，不是服务端内部追踪标识"（insurance-qa-agent `app/schemas/answer.py:56`）；内部 `TR-…` 不对外（提交 e433d80d）。agno / mcp 场景请求不带 trace_id，交付恒为 null（各 11/11），langfuse 带 `{request_id}` 故回显。agno 关联按 session_id + 本轮原话 + 最新 run，不用 trace_id（11 条 14 轮全部关联成功），不改。上下文管理·本应把 trace_id 写进"交付必须原义保留"导致误判（11 条 agno 里只有 1 条这样写，不稳定）；按用户定，属这个系统的接口约定，写进 agno、langfuse 两场景的 `context_memory_expected` 描述框，不改通用规则。② 场景迁移时（`build_verify.py`）从旧样本原样抄了 session_id：三场景各 3 条（fuyunping-policies、bizno、main-G01）写死，重跑累积在同一会话（agno 单轮用例运行时已有 history_runs 1–2 条）；改成 `{session_id}`。仓库与 8036 同步（改前副本 `8036-before-session/`；8036 多一个 UAT 场景 ui-verify-agno，未动）。8036 当前用例池仍是旧用例，要重新"加载 Mock 数据集"才生效。

## 10. 核事实判法与说明回合（2026-10-27 起）

依据：需求 `demand/claims.md` §3.6、C12，`axis_loop.md` L9、§3.3.6–7，`main_axis.md` M9（记录 `demand/draft-20261027/README.md`）；方案 `spec/alg/knowledge-evidence.md` §5"判定：核的是事情"，`spec/alg/axis_loop.md` §3.2、§5.3 第 6 步、§12.4，`spec/alg/fulfilled.md` §4，`spec/alg/process-axes.md` §3.2。起因 C08（8036，mcp `main-C08-two-customers-parallel`）。

| 步 | 内容 | 改哪 | 完成标准 | 状态 |
|---|---|---|---|---|
| T1 | 框架：说明回合。`AxisDef` 读输出 schema 顶层字段的 `x-explain`（只许标在 `x-fill: program` 的字段上，加载期校验）；`Submissions.explained`；`acceptance.submit` 收尾在合成后比 x-explain 字段与 `explained`，不同 → 存下并返回"说明"结果（不算拒）；`Submissions.reset` 清空；`loop._submit` 把它当 Deny 回给模型，事件记 `explain` | `impl/core/axis_loop/definitions.py`、`acceptance.py`、`loop.py`、`validate.py` | 单测：没标 x-explain 的轴一次收下（现有测试不变）；标了的第一次回说明、只改 reason 再交收下、改引用使结果变了再回一次；作废后重新回说明；x-explain 标在模型字段上加载报错 | 完成：`x-explain` 取 true 或键列表（`Work.explained_fields`、`_pick`）；`Outcome.explain`；`explain_text`；被调用启动的 loop 与普通 loop 都接；事件 `explain`。测试 `test_axis_loop_core.py` 4 个、`test_axis_loop_run.py` 1 个 |
| T2 | 兑现：synth 每条加 `status_basis`（按 `derive` 的分支：没给 / 交付不可读 / 只凭交付 / 缺证据组 / knowledge 组不过·判不了（列 claim 及其 text）/ trace 组不过·判不了（列条目及结论））；输出 schema 加字段，`fulfillment_assessments`、`overall_fulfillment`、`verdict` 标 x-explain；说明第 2 条与收尾 reason 按 `fulfilled.md` §4 改写；说明回合的话里列每条 status + status_basis | `axis_code/fulfillment/synth.py`、`axis_definitions.json` | 单测覆盖 status_basis 各分支；C08 重放：第一次提交收到含 c7 的说明 | 完成：`derive` 返回第四项程序依据；兑现说明加第 8 条、收尾 reason 改为最终兑现情况；x-explain 标 `verdict` 与 `fulfillment_assessments`（只回 id / status / status_basis；整体状态即 verdict，不另标 `overall_fulfillment`） |
| T3 | 过程六轴：`needs_external` 锁从 `actual_result` 移到 `check_actual`（判没达到 → 打回，原文按 §12.4）；删 `actual_result` 里丢坏引文、丢光降级（同一份 texts 已在 check 打回）；6 个实际轴 `verdict` 标 x-explain；说明里"程序会锁成无法核""仍不对则丢弃、丢光降成无法核"两句删改 | `impl/projects/llm_probe_loop/process_axes.py`、`axis_definitions.json` | 单测：needs_external 没达到被打回、改判无法核收下；`test_needs_external_only_locks_not_met` 改为打回语义；其余过程测试不变 | 完成：`check_actual` 打回 needs_external 没达到；坏引文对所有行都查；`actual_result` 去掉 texts 参数与 demoted；6 个 synth 同步；说明里两句改为"判了会被退回""改对了才收"；x-explain 标 `verdict`、`composition`（只回 counts） |
| T4 | 主结论依据：没兑现的期望按 delivered 分"给错了：<id>（<status_basis>）"和"没给到：<id>" | `impl/projects/llm_probe_loop/eval_axes/main_verdict.py` | 单测：给了但 refuted → 依据写给错了；没给 → 没给到 | 完成：`_unmet_text`："给错了：<id>（<status_basis>）；没给到：<id>"；材料不够也附依据 |
| T5 | 核事实判法：llm_probe_loop 真实性说明按 `knowledge-evidence.md` §5 重写（判什么 + 6 条易错处；删等价清单、"② 没说不凭常识"、①②③ 框架、对象不存在分支；工具用法、提交格式、basis / gap 不动） | `axis_definitions.json`（truthfulness.instruction） | 加载无报错；C08 用同一份证据重判 c7 → verified | 完成：说明按 §5 重写（判什么 + 6 条易错处；refuted 的 basis 引表明不是这样的那段） |
| T6 | 旧路线同改：llm_probe `adapters/truthfulness.py` 的 `_JUDGE_SYSTEM` 同口径重写。**8032（f1055）的进程从本仓库起，已加载这份代码；改文件不影响正在跑的进程，但它重启就会读到——动之前问用户** | `impl/projects/llm_probe/eval_axes/adapters/truthfulness.py` | 用户确认后再做；llm_probe 真实性测试过 | 待用户确认 |
| T7 | 验收：同步 8036 定义，重启；C08 单跑看 c7、兑现 reason、主结论依据；10-27 那批（mcp / agno / langfuse）全量重跑，refuted 逐条人工复核、对比改前错判与漏判；报每 case 调用数 / token / 耗时变化 | 8036 | `report/axis-loop-explain-20261027/RESULT.md` | 完成：C08 三次 + 33 条全量（见 §10.1 与 RESULT.md）；mcp-G01"单位是元"错判有矛盾待定 |

- 顺序：T1 → T2 → T3 → T4 → T5 → T7；T6 等用户。T1–T4 不改判法，T5 改判法，验收时分开看两者各自的影响（先跑 T1–T4 的 C08，再加 T5）。
- 改 8036 定义前照旧备份到 scratchpad。


### 10.1 验证（2026-10-27，8036）

- 单测：`test_axis_loop_core.py`、`test_axis_loop_run.py`、`test_llm_probe_loop*.py`、`test_llm_probe_eval_axes.py` 共 206 个通过。
- 偏差：8036 实例自带一份 `axis_code`（`.runtime/instances/inst-33ff6254434841b0/data/llm_probe_loop/axis_code`），第一次只同步了 `axis_definitions.json`，跑出来有说明回合、没有 `status_basis`；补同步 7 个 synth 后重启。改前副本 `scratchpad/8036-before-explain/`。
- C08 第一次（新 synth 未同步）：被测回答换了，没写"（无效）"；核事实判 c1"手机尾号 9228"有矛盾——原文 `clientMobile=19909224628`，9228 在原始数据里不存在，判对。兑现说明回合 1 次，每条 reason 写出程序结果和原因（"因为 c1 被否定"）。
- C08 第二次（全部同步）：回答再次写"到期终止（无效）"，说法抽成一条"当前状态为到期终止（无效）"，判 verified，引文同时引 `polStatusDesc` 与 `isValidPol`。`status_basis` 出现；主结论"不确定"，依据写出 c35（保费合计 1259.9，原文字段说明不许跨险种汇总）、c42（查不到）。37 次模型调用、820 s。
- 旧回答重放（`/api/eval_axes/run`，10-27 那次判错的 trace）：36 条全 verified（"保单状态是到期终止（无效）"引了两个字段），主结论由"没做成"变"做成了"。30 次调用、606 s。两次重放说法抽取都没把"（无效）"拆成单独一条，拆开那种写法没有复现。
- 新发现：c42"投保人是掏钱买保险、在合同上签字的当事人"——知识库有"投保人是与保险人签订保险合同并支付保险费的人"，讲的是同一件事；`search_knowledge` 按字面没找到报 not_found，核事实只能判查不到。同一类问题（写法不同当成没有），出在取证一层，`search_knowledge` 说明未改。
- **33 条全量（10-27，8036，并发 4）**：机器重启后按原命令恢复网关 4202、Langfuse 3300、业务 18066、8036（会话 scratchpad 被清空，改前备份 `8036-before-explain/`、`repo-before-explain/` 已丢）。33 条全部跑完、0 失败；有 gold 的 28 条对上 25 条：mcp-bizno 新回答本身错了（判对）、mcp-G01"单位是元"被业务说明"金额不带单位"判有矛盾（错判，违反 claims §3.6）、langfuse-D16 外层工具调用在 trace 里入参输出缺失 → 不确定。refuted 共 3 条，2 对 1 错。三场景 C08 都做成了。平均调用 mcp 29.6 / agno 33.2 / langfuse 24.5；usage 没有 token 数。详见 `report/axis-loop-explain-20261027/RESULT.md`。

## 11. "没有"按局部全集判（2026-10-27（二）起）

依据：需求 `demand/claims.md` §3.7、C13，`demand/information_sources.md` 要求 9（记录 `demand/draft-20261027b/README.md`）；方案 `spec/alg/knowledge-evidence.md` §4.1 第三条、§4.2 gap、§5"有没有、共几个"一条。起因 mcp-B02（10-27 全量批）。只改 llm_probe_loop；llm_probe 旧路线（`adapters/truthfulness.py`）不动，验证过后再议（用户 10-27 定）。

| 步 | 内容 | 改哪 | 完成标准 | 状态 |
|---|---|---|---|---|
| U1 | 取证说明：第 10 条换成"读全了的范围就是原文"（原文见下）；not_found 的 gap 说明里 item_absent 补"且证明不了是全集" | `axis_definitions.json`（loops.search_knowledge.instruction） | 加载无报错；单测过 | 完成（单测 113 过） |
| U2 | 真实性说明："涉及全部、共几个、没有某项"一条换成按全集判（原文见下）；gap 说明里 item_absent 改为"对象在、没有这一项，手里也没有讲清这件事的全集" | `axis_definitions.json`（axes.truthfulness.instruction） | 同上 | 完成 |
| U3 | 不改：`truthfulness/checks.py`（not_found 只能判 unverifiable）、search_knowledge 输出 schema 与 gap 枚举、知识源登记（`insurance-tools` 读法 ③ 已写"本页条数等于 total 即全量，去重张数即全部保单数"）、承载轴说明、兑现 / 主轴合成 | — | — | — |
| U4 | 验收：备份 8036 实例定义到 scratchpad 后同步、重启；先 B02 ×3、F01、A02、G01 单跑，再 mcp 11 条全量；逐条对照下面的基线标注 | 8036 | 见"验收判据" | 第一轮完成（见 §11.1）；B02 目标被知识源工具挡住，待用户定 |

U1 第 10 条原文：

> 10. 说法涉及某个范围里有没有某一项、共几个，或对象本身存不存在时：把这个范围按对象查全，读全了的那份返回（列表、空结果、"未查询到该对象"的提示）就是相关原文，交 found 并引用它，连同表明读全了的总数与条数一起引；不要因为里面没有说法说的那一项就交 not_found。怎样算读全了、哪类查询查回来的就是全部，看知识源的读法说明和数据本身（总数与已读条数）；没读全的交 not_found，note 写明"结果不全：总数多少、看到多少"；查回别的对象、工具报错都不算。

U2 替换条原文：

> - 涉及"有没有、是不是其中之一、共几个、全部"时，先看手里有没有这个范围的全集：按说法问的那个范围（某个对象名下的全部条目、某个对象的全部组成）查过并且读全了（数据里的总数与已读条数相等，或知识源读法说明写明这样查回来的就是全部），这份全集就是讲这件事的原文——说法与全集一致判 verified；全集里没有说法说的那一项、或数目对不上，判 refuted，reason 写明这是哪个范围的全集、怎么知道读全了、里面有什么。查询结果为空也是全集（全集为空），对象本身不存在时它的任何值都不成立。没读全，或手里的全集讲的是别的范围（一条记录读全了，但说法问的那一项不在这条记录讲的范围里），没查到不等于没有，判 unverifiable。

两段都不写具体业务词、字段名。

**基线标注（10-27 全量批，mcp 11 条共 150 条说法：unverifiable 14、refuted 3，其余 verified）**

| case | 说法 | 现判 | 该判 | 与本次改动 |
|---|---|---|---|---|
| B02 c1 | 已购买平安安佑福重大疾病保险 | unverifiable（item_absent） | refuted（名下保单全量里没有这款） | 目标 |
| B02 c4 | 名下保单数量是 2 张 | unverifiable（item_absent） | verified（全量 2 张） | 目标 |
| B02 c11 | 从产品系列看为同一款产品 | refuted | refuted | 不得变 |
| bizno c1 | 寿险客户号对应的客户不存在 | refuted | refuted | 不得变 |
| F01 ×6 | 累计已交保费 / 月缴 / 年缴 / 保额的单位是元 | unverifiable（item_absent） | unverifiable | 防线：不得翻 refuted |
| A02 ×3 | 续期保费单位为元 | unverifiable（item_absent） | unverifiable | 防线：不得翻 refuted |
| G01 c2 | 累计已交保费的单位是元 | refuted | unverifiable | 已知错判（拿读法说明作依据），不是本次目标；看会不会变坏 |
| E01 c1、c2 | 险种代码是 1836、销售状态是在售 | unverifiable（object_absent） | verified | 已知取证字面问题（§10.1 c42 同类），不是本次目标 |

**验收判据**：B02 c1 / c4 三次都判对；F01、A02 的"单位是元"0 条翻 refuted；mcp 全量里原 verified 的不新增 refuted（新增的逐条人工复核）；bizno、B02 c11 不变；报每 case 调用数与耗时变化。被测回答每次会变，对照按说法内容对齐，不按编号。

### 11.1 验证（2026-10-28，8036，mcp 11 条并发 4，job `cc01fd7e`）

- 改前 8036 定义备份 `scratchpad/8036-before-closedworld/`。实际顺序与计划不同：直接跑 mcp 全量（B02、F01、A02、G01 都在其中），B02 另两次未跑。
- 防线守住："单位是元"类说法全批 21 条全部 unverifiable，0 条翻 refuted；G01 由错判 refuted 变 unverifiable（判对）。全批 refuted 0 条（bizno、B02 的回答这次都变了，原来那两条 refuted 的说法没再出现）。
- B02 c1"已购买"仍判 unverifiable，reason"客户保单记录未证明为全集"——判官按新说法判了，但手里确实没有全集。查证记录（`scratchpad/cw1_b02_records/`）：`policy_search` 传了 customer_id 调 4 次，每次返回 `PARTIAL`、别人的保单（P…0001–0006）；只读复现（`scratchpad/probe_policy_search.py`）：`customer_id + "有效保单"` 返回全库 10948 条，`customer_id + "保单"` 返回 AMBIGUOUS。原因：`insurance-tools-mcp/itools/dispatch.py` 的 policy_search 分支没把 `arguments["customer_id"]` 传给 `policy_search_core`（工具说明与 schema 都宣称支持）。评测方因此拿不到任何客户的保单全集。
- 更正 §11 起因里的一句：10-27 那次 mcp-B02 评测方同样没拿到全集（c4 的 reason"客户查询提示保单数量未知"），"incomplete: false 的全量列表"出自被测业务自己的 trace，不是评测方取证。原先"c1 被分支规则压成查不到"只对了一半：规则会压，但那次就算没有这条规则也没有全集可判。
- B02 结论：check_purchase_status 判不了 → 不确定；主结论"没做成"只因等待期没给。核心错误"已购买"漏成不确定。
- 同因：F01"名下共有 2 张保单""名下保单均已交费有效"判 unverifiable（mismatch）。
- 打回：B02 28 次、A02 20 次，全是"同一次回复里拿到的返回要到下一次回复才能用"（判官在取证返回的同一批里就引用）；上一批这两条为 0。是否与本次改动有关未查。
- 主结论变化（被测回答每次不同，不全归因于本次改动）：bizno 没做成→做成了、G01 没做成→做成了、smoke-neg 做不了→没做成、C08 做成了→不确定（c46"投保人是签合同、掏保费的一方"按字面查不到，同 §10.1 c42）、F01 做不了→没做成。judge 耗时多数变长（如 fuyunping 419→651 s），调用数持平或下降。

### 11.2 B02 后续（2026-10-28）

- 更正 §11.1"评测方拿不到任何客户的保单全集"：按姓名查（"余昕雅的保单"）能拿到全集（total 3、读 3、去重 2 张）；customer_id 被丢是真的，但不是唯一的路。B02 漏查是取证没换查法，不是工具挡住；取证下一步单步重放 10 次里 7 次会换成按姓名查（`scratchpad/rr.json`）。
- 判定单步对照（`.claude/hillclimb/truthfulness-absence/`）：手里有全集时"已购买"6/6 判 refuted 且引全集；没有全集时 0/6 判 unverifiable（都判 refuted，理由"她那张是 Y 不是 X"）。两版判定说明改写（P1、P2）都没有变化，未上线。
- 回答原文是"已购买 X。具体如下：保单 9117，产品名称 Y"，本意是"她买的 X 就是 9117 这张"；"X 就是 Y"这层没列成说法（18 次 0 次）。补上这条重放判定（`split-P0/`）：证据够时它 12/12 判 refuted；"已购买"仍全判 refuted。由此转到说法抽取，见 §12。

## 12. 说法都列、隐性期望只引相关说法（2026-10-28 起）

依据：需求 `demand/claims.md` §2.1、§2.4、C14，`demand/main_axis.md` §2.5（记录 `demand/draft-20261028/README.md`）；方案 `spec/alg/knowledge-evidence.md` §3、`spec/alg/fulfilled.md` §2 第 5 行。只改 llm_probe_loop。

| 步 | 内容 | 改哪 | 完成标准 | 状态 |
|---|---|---|---|---|
| V1 | 说法抽取说明："什么算一条说法……序号、排列、指代。"整段换成下面原文；"……这条才不抽。"换成"……也照样列。" | `axis_definitions.json`（axes.claims.instruction） | 加载无报错；单测过 | 完成（10-28；相关 140 测试过） |
| V2 | 兑现说明第 3 条末句"用户没要的附带说法不在这里判。"换成下面原文 | `axis_definitions.json`（axes.fulfillment.instruction） | 同上 | 完成（10-28） |
| V3 | 不改：`claims/checks.py`、真实性说明（"说法只是回答自己的编号、排序、指代……unverifiable"保留）、`fulfillment/synth.py`、需求轴隐性期望写法、blocking | — | — | — |
| V4 | 单步重放（不动线上）：R1 B02 回答，新 / 旧说明各 10 次；R2 其他 10 个不同回答，新说明各 2 次，对照已有记录 | 重放脚本 | 见判据 | 完成（见 §12.1） |
| V5 | 8036 定义备份到 scratchpad 后同步、重启；mcp 11 条全量 | 8036 | 见判据 | 跑完（job `2e4f9747`，见 §12.2）：9 条主结论不变；C08、F01 核事实超预算没出结论，待定 |

V1 原文：

> 什么算一条说法：回答断言"某件事是这样"的一句话。一句话里断言了几件事就是几条，每条 claim 只说自己那一件。不管它关于什么、能不能核、重不重要都列：带不带数字、定性的、说某对象没有某项或不存在、说回答者自己做了什么，都是说法；是不是事实、核不核得了由后面判，这里不筛。回答断言某对象没有某项、或对象不存在时，claim 写成"某对象没有某项"或"某对象不存在"，核的是事实本身，不是回答者那次查到了什么。不是说法的只有不在断言任何事的话：提问、建议、客套，以及回答给内容编的序号、排列本身。

> 回答自己编的序号、指代不放进 context，换成它所指对象的标识在回答里的原文写法；回答和用户问题里都找不到它所指对象的标识，也照样列。

V2 原文（第 3 条改后全文）：

> 3. 每条期望只看和它有关的交付片段、claim 与过程条目；别的期望的结果不影响它。隐性期望 implicit_correct 也一样：claim_refs 引和本轮用户要办的事有关的说法（本轮其他期望涉及的对象和事项，用户没点名问、回答顺带说的也算），和用户要办的事无关的不引。

两段都不写具体业务词，不举本 case 的句式。

**判据**

- R1：新说明下"X 就是 Y"这层成条列出 ≥ 8/10（旧说明 0/18）。程序初筛 claim 同时含两个产品名，再人工看。
- R2：新增条目逐条人工看，混进提问、建议、客套的算错，目标 0；原有条目不丢；报条数变化。
- V5：B02 "X 就是 Y"列出并判 refuted；各 case 隐性期望的 claim_refs 不含"回答者描述自己做了什么"一类说法、含对点名概念的解释（如 C08 投保人）；原 verified 的不新增 refuted；主结论逐条对照 job `cc01fd7e`，变化逐条说明原因；报调用数与耗时变化。

### 12.1 单步重放（2026-10-28，`.claude/hillclimb/claims-assertion/`）

- 脚本 `replay_claims.py`：取记录里交说法清单之前的消息原样重发，只换 V1 两段；别的工具调用、别的任务一律回"只做说法抽取"，最多 4 轮。第一版只发一轮，60 次里 27 次没交清单，作废（`attempt1/`）。
- R1（B02 回答，各 10 次，全部交了清单）：claim 同时含用户说的产品名和惠享版产品名——旧 0/10，新 10/10（如"平安安佑福（惠享版）定期重大疾病保险即用户所指平安安佑福重大疾病保险"）。"知识库未收录……条款"旧 0/10、新 10/10。条数旧 24–27、新 28–33；多出来的是"回答者未能查到……""回答者无法告知……"这类回答描述自己的话（每次 0–2 条）。
- R2（10 个不同回答，各 2 次）：条数 case2 59/58↔61/54、case15 40↔40、case17 7↔7 基本不变；case3 +11、case6 +6、case12 +9、case22 +8；E01 两个回答旧 0 条、新 8/7 和 9/3。新增条目逐条看：没有提问、建议、客套；都是"知识库未收录……""某两人为不同客户""手机号不同""以上金额按工具返回原值""回答者多次检索……"一类断言。边界 2 条：case13"我据实说明"、case12"故分开归档"，按 V1 属于"说回答者自己做了什么"，照列。原有条目没丢：case3 旧的"9116 对应 e生保"在新版里写成 claim"保单号是 9116"、context 带产品名，意思一样；case9 旧 rep1 只有 11 条是那次抽错了轮次（抽的是另一轮回答），不是新说明丢的。
- 新问题：同一句有时既整句列又拆开列（case22"返回的多为其他产品的条款内容，与该产品无关"出现 1 条整句 + 2 条拆开），条目重复；E01 第二个回答两次分别 9 条和 3 条，不稳。未处理。

### 12.2 V5（2026-10-28，8036，mcp 11 条并发 4，job `2e4f9747`，对照 `cc01fd7e`）

- 改前 8036 定义副本 `scratchpad/8036-before-claimsall/`；`axis_code` 与仓库一致，未动。
- 9 条有结论，主结论全部与 `cc01fd7e` 相同（做成了 6、没做成 3）。
- C08、F01 没出结论，都停在核事实：C08 超全局墙钟 1500s（65 次调用），F01 上下文超 200k（约 210k）。核事实一次取 25 条说法的证据，每条约 3–13k 字（中位约 6k），一批约 18 万字；说法变多后要取两批以上，第二批进来就超。F01 本次至少 51 条说法（上次 17 条）。上次 C08 56 条能跑完，这次没跑完。属框架预算问题，未处理，待用户定。
- B02 这次业务回答换了一版（"已购买……实际购买的是诚享版……尾号923680"），不再写"即用户所指"，"X 就是 Y"这条判据本批测不到。判 refuted 3 条，逐条看都对：已购买用户说的产品（实际是惠享版、险种代码不同）、尾号 923680（实际 3680）、诚享版（实际惠享版）。说法 12 条全部被隐性期望引用，隐性期望 not_fulfilled。
- 隐性期望引用：A02 引 18/19，没引的是"已完成核实"（回答描述自己）；其余 case 本批没出现"回答者……"一类说法。renyanlin 隐性期望 fulfilled → not_evaluable：引了"续期应缴日为每月07日"（unverifiable，相关）。E01 t1、t2 隐性期望一条没引 → not_evaluable，t3 引 3 条 → fulfilled（上次 0 条说法）。
- 原 verified 的没有新判 refuted（新的 refuted 只出现在 B02 新回答）。
- 调用数：renyanlin 19→23、A02 22→17、B02 29→37、D16 21→26、E01 27→41，其余 ±2。


## 13. 唯一性原则（2026-10-29 起）

依据：需求 `demand/axis_loop.md` §3.8、L10、§5.3，`demand/claims.md` §2.1、§4.6、C15（记录 `demand/draft-20261029/README.md`）；方案 `spec/alg/knowledge-evidence.md` §3、§4.1 第四条、§4.6，`spec/alg/axis_loop.md` §9 第 2b 条。只改 llm_probe_loop 与 axis loop 框架；llm_probe 不动。

起因更正：F01 的重复来自最后一轮的一个回答里同一内容说了三遍（业务把英文推理、草稿和正式回答一并交出），不是"三轮各说一遍"。

| 步 | 内容 | 改哪 | 完成标准 | 状态 |
|---|---|---|---|---|
| W1 | 说法：`span` → `spans`（数组，至少一段）；说明加"同一件事只列一条"；校验逐段核逐字、按段查 context 夹带 | `axis_definitions.json`（axes.claims 的 instruction、output）；`axis_code/claims/checks.py` | 单测：多段 spans 通过、某段不在回答里被拒、整句与拆件不查重（靠说明，程序不判） | 完成（10-29） |
| W2 | 真实性输出里每条说法带 `spans`（原 `span`） | `axes.truthfulness.output`；`axis_code/truthfulness/synth.py` | 单测 | 完成（10-29） |
| W3 | 取证说明加"已取回的不再取第二份"；取证输出 `evidence` 换成 `records`、`calls`、`cite_records`（`items` 是模型交的，原样不动） | `loops.search_knowledge` 的 instruction、output；`axis_code/loops/search_knowledge/synth.py` | 单测：两条说法引同一条记录，`records` 里只一份；`calls` 每次调用一份；`window` 截法与原来一致 | 完成（10-29）；`items` 是模型交的不改，记录编号放程序字段 `cite_records` |
| W4 | 真实性、承载性说明里读证据那句改为按 `cite_records`、`records`、`calls` 找 | `axes.truthfulness.instruction`、`axes.carryability.instruction` | 加载无报错 | 完成（10-29）；承载性说明里没写证据格式，未改 |
| W5 | 归档：最近一批有几份返回、归档旧的后仍超阈值，同批按先后归档、只留最后一份 | `impl/core/axis_loop/loop.py` `_fit_context` | 单测：同批两份大返回，归档后不超限、留最后一份；单份超限仍失败 | 完成（10-29） |
| W6 | 离线核对：用 2e4f9747 存下的 C08、D16 取证返回跑新 synth，报大小变化；F01 说法抽取单步重放新旧各 3 次 | 重放脚本（`.claude/hillclimb/claims-assertion/`） | 见判据 | 待做 |
| W7 | 8036：实例 `axis_definitions.json` 与 `axis_code` 备份到 scratchpad 后同步，重启；F01、C08、B02 单跑，再 mcp 11 条全量 | 8036 | 见判据 | 完成（job `75fba8c1`，见 §13.2） |

不改：fulfillment（引 claim_id，不读 span）、main_verdict、expectations、blocking、过程轴；待定三项（修饰说法跟不跟随取证、"可一次交多条也可分几次"、回答讲自己做了什么的说法怎么核）不动。

W1 说明改动（原文 → 新文）：

- "claims 每项只含 claim_id（唯一非空标识）、claim、span、context、qualifies 五个键。" → "……claim、spans、context、qualifies 五个键。"
- 在"……以及回答给内容编的序号、排列本身。"之后加：

> 同一件事只列一条（唯一性原则：同一个东西只给一份，用到它的地方引用这一份）。是不是同一件看对象和说的事：叫法、措辞、数字写法不同也是同一件，说的值不同就是两件。回答在几处断言同一件事，只列一条，spans 记下每一处；一句话已经拆成几件列了，就不再另列整句。

- "span：这条说法在回答里的出处，逐字摘自 output_text 的连续原文，不改写；几条说法可以共用同一段 span。" → "spans：这条说法在回答里的出处，每处一段，每段逐字摘自 output_text 的连续原文，不改写；几条说法可以共用同一段。"
- "不得包含 span 里没有的内容" → "不得包含 spans 里没有的内容"；"共用同一段 span" → "spans 与那条数值说法相同"；例子里 `span="…"` → `spans=["…"]`，"三条共用 span" → "三条的 spans 相同"。

W3 取证说明在第 8 条之后加：

> 11. 已取回的不再取第二份（唯一性原则：同一个东西只给一份，用到它的地方引用这一份）：先按对象和范围查，查回的结果供清单里各条共用；已经取回的内容要再看，用 recall(call_id) 回看，不重查。上次没覆盖到——查询没执行、查回的不是这个对象、没读全——换方式再查，这不算重复。

W4 真实性说明："evidence（引文所在的整条记录 window、查询的工具与参数）" → "records（引文所在的整条记录；cite_records 按条列出每条引文的记录编号，与 citations 一一对应）、calls（每次查询的工具与参数，按引文的 ref 找）"。承载性说明同义改。

**判据**

- W6：C08、D16 取证返回字数下降，`records` 里没有重复记录；新旧两份对同一条说法给出的记录内容一致（只是不再重复）。F01 新说明下说法条数接近归并后的 40；逐组看合并的：没有不同对象或不同值被合成一条；原有说法的内容没丢。
- W7：F01 不再超上下文、出结论；C08 出结论或失败原因不再是取证返回撑爆上下文；B02 结论与 2e4f9747 一致或变化说得清。11 条全量对照 2e4f9747：主结论逐条比，原 verified 的不新增 refuted；报说法条数、取证调用数、输入 token、耗时的变化。
- 不达标：回到原则讨论，不加按 case 的规则。

### 13.1 实施与离线核对（2026-10-29）

- 改前副本 `scratchpad/repo-before-unique/`（`axis_definitions.json`、`axis_code/`、`loop.py`）。新单测 `tests/test_llm_probe_loop_uniqueness.py` 4 个、`tests/test_axis_loop_run.py` 归档 2 个；llm_probe_loop 与 axis_loop 相关 146 测试通过。没有别处读取证结果的 `evidence`。
- 偏差：alg 写的"引文上多一个 `record` 编号"会改模型交的 `items`，违反 `demand/axis_loop.md` §3.3.7；改为程序字段 `cite_records`（`{item_id: [记录编号]}`，与 citations 一一对应），alg §4.6 同步。
- W6 取证返回（8036 上存着的全部 25 份，按新格式重组，内容逐条可还原）：合计 244 万字 → 166 万字（68%）；单份 58%–96%。没到预计的 1/3：去重后整条记录仍占约 75%，原因是业务记录本身超过 3,000 字时 `window` 退回成引句前后各约 1,500 字的片段，同一次调用里引句不同、片段就不同（两两重叠约 10%），按"完全相同"去不掉；片段里还夹着业务返回的元数据块（evidence_id、bm25_score 等）。属 window 截法，不在本轮。

- 审查（10-29，aihacking / check / Bussiness）后补改：① `_fit_context` 判"最近一批"原用 `ref.endswith(f"c{i}")`，`c11` 会被当成 `c1`，改为取末尾 `c<序号>` 精确比，加单测；② `claims/checks.py`"spans 至少一段"是死分支（输出 schema `minItems: 1` 在业务校验之前已拦），删；③ 真实性说明两处旧写法（说法字段 `span`、"从 quote 或 window 里摘"）改为 `spans`、`records`；④ 说法、取证两处说明里的原则定义补全（需求 §3.8 要求定义一并写上）。147 测试通过。
- job `792c1b71`（F01/C08/B02 单跑）用的是 ③④ 之前同步的定义，停掉不用；同步最终版后直接跑 11 条全量，job `75fba8c1`（改前 8036 副本 `scratchpad/8036-before-unique/`）。

### 13.2 W7（2026-10-29，8036，mcp 11 条并发 4，job `75fba8c1`，对照 `2e4f9747`）

- 11/11 出结论（上次 9/11）。F01 没做成（与 `cc01fd7e` 同）；C08 做成了（`cc01fd7e` 不确定，上次没出结论）；其余 9 条主结论与上次相同。注意业务回答每次现跑，B02 这次回答又换了一版（如实说两款不是同一产品），主结论变化不全是评测改动带来的。
- 本批 0 条 refuted；没有原 verified 的新判 refuted。
- 说法：记了多处出现的 F01 19/38、B02 11/17、A02 3/8、C08 2/28、D16 1/23；逐条看 C08、F01 的合并，同一对象同一值，没有合错（两张保单各自的"交费有效"仍分开）。
- 用量：主 loop 调用合计 315 → 295。C08 调用 65 → 37、耗时 1509 → 1002 秒、输入 token 381 万 → 217 万、单次最大输入 17.7 万 → 10.9 万；D16 146 万 → 87 万；F01 这次跑完了，调用 46、1264 秒、197 万 token。单份取证返回最大值：D16 18.3 万 → 12.2 万字，A02 12.9 万 → 6.7 万字，C08 基本不变（17.8 万）。上一批逐次记录已被清掉一部分，token 只比得了两批都有记录的 7 条：866 万 → 773 万。
- 同批归档本批没有触发（11 条 archived 都是 0）。
- 剩下的判不了：F01 12 条查不到——金额单位 7 条（业务说明写金额不带单位，同 G01 老问题）、跨险种 / 跨保单合计 2 条（知识源没有合计算法）、回答讲自己做了什么 2 条（`claims.md` ⟡3）、"用户提到的产品名" 1 条；B02 隐性期望判不了，卡在回答说"词典中该产品是独立标准产品"这条查不到。


## 14. 多轮按轮列说法（2026-10-29（二）起，已实施）

依据：需求 `demand/claims.md` §2.6、C16（记录 `demand/draft-20261029b/README.md`）；方案 `spec/alg/knowledge-evidence.md` §3"多轮按轮列"、`spec/alg/fulfilled.md` §4、`spec/alg/axis_loop.md` §12.1。只改 llm_probe_loop；框架（`impl/core/axis_loop`）、llm_probe 不动。

| 步 | 内容 | 改哪 | 完成标准 |
|---|---|---|---|
| M1 | 说法读各轮交付：材料 `case.final_output` → `case.deliveries`；说明不写"最后一轮"，写"给了哪几轮就按哪几轮列"；`spans` 每段改为 `{turn, text}` | `axis_definitions.json`（axes.claims 的 materials、instruction、output） | 加载无报错；路径静态检查通过 |
| M2 | 说法校验：每段 `text` 到它 `turn` 那一轮的回答里核逐字，`turn` 须是材料里给了的轮；context 在任一轮回答或用户原话里逐字；夹带检查按段的 `text` 比 | `axis_code/claims/checks.py` | 单测：两轮各说一件通过；跨轮同一件一条两处通过；段落写错轮被拒；轮次不在材料里被拒 |
| M3 | 删 `case.final_output`：M1 后没人读 | `impl/projects/llm_probe_loop/eval_axes/materials.py`；`tests/test_llm_probe_loop_project.py`（可见性测试里的元组） | 全仓 grep 无引用；测试过 |
| M4 | 兑现：材料里真实性说法的投影加 `spans`；说明加"第 t 轮的期望只引出处里有第 t 轮的说法"；校验按期望的 `turn` 查所引说法的 `spans` | `axes.fulfillment` 的 materials、instruction；`axis_code/fulfillment/checks.py` | 单测：引同轮通过、引别轮被拒、一条说法跨两轮两轮都可引；没有核事实结果时不受影响 |
| M5 | 真实性：`spans` 原样往下传（synth 不改）；说明里"spans"一处不改；**输出 schema 的 `claims[].spans` 同改为 `{turn, text}`**（原计划写"不改"是漏看：第一次单跑 F01/E01 报"完整结果不合输出 schema：claims.0.spans.0 … is not of type 'string'"，补改后重跑） | `axes.truthfulness.output` | 补测 `test_truthfulness_result_with_turned_spans_fits_its_schema`（旧 schema 下会失败） |
| M6 | 测试：`tests/test_llm_probe_loop_uniqueness.py` 改用 `case.deliveries` 与 `{turn, text}`；补 M2、M4 的用例 | tests | 相关测试全过 |
| M7 | 8036：实例 `axis_definitions.json`、`axis_code` 与 `materials.py` 备份到 scratchpad 后同步，重启；先单跑 F01、E01（mcp），再三场景全量 33 条 | 8036 | 见判据 |

说法说明改动（原文 → 新文）：

- "回答 output_text 是材料 case.final_output，用户问题 question 是材料 case.user_turns。" → "回答是材料 case.deliveries：给了哪几轮就是哪几轮，每轮 {turn, output_text}；用户问题 question 是材料 case.user_turns。"
- "spans：这条说法在回答里的出处，每处一段，每段逐字摘自 output_text 的连续原文，不改写；几条说法可以共用同一段。" → "spans：这条说法在回答里的出处，每处一段 {turn, text}：turn 写这段出自哪一轮，text 逐字摘自那一轮 output_text 的连续原文，不改写；几条说法可以共用同一段；同一件事几轮都说了，仍只列一条，每轮的出处都记。"
- "context ……每段逐字摘自 output_text 或用户问题（question）的连续原文" → "……每段逐字摘自任一轮回答或用户问题（question）的连续原文"。
- "question 是用户各轮原话，按先后排列，output_text 回答的是最后一轮；用户问题仅作背景。" → "question 是用户各轮原话，按先后排列；第 n 轮的回答答的是第 n 句；用户问题仅作背景。"
- 例子里 `spans=["七天"]` → `spans=[{turn:"t1", text:"七天"}]`，其余同改。

兑现说明在 claim_refs 那一条后加："第 t 轮的期望只引出处（spans）里有第 t 轮的说法。"

不改：真实性的判定与取证、承载性、主结论、过程轴、期望（F01 第 2 轮"问题不变"没展开另记，`report/eval-main-axis/ISSUES.md` 第 13 条）；"查实没有 / 没查到"按用户定先不动。

**判据**

- 单跑：F01 第 1 轮报的累计已交保费有说法、有核事实结果；第 1 轮"累计已交保费""本轮回答事实都正确"两条不再因"没有引用结果值的说法"判不了。E01 第 1、2 轮同理。
- 全量 33 条对照上一批（mcp `75fba8c1`；agno、langfuse 用实例里现有结果）：单轮 case 主结论不因本次改动变化（变化要说得清是业务回答变了）；原 verified 的不新增 refuted；没有说法引错轮被收下；报说法条数、取证调用、输入 token、耗时的变化。
- agno、langfuse：说法多了，兑现仍按过程记录判，主结论不应因此变化。
- 不达标：回到原则讨论，不加按 case 的规则。

### 14.1 结果（2026-10-29，8036）

- 单跑（schema 补改后，job `93460141`）：E01 第 1 轮"名下保单"、第 2 轮"投保人"及两轮隐性正确由判不了变为做到；F01 撞 1500s 墙钟（88 条说法，真实性取证占 948s）。
- 全量 33 条（job `9835507d`，并发 4，6713s）：33/33 出结论，无一撞墙钟；mcp 11 条判断耗时合计 7019s → 6864s。没有说法引错轮被收下。
  - E01 t1/t2 期望出结论；F01 t2 两条做到，t1"累计已交保费"仍判不了，原因由"没有说法"变为"两张合计 7620 无算法出处"。
  - 主结论变化（mcp）：A02 做成了 → 不确定（列出"关于保单数量双方说法一致"，查不到；单轮，与本次无关）；D16 做成了 → 没做成（4 条"单位是元"由查不到变成有矛盾，依据是读法说明，真实性说明已有的一条没守住；与本次无关）。B02 没做成依据更实（手机尾号、"终身至2056年"两处有矛盾）。
  - agno 伏云平 做成了 → 没做成（后端 customer.search 报错后已兜回，见待议）；langfuse 客户号、任言琳 → 不确定（外层工具记录无正文，见待议）。
  - 拒收 1 → 72（E01 48、F01 24）：真实性把取证返回里 citations 的内部编号当依据编号；退回理由"同一次回复里拿到的要到下一次回复才能用"误导模型原样重交一轮。改为列出能过同一检查的 call_id（`impl/core/axis_loop/checks.py` `usable()`，承载性检查改用同一函数，备份 `8036-before-citeids/`）。复跑 E01、F01（job `4542f1c1`）两条都未引错，改动未在实跑中触发；F01 又撞墙钟（78 条说法，取证子任务 34 轮、732s）。

## 15. 说法以原文为基础（2026-10-29（三）起）

依据：需求 `demand/claims.md` §2.3、§3.8、C17（记录 `demand/draft-20261029c/README.md`）；方案 `spec/alg/knowledge-evidence.md` §3"拆开要拼得回去"、§5 判定第 1 步。只改 llm_probe_loop 的两段说明；框架、llm_probe、提交格式、校验、合成都不动；不加"拆错了"的记录字段（用户定）。

| 步 | 内容 | 改哪 | 完成标准 |
|---|---|---|---|
| N1 | 列说法"数和单位"段补拼得回去、数量级属于数值；加"保额75万元"例子 | `axes.claims.instruction` | 加载无报错；只这两段变 |
| N2 | 真实性第 1 步补：读 claim 带着它在 spans 原文里的意思；拆错了按原文里的意思判，reason 说明 | `axes.truthfulness.instruction` | 同上 |
| N3 | 8036：备份 `8036-before-spanread/`，同步实例 `axis_definitions.json`，重启；先单跑 E01，再 mcp 11 条全量 | 8036 | 见判据 |

说明改动（新增原文）：

- 列说法，"其余说法 qualifies 填空字符串。"后加："拆开后几条合起来要等于原文说的：数值说法就是原文说的那个量，万、亿、% 这类数量级属于数值，单位只留计量单位或币种。"；"乙账户"例子后加："又如"保额75万元"：claim="保额的数值是75万"（c1）；claim="保额的单位是元" qualifies=c1。"
- 真实性第 1 步后加："说法是它出处原文（spans）里的一件事，读 claim 要带着它在原文里的意思读；判的仍是这条 claim，不借原文去判它以外的事。claim 单拿出来和它在原文里的意思不一样时（如"75万元"拆出"数值是75"），按它在原文里的意思判，reason 里说明按什么意思判的。"

**判据**

- E01："75万元"不论怎么拆，数值都判核实；单位查不到不挡；t2 隐性正确不再因它判没做成。
- mcp 11 条：主结论逐条对照上一批；新增的核实逐条人工看，不是借"按原文意思"放过本该有矛盾的。
- 不达标：回到原则讨论，不加按 case 的规则。

### 15.1 结果（2026-10-29，8036）

- E01 单跑（job `499ec51b`）：业务这次回答没有金额，改动没被触发；主结论没做成（该给的没给），与前一致。
- 离线重发（同一份 E01 判卷记录，只换说明）：
  - 列说法：旧说明 2/2 拆成"数值是75 + 单位是万元"；新说明 3/3 拆成"数值是75万 + 单位是元"。说法条数 20–23 → 21–22。
  - 真实性（已拆错的"数值是75"）：旧说明 refuted 5 次；新说明 verified 2、refuted 6。原文在材料里，模型多数仍按 claim 字面判——这句兜底作用弱，起作用的是列说法那一处。
- mcp 11 条全量（job `c9f53dda`，并发 4）：11/11 出结论，无撞墙钟；判断耗时合计 6864s → 6429s。
  - 本批回答都没有"万 / 亿 / %"，单位改动未在实跑中触发；修饰说法 11 条全判查不到，无一判有矛盾。
  - 主结论：A02 不确定 → 做成了；D16 没做成 → 做成了（唯一 refuted 是业务真说错的"两位陈姓人士"，隐性正确为待定项未挡）；其余 9 条不变。
  - C08 撞上引错编号：第 5 批 20 条被拒（退回理由列出可引的 `truthfulness.c0`），第 6 批 20 条全部改对收下——§14.1 的退回理由改动首次在实跑中起作用。

## 16. 侦探指的记录按环节给（2026-10-29（二）起）

依据：方案 `spec/alg/axis_loop.md` §12.2（同日补）；需求不改（侦探仍只指路、不给理由，`demand/draft-20261025/README.md` Q6/Q7/Q9）。只改 llm_probe_loop；框架、llm_probe 不动。备份 `8036-before-leads/`（仓库 `axis_definitions.json`、`process_axes.py`，实例 `axis_definitions.json`）。

起因：langfuse 的工具调用外层 TOOL 记录只记结构，参数与返回记在它的子记录上（11 条里 9 条有工具调用，22 个全是这样）。侦探把子记录补成新环节，但给外层环节指的记录多半只写外层自己（真实 5 条里 4/13 带上子记录）；程序再把侦探指的记录按轴拉平成一串编号，"哪条是给哪个环节看的"丢了。实际偶尔把外层单独判成无法核，结论被卡成不确定（客户号、任言琳，9 条里 2 条）。trace 记录本身分发是齐的（子记录、`parent_ref` 都在材料里）。

| 步 | 内容 | 改哪 | 完成标准 |
|---|---|---|---|
| L1 | 侦探说明可疑环节一条补："source_refs 写全核这个环节要看的记录：环节端点之外，这个环节实际发生的内容还记在哪些记录上（如工具调用只记了结构，参数和返回记在它的子记录或别的记录里），一并写进来；" | `axes.trace_analysis.instruction` | 真实 5 条（实例临时改，测完已还原）：外层环节带上子记录 4/13 → 13/13 |
| L2 | 侦探给本轴某环节指的记录写进该环节 `links[].leads`（侦探补的新环节写它自己的 `source_refs`）；`views.leads` 只留指向别轴环节的（`borrowed`），不重复 | `process_axes.py` `analysis_result` | 单测 `test_detective_refs_for_a_link_ride_on_that_link_not_the_flat_list`；本应投影 `links[].{link_id, link_type, turn, input}` 不含 leads |
| L3 | 输出 schema：`views[].links[]` 加可选 `leads`（字符串数组） | `axes.trace_analysis.output` | 单测 `test_trace_analysis_result_with_link_leads_fits_its_schema` |
| L4 | 6 个实际轴说明："材料里有本轴环节两端的全部原文和侦探指出的记录" → "材料里有本轴环节两端的全部原文；一个环节的内容可能不只记在它自己的端点上，links 里每个环节的 leads 是侦探给这个环节指的记录，也是这个环节的证据：端点没有正文、但 leads 里的记录有，就按 leads 里的记录核，不判无法核；views 的 leads 是侦探指出本轴也要看的其他记录" | 6 个 `axes.<轴>.instruction` | 离线重发（客户号，外层单独成行的本应）：外层两行 无法核 4/4 → 达到 4/4（有效 2 次） |
| L5 | 8036 同步、重启；langfuse 11 条、agno 11 条全量 | 8036 | 见判据 |

**判据**

- langfuse：外层工具记录被判无法核的行数归零或下降；主结论对照上一批，变化逐条说得清。
- agno：主结论不因本次变化；侦探指的记录、实际材料大小与耗时报变化。
- 抽查：引 `links[].leads` 里的记录判达到的行，所引记录确是该环节的内容。
- 已知未处理：侦探补的新环节端点是整条记录时，本应材料里能看到它的输出字段（`input_view` 对"既是入口又是出口"的整条记录不摘），另立一项。

### 16.1 结果（2026-10-29，8036，langfuse job `440e0280`、agno job `a2570b58`，并发 4）

- 主结论（对照实例里上一份结果）：22 条里 21 条出结论；agno F01 撞 1500s 墙钟（上一份 1449s）。langfuse 11 条主结论全不变；客户号、任言琳对照 10-28 全量（不确定）为做成了，但这两条在本改动前的两次重跑里也已是做成了（原问题本就偶发）。agno 伏云平 没做成 → 做成了（业务这次没报错，与本改动无关）。
- 工具执行轴：22 条里不是"达到"的只剩 agno 不存在保单 E2 无法核（上一份就有）；外层空壳行判无法核 0。
- 侦探挂上：每条 case 都有带 `leads` 的环节（langfuse F01 25 个、B02 15 个）。
- 只凭 `links[].leads` 里的记录（不在环节端点上）判达到的行共 63 行；抽查 10 行：7 行所引记录确是该环节的内容（后端子记录的返回、参数），2 行偏弱（只引了请求编号或保单号，证明调用发生、没直接证明无报错），1 行引错（B02 tool_execution E10 引 llm.call 里的产品名当工具返回）。
- 耗时：22 条判断合计 16720s → 17613s（+5%）。实际材料（tool_execution `full`）langfuse F01 25.7 万字、B02 19.8 万字；改前大小未留存，无法对比。

## 17. 互不依赖的调用同一次回复里发（2026-10-29（二）起）

起因：agno、langfuse 15 条 case 500 次模型调用里 433 次（87%）一次回复只发一个工具调用；纯读材料轮次 195 轮、1883s，其中 126 轮读的全是任务一开始目录里就有的编号。框架本来会执行一次回复里的全部调用（客户端开着 `parallel_tool_calls`），慢在模型一轮只发一个。执行层不动：业务 MCP 照旧并发执行，启动子 loop 的工具、读材料、submit 照旧逐个执行；只改说法，不加配置（用户定：调用都可以同一次回复里发，执行按工具特点串或并）。

改动（`impl/core/axis_loop/loop.py`，备份 `8036-before-batching/loop.py`）：主 loop 规则第 3 条去掉"一次回复里也可以同时交多个"，第 8 条去掉"一次取齐……不要一条一条地读"，合成新第 9 条："互不依赖的工具调用，放在同一次回复里一起发：要读的几份材料、要查的几项数据、已经判完的几个任务，一次发出。后一个调用要用到前一个的返回时（先看结构再下钻、按搜索结果去取、交结果要引用刚取回的证据），才留到下一次回复，因为同一次回复里拿到的返回要到下一次回复才能引用。工具执行得很快，慢的是回复的来回次数。"子 loop 提示补同义一段。

离线（各 loop 第一次调用新旧各 4 次）：langfuse 实际第一次回复读的材料份数 2/1/1/2 → 3/4/3/3；agno 实际没变（材料目录 48.7 万字，第一步只看结构）；侦探略好；本应、mcp 取证本来就不是瓶颈。

实跑（8036 job `eedf5ce3`，并发 4，6 条长 case）：

| case | 模型调用 | 纯读轮次 | 判断秒 | 主结论 |
|---|---|---|---|---|
| agno F01 | 70 → 39 | 44 → 22 | 1502（撞墙钟）→ 1160 | 无 → 没做成 |
| langfuse F01 | 50 → 33 | 19 → 13 | 1442 → 1213 | 没做成 不变 |
| agno E01 | 47 → 34 | 20 → 16 | 1401 → 1271 | 没做成 不变 |
| agno B02 | 33 → 36 | 13 → 21 | 936 → 940 | 没做成 不变 |
| langfuse B02 | — | — | 957 → 826 | 没做成 不变 |
| langfuse E01 | — | — | 1308 → 1120 | 没做成 不变 |

判断秒合计 7546 → 6530（−13%）。调用 / 轮次的旧值取自上一轮存档的判卷记录（langfuse B02、E01 的旧记录不全，未比）。拒收里"同一次回复里引用"0 次。业务回答每次现跑，前后不完全可比。

## 18. 过程轴：本应写法三句、轴级说明由程序拼（2026-10-29（二）起，已实施）

依据：方案 `spec/alg/process-axes.md` §4、§5（10-29 修订）；需求不改。只改 llm_probe_loop；框架（`impl/core/axis_loop`）、llm_probe 不动。

| 步 | 内容 | 改哪 | 完成标准 |
|---|---|---|---|
| P1 | 6 个本应轴说明：expectations 一条改为"这条做错了，会让需求清单里哪几条没给到或给错，写它们的 expectation_id；只写会被它直接影响的，都影响不到时写 []；"；statement 一条后加两条（一条只要求一件事，附\"覆盖客户资料和名下保单两个查询\"拆两条的例子；statement 写必须成立什么，不写\"如某某调用\"，材料写明由哪个工具负责时才点名）；输出 `expectations` 描述同改 | `axes.<轴>_expected.instruction`、`.output` | 加载无报错；只这几处变 |
| P2 | 6 个实际轴：`reason` 标 `x-fill: program`；说明去掉"reason 一句话说本轴结论"，problems 的 phenomenon / impact 要求单独读也看得懂（哪一轮、哪一步、怎么了、影响什么） | `axes.<轴>.instruction`、`.output` | 同上 |
| P3 | 合成：`actual_result` 多返回 `reason`，按 `process-axes.md` §5 末的顺序拼 | `impl/projects/llm_probe_loop/process_axes.py` | 单测：problematic / sound 带上游 / not_evaluable（needs_external 与非）/ not_applicable 各一例的首行与条目 |
| P4 | 前端：过程轴说明按行显示（`.axes-reason{white-space:pre-line}`） | `impl/frontend/summary.html` | 页面上多行显示 |
| P5 | 8036：备份实例定义与代码后同步、重启；agno、langfuse 各 11 条全量 | 8036 | 见判据 |

离线（10-29，scratchpad `replay_expected.py`、`compose_reason2.py`）：本应三句——单独管客户资料、只挂客户资料期望的行 旧 0/12 → 新 12/12，"如 X 调用" 7 → 0；规划轴仍有同时挂两条的行，多为整合交付、收尾这类确实影响两件的，路由一类（agno"复合问题应走 Agent 编排"）没达到时仍会拖下"保单给到了"，归兑现（待议 #2）。程序拼说明：22 条 132 个过程轴，中位 39 字（模型写的 93 字）；"核不了""不适用"两处按上表调整拼法。

**判据**

- 主结论对照上一批（10-29 全量）：变化逐条说得清；agno 伏云平、A02 不再因 context_memory 一条挂上"保单给到了"判没做成。
- 本应：同一条里不再同时写客户资料与保单两个子问题；statement 不出现"如某某调用"。
- 前端：每个过程轴的说明首行与标签一致；没有计数套话。
- 耗时报变化（本应行数会变多）。
- 不达标：回到原则讨论，不加按 case 的规则。

### 18.1 实施（2026-10-29）

- P1：12 个过程轴里 6 个本应轴按上表改（三句）；备份 `8036-before-process-reason/`。
- P2、P3 改为：实际的 `reason` 仍由模型写，说明里写法换成"给读者的问题说明"（第几轮哪一步、引原文、违背哪条本应、影响用户哪部分结果；上游写明来源；核不了写缺什么；没问题写核了什么、凭哪段原文；不复述计数，不写撑不住的概括）。当天先试过"程序拼"（`axis_reason`），agno 11 条实跑后看：条目 observed 与本应用字重合中位 0.86，拼出来没有信息量，已删（代码与测试），备份 `8036-before-model-reason/`。
- P4：`summary.html` `.axes-reason` 加 `white-space:pre-line`（保留）。
- 离线（agno 新跑 5 条，判完后按新写法写 6 轴 reason）：E01、F01、客户号、不存在保单都能看出哪里有问题 / 为什么核不了 / 为什么没问题；B02"等待期为什么没给"只能到"只看 trace 证明不了全库没有"。已知：E01 工具执行与知识数据两轴对"条款没返回"的口径不一致；每轴 150–300 字。
- 相关测试 229 条全过。

## 19. 去掉照评测 case 写的说明（2026-11-01 起）

依据：过拟合检查（2026-11-01，用户确认）——共用的轴说明里有几处例子照评测题原文写，还有两条只对保险问答系统成立的"通用职责"。方案 `spec/alg/process-axes.md` §3.4（11-01 修订）、`spec/alg/axis_loop.md` 本应轴一行；需求不改。只改 llm_probe_loop；框架、llm_probe 不动。

| 步 | 内容 | 改哪 | 完成标准 |
|---|---|---|---|
| N1 | 6 个本应轴：拆条例子「覆盖客户资料和名下保单两个查询」换成「给出明天北京的天气和出行建议」拆「拿到明天北京的天气」「给出出行建议」；`basis` 描述去掉"通用职责写 D1" | `axes.<轴>_expected.instruction`、`.output` | 加载无报错 |
| N2 | 列说法：例子"保额75万元"换成"行驶里程3.5万公里"（数值 3.5 万、单位公里） | `axes.claims.instruction` | 同上 |
| N3 | 真实性：删括号"（如"75万元"拆出"数值是75"）"，原则句不动 | `axes.truthfulness.instruction` | 同上 |
| N4 | 上下文本应：删"通用职责 D1/D2"一段；两条原文移到保险场景（agno、langfuse；8036 实例另含 ui-verify-agno）`context_memory_expected` 的描述里 | `axes.context_memory_expected.instruction`、`capability_map.json` | 测试：轴定义里没有"执行余量""PARTIAL"，两个场景的 axis.note 里有 |
| N5 | 程序：删 `STANDING_DUTIES`、`duty_of`、职责按轮合并与输出里的 `standing_duty(ies)`；`check_expected` 去掉不再用的 `axis` 参数 | `process_axes.py`、`axis_code/*_expected/checks.py` | 相关测试全过 |
| N6 | 6 个实际轴：修好 10-29 改坏的一句（"以及之前写定的本应清单（不能改）"接到了 views 的 leads 后面），本应清单放回"材料里有…"一句 | `axes.<轴>.instruction` | 同上 |

**判据**

- 离线：同一输入改前改后对比——列说法用真实回答"保额 30万元"及改成 75 万、120 万的变体；本应用 10-31 的 E01（agno、langfuse）、保费+免责、保单+投保人、两客户共 5 条记录。新例子不比旧例子差；差了那一条不换，回来讨论。
- 实跑：33 条全量对照 10-31（28/33、有害拖累 4 条）；之后补非保险场景的留出验证。
- 已知：D2 移到场景后在保险场景照常生效，A02、E01 的拖累不因此消失（归兑现强制引用，待定 A/B）；同一轮同一条职责不再合并，组成计数可能多一两行，轴结论不变。

### 19.1 结果与撤回（2026-11-01，8036 job `7f82c4a2`，33 条）

- 主结论 25/33（10-31 为 28/33）。改对 2 条（mcp 任言琳、agno A02）；改错 4 条（agno 客户号、任言琳、G01，langfuse D16）全因 N4：D1/D2 进了场景描述后，模型把它和"保留目标与前序结果"合成一行，一件没达到整行挂的需求全被拖下（执行余量拖下的期望 9 → 17）。mcp D16 判不确定是比较类说法查不到，与本次无关。判卷总耗时 24247 → 21226 s，调用 819 → 766，被拒 134 → 79。
- 撤回 N4 的场景部分：D1、D2 不再专门检查，场景描述删掉（见 §20）。

## 20. 唯一性原则补"一份只装一件事"，写进系统提示（2026-11-01 起）

依据：需求 `demand/axis_loop.md` §3.8、L11（11-01 修订）；方案 `spec/alg/axis_loop.md` §5.1、`spec/alg/process-axes.md` §4（11-01）。

| 步 | 内容 | 改哪 | 完成标准 |
|---|---|---|---|
| U1 | 系统提示加第 10 条：唯一性原则全文（一件事只给一份，一份只装一件事） | `impl/core/axis_loop/loop.py` `SYSTEM` | 测试：只出现一次 |
| U2 | 删各轴的拆分句与唯一性副本：列说法（"一句话断言几件就几条""唯一性原则"括号、"不切碎"、"拆开后合起来等于原文"前缀）、需求清单（"一个结果维度（沿用原轴1）""并列要求分别列项"、"完整、独立可核验"）、6 个本应轴（"一条只要求一件事……"整行）；删 4 处文档出处括号。取证子任务（独立上下文、子系统提示）的唯一性副本保留 | `axis_definitions.json` | 测试：各轴说明里没有"唯一性原则" |
| U3 | 场景描述删 D1、D2（仓库 agno、langfuse；实例另含 ui-verify-agno），恢复到 11-01 之前 | `capability_map.json` | 与改前一致 |
| U4 | 测试：删执行余量那条，加唯一性原则只一份 | `tests/test_llm_probe_loop_process.py` | 相关测试全过 |

**判据**：离线同一输入改前改后对比——本应（11-01 判错的 4 条 + 前次 5 条）一行连几件事的比例下降、没达到又挂需求的合并行消失、行数涨幅说清；列说法（"保额 30万元"及变体）拆法不变差；需求清单拆法不变差、隐性期望不被拆。都不差再跑 agno、langfuse 22 条。

### 20.1 离线结果与定稿（2026-11-01）

- U1–U4 离线（8 条记录各重放 3～4 次）：列说法、需求清单拆法与条数不变；本应只靠系统提示拆不开（一行挂 ≥2 需求 31% → 45%）。各轴再点名原则后（"列 X 遵循唯一性原则（系统规则 10）：一条只装一件能单独判……的事，同一件事只列一条"）略好（41%），仍按环节打包。
- 用户定：只改 prompt；轴里点名原则用上面这版；执行余量由场景决定不评——agno、langfuse、ui-verify-agno 上下文本应的描述加"被测系统提示词里的「执行余量」……只是给模型的运行参考，本场景不评它：本应不写这一项，它更新没更新都不算问题。"通用说明里不提。
- 离线（agno 任言琳、G01，langfuse D16 各 5 次）：写到余量的本应 0 行（改前 11 行）。
- 8036 同步（备份 `8036-before-unique3/`）、重启，agno + langfuse 22 条 job `2b1e40e3`。
- job `2b1e40e3` 结果：主结论 20/22（11-01 同 22 条 16/22，10-31 19/22）。11-01 被执行余量拖下的 4 条（agno 客户号、任言琳、G01，langfuse D16）都回到做成了；本应 707 行里专门评余量的 0 行；1 行（agno C08 编排"结束时机"）拿余量提示当依据，写的是"预算充裕时不提前收尾"，C08 主结论做成了、没被拖；另有 11 处出现在 not_covered 里说明不评。langfuse G01 本次判没做成是对的：业务降级回了兜底句，没做到"只回答金额"。仍错 2 条为保单不存在（agno、langfuse neg-unknown，"查实没有"未接上，暂不动）。效率：判卷 16346 s（11-01 16151）、调用 552（552）、被拒 60（65）。一行挂 ≥2 需求仍 65%（462/707），未处理。
- mcp 11 条 job `d20f633a`：判对 8 条。bizno、D16 业务这次回答与前次不同（bizno 答对了；D16 把严言琳的平安 VIP 说成 1，原文为 null），判做成了 / 没做成都对；C08 "名下保单数量是 2"查不到判不确定（推算说法一类）；F01 真实性反复引用取证子任务里的记录编号（`search_knowledge#11.c5`，10-31 也出现过 70 次）被拒 37 次，超 1500 s 墙钟没出结论。33 条合计 28/33（11-01 25/33，10-31 28/33），判卷 25047 s、调用 816、被拒 98（其中 F01 38）。
