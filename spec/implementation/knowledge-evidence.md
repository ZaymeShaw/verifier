# 知识查证实施记录

> 更新：2026-10-14。本文持续维护实施步骤、状态、验证证据和未决事项。
> 当前阶段：P0–P9 完成（离线 87 passed；对照实验见 `report/knowledge-evidence-20261014/RESULT.md`）。待用户：复核长回答标注、定抽取口径、决定是否提交。

## 1. 三类文档的分工

| 文档 | 回答的问题 | 入口 |
|---|---|---|
| 需求 | 要解决什么、要什么、不做什么、怎么验收 | [核事实需求](../../demand/claims.md)（原知识查证需求 2026-10-20 并入；对知识源的要求见 [信息源需求](../../demand/information_sources.md) §4） |
| 方案 | 怎么分工、结构与规则 | [知识查证方案](../alg/knowledge-evidence.md) |
| 实施 | 改哪里、按什么顺序、做到哪、验证证据 | 本文 |

三者冲突时，在本文第 6 节记差异，回对应文档修订；不在实施里偷改口径。代码存在、离线测试通过、真实运行通过分别记录，不互相替代。

## 2. 实施约束

- **隔离**：全部在 worktree `verifier-notrace`（分支 `exp/notrace-basic`，未提交）。不碰主目录，不影响另一进程的优化工作。不改过程六轴、trace_analysis、主判。
- **环境**：只用 `.env` 的 `PYTHON_EXECUTABLE`（agno 环境）。本期不需要新包；如需要，先带版本冻结 dry-run，确认零升级后再问。
- **不保留兼容**（AGENTS.md）：真实性的旧检索路径、旧引用格式直接删；预设数据直接迁，不写 migration 或 fallback。
- **业务服务**：用现有实例，不重启 insurance 后端（18062）。8042 测试实例是本会话起的，代码改完由我重启。
- **提交**：用户说再提交。

## 3. 设计落点（对应方案）

### 3.1 回执台账：统一 call_id（方案 §4.3）

不改 `es_tools` / `material_tools` / `mcp_tools` 内部，**在 loop 这一层统一包一层**：

```text
knowledge_loop/ledger.py
  Ledger
    wrap(tools: list[VerifiableTool], catalog) -> list[VerifiableTool]
      每次调用：分配 call_id = k<n>；按工具名/参数得出 source（es:// 取 index 参数，material:// 取 material_id，
      mcp:// 取工具名前缀）；执行原函数；把模型看到的返回对象原样存进台账；返回值里加上 call_id。
      返回带 error → 台账记 ok=false。
    entry(call_id) -> {call_id, source, tool, args, result, ok, batch}
    quote_ok(call_id, quote) -> bool       quote 逐字（沿用 quote_in_text 的归一）出现在该次返回的任一字符串叶子里
    window(call_id, quote, chars=500) -> str   真实性判定用的前后窗口
```

- 证据 = **模型实际看到的返回**。MCP 返回被截断时，后面的内容要用 `mcp_read` 翻页，翻出来的页也是一次带 call_id 的返回，可以引用。MCP 自己的 `mcp://src#n` 只作翻页句柄。
- 现有 `sources.build_tools` 返回的是 agno 形态，用 `process_loop/tools.dossier_tools` 的同一做法还原成 `VerifiableTool` 再包。
- `material://` 走 `expand_sources(..., material_catalog=True)`，全部进目录，不内联：内联文本没有回执，无法引用。

### 3.2 待查项来源（方案 §3）

- `eval_axes/types.py` 的 `AxisType` 加一个可选字段 `knowledge_items: Callable[[inputs, axis, runtime], list[Item]] | None`。
- 知识查证轴运行时，从 `runtime.enabled_axes` 里找出声明了 `knowledge_items` 的轴，依次调用，合并成清单：`item_id` 加来源前缀防撞，`origin` = 轴 id。
- 真实性声明 `knowledge_items = extract_claims`。`_EXTRACT_SYSTEM`、`_claims`、一次修复，从 `truthfulness.py` 原样搬到 `knowledge_loop/extract.py`，产出 `kind='claim'`。
- 没有任何启用的轴声明来源 → 知识查证 `not_applicable`（"没有启用需要知识依据的轴"）。来源都返回空 → 成功，案卷为空。

### 3.3 查证 loop（方案 §4）

```text
knowledge_loop/loop.py
  SYSTEM                系统提示词：角色、两种结果、归属、正反都查、全引不挑、没找到要写查了什么、
                        数字等价写法、预算；ES 检索语义沿用现在 _VERIFY_SYSTEM 的相应段落
  render_input(...)     首条消息：展开后的场景描述 + 知识源目录 + ES 字段骨架 + 待查清单 + 用户问题
  Checklist(Hook)       state：items、accepted{item_id: 提交}；
                        stop → 全部被接受才 Done，否则 Continue("还差：…")；ready_to_finish → 全部被接受
  submit_item           验收规则见方案 §4.4，逐条报拒绝原因
  KnowledgeLoop         组装 ToolLoop：tools = ledger.wrap(知识源工具) + submit_item；
                        completion_hook = Checklist；budget = BudgetStop(...)；end → 案卷
```

- 同批不可见：`submit_item` 只认此前批次的台账条目。台账记录每条的 `batch`，校验时和当前调用的 batch 比较。
- 预算初值：`tool_calls = 16 + 6n`、`llm_calls = 8 + 3n`、`seconds = 900`（n = 条数）。P7 校准后回填。
- 模型客户端沿用 `trace_analysis._AnalysisClient` 的做法：每步检查轴时间；端点失败转成 `AxisRequestFailed`。角色 `truthfulness`，effort `low`。

### 3.4 知识查证轴（方案 §6）

`eval_axes/adapters/knowledge_evidence.py`：

- 被测系统调用失败 → `not_applicable`（同现状）。场景框没有知识源引用 → `not_applicable`。
- 抽取失败 → `failed`。loop 未完成（预算 / 阻断上限）→ `failed`，失败原因带最后一次拒绝原因、已接受条数，**不产出部分案卷**。
- `output = {items, searches, sources, coverage, errors}`。`searches` 来自台账。`coverage = {items, found, not_found, by_origin}`。
- `summary.items`：key = 待查项原文（同 `_claim_label`），value = found / not_found，reason = note。
- 注册到 `registry._REGISTERED`，排在 truthfulness 前面。

### 3.5 真实性改造（方案 §5）

- `depend_on = (Dependency('knowledge_evidence'),)`；`inputs` 加 `Input('evidence', source='axis.knowledge_evidence.output', fields=('items', 'sources'))`。
- `scenario_fields`：`description` 改为非必填、`expand='prompt_load'`，只作判定口径补充。
- 只取 `origin == 'truthfulness'` 的条目：
  - `not_found` → `unverifiable`，不调模型；
  - `found` → 一次不带工具的 `complete_json`，输入为条目 + 各引用（quote + 窗口），输出 `reason/verdict/citations`。程序校验 citations 是给定引用的子集，不合格修复一次。
- 输出形状不变。引用展开成 `{source, ref: call_id, note: quote}`，能力兑现、前端、导出都不改。
- 上游 `not_applicable` → 真实性也 `not_applicable`。现在 runner 对必需依赖未成功一律 `blocked`，要在 `_run_one` 第 2 步加一条：必需上游全部是 `not_applicable` 时，本轴 `not_applicable`，原因带上游的原因。改 runner 前先看其他轴是否受影响（目前只有能力兑现可选依赖真实性，不受影响）。
- 删除：`_VERIFY_SYSTEM`、`_verify_result`、`_outline_sources`、逐断言检索循环，以及对 `EsTools.verify_quote` / `verify_mcp_quote` / `verify_material_quote` 的引用。删完后若这些函数已无调用方，一并删除；承载性仍在用的保留。

### 3.6 校验与预设迁移（方案 §7）

- `validate.validate_scenario_axes`：真实性框 `description` 里出现 `{es://` / `{mcp://` / `{material://` → 报错"知识源引用放到知识查证框"。
- 迁移脚本放在 `report/knowledge-evidence-<日期>/migrate_presets.py`，一次性使用，不进 impl：
  - 处理两处 `capability_map.json`：仓库 `impl/data/llm_probe/`、实例 `.runtime/instances/inst-8dd281076ebd43fa/data/llm_probe/`，各 2 个真实性框；
  - 新建 `knowledge_evidence` 框（`enabled` 同真实性），描述 = 原真实性描述；真实性框描述清空；
  - 先备份，跑完打印前后差异给我核对。
- `knowledge_sources.json` 的删除保护（`_referencing_presets`）按全文找引用，不用改。

## 4. 实施步骤与状态

| 步 | 内容 | 产出 / 验证 | 状态 |
|---|---|---|---|
| P0 | **基线**：动代码前，用现有实现跑长回答样本 | 首跑被我中途改登记数据污染（r1/r3 的 X1 报"未知字段 tools"）；另发现抽取对 Markdown 加粗逐字失败（见 §6）。改为在 scratchpad 副本（第三轮代码 + 同一抽取修补）重跑：`old-p1..p3`（长回答）、`o1..o3`（F/L）、`m1..m3`（M）。未修补的首跑留作"修补前抽取失败率"数据 | 长回答完成；F/L/M 进行中 |
| P0.1 | **长回答样本**：18062 问 5 个多事项问题，取 X1 贷款 / X3 理赔 / X4 复效 3 条标注 | `long-raw/`、`samples_long.py`、`kb/`。首版标注漏查（4 处误标"查不到"），补查后修订；**待用户复核** | 待复核 |
| P1 | 证据编号：**不另建台账**，直接用 ToolLoop History（§6） | `knowledge_loop/evidence.py`；单测 | 完成 |
| P2 | 待查项来源字段 `AxisType.knowledge_items` + `extract.py` 搬迁 | 单测 | 完成 |
| P3 | 查证 loop：Checklist、submit_item 验收、提示词、预算 | `knowledge_loop/loop.py`；`tests/test_knowledge_loop.py` 16 条 | 完成 |
| P4 | 知识查证轴 adapter + 注册 + 校验 | `adapters/knowledge_evidence.py`；validate：非目录展开的框写 es/mcp 引用报错 | 完成 |
| P5 | 真实性改造 + runner 的 not_applicable 传递 | `adapters/truthfulness.py` 重写；`runner._run_one` 必需上游全 n/a → 本轴 n/a | 完成 |
| P6 | 预设迁移 + 重启 8042 | 仓库与实例两处 `capability_map.json` 各 2 个预设已迁（按句拆：带引用的句子归查证，其余留真实性作判定口径；有备份）；8042 已重启；前端（8042 资料页）已看：知识查证框在真实性之前，描述与依赖提示正确，无控制台错误 | 完成 |
| P7 | 对照实验 | 新旧各 3 轮全部跑完：F/L 持平（96%）、M 持平（100%）、长回答 62%→87%、轴失败 4/9→0/9；模型调用约 1.5–2 倍。详见 RESULT.md | 完成 |
| P8 | MCP 零改动演示 | `demo_mcp/`：最小 FAQ MCP（fastmcp），经 8042 API 登记，场景引用后查证；代码指纹前后一致；4 条事实全对（免赔额说错被 refuted）。演示途中发现并修了 2 个评测器问题（§6） | 完成 |
| P9 | RESULT.md、回填、回修方案 | RESULT.md 已写；方案 §4.3、§7 已回修；旧实现结果拷入 `baseline/` 可复算 | 完成 |

每步完成后在本表更新状态，并在第 5 节记证据（命令、产物路径、数字）。

## 5. 验证证据

- 离线：`tests/test_knowledge_loop.py`、`tests/test_llm_probe_eval_axes.py` 共 87 passed。
- 真实运行：`report/knowledge-evidence-20261014/RESULT.md`（新旧各 63 次案例运行，同一标注、同一打分脚本）。
- 零改动演示：`report/knowledge-evidence-20261014/demo_mcp/`（代码指纹 `code_hash.txt` 前后一致）。
- insurance e2e 无 trace 对照（44 轮 × 3）：`RESULT.md`「insurance e2e 对照」。轴失败从 93/132 降到 11/132；分歧事实中新版对 24/30。但新版 refuted 34 条里 23 条错判，根源在判定案卷（窗口 ±500 字切断结构化记录、不带调用参数、把工具固定提示当限定条件）和知识源身份写死。

## 6. 与需求 / 方案的差异

- 方案 §4.3 / 本文 §3.1 写"补存返回原文、loop 层包一层台账"。实施发现 ToolLoop 的 History.calls 已记下每次调用的参数、返回与批次，pre_tool 只看得到此前批次（正好是"同批不可见"），于是**不建台账**：call_id = `c<调用序号>`，由 post_tool hook 盖进返回；核对直接查 History。证据口径 = 模型实际看到的返回（含 JSON 字符串里解出的字段）。
- 抽取逐字校验：长回答常带 Markdown 加粗，模型摘句不带 `**`，原规则判"不是原文"，抽取直接失败（基线 3 轮里 X3 两轮、X1 一轮因此失败）。改为比对前两边去掉空白和 `*`、反引号；改了字仍判失败（新增单测）。原单测"`答 复` 不算逐字"随之改为"`答案` 不算"——**这是有意改标准**，空白不算内容。为公平，基线副本打同样补丁。
- MCP 工具白名单（需求 §2.7"只读"）原计划里漏了：登记加必填 `tools`，评测只暴露列出的工具；insurance-tools 只放开 product_knowledge / benefit_info / general_qa。
- 演示发现的评测器问题：① MCP 返回里自带的翻页句柄也叫 `call_id`，盖章时被它覆盖，模型引用了错的编号、全部提交被拒——翻页句柄改名 `page_id`，盖章放最后，加回归单测；② MCP 入参没写 description 时工具协议拒收——评测侧补中性占位，不要求业务方改 schema。①影响了第一次启动的新实现实验，已中止重跑（`aborted/`）。
- 删除：`verify_mcp_quote`、`_string_leaves`（只剩旧真实性用），对应单测改为只测引用格式。
- 预设整表保存（`/api/capability/save`）被另一预设 `insurance-agno-e2e` 的既有问题挡住（`sqlite_path` 物理绝对路径），与本次无关，未动它；演示改用脚本给预设。
- 方案没写 runner 的 `not_applicable` 传递，实施需要（§3.5），P5 后回补到方案。

### 6.1 v8 落地（2026-10-18，合并工作区 verifier-integrate）

起因：三场景对照批次（`report/integrate-verify-20261018/`）里 MCP 场景扩展兑现轴 3/10 与主判不一致，查原始数据：
D16 业务直接引用客户详情字段 `annPremAmt`=4156.6，查证只读了客户详情 53,765 字的前 6,000，没找到便自算合计再判冲突（`information_sources.md` S4）；
F01 判定把业务工具提示"不能跨险种汇总"当冲突依据（S8）。两处在 v8 实验里已有修法，按方案 §3 / §4.1 / §5 采用：

- `variant-v8.patch` 原样合入（实验目录 `verifier-notrace/report/knowledge-evidence-20261014/`）：判定一条边界；拆说法；`mcp_find`；引用附查询工具与参数、整条记录窗口；登记 `description` 作 `notes` 给查证和判定；MCP 身份 `{request.<字段>}`；业务描述资料 `materials/insurance-business`。
- 数据：仓库与实例两处 `knowledge_sources.json`、`materials/insurance-business` 同步；实例预设 `verify-insurance-mcp` 的知识查证框追加"业务说明见 {material://llm_probe/insurance-business}。"（实例备份 `capability_map.json.bak-before-v8`）。
- 方案 §3、§4.1、§5 三处 ⟡ 改为采用；§4.3 / §4.6 补身份绑定、`mcp_find` 与判定上下文。
- 实验补丁不删：Terminal1 的工作区尚未合入，等两条线合回主线时一并清理。
- 验证（8031，`verify-insurance-mcp` 10 条；业务每次重跑，回答与上一批不同）：测试全量失败集合与未打补丁副本相同（100 条既有失败，无新增）。
  - 客户号查人：核实不了 4 → 0；A02：3 → 0（`mcp_find` 找到原先漏看的字段）。B02 本次回答未再说"共 2 张"，无冲突判定。
  - F01：合计不再判冲突；但回答给金额补了"元"，业务数据不带单位，7 条判核实不了，扩展兑现因此 not_evaluable（S7"金额单位"仍待定）。
  - D16：4156.6 由冲突变为核实不了，但仍没找到客户详情里的 `annPremAmt`：查证在客户详情上搜的是 education，在保单上搜 sum_ins / year_pay_prem，没搜"年缴保费"。S4 只修了一半。另判出业务把两人手机号脱敏写错（199****2141，原文 19909221141），核对原文属实。
  - dev 后端 17:16 起"查数据"一步连续超时（RemoteProtocolError / 后端服务暂时不可用），D16、F01、C08 首轮作废，恢复后重跑。

## 7. 未决

- 长回答样本的标准答案由用户复核（P0.1）。首版标注漏查过一次，说明这个业务库对查询措辞很敏感，人工标注也会漏。
- 预算和 effort 的最终值待 P7 实验后定。
- ~~判定案卷要补调用参数、按结构取窗口、判定提示补 hint 规则；知识源身份改成从样本请求取（改登记协议）~~：2026-10-18 随 v8 落地（§6.1）。险种行加总口径仍按方案 §5"算出来的值"处理，未另定。
