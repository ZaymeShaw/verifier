# 资源与引用：实现记录

需求 `demand/draft-20261104/resources-pilot.md`（2026-11-04 确认）；算法 `spec/alg/resources.md`（同日确认）。

## 1. P1 离线复核（2026-11-04）

### 1.1 新增（现有代码、配置、提示词、校验都没改；新代码只被测试与离线脚本引用）

| 位置 | 内容 |
|---|---|
| `impl/core/resources/spec.py` | 地址 `Address`（解析、上一级；不带 `#`）、JSON Pointer 拼接与拆分（内部记位置用）、`Block`（MCP `Resource` 描述 + 正文）、`_meta` 前缀 `local.verifier/` |
| `impl/core/resources/text.py` | `render`：与 `dump` 逐字一致的规范序列化 + 区间对照表；`normalize_map` / `find_all` / `closest`：带下标映射的宽容比对；`smallest`：包含区间的最小节点 |
| `impl/core/resources/types/record_set.py` | 记录集：`text`、`templates`（字段模板 `{+record}/fields/{field}`）、`resolve`、`slice`、`read`（返回 MCP `TextResourceContents`）、`locate`、`extract`、`role`（结构化 `Role`） |
| `impl/core/resources/mount.py` | `ResourceTable`：`mount` 建 MCP 描述（校验 RFC 3986、唯一、直接资源不互为上下级）、`get`、`part`（地址 → 块 + 节点）、`list`（= resources/list）、`templates`（= resources/templates/list）、`read`（= resources/read：直接 / 模板 / 自动生成的目录资源 `inode/directory`） |
| `impl/core/resources/cite.py` | 公共核对：资源存在 → 读过 → 在引用范围内 → 找得到即过；只收完整地址；返回各处命中（节点、规范文本上的区间）与角色；不过给原因与提示 |
| `impl/projects/llm_probe_loop/business_trace/providers/langfuse.py` | provider 约定加 `mount(dossier, table)`：目录标签取自正文，角色表按 `links.TYPE_AXES` 分轴，放 `_meta` |
| `tests/test_resources_text.py`、`test_resources_cite.py`、`test_langfuse_mount.py` | 20 个用例，全过 |
| `report/resources-pilot-20261104/recheck.py`、`README.md` | 复核脚本与结果 |

### 1.2 与 spec 的出入（已在 spec 里注明"实现时修订"）

- 挂载收的是按 case 建的案卷而不是单份快照，实现放在 provider 模块（案卷把多轮快照合起来建、编号带 `turnN/` 前缀，单份快照对不上）。
- 宽容规则加了中英文引号归一（16 条引用只差在弯引号）。

### 1.3 按 MCP 资源标准修订（2026-11-04，审查后，用户确认）

审查（check / Bussiness / aihacking）发现的标准问题，改法都以 MCP 资源标准为准（spec/alg §0）：

| # | 问题 | 改法 |
|---|---|---|
| C1 | 挂载直接拿 `link_type` 当轴名（现在两者恰好一对一同名） | 改查 `links.TYPE_AXES`，与过程轴核对同一张表 |
| C2 | `outline` 没被用、没测试，签名与 spec 不一致；列目录本不是类型能做的事（类型拿不到资源表） | 删 `RecordSet.outline` 与 `ResourceTable.children`；列目录改为读目录资源，`read` 返回 MCP 结构，均补测试 |
| C3 | `meta` 混了目录标签与记录属性，和正文重复——标准没定清 | 资源 = MCP 描述 + 正文：能引的全在正文；目录标签放描述标准字段；类型名、角色表放 `_meta`。原 `meta`、`params` 删掉 |
| O1 | 框架 `cite` 默认补 `trace://`、转裸编号，把项目约定写进了框架 | `cite` 只收完整地址，转换放调用方（P1 是复核脚本） |
| O2 | spec 的类型接口写"传地址"，类型却拿不到资源表 | 类型接口改为收一块资源；按地址取与列目录归资源表 |
| O3 | `role` 返回拼好的中文串，参数键叫"轴"（项目概念） | 返回结构化 `Role`；参数键改"视角"，中文标签由复核脚本转；"元信息"改称"属性" |

验证：改前改后各跑一遍复核，910 条 × 两种口径的判定、节点、区间、seen_only、命中各处逐条比对，**0 条不同**（只有角色标签"元信息"改名"属性"）。

### 1.4 结果（详见 `report/resources-pilot-20261104/README.md`）

910 条过程轴引用（§1.8 之后的口径）：误拒消掉 102 条（宽松口径；严格 81 条），真错误 2 条仍被拒；原来没拒的 806 条里只拦深层值没展开的 2 条，另有 166 条"跨字段多处"单列待使用方判（去重占位由复核脚本还原后 28 条全过，见 §1.7）。

### 1.5 推广前必做

- **C4 宽容规则收成一套**：现在有四份——`axis_loop/text.py` 的 `_normalize`、过程轴核对（另加弯引号）、说法轴 `claims/checks.py`（`_plain` + 引号表）、`resources/text.py`（`_normalize` 的带下标版 + 说法轴引号表）。P1 不动现有三份；推广时只留 `resources/text.py` 一份，其余改为引用它。
- 地址里加 case / run 编号：真当 MCP 服务对外提供时需要（2026-07-28 版要求列表不随连接变）；离线一张表一个 case 不需要。

### 1.6 待定

- "一条引用够不够支撑结论"（④ 业务使用方）：引用写在整条记录这一级、命中好几个字段时够不够，P2 定。
- 现有展示的两个问题（与试点无关）：深层值没展开成原文（约 5% 读回的记录）；同一条记录两种渲染（本轴材料与 `case.trace`）。

### 1.7 地址写到字段；去重归调用方（2026-11-04，用户确认；"写到字段"的做法已被 §1.8 取代）

| 位置 | 改动 |
|---|---|
| `types/record_set.py` `locate` | 加 `pointer`：只在该节点里找（对象成员连键名算），这份看到的文本里没有该节点返回 None |
| `cite.py` | 地址带块内位置时按节点找；各份看到的文本里都没有该节点 → `no_node`；`not_found` / `ambiguous` 回带完整地址 |
| `tests/test_resources_cite.py` | 加 3 个：写到字段收窄、`no_node` 与找不到时提示原文所在节点、同节点重复仍对上多处；共 20 个，全过 |
| `report/…/recheck.py` | 去重是上游展示层的事、资源层不管：复核脚本算"看到过"时把"〔同 X 里已给过的那段，N 字〕"还原——取这一块正文同一位置的原文、且该原文在 X 看到的某份里出现过才还原 |

复核重跑：原 28 条去重占位"找不到"全过（角色按被引这一块：输出端 24、输入端 4）；1 条原通过的因还原多出一处变对上多处；其余判定不变。过程轴现在的提交写不了块内位置，所以这批数据里没有写到字段的引用；P2 要改提交格式与提示词，动之前另报。

### 1.8 直接资源 + 模板资源；去掉 `#` 与"只能对上一处"（2026-11-04，用户确认）

起因：MCP 里能单独读、单独引的最小单位是一个 URI。`#` 后面不是资源（RFC 6901 明说 `application/json` 的片段不是 JSON Pointer），按 MCP 读到的仍是整条记录。MCP 的标准做法是两种资源：基本单位逐条列出（直接资源），更细的按地址形状声明、读时现取（模板资源，RFC 6570），官方示例服务、文件类服务都这么做。

分工（spec/alg §0.1）：资源类型按数据长相定义、放在资源层，langfuse 与 agno 建成案卷后记录长相相同，共用记录集；信息源只写挂载。

| 位置 | 改动 |
|---|---|
| `spec.py` | `Address` 去掉块内位置，带 `#` 的地址不收 |
| `types/record_set.py` | 加 `templates`（`{scheme}://{+record}/fields/{field}`）、`resolve`（以最后一个 `/fields/` 为界拆）、`slice`（该节点在整条记录规范文本里那一段）；`read` 可读字段；`locate` 的范围改为地址所指的资源；`Role` 可排序 |
| `mount.py` | 加 `part`、`templates`；`read` 认模板地址（交给类型 `resolve`，所属块须已挂且类型一致）；不存在报"资源不存在" |
| `cite.py` | 资源是最小引用单位：找到即过，不再判"对上多处"（`ambiguous`、`no_node` 删掉）；结果改为各处命中 `regions` + 角色 `roles` |
| `tests/test_resources_cite.py` | 改为：模板声明、读字段资源（文本与整条记录里那段一致）、读不存在的字段报错、记录级命中两端照过并报两种角色、字段级只落一端、同一资源里重复全过；共 20 个，全过 |
| `report/…/recheck.py` | 通过的分三档：一处 / 同一字段多处 / 跨字段多处（需使用方判） |
| `providers/langfuse.py` | 不改 |

复核重跑与改前逐条比对：原来通过的 643 条（宽松；严格 629）节点、角色、区间全部不变；原来"对上多处"的 263 条（宽松）全部变成通过，命中节点集合与原来一致——同一字段多处 90、跨字段多处 173（其中原来没拒的 166）；拒的不变。过程轴现在的引用都写在记录级，没有字段级引用；字段级的效果要 P2 改提交格式后才看得到。

## 2. P2 实验（2026-11-05，隔离副本 `verifier-resources`，分支 `exp/resources-uri`；同日合回主工作区，未提交）

需求 `demand/draft-20261104/resources-p2.md`；算法 `spec/alg/resources.md` §10。源代码目录只改了文档；实验脚本在 scratchpad `p2/`（`dump_materials.py`、`check_visible.py`、`replay3.py`、`judge3.py`、`judge_expected.py`）。副本里的 `.env` 是指向源代码目录 `.env` 的链接（不改、不读出）。

### 2.1 改动（副本里）

| 位置 | 改动 |
|---|---|
| `impl/projects/llm_probe_loop/resources/`（新） | 登记表 `REGISTRY`、`case_trace.py`：`dossier.py` 的组织部分原样移入（`build_dossier`、`_snapshots`、`_Contents`、`expand_content`、`render_value`、`record_body`、`source_record`），`resources(dossier)` 每条记录（含每轮原始请求响应 `turnN`）一个记录集直接资源，`_meta` 记出处；`render_value` 深度 8 → 16 |
| `business_trace/dossier.py` 等 | 只剩展示；`tools.py`、`materials.py`、`links.py`、`design_rules.py`、`process_axes.py`、`eval_axes/materials.py` 改从 `case_trace` 引用；`eval_axes/materials.py` 的 `case.trace` 声明 `resources` |
| `business_trace/materials.py` | `material_view` 不再给模型字段来源 `ref` 与记录 `ref`（`same_as` 的判断改用案卷里的 ref） |
| `providers/langfuse.py` | 删 `mount` |
| `impl/core/resources/mount.py` | 删自动目录资源与"不能互为上下级"；同一地址只能是一个资源（含与模板地址相同）；`name` 唯一，加 `by_name` |
| `impl/core/resources/cite.py`、`types/record_set.py` | 去 `seen` / `not_seen` / `seen_only` / 视角与角色表；`role` → `place`；在规范文本里找 |
| `impl/core/resources/text.py` | 宽容规则加：引号、markdown 强调符号 `*` `` ` `` 两边都去掉 |
| `impl/core/axis_loop/materials.py` | `Material.resources`；`MaterialTable.resources`（一 case 一张）；取值时挂载，挂载出错 = 取不到 |
| `impl/core/axis_loop/visible.py`（新）、`view.py`、`loop.py` | `Visible`：按给模型的那份材料（`view`）算可见；`address` 按 name 换地址；`cite`；`TaskView.resources`；系统提示第 4 条改为出处分层级 + 原文照显示样子抄 |
| `axis_definitions.json` | 过程实际六轴：引文规则、`quotes.ref` / `quote` 说明（resources.md §10.6）；删"英文双引号写成中文引号…尽量摘不带引号" |
| `axis_code/<6 轴>/checks.py` | `check_actual(..., view.resources)` |
| 测试 | 删 `test_langfuse_mount.py`；加 `test_case_trace.py`；改 `test_resources_cite.py`、`test_resources_text.py`、`test_llm_probe_loop_process.py`；相关 293 个全过；全量测试副本多出的失败均为副本缺 `.env` / `report` 快照等未入库文件 |

### 2.2 结果（8037 那 22 条 run；1 条当时侦探没交结果，跳过）

1. **只搬家**：`case.trace` 与侦探合成 22 / 22 逐字节相同；资源 831 个与 `case.trace.records` 一一对应。深度 16：52 条记录（14 条 run）变，未展开的 `content_ref` 100 → 0，过程轴材料不变。
2. **可见性**：侦探 21 / 21、过程实际 126 / 126（= 严格口径）、过程本应 126 / 126 一致。实现时修订：按 `for_code` 算会把过程本应的不可见记录算进来（111 / 126 多算），改按 `view`。
3. **重放第一次提交**（老代码重新生成上下文 ≈ 当时记录：≤ 120 字差异，来自这段时间的代码变化；四组都按最终的资源核对判）：

| | 当时 | 老代码重放（基线） | 新·第一轮 | 新·第二轮（提示词与宽容规则修订后） |
|---|---|---|---|---|
| 引用 | 471 | 424 | 451 | 558 |
| 写到字段 | 0% | 0% | 89.8% | 96.1% |
| 跨字段多处 | 14.2% | 8.5% | 2.7% | 0% |
| 地址不存在 / 原文找不到 / 不在本轴材料里 | 0 / 1 / 14 | 0 / 2 / 26 | 3 / 0 / 4 | 0 / 6 / 3 |

第一轮 13 条拒（按当时的宽容规则）：3 条把记录属性 `name` 写成 `…/fields/name`（出处层级没定义清 → 系统规则 4 统一定义）；7 条格式改写（"键: 值" 5 条，起因是旧提示"尽量摘不带引号"；漏 `**` 2 条 → 宽容规则）；2 条结尾多补、1 条两处原文混成一句（真错误）。第二轮 6 条找不到全是真错误：2 条把 `"level": {…"value": "DEFAULT"}` 压扁成 `"level": "DEFAULT"`，4 条把输出端（`tool_calls` 参数）写成输入端（记录级写法下会放过）。
判定标准（需求 §5.4）：1 达到；2 达到（真错误除外 0 ≤ 基线 2 + 2）；3 过程本应（第一轮）新 vs 当时 条数差 61 / about 不同 323，老 vs 当时 61 / 319，在波动内；第二轮（全局系统规则改后）用最终代码再跑：新 vs 当时 63 / 307，仍在波动内；4 达到（引用多 32%）。

### 2.3 已知、未处理

- 同一条记录两种渲染：过程轴看的材料字段没有 `chars`，资源正文有（P2 原则 3 未完全做到）；这两轮没有因此被拒的引用，暂缓（用户 11-05 定）。
- 老代码重放在源代码目录跑时新增的 21 个 `resources-p2-*` 调用记录目录已删（用户 11-05 定）。

### 2.4 隔离实例真跑（需求 §5.5；2026-11-05）

同一份存档（8037 那 22 条 run 存下的 trace），不调业务系统，全部轴从头评一遍：老代码在源代码目录、实例 `inst-0000000000000a01`；新代码在副本、实例 `inst-0000000000000b02`（两个都是 8037 的拷贝，新的换了 `axis_definitions.json` 与 6 个 `checks.py`）。脚本 scratchpad `p2/bench_p2.py`、`bench_compare.py`。22 / 22 两边都跑完。

| | 老代码 | 新代码 |
|---|---|---|
| 模型调用 | 395 | 368 |
| token 合计 | 11.69M | 10.40M（−11%） |
| 耗时合计 | 14889 s | 14124 s |
| 被拒提交（全部 / 过程实际） | 60 / 47 | 19 / 4 |
| 过程实际被拒原因 | 136（找不到原文 97、编号不在材料里 39） | 6（不在本轴材料里 5、找不到原文 1，都是真错） |
| 过程实际最终引用 / 写到字段 | 663 / 0 | 756 / 722（95.5%） |

结论翻转（每边 418 个结论）：老 vs 新不同 14 个，主结论 2 个；**噪声基线**：老代码 vs 8037 当时（同一套老代码）18 个，主结论 2 个。逐条看：

| case | 轴 | 当时 / 老 / 新 | 谁对 | 原因 |
|---|---|---|---|---|
| G01-short-answer | 意图理解 → 兑现、主结论 | sound·做成了 / 无法核·不确定 / sound·做成了 | 新 | 老代码两次误拒引文（"编号不在材料里""找不到原文"），模型放弃改判无法核——正是 P2 要消的误拒 |
| fuyunping-policies | 模型能力 → 兑现、主结论 | 不适用·做成了 / 不适用·做成了 / 无法核·不确定 | 老 | 新这次的本应把 `workflow.step.gate`（CHAIN，非模型调用）当模型步骤；与引用改动无关，属本应轴波动 |
| F01-name-correction、E01-ref-product-knowledge | 知识数据 | problematic / 无法核 / problematic | 新 | 查"平安安佑福"返回的是"平安e生保"文档，新与当时都抓到 |
| bizno | 知识数据 | 无法核 / 无法核 / sound | 存疑（偏老） | 客户号查无结果，新判"正常返回空"；"查无"怎么判是已知未定问题 |
| 4 条 | 模型能力 | — | 2 新 2 老 | 都是"调用工具时说了旁白"这一条有时抓到有时漏，两边各漏 2 次 |
| langfuse-F01 | 工具执行 | sound / problematic / sound | 老 | 第 2 轮 `HandlerUnavailable` 后重试，老抓到，当时与新都漏 |

不该受影响的轴：说法、真实等 128 个结论两边全同；兑现与主结论的翻转都跟着上游过程轴走。
另：说法轴格式错（`spans` 写成字符串）老 1 次 / 新 4 次，都在下一次提交改对、结论不变；可能与系统规则 4 新加的"JSON 键和字符串连同双引号照抄"有关，样本小，未定。

### 2.5 合回（2026-11-05，用户定）

- 代码：副本里改的 30 个文件原样拷进主工作区（26 改、1 删、3 新），逐个比对相同；主工作区自 f9c0b80f 起只改过文档，无重叠。
- 实例数据（服务读实例里的 `axis_definitions.json` 与 `axis_code/*/checks.py`，不读代码目录那份）：8036（`inst-33ff6254434841b0`）、8037（`inst-5ac0245dc11a4220`）先备份到 `dataset-building/backups/<实例>-20261105-resources-p2/`，再改。8037 与老代码一致，直接换成新文件；8036 多 12 处 `x-explain`，当时误以为是 8036 自己的配置，只替换了这次改的字段（6 轴 `instruction`、`quotes.ref` / `quote` 说明）；实为 11-04 去掉过程轴说明回合时 8036 特意没改、等用户定的旧配置（`spec/implementation/axis_loop.md` §21）。同日用户定去掉，8036 与代码目录、8037 逐字节相同（去之前那份备份为 `axis_definitions.with-explain-merged.json`）。6 个 `checks.py` 两边直接换。
- 其余实例（8022、8032–8035，当前都没在跑）仍是老 `checks.py`，新代码下过程实际六轴会报错；起之前要同样换，未动。


### 2.6 合回后 8036 现场回归（2026-11-05）

8036 跑 22 条：`verify-insurance-mcp` 11 条 + `verify-insurance-langfuse` 现场 11 条（真调业务系统）。批量会整个替换候选区，8036 原来的 120 条 dataset-A 已整份备份在 `dataset-building/backups/inst-33ff6254434841b0-20261105-resources-p2/latest_runs.sqlite3`。

- 第一轮 langfuse 11 条全部"trace 采集失败"：合回后重启服务时没先 `source scripts/import-env.sh`，Langfuse 钥匙只在 `.env-dynamic` 里，进程拿不到。补上后按行重跑这 11 条；与代码改动无关。
- mcp 11 / 11 完成（没有 trace，过程轴不跑）；主结论 做成了 6、没做成 4、不确定 1；没有可比的旧结果。
- langfuse 11 条对照 8037 当时（老代码、现场）：10 条出结论，主结论 9 条相同；fuyunping 不确定 → 做成了（新对，见 §2.4）；F01 超过全局墙钟上限 1500 s 没出结论（41 次调用）。过程实际被拒提交 23 → 5，最终引用 385 条、写到字段 349 条（91%）。
- 成本不能直接比：8036 的配置给 6 个过程轴配了 `x-explain`（8037 只有兑现轴有），每条 case 多 6 次"说明原因"调用；按 trace 复评的 bench（§2.4）两边同配置，调用 −7%。因此去掉 8036 的 12 处 `x-explain` 后，按行重跑这 11 条（job `3766f805`），结果见下。
- 剩下的 5 次过程实际被拒：`level` 压扁 1、把记录属性 `name` 写成 `…/fields/name` 2、不在本轴材料里 4、原文在输入端却写成输出端 1、**抄了去重占位"〔同 X 里已给过的那段，N 字〕" 2**。最后一类：材料里被去重换成占位的那段，模型看不到原文，只能去引 X；P1 时由复核脚本还原，P2 没有处理，待定。
- **去掉 8036 的 `x-explain` 后重跑**（job `3766f805`，与 8037 同配置）：11 / 11 出结论；对照 8037 当时：调用 196 → 190，耗时 8127 → 7087 s，过程实际被拒提交 23 → 0，最终引用 365 条、写到字段 357 条（98%）。主结论 9 / 11 相同；翻的 2 条都是业务这次答得不一样：bizno 当时答"未命中"、这次答出客户何承琪（没做成 → 做成了）；D16 这次严言琳的查询连续报 `upstream` 错、只给了一位的档案（做成了 → 没做成）。过程轴结论另有 13 处不同（模型能力 5 处为主），都落在这两条业务变化的 case 或已知的"旁白有时抓到有时漏"上。
- **逐条判对错**（按 `report/eval-gold-dataset-a/RULES.md` 口径，`q.py` 只读查数据源取证）：评测器主结论 22 条对 20 条（mcp 10 / 11、langfuse 10 / 11），错的 2 条都是判成"不确定"，没有误放行、没有误判没做成。mcp-C08：回答把 9117 两条险种的月缴 108.3 + 62.5 写成"约 1,170.8 元"（应 170.8），是用户没要的附带说错，按口径应判做成了，评测器判不确定；langfuse-fuyunping：回答正确，评测器又把 gate 步骤当成模型调用判无法核 → 不确定（§2.4 同一问题）。数据源核实的关键事实：严言雅为男（langfuse-D16 写"女"是错的）；何承琪手机 19909220884（langfuse-bizno 的"尾号 0884"属实，只是 trace 里脱敏，模型能力轴按"输入里没有"判编造）。
