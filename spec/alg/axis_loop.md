# 评测轴任务化（axis loop）方案

> 状态：草案（2026-10-21），对着 `demand/axis_loop.md` 打磨，已经过两轮方案 grill（结论记在各节，标注"10-21 定"）。2026-10-22 按 dev 对比后的 grill 修订（标注"10-22 定"）：独立运行的轴、分发脚本、公共 loop 工具、去掉"轴自带子 loop"与带参数的内置材料、实施中的偏差回填。需求与本文冲突时以需求为准，回来修本文。
> 结论口径以 `demand/main_axis.md`、`expectations.md`、`claims.md`、`process_axes.md` 为准；本文只改"怎么组织、怎么执行"，不改"判什么"。
> 内核：`impl/core/tool_loop`（`spec/adapter/tool-loop-plan-20260922.md`），本文不改它的接口。
> 实施记录写在 `spec/implementation/axis_loop.md`（本文确认后再写）。
> 2026-10-25 第二期 grill 修订（需求 `demand/axis_loop.md` 同日修订，记录 `demand/draft-20261025/README.md`）：loop 定义取代"主 loop / 独立运行的轴 / 公共 loop 工具"（§3.3、§6）；大材料先目录后按需读（§4.4、§9）；信息源检查工具与 trace 采集（§8）；第二期展开（§12.2）。
> 2026-10-29 补（需求 `demand/axis_loop.md` §3.8 唯一性原则、§5.3）：§9 第 2 条归档补"同一批里有几份返回"的情况。
> 2026-10-29（二）补（§12.2）：侦探指的记录按环节给。侦探可疑环节的 `source_refs` 写全核这个环节要看的记录；侦探给本轴环节指的记录写进那个环节（`links[].leads`），保留"哪些记录是给哪个环节看的"；指向别轴环节、侦探点名本轴也用得上的，照旧放进 `views.leads`；实际的说明讲清 leads 的用意。侦探仍只指路、不给理由（`demand/draft-20261025/README.md` Q6/Q7/Q9 不变），本应仍看不到 leads。
> 2026-11-01 补（需求 `demand/axis_loop.md` §3.8 补"一份只装一件事"、L11）：§5.1 系统提示加唯一性原则全文（两半都写），各轴说明里不再各抄一份、也不再各写拆分句（说法、需求、本应三轴原有的拆分句删掉，只留各轴自己的细则）。
> 标 ⟡ 的条目待用户确认，或者需要试运行后再定。

# 第一章：方案

## 1. 总体

```text
轴定义存储（页面编辑）              材料注册表（代码里的字典）          信息源登记（MCP 实例）
  axes：每个轴的配置 + 说明           case.* / scenario.* / axis.*         knowledge / trace
  loops：每个 loop 的名字、怎么启动     + result.<轴id>（由输出 schema 生成）  + 检查工具
  可选上传：checks.py / synth.py / 各 loop 的 dispatch.py
              │                              │                               │
              └──────────────┬───────────────┴───────────────────────────────┘
                             ▼
case ─► 加载：场景启用的轴 → 依赖、白名单、工具类别、loop 图检查（fail fast）
                             ▼
        CaseRun（一个 case 一个）：按 loop 定义一个一个起 loop，每个 loop 是一个搭在 ToolLoop 上的 AxisLoop
          工具（每个 loop 从头到尾固定）：submit、recall、read_material、信息源工具、选用的被调用启动的 loop
          hooks：
            start / post_batch  台账：谁出现、谁作废、跑程序任务、该起哪个 loop → 推送消息
            pre_tool            门禁（工具类别没解锁就拒）；submit 走验收流水线
            post_tool           给每个返回盖 call_id
            stop                本 loop 已出现的任务都完成、没有作废待重交
                             ▼
        报告（与现有 build_report 同形）
```

- 任务机制与项目无关，放在 `impl/core/axis_loop/`。轴定义、loop 定义、材料注册表的项目部分、内置信息源由项目提供。
- 模型只做三件事：读推送来的任务；调工具（读材料、信息源、被调用启动的 loop）；调 submit。顺序由模型自己定（需求 §3.2.6）。

## 2. 项目与代码落点（10-21 定）

### 2.1 新项目 `llm_probe_loop`

- 整体复制 `impl/projects/llm_probe/` 到 `impl/projects/llm_probe_loop/`。26 个文件里的 91 处 `impl.projects.llm_probe` 自引用、3 处写死的项目 id 批量改名。
- 原样保留，与 loop 无关的部分：跑业务（`live.py`、`live_schema.py`、`show_schema.py`、`adapter.py`、`mock.py`）、场景与资料（`capability.py`、`materials.yaml`、`schema/`）、trace 采集（`business_trace/` 的采集部分）、旧判官与归因（`need_judge.py`、`text_carrier.py`、`claims.py`、`attribute.py`、`tools.py`、`material_tools.py`）。
- 替换掉的部分：`eval_axes/`、`knowledge_loop/`、`process_loop/` 删除；`judge.py` 中调用评测的入口改为调用 axis loop。
- 数据：建项目时把 llm_probe 现有的场景预设、知识源登记拷一份快照到 `impl/data/llm_probe_loop/`。两边以后各自维护，不要求严格同源（10-21 用户定）。

### 2.2 不影响其他项目

- `service.py` 里 12 处 `project == "llm_probe"` 改成 `project in EVAL_AXES_PROJECTS`，其中 `EVAL_AXES_PROJECTS = {"llm_probe", "llm_probe_loop"}`。`from ..projects.llm_probe.xxx import` 改成按项目 id 取模块。
- 前端 13 处写死（`live.html` 3、`materials.html` 6、`summary.html` 2、`context.html` 1、`tool_loop_lab.html` 1）做同样的处理。
- `core/table_view.py` 里对 `llm_probe.eval_axes.registry` 的硬 import 改成按项目取。
- 不在集合里的项目，行为和现在完全一样。分出胜负后，集合缩回一个。

### 2.3 代码位置

| 位置 | 放什么 |
|---|---|
| `impl/core/axis_loop/` | 轴定义的加载与校验、材料表与白名单取值、台账、门禁、验收流水线、视图、标准校验库、子 loop 运行器、AxisLoop 组装、报告组装 |
| `impl/projects/llm_probe_loop/axis_loop.py` | 项目接入：从 RunTrace 构造 case；登记本项目的内置材料取值函数；出 `build_report` 同形报告 |
| `impl/data/llm_probe_loop/axis_definitions.json` | 轴定义存储（§3） |
| `impl/data/llm_probe_loop/axis_code/<轴id>/` | 上传的 `checks.py`、`synth.py` |
| `impl/data/llm_probe_loop/axis_code/loops/<loop名>/` | loop 的 `dispatch.py`；被调用启动的 loop 的 `checks.py`、`synth.py`（原 `axis_code/shared/<名>/`，10-25 挪） |

### 2.4 页面：先能从零配出一个场景（P10 第一步，10-27 定，待确认）

目标：新开一个端口，在资料管理页上登记 trace 源、建场景、选轴，在 live 页跑出结果，全程不手改 JSON。轴定义页（新建 / 编辑轴、上传代码）是 P10 第二步，这一步不做。页面编辑的仍是同一份存储，后端的保存校验不变。

| 层 | 改不改 | 改什么 |
|---|---|---|
| 轴类型接口（`/api/eval_axes/types`） | 改 | llm_probe_loop 按页面已用的形状返回：`type_id`、`title`、`summary`（说明正文第一句）、`depend_on`、`trigger_when`、`verdict_enum`、`scenario_fields`。白名单含 `axis.note` 的轴（描述就是材料）或用信息源的轴（自己或它调用的 loop 用，如真实性经 `search_knowledge`；描述里写 `{mcp://…}` 等引用来选信息源，§8）给 `scenario_fields: [{name: description}]`，其余不给（页面据此显示 / 不显示描述框）。两个项目同一形状，页面不分项目写两套 |
| 信息源页：登记 | 改 | 类型下拉按项目支持的类型列（llm_probe_loop 多出 `agno`、`langfuse`）；模板取 provider 的连接字段，不含 `bindings`（绑定属于场景，§8.2） |
| 信息源页：测试连接 | 改 | trace 源也经它的 MCP 服务测：trace MCP 服务加一个连接检查工具（同 §8.1 的 `check_tool`），页面按钮调它；现在会落进知识源 MCP 分支报错。场景页的"测试 Trace 连接"同样改走 MCP（现在的 `check_connection` 绕过 MCP 直连 provider，与 §8 "外部一律经 MCP"不一致） |
| 场景页：业务 trace | 改 | llm_probe_loop 下改成"从已登记的 trace 源里选一个 + 写 `bindings`"，存成 `{source, bindings}`；测试按钮见上一行。llm_probe 的旧表单不动，分出胜负后删输的那种 |
| 场景页：过程职责 | 改 | 场景字段 `process_obligations`（材料 `scenario.process_obligations`，§4.1）页面上没有入口：轴类型里有轴读这个材料时，显示一个 JSON 数组输入框，存进场景；形状由现有保存校验管 |
| 场景页：选轴 | 改 | 加"添加全部轴"：一次加齐所有已定义的轴、默认启用；单个开关照旧。依赖不齐、信息源对不上由现有保存校验报错，警告（`warnings`）显示在保存结果里 |
| 新实例 | 改 | 新端口第一次绑实例时，从仓库 `impl/data/` 拷一份当出厂数据（轴定义、代码、样例场景与登记），之后各自维护；现在是空目录，llm_probe_loop 连轴定义都没有、直接报错 |
| live 页 | 先不改 | 用"统一全链路"跑。分两步（先请求业务、再请求 Judge）时拿不到 trace 的旧问题（10-18 记录）这一步实测确认，确认还在再单列 |

上表"轴类型接口"的描述框规则与"场景页：过程职责"一行由 §2.5 取代。

### 2.5 场景对轴的描述（需求 §3.7，10-26 定，待确认）

本轴描述是一个固定槽位：框架给每个模型执行的轴拼任务时，在说明、材料之后放进场景对这个轴写的描述（`axis.note`，`impl/core/axis_loop/loop.py:305`，现状就是这样），空的不放；任务出现时放一次，分发出来的每一份各自出现时各放一次。它是配场景的人写给这个轴的，没有越界读的问题，所以不走白名单。

现状要改的（10-26 查）：需求侧材料 `case.requirements` 又按轴名取需求轴的框当"场景判准"（`component=criterion`，只放最后一轮那份），于是需求轴的描述在最后一轮出现两次；§2.4 的描述框规则看白名单，而没有一个轴把 `axis.note` 写进白名单，结果只有真实性有框；过程职责、能力边界另设字段。

| 层 | 改不改 | 改什么 |
|---|---|---|
| 框架：本轴描述槽位 | 不改 | 现状即槽位 |
| 材料：`case.requirements` | 改 | 去掉 `component=criterion`（不再按轴名读需求轴的框），只剩各轮原话、历史、业务背景 |
| 需求轴：说明 | 改 | 原来讲"场景判准（component=criterion）"的几段改讲"本轴描述"：它写这个场景需求方面的特定要求（如"办成"一般指交付什么），拿它把用户这一轮的要求落到具体交付上；不能独立产生期望。"每条期望必须引本轮用户原话"已由 `checks.py` 程序校验，不靠提示词 |
| 需求轴：分发脚本 | 改 | 不再给最后一轮单独加判准（判准已不在 `case.requirements` 里）；每份照常按轮切 |
| 兑现：说明 | 改 | 加一句：本轴描述是"怎样算交付到位"的特定要求，与期望一起判，不替代期望；空就只按期望判 |
| 材料：`scenario.process_obligations` | 删 | 6 个本应轴改读自己的本轴描述。现有条目（`id / link_type / situation / duty / confirmed`）迁成对应本应轴框里的文字，确认日期写在文字里。查过：loop 里没有校验按条目结构读，只给模型看，去掉结构不丢校验 |
| 材料：`scenario.boundary` | 删 | 没有轴读。场景里的 `boundary` 文字在承载性迁入时移进承载性的框（§15 第 1 条）；迁入前先留在场景里不动 |
| llm_probe_loop 场景校验 | 改 | 带 `process_obligations` 报错；承载性迁入后带 `boundary` 也报错。共用存储（`impl/core/capability_store.py`）不动，llm_probe 仍在用这两个字段 |
| 轴类型接口 `scenario_fields` | 改 | 规则改成"模型执行的轴都给描述框"，程序执行的（主轴结论）不给；去掉"白名单含 `axis.note` / 用信息源"两条 |
| 场景页 | 改 | 删过程职责输入框；描述框随 `scenario_fields` |
| `capability`（场景总述） | 不改 | 共用存储必填，只给人看，不进任何轴（需求 §3.7.4） |
| 场景数据 | 改 | 仓库样例与 verify 场景：`process_obligations` 迁进本应轴的框；原先写在需求轴框里的判准，按"需求方面 / 兑现方面"拆到需求轴、兑现轴两个框 |

## 3. 轴定义（全部是配置，10-21 定）

### 3.1 存储

- 所有轴、所有 loop 的定义存成一个配置存储 `axis_definitions.json`，两节 `axes`、`loops`（10-25 定，`shared_tools` 并进 `loops`），读写机制与 `capability_map.json` 相同（`capability_store` 那一套，保存时校验形状）。
- 说明正文（这个轴的"system prompt"）是其中一个文本字段，只写判法。
- 上传的代码三种固定插口（10-22 定）：`checks.py` 定义 `check(view)`，`synth.py` 定义 `synthesize(view)`，放在 `axis_code/<轴>/`；`dispatch.py` 定义 `dispatch(view)`，挂在 loop 上，放在 `axis_code/loops/<loop名>/`（10-25 定）。加载时检查名字与参数个数。

### 3.2 一个轴的字段

| 字段 | 意思 | 例（真实性） |
|---|---|---|
| `id`、`title` | 标识、显示名 | `truthfulness`、真实性 |
| `executor` | `model` 或 `program` | `model` |
| `loop` | 所属 loop 的名字（§3.3）；不写就是 `start: case` 的那个（10-25 定，取代 `run_mode`） | `truthfulness`（它自己一个 loop） |
| `role` | `analysis`（中间产物，展示时不算评测结论）或 `evaluation`（缺省）（10-22 定） | `evaluation` |
| `display` | 结果页明细里默认 `expanded`（展开）还是 `collapsed`（收起，进"其余分析"折叠块、不进令牌行；没跑成的照常显示）。不写按 `role`：评测轴展开、分析轴收起（10-27 定；需求分析、blocking、说法抽取写 `expanded`） | 不写 |
| `depends` | `[{axis, hard}]` | `[{axis: claims, hard: true}]` |
| `trigger` | `{axis, verdict_in}`，只能引用硬依赖 | — |
| `instruction` | 说明正文：只写怎么判；推送任务时放进上下文 | "判定回答里的每条说法是否属实……" |
| `materials` | 材料白名单（§4） | `["result.claims.claims[]"]` |
| `tool_categories` | 信息源类别 `[{category, required}]` | `[{category: knowledge, required: true}]` |
| `tools` | 选用的被调用启动的 loop（§3.3），按名字 | `["search_knowledge"]` |
| `submit` | `once` 或 `per_item`；`per_item` 时写 `items_field` 与 `item_key` | `per_item` |
| `output` | 输出 JSON Schema，顶层字段用 `x-fill: model \| program` 标谁填；程序填的字段里，是模型没直接给出、由规则推出的结论，再标 `x-explain: true`（§5.3 说明回合，10-27 定） | 见 §12.1 |
| `checks` | 选用的标准校验，带参数（§7），可加 `on: item \| final` | `[{quote_in_call: {field: "basis[]", category: "subloop", on: "item"}}]` |

- `output` 必须包含 `verdict`、`reason` 两个字段，它们同样可以标程序填（需求 §3.3）。
- 存在程序填的字段就必须上传 `synth.py`；反过来没有就不能上传。所属 loop 有 `dispatch.py` 的轴必须有 `synth.py`（合并各份结果）。

### 3.3 loop 的字段（10-25 定，取代 10-22 的"公共 loop 工具"一节）

存放在存储的 `loops` 里。一个 loop 是一个上下文；里面的任务出现、推送、提交、验收规则全一样（§5），主 loop 只是 `start: case` 的那一个。

| 字段 | 意思 | 例 |
|---|---|---|
| `id`、`title` | 名字、显示名 | `process`、过程评测 |
| `start` | `case`：case 开始就启动（恰好一个）；`ready`：它的任务依赖的、属于别的 loop 的任务都齐了，由台账启动（§6.1）；`tool`：被模型当工具调用时启动（§6.3） | `ready` |
| `dispatch` | 是否按材料起几份；有就上传 `axis_code/loops/<id>/dispatch.py`（§6.2） | 需求 loop：按轮 |
| `start: tool` 才有：`description`、`materials`、`params`、`tool_categories`、`submit` / `items_field` / `item_key`、`output`、`checks` | 同 10-22 的公共 loop 工具：给调用方看的说明、它自己的说明正文（`instruction`）、只读内置材料、调用方可写的参数（每个参数写 description）、输出不要求 verdict / reason | `search_knowledge` |

- 要单独一个 loop 只有两种理由（需求 §3.5.4）：隔开可见性；过程产物大、别的任务用不上。按任务换模型也走单独的 loop。
- `start: ready` 的 loop 什么时候起不另写，由程序从任务依赖推出（§6.1），页面上展示推导结果。
- 第一期的映射：`run_mode: isolated` 的轴 = 只装它一个任务的 `start: ready` loop；轴上的 `dispatch.py` 挪到它的 loop 上；`shared_tools` = `start: tool` 的 loop。

### 3.4 加载期校验（fail fast）

以下情况在场景保存时，或者加载时报错：
- 硬依赖没开、trigger 引用的不是硬依赖或枚举值不存在；
- `output` 缺 `verdict` / `reason`（仅限轴）；
- `fill` 与 `synth.py` 对不上；
- 白名单里的名字不在注册表里，或者字段投影 / 元素筛选的路径不在 schema 里，或者超出读取范围（§4.3）；
- `checks` 的名字未知或参数不对，或者 `of` / `field` 的路径不存在；
- `per_item` 没写 `items_field`；
- 必需的工具类别在场景里一个实例都没有；
- 被调用启动的 loop 的参数没写 description；选用了未定义的、或不是 `start: tool` 的 loop；
- 所属 loop 不存在；`start: case` 的 loop 不是恰好一个；`start: tool` 的 loop 里放了轴；
- 依赖会卡死（10-25 用户定）：任务当节点，两种边——任务的依赖（u → t），以及 ready loop 要等齐才起带来的被迫等（这个 loop 等的每个任务 → loop 里的每个任务）；有圈就报错并列出圈上的任务。case loop 一开始就在跑，不带来被迫等，所以经过它的来回（说法抽取 → 核事实 loop → 兑现）是一条直线，不报。取代原来的"依赖成环"与"loop 之间成环"；
- 有 `dispatch.py` 的 loop 里有轴没配 `synth.py`。

## 4. 材料（10-21 定）

### 4.1 注册表

代码里维护一张字典：标准名 → `{schema, description, load(case)}`。

| 标准名 | 是什么 | 值的形状 | 取自 |
|---|---|---|---|
| `case.user_turns` | 每一轮用户原话（含历史） | `[{turn, text}]` | RunTrace |
| `case.requests` | 每一轮请求体 | `[{turn, body}]` | RunTrace |
| `case.deliveries` | 每一轮被测系统的回答 | `[{turn, text}]` | RunTrace |
| `case.business_status` | 业务调用是否正常返回 | `{ok, http_status, error}` | RunTrace |
| `scenario.description` | 业务描述（其中的资料引用会被展开） | 文本 | 场景登记 `description` |
| `scenario.downstream` | 下游要求 | `[文本]` | 场景登记 `downstream` |
| `case.trace` | 这一轮 trace 的存档整理成的案卷（大材料，§4.4） | `{catalog, links, program_suspects, gaps, records}`：目录（编号、类别、轮次、大小、一行摘要）、程序枚举的环节表（每个环节的类型、输入端 / 输出端编号与字段）、程序按事实标的可疑环节、采集缺口、记录正文 | 运行记录里的存档 → 现有 `build_dossier` + `build_links`（10-25 定，§12.2） |
| `axis.note` | 本轴描述：场景对当前这个轴写的特定要求（需求 §3.7） | 文本 | 场景登记 `axes[]` 中该轴的 description；框架按槽位放进本轴任务，不走白名单（§2.5） |
| `result.<轴id>` | 某个轴被接受后的完整结果 | 该轴的输出 schema | 运行中写入材料表 |

- `case.*`、`scenario.*`、`axis.*` 由项目接入登记取值函数；`result.*` 根据轴定义自动生成。
- 内置材料的取值函数取不到（例：`case.trace` 的存档是采集失败，或缺了整轮）→ 这个 case 记运行失败，原因写取值函数给的说明（需求 `information_sources.md` 要求 1，10-25 定）。规则对所有内置材料一样。

### 4.2 白名单写法

```
"<标准名>"                                  取整个值
"<标准名>.<路径>"                           取一部分；路径写法沿用现有的 item_path：列表[].字段
"<标准名>.<路径>.{字段1, 字段2}"            再投影出几个字段
"<标准名>.<列表>[字段=值1,值2]…"            只取这个字段等于这些值的元素（10-22 定；分发脚本按它给每份子 loop 列选择）
```

内置材料不带参数，一个 case 一个值（10-22 定，撤掉 10-21 加的"带参数的内置材料"）。

### 4.3 读取范围

| 使用方 | 内置材料 | `result.*` |
|---|---|---|
| 轴（不论在哪个 loop） | 可以 | 只能读自己 `depends` 里的轴（可以跨 loop） |
| 分发出来的每一份 | 只能读分发脚本给它的那份选择 | 同上（选择不能超出这个 loop 各轴的范围，框架检查） |
| 被调用启动的 loop | 可以 | 不可以；另有调用方传的参数 |
| 校验、合成、分发代码 | 与所属方相同 | 与所属方相同 |

软依赖没开时，对应的 `result.*` 为空，放进上下文时写明"未启用"。

### 4.4 呈现与引用

```
【axis.note】
查询类场景：给出所问字段的值
【result.expectations.expectations[].{expectation_id, statement}】
[{"expectation_id":"E1","statement":"给出这张保单当前的退保金额"}, ...]
```

- 文本原样放入；结构化的值用 `json.dumps(ensure_ascii=False, sort_keys=True)` 序列化，保证同一份值每次的文本一样，可逐字引用。
- 引用材料：`{ref: "<标准名>[#轮次]", quote}`，quote 必须逐字出现在那一段的文本里。引用工具返回：`{ref: "<call_id>", quote}`。
- 小材料由程序直接放进上下文（10-21 定）。
- **大材料先给目录，正文按需读**（10-25 定，需求 §3.6.6；做法沿用现有案卷与 ES 的"先 outline 再读"，参照 Claude Code 的大结果落盘 + 按需读）：
  - 序列化后超过 `eval_axes.loop_material_inline_chars`（缺省 20000）的材料，推送时只把记录正文换成目录（材料自己声明哪个字段是目录，例 `case.trace.catalog`；没声明的放前 2000 字预览 + 大小）；记录库旁的其他字段（例 `case.trace` 的 `links` / `program_suspects` / `gaps`）照推，单个超过上限的给前 2000 字预览 + 按 `path` 读的写法（10-26 修：之前连这些字段一起丢了，侦探拿不到环节表）。
  - 正文用 loop 内置工具取，两种找法（10-25 定）：按目录挑编号，`read_material(name, ids?, path?, full?)` 取记录，单条超过上限时返回结构图（字段、大小），带 `path` 下钻，确需整段时 `full=true`；目录摘要定位不到时，`search_material(name, query)` 按关键词逐个字段找（值是 JSON 文本的先解开），返回命中的编号、字段位置 path 与可读片段，再用 `read_material` 按编号 + path 取；按 path 下钻遇到 JSON 文本先解开再走，走不通时报出这一层有哪些字段（10-26 改：原来在整条记录的 JSON 文本里找，片段满是转义符、看不出在哪个字段，模型反复搜、猜 path）。单次读取的上限与推送上限是同一个（`loop_material_inline_chars`），不另设；超限时从最长的正文段起换成预览（开头一段 + 全文字数 + 读全文的 path，同 Claude Code 读大文件的做法），其余照给全文，要全文再按 path + `full=true` 取，连结构都放不下才只给结构图；同一 loop 里已给过的长段正文（≥300 字），在别的记录里再出现时只给指向"同 X 里那段"，按大小判断前先去重（被测系统每次调模型的请求都带着完整累积对话），重读同一条记录照常给全文（10-25 定）。即侦探现有的 `dossier_collect` / `dossier_read` / `dossier_search` 推广给所有 loop；`dossier_timeline` 不做工具，轮次与先后顺序写进目录；`dossier_verify_quote` 删除，引文由验收程序核。
  - **能读到的范围 = 这个 loop 里已出现任务白名单的合集**（同一上下文里已推进来的本就收不回，按合集算是一致的）。白名单没选的字段、元素读不到，所以可见性仍由程序保证。读回的原文是一次普通工具返回，可被 `quote_in_call` 引用，按 §9 归档。

## 5. loop 协议

### 5.1 消息布局

```text
system   通用评测协议（固定）：你会陆续收到任务；按说明做；用 submit 交；被拒就按原因改了再交；
         引用写成 {ref, quote}；工具返回要到下一次回复才能引用……；
         唯一性原则（需求 §3.8 全文：一件事只给一份，一份只装一件事）
user     case 头 + 初始就出现的任务（没有依赖的），每个任务一段：
         【任务 expectations】说明 + 它的材料（按白名单）+ 可用工具（含子 loop）及其用法 + 提交格式（模型填的那部分 schema）
assistant / tool …
user     （post_batch 推送）【新任务 …】 / 【作废 …】 / 【撤下 …】
```

- 推送永远是追加一条新的 user 消息，不改写旧消息（中转站只有"新起一轮"才稳定命中前缀缓存，见 `report/process-axes-compare-20261009/CACHE-FINDINGS.md`）。
- **工具列表在一个 loop 里从头到尾固定**（10-21 定）：`submit`、`recall(call_id)`、`read_material`、`search_material`（10-25 加）、这个 loop 里各任务选用的信息源的工具（按信息源暴露为 `<信息源>__<工具>`，加框架统一的 `mcp_read`、`mcp_find`；登记里指定的检查工具不暴露），加上各任务选用的被调用启动的 loop。工具定义排在请求的最前面，中途增减会让整个前缀缓存失效。这和 Claude Code 的 skill、延迟加载工具是同一种做法：固定一组通用工具，具体用法写进追加的消息里。某个信息源实例有哪些工具、怎么用，写在任务推送里。
- 门禁：某个信息源类别还没被已出现的任务带进来，或者某个被调用启动的 loop 还没有已出现的任务选用，调用就直接拒绝，并说明原因。

### 5.2 submit

```json
{"task_id": "fulfillment", "item_id": "E2", "payload": {...}}
```

- `item_id` 只在 `per_item` 的任务上出现：带它是交一个分项，不带是收尾。`once` 的任务不能带。
- 交给一个已完成的任务，就是修改它：走同样的验收，通过后按 §5.4 让下游作废。

### 5.3 验收流水线（pre_tool 内依次执行；任一步不过就拒，并回告这一步的全部原因）

```text
1. 任务存在且已出现；提交形状与 submit 方式相符（分项 id 在清单里、同一分项不重复交）
2. 用"模型填的那部分 schema"做 JSON Schema 校验（jsonschema 4.26，环境已装）；条件字段用 if/then 表达
3. 依次执行选用的标准校验（§7）
4. checks.py 的 check(view)
5. 通过 → 有 synth 就执行 synthesize(view) → 完整结果再过一次完整 schema
6. 说明回合（需求 §3.3.6，10-27 定）：输出里有 x-explain 字段，且这次算出的 x-explain 字段和上一次回给模型的不同（或从没回给过）
   → 不接受，回给模型：这些字段的值（含程序依据）+ 固定要求
     "reason 写最终结论为什么是这样，包括程序算出的部分；认为程序结果或它依据的上游结论不对，在 reason 里写明依据挑战，不改结论；改好再交一次"
   和上一次回给的相同 → 接受
7. 接受 → 写入材料表 result.<id>
```

- 说明回合按程序结果判是否相同：再交时只改了 reason 等说明文字，程序结果不变，直接接受；改了引用、判断，使程序结果变了，就再回一次。来回次数由预算约束（`max_blocked` 只管"想结束但没交完"，不管打回）。说明回合不算被拒，事件记 `explain`。程序记住上一次回给模型的那份（`Submissions.explained`），任务作废重做时清空。分条提交的轴只在收尾时走说明回合。
- 合成只填程序字段（已有检查：返回的键恰好是程序字段）；程序字段里照搬模型交的值时原样照搬，不改（需求 §3.3.7）。某种条件下模型的值不能成立，写成第 4 步的 check 打回。

- 第 5 步合成出错，或结果不合 schema，属于评测器自己的 bug：直接中止整个 loop，记运行失败，不打回给模型（需求 §3.2.8）。
- 同一批里的多个 submit 各自独立验收（ToolLoop 的既有语义：同一批调用彼此看不见）。所以同一批里同时交上游和依赖它的下游，下游这一次会因为"任务未出现"被拒。这是对的。

### 5.4 台账（start / post_batch，全部由程序完成）

1. **作废**：本批被修改的任务，它所有已完成的传递下游都作废，回到"已出现、待重交"。
2. **出现**：依赖全部完成或不出现（软依赖没开视为满足），并且触发条件满足，就出现。分发给了先后的那一份（§6.2），列表里排在前面的任务当作后面任务的依赖，一样走这一条。
3. **撤下**：已出现但触发条件不再满足的，撤下，它交过的东西作废。
4. **程序任务**：依赖满足就当场合成；上游一变就重算。不推送给模型。
5. **起 loop**（10-25 定，取代 10-22 的"独立运行的轴"）：某个 `start: ready` 的 loop 等的任务（§6.1）都齐了，就由程序起它（有 `dispatch.py` 就按分发起多份），跑完再回到当前 loop。它等的任务被改了，它整个作废、下次齐了重起。
6. **推送**：本 loop 里新出现、被作废、被撤下的任务，合成一条 user 消息（大材料按 §4.4 只推目录）。

"不出现"是确定的状态：对下游来说算作已完成，`result.<id>` 为空。

### 5.5 完成与失败

- completion_hook：所有已出现的任务都完成，并且没有作废待重交，返回 Done，否则返回 Continue 并列出还差什么。`ready_to_finish` 用同一个判断。
- completion 看本 loop；一个 case 在所有 loop 都结束、没有该起没起的 loop 时结束。
- 失败（整个 case 记运行失败，不出部分结论）：预算耗尽；`max_blocked` 用尽；合成 / 分发出错；任一 loop 失败（含被调用启动的）；上下文归档后仍然超限（§9）；内置材料取不到（§4.1）；信息源检查工具报错（§8）。失败时各轴不保留做了一半的输出，过程只留在 loop 记录里（10-22 定）。

## 6. loop（10-25 定，取代 10-22 的"独立运行与公共 loop 工具"）

### 6.1 `start: ready` 的 loop 什么时候起

- **它等的任务** = 这个 loop 里各任务 `depends` 中、属于别的 loop 的那些任务。程序推出，不另写。
- **全部齐了才起**；"齐了" = 完成了，或已确定不出现。
- **它等的任务被改了**：整个 loop 作废，结果全部撤回，下游传递作废；齐了再在新上下文里起。
- **会卡死的**：加载时按 §3.4 的等待图查圈报错；运行时兜底——某个 loop 没有可交的任务、也起不了别的 loop，却还有任务没完成，当场记运行失败，写明谁在等谁（不空转到 max_blocked）。
- **一个一个跑**（10-25 定）：由当前 loop 的台账在 `post_batch` 里同步起，跑完再继续；第一个起的是 `start: case` 的 loop。⟡ 并发待实测耗时后再议。
- 起法：一个新的 ToolLoop，system = 通用评测协议（同主 loop），首条 user = case 头 + 这个 loop 里初始出现的任务；`ToolLoop.run(input, LoopContext(trace_id, stage=<loop id>))`。被接受的结果写进同一张材料表，别的 loop 按白名单读。

### 6.2 分发

```python
def dispatch(view) -> list[dict]:
    """view：这个 loop 各任务白名单材料的合集。返回每一份的材料选择，写法同 §4.2 白名单。"""
    return [{"id": "t1", "materials": ["case.requirements.sources[turn=t1,case]"]}, ...]
```

- 不上传就只起一份。每一份跑这个 loop 的全部任务，只看到它那份选择取出的材料；框架检查选择合法且不超出这个 loop 的读取范围，不合法算评测器出错。
- **一份只跑部分任务、只排真实先后**（2026-10-26 用户定，需求 §3.5.5；同日由"按列表顺序一个一个出现"改为先后对）：一份写成 `{"id", "tasks"?: [任务 id], "after"?: [[前, 后], …], "materials"?: [...]}`。
  - `tasks`：这一份只跑列出的任务（列表顺序没有含义）。不写就是这个 loop 的全部任务。
  - `after`：每一对的前一个当作后一个的依赖（§5.4 第 2 条），前一个交完后一个才出现，它的白名单才进 `read_material` 的读取范围（§4.3 本来就是"已出现任务的白名单合集"）；不在任何一对里的任务一开始就出现。各对只能是本份的任务、不能成环，否则分发出错。
  - **锁**：一对里后一个出现后，前一个的 submit 一律拒（"已锁：后面的任务已出现"）。
  - `materials`：不写时每个任务读自己的白名单；写了就照原样，这一份的任务都只读这份选择。
  - 每个任务至少在一份里，否则分发出错；同一任务在几份里出现，各份结果照常收进 `view.parts`。
  - 分发脚本的 `view.params.tasks` 是这个 loop 里场景启用的任务（脚本按它分，不自己假设开了哪些）。
- 各份按各任务的输出 schema 提交、验收；框架把每个任务各份被接受的结果收成 `[{id, result}]`，作为 `view.parts` 交给这个任务的 `synth.py` 合并。
- 各份一个一个跑。

### 6.3 被调用启动的 loop（原公共 loop 工具）

- 选用它的任务的模型调用它：`<loop id>(参数)`；框架新开一个 ToolLoop（每次调用一个，提交状态各自独立），system = 通用子任务协议 + 它的 `instruction`，材料按它的白名单取，加上参数。通过 `as_tool()` 嵌入调用方，继承 trace_id 与 stage。
- 被接受的结果作为这次工具调用的返回：`text` 加 `structured`；调用方用 `{ref: call_id}` 引用，代码从 `view.calls[].structured` 读。
- **嵌套只有一层**：被调用启动的 loop 里不能再调这种 loop。
- 门禁：这个 loop 里还没有已出现的任务选用它，调用就拒绝。
- 调用次数与 token 计入全局预算。
- **必需与可选**（10-27 定，需求 §4.3）：轴在 `tools` 里选用，默认必需；写进 `optional_tools` 的是可选。它声明的必需信息源类别，选用它的轴一个实例都没挑到时：必需 → 加载时报错；可选 → 这个 case 不提供它，任务文本的可用工具里写"本场景不可用（场景没选 X 类信息源）"，轴按自己的说明处理。对所有被调用启动的 loop 一样，框架不认具体名字。

## 7. 视图与标准校验

### 7.1 视图（check / synthesize / dispatch 的唯一输入，只读）

```python
@dataclass(frozen=True)
class TaskView:
    task_id: str
    own: Mapping            # 本次提交里模型填的部分；分条交收尾时含全部已接受分项
    materials: Mapping      # {标准名: 完整值}，只含白名单里出现的名字（10-21 实施时定：投影只决定给模型看多少，代码拿完整值）
    params: Mapping         # 仅被调用启动的 loop：本次调用的参数
    calls: Sequence[CallView]  # 此前批次的调用：call_id, tool, category, args, batch, text, structured, is_error
    stage: str              # item（校验一个分项）/ final（收尾）
    parts: Sequence[Mapping]   # 仅有分发的轴的 synth：[{id, result}]，各份被接受的结果（10-22 定）
```

- 视图只包含白名单里的材料，代码拿不到白名单以外的东西（需求 §3.4.3）。
- 自定义代码的确定性靠测试保证：同一个视图连续跑两次，结果必须相同，不做沙箱（10-21 定）。

### 7.2 标准校验库

| 名字 | 种类 | 参数 | 说明 |
|---|---|---|---|
| （schema） | V1/V2 | — | 来自 output 定义，自动执行 |
| `covers` | V3 | `field`、`of` | `field` 取出的 id 集合与 `of` 指向的集合相等 |
| `refs_in` | V4 | `field`、`of` | `field` 取出的每个 id 都在 `of` 指向的集合里 |
| `quote_in_material` | V5 | `field`、`material` | 引文逐字出现在指定材料里 |
| `quote_in_call` | V5+V6 | `field`、`category?` | ref 是此前批次中没报错的调用（可限定类别），quote 逐字出现在它的 text 里 |
| `searched` | V6 | `field`、`category` | 列出的调用都是此前批次中没报错、属于该类别的调用，至少一个 |
| `from_call` | V4+V6 | `field`、`tool` | ref 指向一次已被接受的、指定子 loop 工具的调用 |

- `of` 用路径指向视图：`own.<路径>`、`params.<路径>`、或 `<标准名>.<路径>`（白名单里的材料）。
- 需要先算出来的集合（比如"没给到的期望"），由上游的合成程序算成一个程序填字段，下游直接引用。校验库里不加计算语言。
- 遇到新的通用形式，就往这张表里加一行（需求 §3.4.1）。

## 8. 信息源（MCP）

| 层 | 落在哪 | 内容 |
|---|---|---|
| 类型 | 代码：知识源 `es`、`mcp`；trace 源 `agno`、`langfuse`（第二期，沿用现有 provider；llmtracing 不在第二期，§12.2） | 怎么连、怎么读；外部一律经 MCP（ES、trace 存档由评测器自动拉起本地 MCP server，§12.2.1） |
| 全局登记 | 资料管理页：知识源与 trace 源同一份登记（`knowledge_sources.json`） | 选类型、按类型填连接配置；凭据写成 `${VAR}`；可选 `check_tool`（§8.1）。一条登记拿来做什么由它的类型决定（10-22 定） |
| 场景选用 | 知识源：轴框描述里的 `{es://名/索引}`、`{mcp://名}`、`{material://项目/资料}` 引用（沿用现有写法）；trace 源：场景条目 `business_trace: {source: <登记名>, bindings: {...}}`（§8.2） | 一个轴框里引用的就是这个轴挑的；场景选用 = 各轴框引用的并集 |

- 信息源工具按信息源暴露（`<信息源>__<工具>`，名字、说明、参数取自 MCP 服务本身）。一个信息源要加查询工具，加在它自己的 MCP 服务里（10-22 定）。
- 返回形状按 MCP：`content`、`structuredContent?`、`isError`。是否报错看 `isError`。
- ES：现有 `es_tools` 包成本地 stdio MCP server（`impl/projects/llm_probe_loop/mcp_servers/es/`），检索语义不变；直连与 `verify_quote` 回读删除（10-21 定）。
- 校验场景选没选某类信息源：按引用找到登记，按登记的类型判断，不搜描述文字（10-22 定）。

### 8.1 检查工具（10-25 定）

- 登记里可选写 `check_tool: <工具名>`：这个 MCP 服务里哪个工具是"这个 case 能不能用"的检查。用于评测时才实时去查的信息源（知识源）。
- loop 起之前，对这个 loop 里任务声明为必需（`tool_categories[].required`）的每个信息源实例，框架调一次它的检查工具（入参：按登记的身份绑定从请求取，同查询工具）。返回 `isError` → 整个 case 记运行失败，原因带上返回文本。不写就不查。
- 检查工具不进任何 loop 的工具列表，模型看不到。

### 8.2 trace 源（10-25 定）

- **外部的事归信息源，case 里的事归框架**：trace 源 MCP 服务提供采集工具（入参：这一轮的关联标识，即场景 `bindings` 从请求 / 响应取出的值；返回：这一轮 trace 的原样快照，或 `isError` + 原因）。跑完业务时由 live 层调用，结果原样存进运行记录 `project_fields.business_trace`（报错就存"采集失败 + 原因"）。评测时 loop 里不连 trace 平台，只读存档（`case.trace`，§4.1）。
- 类型：agno、langfuse（第二期）。现有 `business_trace/providers/agno.py`、`langfuse.py` 的采集逻辑包进各自的 MCP 服务（`impl/projects/llm_probe_loop/mcp_servers/trace_agno/`、`trace_langfuse/`，同 ES 的做法）；连接配置挪进全局登记，场景只留选用与字段绑定。llmtracing 第二期不做。
- 采集条件：场景启用的任务里，有任务的白名单选了 `case.trace`。

## 9. 上下文与成本

1. 上限：`axis_loop.context_limit_tokens`，可配置。每次请求前估算。
2. 到上限的 80% 时（可配置），把已完成任务的旧工具返回（含 `read_material` 读回的正文）替换成 `"[已归档] call_id=c12，需要时用 recall(call_id) 重看"`。这和 Anthropic API 的 context editing（clear tool uses）是同一种做法。原文仍在调用记录里，校验和引用不受影响；`recall` 本身是一次新调用，返回的原文可以被引用。
2a. 大材料推送时只放目录（§4.4），正文不进推送消息，所以推送消息不需要归档。
2b. **同一批里有几份返回、归档旧的之后仍超过阈值**（2026-10-29，需求 §5.3）：同一批的返回也按先后归档，只留最后一份。模型用留下的那份判完，要看归档的那份就 `recall`；`recall` 是新的一批，前面那份随之成为旧返回、可以归档。依据：F01 真实性同一步发了两次取证，两份返回都算"最近一批"不归档，合计约 21 万 token 超限，case 没出结论（2026-10-28）。单份返回本身超限仍按第 3 条记运行失败。
3. 归档之后仍然超限：记运行失败，原因写明上下文超限（需求 §5.3）。
4. 归档会让缓存失效一次，所以只在接近上限时触发。

## 10. 预算

全局一份，进全局运行配置（10-22 定）：放在现有的可选节 `eval_axes` 下，`eval_axes.loop_llm_calls`、`loop_tool_calls`、`loop_seconds`、`loop_context_limit_tokens`、`loop_archive_ratio`、`loop_material_inline_chars`（10-25 加），都有缺省值，现有 config.yaml 不用改。一个 case 的所有 loop 共用一份计数。

## 11. 记录与报告

### 11.1 报告（与现有 `build_report` 同形）

```text
{ main_verdict, run_id, scenario_id, trace_id, case_id, axes, warnings,
  results: [ {type_id, status, output, summary, ...} ],     ← 每个轴一条，output = 完整结果
  route: "loop",
  loop: { status, reason, llm_calls, tool_calls, seconds, tokens, events: [...] },     ← 整个 case 的汇总
  loops: [ {id, status, reason, llm_calls, tool_calls, seconds} ] }                     ← 每个 loop 一条（10-25 加）
```

- 主轴结论：程序任务 `main_verdict` 的 synth 调用现有的 `main_verdict(results)`，函数不改。
- status 沿用 `succeeded` / `not_applicable`。没出现的写明"触发条件未满足"。loop 失败时全部记 `failed`，`main_verdict` 为 None。
- 前端 summary、live 不用改。`events` 第一期只放进报告 JSON，按任务的时间线视图放到第二期（10-21 定）。

### 11.2 事件记录

```text
{loop, batch, kind: appear | submit | accept | reject | invalidate | withdraw | program | loop_start | loop_end | archive,
 task_id, item_id?, call_id?, reasons?}
```

- 每一步的模型请求已经由 LlmClient 写成 ContextRecord，挂在同一个 trace_id 下。子 loop 的请求用 `<父 stage>/<子loop id>` 作前缀（ToolLoop 嵌套的既有行为）。
- 判错时的定位路径：在 events 里找到那个轴最后一次 accept → 找到对应 batch 的模型请求 → 看当时的上下文。

## 12. 现有轴映射与分期

### 12.1 第一期：主轴（无 trace 场景，也就是评测集的范围）

| 轴 | 执行者 | loop | 依赖 | 材料 | 工具 | 代码 | verdict |
|---|---|---|---|---|---|---|---|
| `expectations` | 模型 | `expectations`（ready，按轮分发） | — | `case.requirements`（全部需求侧材料，每条标轮次） | — | `dispatch.py` 按轮切（每轮只选本轮及之前的原话、业务背景；本轴描述走槽位，§2.5）；`checks.py`（期望必须引本轮用户原话等）；`synth.py` 合并各轮、编号加轮次前缀 | 程序（complete / partial） |
| `blocking` | 模型 | `blocking`（ready） | expectations（硬） | `result.expectations.expectations[].{expectation_id, turn, about, statement, condition, ambiguity_group}` | — | `checks.py`（同一歧义组 blocking 一致） | 程序 |
| `claims` | 模型 | `main`（case） | expectations（硬） | `case.deliveries`（看哪几轮由这一条选，现在取全部轮；10-29（二））、`case.user_turns` | — | `checks.py`（逐字按出处所属的轮核对，轮次须是材料里给了的；隔离规则） | 程序 |
| `truthfulness` | 模型 | `truthfulness`（ready） | claims（硬） | `result.claims.claims[]` | 信息源 knowledge；被调用启动的 loop `search_knowledge` | `checks.py`（依据的那次取证里有这一条；取证没找到只能判 unverifiable——读全了的范围取证交 found，见 `knowledge-evidence.md` §4.1，10-27 定）；`synth.py` | 程序 |
| `fulfillment` | 模型 | `main` | expectations（硬）、blocking（硬）、truthfulness（软） | `case.deliveries`、`result.expectations`、`result.blocking`、`result.truthfulness.claims[].{…}` | — | `checks.py`（check_assessments；引的说法须有出处在这条期望的轮次，10-29（二））；`synth.py`（blocking 取自 `result.blocking`，整体状态派生） | 程序 |
| `main_verdict` | 程序 | `main` | fulfillment（硬）、truthfulness（软） | 二者的 `result.*` | — | `synth.py` 调现有 `main_verdict()` | 程序 |

- **交付第一次进主上下文**是 `claims` 出现时，此时期望已定（硬依赖）；`blocking`、`expectations` 各自单独一个 loop，材料里没有交付。
- **真实性**（10-22 定）：单独一个 loop。它的模型调 `search_knowledge` 取证（可以针对证据不够的几条再调，补查），拿证据逐条判；检索过程在最里层，判定看不到。证据原文只在真实性 loop 的上下文里，主 loop 只经兑现的材料读到每条说法的结论。每条提交：`verdict`、`reason`、`basis`（`{ref: 那次 search_knowledge 调用, quote}`）、`evidence_call`、`gap`。
- **错误码归为运行失败**（10-22 定，需求 `main_axis.md` §3.6）：场景配置里事先维护错误码 `business_failure: {http_status: [...], body: {pointer, values: [...]}}`；返回命中即记运行失败、不出结论、不启动 loop；没命中（含没登记的非 2xx）照常进 loop。没配就不判失败。现有"非 2xx 即失败"的写死规则在 llm_probe_loop 里不再用。这段判断在项目入口统一一处手写，不进任何轴。
- **兑现不自推期望**（10-21 用户定）：`fulfillment` 硬依赖 `expectations`。
- 承载性见 §12.3（10-27）。

### 12.2 第二期：trace 与过程六轴（2026-10-25 grill 定，需求 `demand/draft-20261025/README.md`）

范围：agno、langfuse 两种 trace 源。llmtracing（只有对话稿）不做：场景选了它又开了过程轴，加载时报错。

#### 12.2.1 trace 进 case

- 采集：§8.2。trace 源 MCP 的采集工具在跑完业务时调，存档进运行记录；loop 里不连平台。
- 内置材料 `case.trace`（§4.1）：存档 → 现有 `build_dossier` + `build_links`，给出目录、环节表、程序标的可疑环节、缺口、记录正文。大材料，推送只放目录，正文用 `read_material` 读（§4.4）。
- 取不到（存档是采集失败，或缺整轮）→ case 运行失败（§4.1）；一轮里缺端点 → 写进缺口，照常评（需求 `information_sources.md` 要求 1）。

#### 12.2.2 loop 与轴

```text
loop main（case）              claims → fulfillment（等 process）→ main_verdict
loop expectations（ready，按轮分发）   expectations
loop blocking（ready）          blocking
loop truthfulness（ready）      truthfulness ── 调 search_knowledge（tool）
loop trace_analysis（ready，不等任何任务）   trace_analysis（侦探）
loop process_expected（ready，等 expectations、trace_analysis；按分组分发）   6 个 <轴>_expected（分析轴）
loop process（ready，等 6 个 <轴>_expected）                                   6 个 <轴>（评测轴）
```

- 一个一个跑（§6.1）：`main` 的 start 钩子里依次起已齐的 loop，`fulfillment` 等 `process` 跑完才出现。
- **屏障不加机制**：`process` 里每个实际轴只依赖自己那条本应；`process` 这个 loop 等的是 6 条本应，按"全齐才起"自然在 6 条都交完后才起（10-25 定）。增减一个过程轴只动它自己的两条定义（加它的本应 loop）。
- **可见性**：每个轴的本应单独一个 loop（实施 S5 时改，10-25）：一个轴的输出常是另一个轴的输入（模型输出 = 上下文管理"交付保留原义"的输入），6 个本应共用一个上下文时，模型能力轴会从上下文管理轴的输入里看到自己的输出——防污染测试在真实存档上抓到了（最终回答、编排步骤产出漏进本应上下文）。所以本应各自一个上下文，只有本轴的输入端；实际共用 `process`，那时输出端本就该看。侦探的怀疑理由不进任何白名单；它指的记录只给实际：给本轴环节的写进那个环节（`links[].leads`），指向别轴环节的放 `views.leads`（2026-10-29（二））。
- **本应分组同做（2026-10-26 用户定）**：各自一个上下文时，六个本应读的材料大量重叠（r1c-t 21 条：分开读的记录条次是去重后的约 2.7 倍），本应阶段是最耗时的一段。改为一个 `process_expected` loop，`dispatch.py` 每个 case 现算：
  - 先后关系：轴 B 的输出端（`views[axis=B].links` 的 output 端，`(ref, field)`）出现在轴 A 的本应材料（`views[axis=A].input` 的记录字段）里 → B 要排在 A 前面（A 的材料会把 B 的实际产出带进上下文）。由侦探的合成程序算好放进 `result.trace_analysis.feeds`（`[{from, to}]`，只有轴名，不含内容）。
  - 分组：六个轴分成最少的组，每组内部的先后关系无环（六个轴最多 203 种分法，穷举）；同样组数的取各组轮数（最长先后链）之和最少的。每组一份 `{"id": "g1", "tasks": [...], "after": [组内的 feeds 对]}`，按 §6.2 只排真实先后、交完即锁，没先后的同时出现、可一次交齐（10-26 改：原来组内排成一整串，没关系的两个轴也要排队；按 r1f-t 22 条，本应要排的轮数合计 132 → 94，每条 3–6 轮）。
  - 隔离不变：写任何一个轴时，上下文里只有排在它前面的轴的材料，而那些材料里没有它的输出。排不开的（成环）分到不同的份，各自一个上下文。
  - r1c-t 实测分组：1 组 4 条、2 组 14 条、3 组 3 条、4 组 1 条，平均 2 组（原来 6 个上下文）。各份一个一个跑（§6.2 原样）。
- 代价：`process` 是新上下文，本应阶段读过的输入端要重读，吃不到现方案"同一会话追加"的前缀缓存；实测后看。

| 轴 | 执行者 / 角色 | loop | 依赖 | 材料 | 代码 | verdict |
|---|---|---|---|---|---|---|
| `trace_analysis` 侦探 | 模型 / 分析 | `trace_analysis` | — | `case.trace`（全部）、`axis.note` | `checks.py`：引用的记录编号必须是此前 `read_material` 读回过的（`searched` / `quote_in_call`）；`link_id` 在 `case.trace.links` 里；新环节至少一端有已读的记录。`synth.py`：现有 `merge_suspects`，再整理出 `links[]`（程序枚举 + 补的漏列环节，每个标 `axes`：环节类型对应的轴，并上侦探点名"可能用得上"的轴——侦探偏召回，一条记录常是几个环节的证据，每条发现都交 `axes` 多选，10-25 定）、`links[].leads` 与 `leads[]`（2026-10-29（二）由每轴一份 `{axes, refs}` 改：侦探在本轴某环节上交的 `source_refs`，写进那个环节的 `leads`；侦探补的新环节写它自己的 `source_refs`；`views.leads` 只留指向别轴环节、侦探点名本轴用得上的记录（即 `borrowed`），已写进本轴环节的不重复。原因：按轴拉平后丢了"哪条记录是给哪个环节看的"，langfuse 的工具调用外层只记结构、参数与返回记在它的子记录上，实际偶尔把外层单独判成无法核、结论被卡成不确定，9 条里 2 条；指向别轴环节的线索本应不会为它写行，不会出这个问题，照旧平铺）、`views[]`（`{axis, input, full}`：`input` = 本轴环节的输入端字段，即现有 `input_view`；`full` = 本轴环节两端 + 指的记录，即现有 `material_view`）、`feeds`（`[{from, to}]`：from 轴的输出端出现在 to 轴的本应材料里，给本应分发排先后，10-26 定）、`why`（怀疑理由，只给页面）。现方案的"行动路线""覆盖说明"不再要。侦探说明里，可疑环节一条补：`source_refs` 写全核这个环节要看的记录——环节端点之外，这个环节实际发生的内容还记在哪些记录上（如工具调用只记了结构，参数和返回记在它的子记录或别的记录里），一并写进来（2026-10-29（二）；只写编号，不写理由） | 程序（complete / partial，按缺口） |
| `<轴>_expected` × 6 本应 | 模型 / 分析 | `process_expected` | expectations（硬）、trace_analysis（硬） | `result.expectations.expectations[]`、`result.trace_analysis.links[axes=<轴>].{link_id, link_type, turn, input}`（小，全量推）、`result.trace_analysis.views[axis=<轴>].input`（大材料）、`axis.note`（含过程职责，§2.5）、`result.trace_analysis.feeds`（分发排先后用，10-26） | `checks.py`：id 不重复、turn 在环节所属轮里、来源是需求的条目 `expectations` 非空且在 E 里（`process-axes.md` §4）。不加覆盖校验：说明里写清"该看的环节都要看、依据要充分"，环节表全量给、侦探补漏指重点（10-25 定）。`synth.py`：各轴只在一份里，取那一份的 `expected`、`not_covered`（10-26 起本应走分发） | 程序（ready） |
| `<轴>` × 6 实际与轴结论 | 模型 / 评测 | `process` | `<轴>_expected`（硬）、trace_analysis（硬） | `result.<轴>_expected`、`result.trace_analysis.links[axes=<轴>]`、`result.trace_analysis.views[axis=<轴>].full`（大材料）、`result.trace_analysis.views[axis=<轴>].leads`。说明里讲清 leads：一个环节的内容可能不只记在它自己的端点上，`links[].leads` 是侦探给这个环节指的记录，也是它的证据，端点没有正文、但这些记录里有，就按这些记录核，不判无法核；`views.leads` 是侦探指出本轴也要看的其他记录（2026-10-29（二）） | `checks.py`：现有 `check_actual`（与本应一一对应、problem 只引没达到 / 意外、没达到和意外必须有引文、引文逐字在所引记录里）。`synth.py`：现有 `settle`（锁"必须独立查证"）+ `aggregate`（五值与组成）+ `issues_of`（问题记录，不再有跨批 `same_as`） | 程序（五值） |
| `expectations` | 模型 | 不变 | — | 不变 | `checks.py` 加：每条 `needs` 合法（`spec/alg/expectations.md` §2.2） | 不变 |
| `fulfillment` | 模型 | `main` | 加：6 个 `<轴>`（软） | 加：`result.<轴>.results[].{id, expectations, statement, verdict, observed, attribution}`；场景配了哪些证据（程序填进视图） | `checks.py` 加：`process_refs` 在 P 里；本应 `expectations` 含本条的过程条目都在 `process_refs` 里。`synth.py`：按 `spec/alg/fulfilled.md` §2.1 派生每条 status、档位、缺的组 | 程序 |

- **不分批**：一个轴一个本应任务、一个实际任务；材料大用目录 + 按需读。现有分批（`axis_batches`）与跨批合并不迁。
- 六轴的子能力、"本轴不判"写进各轴定义的 `instruction`；只对某个被测系统成立的职责写在场景的过程职责里，从本应轴的 `axis.note` 读（§2.5），轴定义里不放（2026-11-01）。
- 旧路线里"主判官读 E + 案卷 + 六轴再判一次"（`need_judge`）不迁；主结论由 `main_verdict` 按程序合成（§12.1）。
- llm_probe_loop 的判官：场景没开 `fulfillment` 时记运行失败、写明原因，不再退回单次判官。

#### 12.2.3 主轴的证据组（`spec/alg/fulfilled.md` §2.1）

- 场景"配了知识" ⇔ 场景选用了知识源；"配了 trace" ⇔ 场景选用了 trace 源（10-25 定，按信息源，不按轴）。框架把这两个布尔值放进 `fulfillment` 的视图，合成程序据此算可用组。
- 轴与信息源对不上：开了核事实没选知识源、开了过程轴没选 trace 源 → 加载报错（必需类别缺失）；选了知识源没开核事实、选了 trace 源没开过程轴 → 警告（场景保存时提示，写进每个 case 报告的 `warnings`），因为那一组算可用却没人核，会系统性落到不确定。
- `fulfillment` 的模型只填 `delivered`（给了 / 没给 / 不可读）、交付原文位置、`claim_refs`、`process_refs`、`reason`；`status`、`evidence_tier`、`missing_evidence` 由合成程序算。`main_verdict()` 的规则不变，组成里多出档位与缺的组。

#### 12.2.4 验收

- 冻结样本：8031 上 10-19 那批 verify-insurance-agno / langfuse 22 条（`report/eval-main-axis/verify33/old.jsonl`，带 trace 存档），两条路线都在存档上跑，不重新调业务。场景先按"只配 trace"（不选知识源、不开核事实）跑一轮，验证 trace 档；再按"知识 + trace"跑一轮。
- 对照：主结论按 gold 计命中与误放行（gold 按新口径逐条核，变化列出给人）；六轴逐轴比轴级值与现方案（llm_probe 工作流路线），不一致逐条列；每 case 模型调用、token、耗时。
- 防污染测试：`process_expected` 每一份里，每个本应任务提交之前的模型请求里不出现本轴的输出端字段，`read_material` / `search_material` 在这里读不到输出端；侦探引用的编号都读过。
- 无 trace 场景（第一期 dev 43 条）回归：加了 `needs` 与证据组后，结论变化逐条列出。

### 12.4 结论要说明原因（2026-10-27 定；需求 `axis_loop.md` §3.3.6–7、L9，`main_axis.md` M9）

| 轴 | 标 x-explain 的程序字段 | 程序依据 | 其他 |
|---|---|---|---|
| `fulfillment` | `fulfillment_assessments`（只回 `expectation_id`、`status`、`status_basis`）、`verdict`（即整体状态） | 每条加 `status_basis`：程序为什么得出这个 status，如"knowledge 组不过：c7 有矛盾（保单状态为无效）""trace 组判不了：tool_execution.E2 无法核" | 说明改为：对不对由程序按证据组算，但你要读懂所引 claim 和过程条目的结论，每条 reason 写清为什么是最终那个结果；觉得某条 claim 或过程结论判得不对，在 reason 里写明依据挑战，不凭自己的业务知识、不改引用。`reasoning_summary` 照模型最终 reason |
| 过程六轴实际（6 个） | `verdict`（轴级五值）、`composition`（只回 `counts`） | 已有 `composition` 计数 | "必须独立查证"锁从 `actual_result` 移到 `check_actual`：needs_external=是 的条目判没达到 → 打回，"trace 证明不了没做是错的，看得到做到了判达到，看不出判无法核"。删掉丢坏引文后降级（同一份原文先在 check 打回，合成里永远走不到） |
| `main_verdict` | —（程序轴，没有模型） | `basis` 把给错和没给分开：没兑现的期望里 delivered=给了 → "给错了：<id>（<status_basis>）"，没给 → "没给到：<id>" | — |

其他轴的程序字段是改名、计数或照搬（blocking、claims、truthfulness、carryability 的 verdict），不标 x-explain。

- 成本：兑现与六轴各多一轮模型调用（输入是前缀加一条短消息，前缀缓存命中）。验收时报每 case 的调用数、token 变化。
- 验收：C08 的兑现 reason 写出 c7 及原因；造一条 needs_external 没达到的用例，提交被打回、模型改判；复跑 10-27 那组用例，看兑现 reason 与 status 不再说两件事、主结论依据分得开给错与没给。

### 12.3 承载性（2026-10-27 定，待确认；需求 `main_axis.md` §3.3、`axis_loop.md` §3.7）

照 llm_probe 的 `carryability`（`impl/projects/llm_probe/eval_axes/adapters/carryability.py`）迁，形状同真实性。

| 轴 | 执行者 | loop | 依赖 / 触发 | 材料 | 工具 | 代码 | verdict |
|---|---|---|---|---|---|---|---|
| `carryability` | 模型 | `carryability`（ready） | expectations（硬）、fulfillment（硬）；触发：fulfillment 的 verdict 为 `not_fulfilled` | `result.fulfillment.not_fulfilled[]`（程序算好的"blocking 且没给到"清单：`expectation_id, statement`）、`result.expectations.expectations[].{expectation_id, about, condition}`；本轴描述（槽位，即责任范围） | `search_knowledge`（可选） | `checks.py`：逐条 `basis` 的出处只能是 `axis.note`（quote 逐字在框里）或这次的 `search_knowledge` 调用（那次取证里有这一条、quote 逐字在返回原文里；那次这一条是 not_found 的不能当依据）；carry 为 yes / no 时 `basis` 至少一条；`covers`：逐条覆盖 `result.fulfillment.not_fulfilled[].expectation_id`。`synth.py`：carry → placement（no → 做不了，yes → 做错了，undecidable → 说不清），出 `placements[]` | 程序：按条（`做不了` / `做错了` / `说不清`） |
| `main_verdict` | 程序 | `main` | 加：carryability（软） | 加：`result.carryability.placements[].{expectation_id, placement}` | — | `main_verdict()` 已按 placements 合成（`main_verdict.py`），不改 | 程序 |

- **逐条提交**：`{expectation_id, carry, reason, basis: [{ref, quote}], gap_kind, missing_material}`；carry = undecidable 时 `gap_kind`（口径分歧 / 空间未受治理）与 `missing_material` 必填、`basis` 为空。`ref` 写 `axis.note`，或 `search_knowledge` 的 call_id。
- **说明**沿用旧轴的 `_SYSTEM`，改两处：依据里的"责任范围登记"改指本轴描述（框里原文就是登记的责任范围，需求 §3.3）；去掉"背景"一段（场景总述不进本轴）。不看交付、不看被测系统的说法、不读 trace（需求 §3.3，10-27 用户再确认）。
- **search_knowledge 的待查项**：`{item_id: expectation_id, text: statement, context: about + condition}`；查的是"这条要的结果在信息源里本来有没有"。它的说明按"待查项"写，不改。
- **`search_knowledge` 是可选工具**（`optional_tools`，§6.3）：场景没选知识源也能开承载性，只凭本轴描述判；框也空就只能交 undecidable，主轴照规则 1 判没做成并注明"能不能做没分清"。场景不开承载性时同现状（"能不能做没区分"）。
- 场景校验：llm_probe_loop 场景带 `boundary` 报错（§2.5）；原 `boundary` 文字迁进承载性的框时，系统自称能做什么的句子挪进场景总述（需求 §3.3），迁前逐个场景给用户看拆法。

## 13. 对比与验收

- 数据：`report/eval-main-axis`，dev 43 条，holdout 19 条。
- 流程：只在 dev 上调。dev 满足需求 §9 的硬门槛后，跑一次 holdout。holdout 不用来调规则。
- 重跑一致性：每条 case 两条路线各跑 3 次（10-21 定）。
- 加轴成本：逐个对比第一期每个轴的"配置字段数 + checks / synth 行数"，和现有对应 adapter 及其校验的行数。
- 防污染：写成测试，检查 events 与消息：`claims` 出现之前，主上下文里没有出现交付；`blocking`、`expectations` 子 loop 的消息里从头到尾不出现交付；`expectations` 每轮子 loop 里不出现后面轮次的原话。

## 14. 不做

- 不改 `impl/core/tool_loop` 的接口；缺能力先和你确认。
- 不做：代码工具、events 的前端视图、超过一层的嵌套、loop 与分发并发（10-25 定先一个一个跑）、llmtracing 的过程轴。
- 不在框架机制之外加自定义代码（10-22 定）：轴只用配置与三个代码插口（checks / synth / dispatch），新增内置材料走注册表；框架不够用就先和用户讨论改框架。
- 不做兼容层：分出胜负后删掉输的项目和 `EVAL_AXES_PROJECTS` 里的那一项。

## 15. 待确认 ⟡

1. ~~承载性迁入时的配置~~：已定，见 §12.3（10-27）。
2. 分发子 loop 并发执行：第一期串行，耗时数据出来后再定。
