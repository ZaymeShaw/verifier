# 场景扩展评估轴 v5：ES 知识源、可选依赖、真实性轴

状态：设计稿，未实现。范围仍是 `llm_probe` 内的扩展评估轴；生产轴1/轴2不改。
本文是 v4 的增量：v4 全部保留，这里只写新增和改动。

---

## 0. 本版决定（一眼可否决）

| # | 决定 | 依据 |
|---|---|---|
| D13 | ES 作为资料工具箱的**第二种数据源**接入，引用记号 `{es://<index>}`，与 `{material://}` 并列；不把 ES 导出成文件 | 知识本来就在 ES 里，导出会过期；工具箱合同本就允许"只读 + 出回执 + 范围受限"的工具加入 |
| D14 | ES 访问走标准库 HTTP（`GET _doc` / `POST _search` / `GET _mapping` 三个调用），**不引入** `elasticsearch` 库；地址和凭据走 `config.yaml` 注册 + `required_when` 条件必填 | 零新增依赖；没启用 ES 的部署不用装库也不用配变量 |
| D15 | ES 文档形状不假设：locator 两级 `<_id>#<field>`（字段级可选）；可检索字段由 `es_outline` 现场从 mapping 读出，场景框描述里可指定优先字段 | 用户明确 ES 文档形状尚不确定 |
| D16 | 依赖协议加"可选依赖"：`Dependency(type_id, optional=True)`。可选上游在本预设没有框或未启用 → 当它不存在，正常跑；有且启用 → 等它、吃它 | 让 fulfillment 能按场景选择是否依赖真实性轴，同时守住"框就是开关"、不开放场景级依赖编辑 |
| D17 | 新类型 `truthfulness`：核的是**回答里的事实断言 vs 知识库**，`verdict_scope=item`，逐断言 `verified / refuted / unverifiable`；输入只有 `sample.trace`；不给轴2用 | 用户确认 |
| D18 | fulfillment 声明可选输入 `truth ← axis.truthfulness.output`；有则作为证据注入 prompt，被 `refuted` 的断言按 not_fulfilled 处理；结果所依赖的断言被判 `unverifiable`、trace 内也没有业务核实记录时，相关期望判 not_evaluable，不得自行推测成 fulfilled（2026-10-17 补）。这使启用真实性框的场景下 fulfillment 的 prompt 与生产分叉，列入已知差异 | 让轴1不必自己查库，保持轻 |

---

## 1. ES 数据源

### 1.1 引用与解析

场景框的描述里写 `{es://<知识源名>/<index>}`（可带多个）。各业务系统的 ES 各自独立，知识源名指向 §1.4 登记的连接。解析规则与 `{material://}` 同一套：

- 保存时（`capability_store.validate_entry`）校格式：`es://` 后是 `<知识源名>/<索引名>`（`^[a-z0-9][a-z0-9_-]*/[a-z0-9][a-z0-9_.-]*$`）；**不连 ES**，保存不依赖服务在线。
- 加载时（`eval_axes/validate.py`）：引用的知识源未登记、或登记配置不合法（地址、凭据变量未设置等）→ 报错，跑之前拦。
- 运行时：`{es://}` 不内联正文（ES 是活数据、无边界），一律转目录条目 + 工具，和 `{material://}` 超预算时的路径一致。目录条目形状：

```yaml
source: es
uri: es://biz-a/kb_policy
title: biz-a/kb_policy      # 知识源名/索引名，工具的 index 参数就填它
description: <框描述里紧跟引用的一句话，可空>
doc_count: 12873            # 加载时 _count 取一次
snapshot_id: <index_uuid>@<查询时刻 ISO>   # ES 没有内容封口，只能记时刻
```

### 1.2 工具

与 `material_*` 三件套同形，加 `es_` 前缀，同一个 `build_material_tools` 里按目录条目的 `source` 分发：

| 工具 | 对应 ES 调用 | 返回 |
|---|---|---|
| `es_outline(index)` | `GET /<index>/_mapping` + `_count` | 字段清单（名、类型、是否 text/keyword）、文档数；标出可全文检索的 text 字段。这是 D15 "形状不假设"的落点 |
| `es_search(index, query, fields?)` | `POST /<index>/_search`，`multi_match` on `fields`（缺省 = outline 里所有 text 字段），`highlight` 开 | 命中列表：`locator=<_id>#<field>`、得分、高亮片段（截断） |
| `es_read(index, locator)` | `GET /<index>/_doc/<_id>` 取 `_source`，按 `#<field>` 投影 | 字段原文（超长截断并标注）；locator 只有 `_id` 时返回整篇的字段摘要 |

只读、每次调用出回执（tool、参数、返回的 locator 列表）、只准查目录里出现的索引——三条准入规则不变。`tool_call_limit` 沿用 8。

### 1.3 引用核验

`citations[].source = es://<知识源名>/<index>`，`ref = <_id>#<field>`，`note = 逐字引句`。核验 = `es_read` 回读该字段，`quote_in_text` 检查。回读失败（文档被删/字段不存在）→ 核验失败 → 打回重试，与文件资料同一节奏。

### 1.4 配置：按业务系统登记知识源

（2026-10-13 改：原为 `config.yaml` 的 `eval_axes.es` 单节 + 4 个 `EVAL_AXES_ES_*` 变量，一个部署只能连一个 ES；多业务系统各有独立 ES，已删除，不留兼容。）

登记文件 `knowledge_sources.json`，与 `capability_map.json` 同一数据根（仓库 `impl/data/llm_probe/` 或实例数据目录），由资料管理页「知识源（各业务系统）」分区增删改、测试连接；被预设引用的知识源不能删。按名字登记：

```json
{
  "biz-a": {"type": "es", "url": "http://es-a:9200", "api_key": "${BIZ_A_ES_API_KEY}"},
  "biz-b": {"type": "es", "url": "https://es-b:9200", "basic_auth": "${BIZ_B_ES_AUTH}", "max_hits": 5}
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `type` | 是 | 目前只有 `es` |
| `url` | 是 | 无凭据的 HTTP(S) 地址 |
| `api_key` / `basic_auth` | 否，二选一 | 写 `${VAR}`，值取 .env + 进程环境（进程覆盖 .env）；变量须在 `project.yaml` 的 environment 里登记 |
| `timeout_seconds` / `max_hits` / `max_field_chars` | 否 | 缺省 15 / 8 / 6000 |
| `description` | 否 | 给人看的说明 |

凭据写法与被测服务请求头的 `${VAR}` 同一套。读登记不连 ES。

### 1.4.1 MCP 知识源（2026-10-14 加）

业务系统把查询接口做成 MCP 服务时，登记 `type: mcp`（与 `.mcp.json` 的 `mcpServers` 条目同形，只支持 stdio）：

```json
{"insurance-tools": {"type": "mcp", "command": "/abs/.venv/bin/python", "args": ["-m", "itools"], "env": {"ENV_TYPE": "dev", "ITOOLS_AGENT_ID": "${ITOOLS_AGENT_ID}"}}}
```

场景描述写 `{mcp://<知识源名>}`。运行时：
- 工具名、说明、入参 schema 全部取自 MCP `tools/list`，对模型暴露为 `<知识源名>__<工具名>`（非字母数字换成 `_`）；另加 `mcp_read(call_id, start)` 翻页。客户端用 fastmcp 2.2.0（不升级现有依赖能装的最高版本），每次调用拉起一次进程、用完即关。
- 每次调用产生 `call_id = mcp://<知识源>#<序号>`，完整返回原文进回执；引用 `source=mcp://<知识源>`、`ref=call_id`、`note=逐字引句`，回读只核对本轮回执里的原文（返回体是 JSON 时也比对解出的字符串字段）。
- MCP 是业务自己的检索：它没查到不等于知识库没有；评测侧借它查，会继承它的检索缺陷。

真实性轴通用约束（同日加）：有知识源时判 `unverifiable` 前至少调用一次知识源工具，否则打回重做——"没查就说查不到"不收。

### 1.5 实现位置

```
impl/projects/llm_probe/eval_axes/
  sources/
    __init__.py       # 目录条目 → 工具集 的分发：source=material 走现有 material_tools，source=es 走 es_tools
    registry.py       # 知识源登记：knowledge_sources.json（与 capability_map.json 同数据根）按名字取连接，展开 ${VAR} 凭据；增删由资料管理页「知识源」分区维护
    mcp_tools.py      # MCP 知识源：tools/list 原样转工具、调用原文进回执、按 call_id 回读核验
    es_client.py      # stdlib urllib：get_doc / search / mapping / count；错误映射；超时；一个知识源一个客户端
    es_tools.py       # es_outline / es_search / es_read + verify_quote，VerifiableTool 形状
```

`material_tools.py` 不改；`build_material_tools` 的调用点改为调 `sources.build_tools(catalog, recorder)`，内部把 material 条目原样交给旧函数。`text_carrier.py`（生产）不碰，扩展轴的 `BoxBoundaryCarrier` 才走新分发——所以 carryability 的边界描述也能引用 `{es://}`，但这是顺带，首版不主推。

---

## 2. 可选依赖

### 2.1 类型层

```python
@dataclass(frozen=True)
class Dependency:
    type_id: str
    optional: bool = False

AxisType.depend_on: tuple[Dependency | str, ...]   # str 等价于 Dependency(str)
Input.required 已有；可选上游的输入槽必须 required=False（构造时校验）
```

### 2.2 运行器（v4 §5 第 2 步改写）

```
2. 对每个 depend_on 项：
   - 必选：上游不在本预设 / 未启用 / 未 succeeded → 本轴 blocked（不变）
   - 可选：上游不在本预设或未启用 → 视为不存在，继续；
           上游存在且启用 → 等它结束；succeeded → 输入槽有值；
                             其他状态 → 输入槽为空，继续跑，trigger_decision 记 upstream 状态，
                             summary.text 追加"（<上游>未完成，未纳入）"
```

拓扑排序把可选边也算进去（保证先后），只是缺边不报错。

### 2.3 加载期校验（v4 §7 增改）

| 规则 | 级别 |
|---|---|
| 必选 `depend_on` 引用的类型必须在本预设内已启用 | 错误（不变） |
| 可选 `depend_on` 引用的类型可以不在本预设 | 允许 |
| 可选上游对应的 `Input` 必须 `required=False` | 错误（类型构造期） |
| `trigger_when` 不得引用可选上游 | 错误（筛选条件必须确定存在） |

### 2.4 场景配置者看到的

不变：加框、写描述、勾启用。fulfillment 框的只读区多一行"可选依赖：truthfulness（本预设已启用 / 未配置）"。

---

## 3. `truthfulness` 类型

```python
AXIS_TYPE = AxisType(
    type_id="truthfulness",
    title="真实性",
    summary="从回答里提取事实断言，逐条对照知识库核验",
    verdict_scope="item",
    verdict_enum=(
        Verdict("verified",     "知识库中有原文支持该断言"),
        Verdict("refuted",      "知识库原文与该断言矛盾"),
        Verdict("unverifiable", "知识库中找不到能支持或反驳的原文"),
    ),
    item_path="claims[].verdict",
    depend_on=(),
    trigger_when=None,
    inputs=(Input("trace", source="sample.trace"),),        # 只看回答，不看轴1/轴2
    output_fields=("claims", "sources", "coverage", "errors"),
    scenario_fields=(Field("description", required=True, expand="catalog"),),   # 描述里写核什么 + {es://…}
    limits=ExecutionLimits(llm_calls=None, tool_calls=8, seconds=None),
    run=run_truthfulness,
)
```

### 3.1 输出

```yaml
claims:
  - claim_id: 犹豫期天数
    text: "犹豫期为15天"                    # 一个具体值及其事项，逐字摘自回答；一句多值拆多条，套话/建议不抽
    context: ["康宁终身险"]                  # 核验所需的最少上下文片段（对象、成立条件），逐字摘自回答；不得含别条断言的值
    verdict: refuted
    reason: "知识库条款写明犹豫期为20天"
    citations: [{source: es://kb_policy, ref: "doc_8821#clause_text", note: "犹豫期二十日"}]
sources: [{uri: es://kb_policy, snapshot_id: ...}]
coverage: {extracted: 4, verified: 2, refuted: 1, unverifiable: 1}
errors: []                                  # 某条断言核验失败（工具错、重试耗尽）
```

`summary.text` 复制"裁决列"的写法：`$refuted\n犹豫期天数（…）\n\n$unverifiable\n…`；`items` = 每条断言一格。`errors` 非空 → `status=failed`（与轴2同规则）。回答里**没有可核的事实断言**（纯操作性回复、拒答）→ `claims=[]`，`status=succeeded`，`summary.text="回答不含可核验的事实断言"`——这是业务结论，不是 not_applicable。

### 3.2 `run()` 流程（多阶段，各阶段输入隔离）

```
① 提取断言   输入：output_text（+ 用户问题作背景）
            输出：claims[].text + claims[].context（都逐字引自回答，机械核验必须在 output_text 里；
                  一条断言一个值，context 保住对象和条件——只留“犹豫期二十天”会被别的产品的条款核验成 verified；
                  context 不得含别条断言的 text，否则等于把整句塞回来，隔离失效，程序打回）
            一次结构化调用；不给工具
② 逐条核验   输入：一条断言 + 框描述 + 目录条目 + es_*/material_* 工具
            输出：verdict / reason / citations；refuted 与 verified 必须有引用，引用回读核验，不过打回重试（≤3）
            每条一次会话；不看其他断言、不看轴1
③ 汇总       确定性程序：coverage 计数、errors 收集、summary 拼装。不再调模型
```

阶段①提取不出断言就直接到③。阶段②的 prompt 只说"这条断言在资料里能否找到支持/反驳"，不问"回答对不对"。

### 3.3 fulfillment 如何消费（D18）

```python
# fulfillment 类型声明增改
depend_on=(Dependency("truthfulness", optional=True),),
inputs=(
    Input("trace", source="sample.trace"),
    Input("truth", source="axis.truthfulness.output", fields=("claims", "coverage"), required=False),
),
```

`build_context` 里：`inputs.get("truth")` 有值时，`user_prompt_extras["truthfulness"] = {claims: [...仅 claim_id/text/context/verdict/reason/citations...]}`，`system_prompt_extras` 追加：

> ## 真实性核验结果
> 上游已对回答中的事实断言逐条核验。`refuted` 的断言视为事实错误，据此判相关期望 not_fulfilled。
> `unverifiable` 表示评测侧在知识源里没找到支持它的原文——可能是业务编造，也可能是评测侧没检索到，不能据此判对，也不能据此判错：结论依赖该断言的期望判 not_evaluable，不判 fulfilled，也不判 not_fulfilled；trace 里有业务自己核实过该事实的记录时除外。
> 不要重复核验，也不要发明核验结果里没有的断言。

（2026-10-14 改：原句"`unverifiable` 不构成失败依据"写死了放过，实测编造的现金价值比例在最高推理档 9/9 判 fulfilled；中间版本按能力描述判 not_fulfilled，会把评测侧漏检误判成业务没办成。定为 not_evaluable：不放过，也不冤枉。）

没有 `truth` 时这两段都不出现，prompt 与生产逐字相同（现有的逐字相等测试继续钉住这条路径）。

**2026-10-17 补（与 10-14 口径合并于 integrate/langfuse-notrace）**：在 10-14 口径上补一个例外——trace 里有业务自己核实过该事实的记录（例如业务调了详情接口、返回里有能对上的字段）时，不因真实性轴 unverifiable 判 not_evaluable。主轴不得把真实性轴的 `unverifiable` 自行升级为成立。只在场景启用了真实性轴时生效。
trace 路线主判提示词里的"需要的证据缺失时判 not_evaluable，即使答复可读也不能据此通过"（`impl/projects/llm_probe/judge.py`）早于本条、对所有 trace 场景生效，出处是 `spec/alg/fulfilled.md` §2.1，不是本条。
背景：Langfuse 验收的单轮 case（`spec/implementation/business-trace-langfuse.md` 真实验收结果）。
实测：`report/d18-validation-20261017/RESULT.md`（核心核实不了的 3 条由 F×9 变 NE×9，其余 13 条及注入的附带细节检查结论不变）。

---

## 4. 已知差异（v4 §11 追加）

| 差异 | 旧 | 新 | 为什么 |
|---|---|---|---|
| 启用真实性框后 fulfillment 的 prompt | 无 | 多"真实性核验结果"两段 | D18；只在启用了框的场景出现，对照等价性对这类场景不再成立 |
| 知识源 | 只有文件资料 | 文件 + ES | ES 无内容封口，`snapshot_id` 是时刻不是哈希 |

---

## 5. 触点与落地顺序

新增全部在 `eval_axes/` 内：`types.py`（Dependency）、`runner.py`（可选依赖）、`validate.py`（校验增改 + es 引用）、`sources/`（三文件）、`adapters/truthfulness.py`、`adapters/fulfillment.py`（可选输入 + prompt 注入）。

共享文件加法：`config.yaml` / `config_schema.py` / `config.py`（`eval_axes.es` 节与 4 个变量）、`capability_store.py`（`{es://}` 格式校验分支）、`materials.html`（只读区显示可选依赖）、`summary.html` 无改动（第 14 列按 items 渲染，真实性轴自动能显示）。

不碰：生产轴1/轴2、`material_tools.py`、`text_carrier.py`、`materials_store.py`。不新增 Python 依赖。

顺序：
1. `Dependency` + 可选依赖运行器/校验 + 单测（无 ES）。
2. `sources/` 分发层 + `es_client` + `es_tools` + 配置；单测用假 HTTP 服务器（stdlib `http.server`）模拟 `_mapping / _search / _doc`。
3. `truthfulness` 类型 + 单测（假 LLM + 假 ES）。
4. fulfillment 可选输入 + prompt 注入 + 逐字相等测试（无 truth 时必须和生产相同）。
5. 接你们一个真实 ES 索引跑通一条，看 `es_outline` 对实际 mapping 的可用性，再定 `es_search` 的默认字段策略。

## 6. 留待

- ES 向量检索（kNN）：等知道索引里有没有向量字段再说；`es_search` 先只做 `multi_match`。
- 真实性轴给轴2用：不做（D17）。
- 场景级编辑依赖图：仍不做；可选依赖已覆盖当前需求。
- 除 ES 之外的数据源（数据库表、HTTP 知识 API）：`sources/` 的分发结构留了位置，需求来了再加。

## 实施记录（2026-09-09）

按 `handoff-axe-v5.md` 的顺序实施；每步先通过 `tests/test_llm_probe_eval_axes.py` 再进入下一步。所有 Python / pytest 均经 `bash run.sh python ...`。未提交 git。

### 做了什么

- `eval_axes/types.py`、`registry.py`、`validate.py`、`runner.py`：新增 `Dependency`，构造时规范化字符串依赖；可选依赖参与拓扑排序，失败输出不注入下游，保留上游状态并追加未纳入说明；拒绝可选必填输入及可选上游筛选。API 依赖声明统一返回 `{type_id, optional}`；`impl/frontend/materials.html` 同步显示。
- `eval_axes/sources/{__init__,es_client,es_tools}.py`：标准库 HTTP 接入 ES，目录分发、mapping 字段发现、multi_match/highlight、字段回读、范围守卫、逐调用回执与引用核验；文件目录原样交给已有工具箱。
- `impl/config.yaml`、`impl/core/config_schema.py`、`impl/core/config.py`、`.env.example`：注册 ES 类型化配置及四个变量、URL 条件必填、禁用时跳过 ES 连接参数解析、密钥不进入公开配置视图。保存期只校 `{es://}` 格式；加载期检查启用状态及连接配置，不连网。`impl/core/capability_store.py` 的 material 校验分支未改。
- `eval_axes/adapters/carryability.py`：仅扩展轴接入资料分发，追加 ES 工具说明与引用回读，ES 查询时刻参与快照，引用回读纳入工具用量。生产 `TextCarrier` / `material_tools.py` 未改。
- `eval_axes/adapters/truthfulness.py`：断言提取、逐条独立核验、程序汇总；断言必须是回答的连续原文；有结论的引用必须回读，单断言最多三次尝试；部分结果保留但 errors 非空即 failed；无断言成功返回空列表。全部新客户端经 `axis_llm`。
- `eval_axes/adapters/fulfillment.py`：可选 truth 输入仅投影 claims/coverage，有值时只增加 §3.3 指定的 system/user 材料；无值逐字保持生产材料。失败出口也提供非空 summary。
- `tests/test_llm_probe_eval_axes.py`：覆盖依赖四种上游状态、静态拒绝、假 HTTP ES、配置条件及隔离、文件工具分发、三阶段输入隔离、伪造断言/引用、重试/部分失败、无断言及三轴端到端。保留原生产逐字相等测试。

### 与设计稿的偏差及原因

1. 为实现真实的 `<index_uuid>@<时刻>`，增加只读 `GET /<index>/_settings/index.uuid`。设计列出的 mapping/count 接口不提供索引 UUID，不能伪造。API 依据：https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-indices-get-settings 。引用限定为具体索引，别名/多索引不冒充单索引快照。
2. mapping 中递归展示 object、multi-field、nested；multi-field locator 映射回 `_source` 字段。nested 字段明确标注且不默认搜索，显式搜索时说明需要 nested 查询，不把普通 multi_match 的漏检伪装成不存在。真实索引字段策略仍待人工接入确认。
3. 真实性轴将引用的文件资料统一目录化，即使小文件也提供工具和来源快照；原承载性小资料内联路径不变。这保证文件断言也能用 locator 回读。
4. 为使 ES 引用在扩展承载性轴中真正可用，除工具分发外覆盖其重试核验入口和快照入口；仍复用生产解析、文件核验及锁定的 `place()`。扩展轴工具硬限按交接固定为 8（生产当前是 16，未改）。
5. 原两项模型策略测试受本机 `.env` 的 `same_model` 干扰：显式隔离测试策略，保留 `any` 默认及环境覆盖断言。同步 `.env.example`，其中补上 HEAD 已遗漏的模型策略变量。

### 没有做

没有连接真实 ES、添加 Python 依赖、实现向量/nested 检索、开放场景依赖编辑、让轴2消费真实性结果；没有改生产轴1/轴2、`materials_store.py`、`summary.html`、`live.html`、`tmp/` 对照脚本或 `project.yaml`；没有修复本轮无关的既有回归失败。

### 测试结果

- 第 1 步：37 passed。
- 第 2 步：43 passed；附加配置合同联合测试 75 passed / 1 个交接已知失败。
- 第 3 步：52 passed。
- 第 4 步：56 passed；随后补充文件资料和配置边界测试，最终结果见下。
- 指定八文件回归首轮：234 passed / 3 failed，均为交接已知项（配置消费者旁路、summary 两个 JSON 呈现测试）。
- 全量回归（Codex 因额度用尽中断后由接手方补跑）：1189 passed / 17 failed / 4 skipped / 1 deselected。17 个失败全部在 HEAD（`85c2c439`）上以相同 ID 复现：`test_deerflow_attribute_evidence` ×6、`test_golden_multiturn::test_golden_replay` ×6（HEAD worktree 复制本机 `.env` 后同样失败，属环境项）、`test_project_live_smoke::test_marketting_planning_live_run_smoke`、`test_schema_validator` ×2、`test_summary_trace_column` 的两个 JSON 呈现测试。**新增失败为零。**
- 接手方复核：生产保护文件与 `requirements.txt` 对 HEAD 零 diff；新代码无 `os.getenv` / `elasticsearch` 导入；所有新客户端经 `axis_llm`；生产逐字相等测试原样保留；`eval_axes` 套件在配置类测试之后运行亦全绿（161 passed），无测试顺序依赖。
