你这个思考其实触及了 tool2.md 里被砍掉、但你一直放不下的那条线——**源代码拆解**。我说说我的看法。

## 你现在的纠结点

tool2.md 最终方案砍掉了通用拆解器、LiveSegment、重放器，理由是"太重"。但你心里清楚：**没有源码拆解，"找合适 tool"就失去了最硬的线索来源**——因为 tool 到底对应业务链路的哪一段、能验证什么，这件事的根在源码结构里，不在 trace 形状里，也不在 LLM 的猜测里。

现在的状态是：项目 adapter 手工挑了几个关键函数做成 tool（client_search 的 search_api / field_capability / rule_verify）。但"挑哪些函数"完全是人工判断，没有源码分析支撑——这等于把拆解器的活儿全压到人脑上了。

## 我的判断：源码拆解该回来，但定位要变

之前砍它是对的——**作为"全量链路重放器"它太重**（要拆完整条链路、要构造执行环境、要重放定位最早分歧）。

但**作为"tool 发现的辅助线索"它该回来**——定位从"全量重放"降级为"源码结构分析，产出 tool 候选 + 它们能验证什么"。

具体说，拆解器不再追求：
- ❌ 拆完整条 live 链路
- ❌ 构造可重放的 segment 闭环（输入schema→函数→输出schema）
- ❌ 沿链路重放定位最早分歧

而是只做：
- ✅ 从源码识别"这是 live 链路上的一个确定性转换函数"
- ✅ 标注它"能验证什么"（入参出参形状、是否确定性、环境依赖）
- ✅ 产出一份"候选关键函数清单"给项目 adapter 参考，adapter 从清单里挑哪些做成 tool

这样拆解器的输出不是重放用的 segment，而是**"tool 候选 + 能力标注"**——人（或 LLM）在这个清单上做最终挑选，比凭空想"该挑哪些函数"靠谱得多。

## 前端能不能成为辅助

能，而且正好契合你的两个期望：

**作为 tool 查看点**（期望1）：展示已注册 tool，这个不依赖拆解。

**作为"链路追踪线索帮找 tool"的辅助**（期望2）：前端可以展示拆解器产出的"源码结构 → 候选关键函数 → 能验证什么"这张图。你看着这张图，能判断：
- 哪些候选函数已经被做成 tool 了（已注册）
- 哪些候选函数还没做成 tool 但"看起来对归因有用"（拆解器标了它能验证某段，但 adapter 还没实现它）——这就是"该补哪些 tool"的线索
- 业务链路的大致形状（哪些函数在 live 链路上、上下游依赖）

所以前端的真正价值不是"自动发现 tool"，而是**把拆解器产出的源码结构可视化，让你人工判断"哪些候选值得做成 tool、现在的 tool 集合有没有覆盖关键链路段"**。这是个审查/规划工具，不是自动执行工具。

## 关于"大模型自动完成"的机制

如果将来想自动化，机制应该是：

1. **拆解器**（确定性，源码分析）：产出"候选关键函数 + 能力标注"清单
2. **LLM**（在清单上做有界决策）：看 trace + 候选清单，判断"这个 case 该验证哪几个候选"，并产出"把 X 候选做成 tool"的建议
3. **人/adapter**：把 LLM 建议的候选实现成 VerifiableTool

LLM 不在"全量源码"里盲选，而是在"拆解器筛过的候选清单"里选——选择空间被收窄了，可靠性才有保障。这和我之前讲的"通用层粗筛 + LLM 精细决策"是同一个思路，只是粗筛的依据从 trace 启发式升级成了源码拆解。

## 落地建议

如果你认同，推进顺序应该是：

1. 先做 tool.html 的"查看点"部分（期望1）——这个不依赖拆解器，纯展示已注册 tool + ToolResult 历史，能立刻用
2. 把源码拆解器作为一个**独立的辅助模块**做回来（不是全量重放，只做"候选函数 + 能力标注"），产出存到项目级 schema
3. tool.html 扩展"链路线索"栏（期望2）——可视化拆解器产出的候选清单，标注哪些已注册成 tool、哪些是缺口
4. LLM 自动发现作为最后一步，在前三步稳定后再上

核心一句话：**拆解器该回来，但从"全量重放器"降级为"tool 发现辅助器"；前端是这套结构的可视化审查工具，不是自动执行器。** 你觉得这个降级后的拆解器定位对吗？




---------




你说得对，前面那些分层（不管是四层还是三类）都是我脱离项目实际、凭空设计的框架，没有项目源码支撑，当然不可信。

## 我能做什么

我可以 spawn 一个 agent，专门做项目 research，从你们提供的项目实际源码出发，找到真正适合归因的 tool。这个 agent 的工作方式应该是：

1. **先读项目源码**，搞清楚这个项目的 live 链路实际长什么样——从入口到最终输出，真实经过了哪些函数/API/配置，而不是套一个预设的"分层"模子。

2. **沿真实链路逐个环节分析**，每个环节判断：
   - 它在链路里干什么（这是从源码看出来的事实，不是我预设的"路由层/处理层"标签）
   - 能不能试跑（直接调函数 / 调远程接口 / 跑不了）
   - 试跑能产出什么证据，对归因有没有用

3. **从分析结果里挑 tool**，挑的判据是"能产出 actual 证据支撑归因判断"，而不是"好实现"。

4. **每个挑出的 tool 当场试跑**，贴出 actual，跑不出 actual 的不算数。

## 需要你们提供什么

为了让这个 agent 真能干成事，你们需要提供：

- **业务系统源码的路径或访问方式**（比如 client_search 业务系统源码在 `llm_client_search_0513` 那个路径下）
- **哪些是 live 链路的入口**（或者让 agent 自己从 adapter.build_request / call_or_prepare 反查）
- **能调用的远程接口信息**（API 地址、鉴权方式，如果有）
- **能跑的环境**（哪些函数能本地直接跑，哪些需要 mock，哪些只能远程调）

## 关于"信任"的问题

前面不可信，根因是**我没有真的去读项目源码，只在脑子里设计框架**。spawn agent 的价值就在于它必须落地读源码、落地试跑，产出的是"这个项目实际链路是这样、这些函数能跑、这是 actual"——有事实支撑，不是空谈框架。

不过有件事我要说清楚：**我（当前这个响应）没有工具，spawn 不了 agent**。你要让主 agent 来 spawn——直接对它说"spawn 一个 agent 去做项目 research 找归因 tool"就行。它会带着我们刚才讨论的判据（actual 作证据、能试跑、不搞信息搬运、当场跑出 actual 才算数）去执行。



--------


## 完整方案：双模式归因

### 核心思路

在项目配置里加一个开关，让归因有两种运行模式：
- **固定 tool 模式**（低成本、稳定）：走现有 VerifiableTool + ToolOrchestrator，tool 是预定义的，LLM 在有限集合里选
- **Claude research 模式**（高上限、实验性）：放弃预定义 tool，让 Claude Code 直接读源码、调 API、跑函数，自由探索归因路径

两种模式共享同一套归因链路（judge → attribute → cluster → check），只是在 attribute 阶段的"怎么找证据"上分叉。

### 开关设计

在 `project.yaml` 或 `config.yaml` 里加：

```yaml
attribute:
  mode: fixed_tool  # fixed_tool | claude_research
  fixed_tool:
    tool_call_limit: 5
  claude_research:
    enabled: false
    model: sonnet       # 用什么模型跑 research
    max_turns: 20       # 最多探索多少轮
    output_report: true # 是否输出结构化报告
```

### 两种模式怎么工作

**固定 tool 模式**（现状，补全）：
- attribute agent 收到 case，拿到预注册的 VerifiableTool 列表
- 在 tool_call_limit 内选择调哪些 tool，拿到 actual 做归因
- 成本可控、可复现、适合批量评测

**Claude research 模式**（新增）：
- attribute 阶段不启动 agno agent，而是 spawn 一个 Claude Code skill（`attribution-research`）
- 这个 skill 拿到 case 的完整上下文（trace、judge 结果、项目源码路径、配置路径）
- 自由探索：Bash 读源码、Read 看配置、Bash curl 调 API、甚至 Bash python 跑本地函数
- 探索结束后，自己总结归因结论 + 调了哪些 tool/操作 + 每个操作拿到了什么 actual
- 这个总结是结构化 JSON，格式和 AttributeResult 对齐，可以直接喂给下游（cluster、check、前端）

### Claude research 模式的 skill 设计

`.claude/skills/attribution-research/SKILL.md` 核心内容：

```
你是归因研究员。给你一个 case 的问题现场（trace + judge），
你要去项目源码里找原因。

可用工具：Bash、Read、WebFetch、Grep、Glob

工作流程：
1. 读 trace.execution_trace，定位第一个 diverged/failed 节点
2. 从 adapter 源码反查这个节点对应的业务函数/API
3. 沿业务函数往上下游追溯，搞清楚数据流
4. 对每个关键环节，试着"执行验证"：
   - 调 API 拿当前 actual（curl）
   - 读配置看规则是否生效（Read YAML）
   - 跑本地函数看输出（python -c）
5. 产出归因结论 + 操作记录

输出格式（写死在 skill 里）：
{
  "root_cause": "...",
  "causal_chain": [...],
  "operations": [
    {"type": "api_call", "target": "...", "actual": {...}, "evidence": "..."},
    {"type": "config_read", "target": "...", "actual": {...}, "evidence": "..."},
    {"type": "function_run", "target": "...", "actual": {...}, "evidence": "..."}
  ],
  "suspected_locations": [...],
  "fix_direction": "..."
}
```

### 前端 tool.html 的定位

在两种模式下，tool.html 的角色不同：

- **固定 tool 模式**：展示预注册的 VerifiableTool 目录 + ToolResult 历史（查看点），也可以手动试跑（调试辅助）
- **Claude research 模式**：展示 research skill 的 operations 记录——每条记录是"调了什么、拿到了什么 actual、得出了什么证据"。这个记录就是"链路追踪线索"——它告诉你这个 case 的归因经过了哪些操作、哪些操作是有效的、哪些是死胡同。**这是期望2的兑现：帮你在后续把有效的操作沉淀成固定 tool。**

### 两种模式的衔接

Claude research 模式的真正价值不是"用它做批量归因"（太贵），而是**用它做 tool 探索**：
1. 开 claude_research 模式跑几个典型 case
2. 看 operations 记录，找到"被反复调用的、产出关键 actual 的"操作
3. 把这些操作沉淀成 VerifiableTool，注册到固定 tool 模式
4. 后续批量归因用固定 tool 模式，成本低且稳定

tool.html 就是做第 2 步的界面——看 operations 记录，判断哪些值得沉淀成 tool。

### 实现层面

- `impl/core/config.py` 加 `attribute_mode` 配置读取
- `impl/core/pipeline.py` 的 attribute 阶段加分支：`if mode == "claude_research": spawn skill; else: 走现有 agno agent`
- `impl/server/service.py` 的 attribute 接口增加对 claude_research 模式的返回处理（operations 字段）
- `AttributeResult` 加 `operations` 字段（和 tool_call_log 平级，但语义不同：tool_call_log 是固定 tool 模式的调用记录，operations 是 claude research 模式的操作记录）
- 前端 tool.html 兼容两种模式的展示

### 成本对比

| 维度 | 固定 tool 模式 | Claude research 模式 |
|------|---------------|---------------------|
| 单 case 成本 | 低（几次 tool call） | 高（20 轮对话 + 大量源码阅读） |
| 覆盖范围 | 预设 tool 能覆盖的环节 | 整条链路，自由探索 |
| 可复现性 | 高（tool 确定性） | 中（LLM 探索路径不固定） |
| 适用场景 | 批量评测、CI | tool 探索、归因难点攻坚 |
| 前置条件 | 已经知道哪些 tool 有用 | 不需要，现场探索 |




------------


## 完整方案：Judge + Attribute 双模式

### 核心思路

Judge 和 Attribute 都支持两种模式：**固定 tool 模式**（低成本、稳定）和 **Claude research 模式**（高上限、实验性）。两者共享同一套归因链路，只是在"怎么获取证据做判断"上分叉。

Judge 和 Attribute 的难度差异决定了两种模式的价值：
- **Judge**：判断"对还是错"，相对简单，固定 tool 模式通常够用。Claude research 模式主要用于"边界 case 判定不准"时深入分析。
- **Attribute**：找"为什么错"，更难，需要探索源码、配置、API 行为。Claude research 模式在这里价值更大。

### 配置设计

```yaml
# config.yaml 或 project.yaml
judge:
  mode: fixed_tool  # fixed_tool | claude_research
  fixed_tool:
    tool_call_limit: 3
  claude_research:
    enabled: false
    model: haiku        # judge 相对简单，用轻量模型
    max_turns: 10

attribute:
  mode: fixed_tool  # fixed_tool | claude_research
  fixed_tool:
    tool_call_limit: 5
  claude_research:
    enabled: false
    model: sonnet       # attribute 更难，用更强模型
    max_turns: 20
```

### Judge 双模式

**固定 tool 模式**（现状）：
- 拿到 case 的 trace、expected/actual、field_patterns、capability_manifest
- 在 tool_call_limit 内调 field_capability、rule_verify 等 tool 做语义对照
- 产出 JudgeResult（verdict、wrong/missing/extra、fulfillment_assessments）
- 成本低、可复现

**Claude research 模式**（新增）：
- Spawn `judge-research` skill
- 拿到 case 的 trace + 项目源码路径 + 配置路径
- 自由探索：读配置看字段定义、读源码看边界条件、调 API 拿当前 actual 做交叉对照
- 产出结构化 JudgeResult + operations 记录
- 适用场景：边界 case 判定（"这个 query 到底算对还是算错"）、新字段/新规则首次出现时

**Judge 的 Claude research skill 设计**：

```
你是判定研究员。给你一个 case 的执行现场，你要判断业务输出是否正确。

工作流程：
1. 读 trace.extracted_output 看 actual 输出
2. 读 judge 的 expected/reference 看期望
3. 去项目源码里找判定依据：
   - 字段定义（field_definitions.yaml）：actual 用的操作符是否在字段能力范围内
   - 值映射（value_mappings.yaml）：actual 的值是否语义等价
   - 业务边界（judge_boundary.md）：这个 case 是否在判定范围内
4. 如果判定依据不足，调 API 拿当前 actual 做交叉对照
5. 产出判定结论 + 操作记录

输出格式：
{
  "verdict": "correct|incorrect|uncertain",
  "wrong": [...],
  "missing": [...],
  "extra": [...],
  "fulfillment_assessments": [...],
  "operations": [
    {"type": "config_read", "target": "field_definitions.yaml", "finding": "clientAge 支持 RANGE/GTE/LTE/MATCH", "actual": {...}},
    {"type": "api_call", "target": "search API", "params": {"query": "..."}, "actual": {...}, "comparison": "和 trace actual 一致"}
  ],
  "boundary_decision": {"judge_scope": "...", "reason": "..."}
}
```

### Attribute 双模式

**固定 tool 模式**（现状）：
- 拿到 case 的 trace、judge 结果、预注册的 VerifiableTool
- 在 tool_call_limit 内调 search_api、field_capability、rule_verify 等 tool
- 产出 AttributeResult（root_cause、causal_chain、suspected_locations）
- 成本可控

**Claude research 模式**（新增）：
- Spawn `attribution-research` skill
- 拿到 case 的完整上下文（trace + judge 结果 + 源码路径 + 配置路径）
- 沿业务链路自由探索：读源码找函数、调 API 验证行为、读配置查规则生效、跑本地函数验证逻辑
- 产出结构化 AttributeResult + operations 记录
- 适用场景：复杂归因（judge 判错但不知道原因）、tool 探索（哪些操作有效）

**Attribute 的 Claude research skill 设计**：

```
你是归因研究员。给你一个 case 的问题现场（trace + judge），
你要去项目源码里找问题原因。

工作流程：
1. 读 judge 结论，确认"错在哪里"（wrong/missing/extra）
2. 读 trace.execution_trace，定位第一个 diverged 节点
3. 从 adapter 源码反查这个节点对应的业务函数/API
4. 沿业务函数往上下游追溯，搞清楚数据流：query → 路由 → 字段提取 → 值转换 → 条件构造 → 最终输出
5. 对每个关键环节，试着"执行验证"：
   - 调 API 拿当前 actual（curl），对照 trace recorded actual
   - 读配置看规则是否生效（Read YAML），对照 trace 里的 matched_patterns
   - 读源码看处理逻辑，判断"这个函数在给定输入下该产出什么"
   - 如果函数是纯 Python，跑它看输出（python -c）
6. 定位根因：在哪个环节、什么原因导致了错误
7. 产出归因结论 + 操作记录

输出格式：
{
  "root_cause": "intent_api_call 阶段，LLM 对'年金险'查询返回 intent='other'，未正确映射到 nbev_planning",
  "causal_chain": [
    {"node": "request_normalization", "status": "passed", "evidence": "query 正常传递"},
    {"node": "intent_api_call", "status": "diverged", "evidence": "LLM 返回 other 而非 nbev_planning"},
    {"node": "label_mapping", "status": "diverged", "evidence": "other 无法映射到期望的 nbev_planning"}
  ],
  "operations": [
    {"type": "source_read", "target": "intent_prompt.py", "finding": "prompt 中未包含 nbev_planning 的 few-shot 示例", "actual": "..."},
    {"type": "config_read", "target": "intent_mapping.yaml", "finding": "4001 映射到 nbev_planning，但 LLM 未输出 4001", "actual": {...}},
    {"type": "api_call", "target": "search API", "params": {"query": "年金险规划"}, "actual": {"intent": "other"}, "comparison": "和 trace 一致，确认问题复现"}
  ],
  "suspected_locations": ["intent_prompt.py:45-78", "intent_mapping.yaml:12"],
  "fix_direction": "在 intent_prompt.py 中增加 nbev_planning 的 few-shot 示例",
  "cant_verify": [
    {"target": "LLM 的完整推理过程", "reason": "LLM 调用是黑盒，无法确定为什么没输出 4001"}
  ]
}
```

### 两种模式的衔接：从 research 沉淀到 fixed tool

这是整个方案的核心价值链路：

1. **开 claude_research 模式跑典型 case**（Judge 和 Attribute 都可以）
2. **看 operations 记录**，找到"被反复调用的、产出关键证据的"操作：
   - 反复调的 API → 沉淀成 `search_api` tool
   - 反复查的配置项 → 沉淀成 `field_capability` / `rule_verify` tool
   - 反复跑的本地函数 → 沉淀成可执行验证 tool
3. **把这些操作实现成 VerifiableTool**，注册到对应 adapter
4. **后续批量评测切回 fixed_tool 模式**，成本低、稳定、可复现

tool.html 就是这个过程的界面——看 operations 记录，判断哪些值得沉淀。

### 前后端改动

**后端**：
- `AttributeResult` 加 `operations` 字段（和 `tool_call_log` 平级，语义不同）
- `JudgeResult` 加 `operations` 字段
- `pipeline.py` 的 judge/attribute 阶段加模式分支
- `server.py` 的 judge/attribute 接口支持两种模式的返回

**前端 tool.html**：
- 两种模式共用同一个页面
- 左栏：固定 tool 模式展示 VerifiableTool 目录；Claude research 模式展示 operations 记录
- 中栏：operations 的详情（调了什么、拿到了什么 actual、得出了什么结论）
- 右栏：从 operations 中标记"值得沉淀成 tool 的操作"，一键生成 VerifiableTool 代码骨架

### 成本和适用场景

| | 固定 tool 模式 | Claude research 模式 |
|---|---|---|
| Judge | 日常判定，成本低 | 边界 case 判定、新规则探索 |
| Attribute | 日常归因，成本低 | 复杂归因、tool 探索、新项目初始化 |
| 单 case 成本 | Judge: ~1-2 次 LLM 调用; Attribute: ~2-3 次 | Judge: ~10 轮; Attribute: ~20 轮 |
| 可复现性 | 高 | 中（探索路径不固定） |
| 前置条件 | 已有 tool 沉淀 | 无，现场探索 |

### 推进顺序

1. 先在 `config.yaml` 加开关，pipeline 加分支（空壳，先走 fixed_tool）
2. 实现 `judge-research` skill + `attribution-research` skill
3. JudgeResult/AttributeResult 加 `operations` 字段
4. 前端 tool.html 兼容两种模式的展示
5. 在 client_search 上跑几个典型 case，验证 Claude research 模式能产出有效 operations
6. 从 operations 中沉淀出新的 VerifiableTool，验证"research → 沉淀"的闭环




------


你说得对，我之前的 skill 设计里有项目特定字段（`source_field_definitions`、`judge_boundary_protocals.md` 等），这些在新项目里不存在就无法运行。

## 泛化版 Skill 设计

核心原则：**skill 只描述输入和输出，输入全部从调用方传入，skill 内部不写任何项目特定路径或文件名。**

---

## Judge Research Skill

```markdown
# Judge Research Skill

## 输入

调用方传入一个 JSON 对象，包含：

- **case**：当前 case 的完整信息
  - trace：执行记录（含 extracted_output、execution_trace、normalized_request）
  - expected：期望输出（如果有的人为标注）
  - reference：参考输出（如果 case 自带）

- **project**：项目相关信息
  - source_root：业务系统源码根路径
  - config_files：配置文件路径列表（YAML/JSON/TOML）
  - docs：文档路径列表（业务说明、边界定义、判定标准等）
  - boundary_rules：判定边界说明文本（如果有）

- **context**：额外上下文
  - field_definitions：字段能力定义（如果有）
  - value_mappings：值映射规则（如果有）
  - equivalence_rules：语义等价规则（如果有）

## 任务

判断 case 的 actual 输出是否正确。

## 输出

单个 JSON 对象：
- verdict：correct / incorrect / uncertain
- wrong / missing / extra：条件列表
- fulfillment_assessments：逐期望判定
- boundary_decision：判定边界说明
- operations：操作记录列表，每条记录包含 type、target、finding、actual
- evidence_summary：一句话总结判定依据

## 约束

- 不确定就写 uncertain，说明缺什么信息
- 判定依据必须来自 config_files 或 docs 中的真实内容，不能编造
- 优先读配置和文档做判定，证据不足再调 API
```

---

## Attribute Research Skill

```markdown
# Attribute Research Skill

## 输入

调用方传入一个 JSON 对象，包含：

- **case**：当前 case 的完整信息
  - trace：执行记录（含 extracted_output、execution_trace、normalized_request）
  - judge：judge 的判定结果（含 wrong/missing/extra、fulfillment_assessments）

- **project**：项目相关信息
  - source_root：业务系统源码根路径
  - adapter_file：adapter 文件路径（描述了 live 链路的入口）
  - config_files：配置文件路径列表
  - docs：文档路径列表
  - api：远程 API 信息（base_url、endpoint、鉴权方式，如果有）

- **context**：额外上下文
  - 和 judge 一样的字段定义、映射规则等（如果有的话，帮助理解业务）

## 任务

找到这个 case 为什么出错的根因。

## 工作方式

1. 从 judge 的 wrong/missing/extra 入手，搞清楚"错在哪里"
2. 从 trace 找到第一个 diverged 的环节
3. 从 adapter 源码反查业务链路：入口 → 内部处理 → 最终输出
4. 对每个环节，能执行验证的就执行：读配置、调 API、读源码
5. 定位根因，说明证据

## 输出

单个 JSON 对象：
- root_cause：根因描述
- causal_chain：链路节点列表（每个节点：name、status、evidence）
- suspected_locations：疑似文件/配置位置
- fix_direction：修复方向
- operations：操作记录列表，每条记录包含 type、target、finding、actual
- cant_verify：无法验证的环节及原因
- evidence_summary：一句话总结

## 约束

- 有多少证据就下多强的结论，证据不足就标注 incomplete
- 优先读源码和配置，其次调 API
- 无法验证的环节如实标注，不要假装能验证
- 所有文件路径、配置项名称必须来自 project 信息中真实存在的路径，不能编造
```

---

## 泛化性的关键

两个 skill 都不写任何项目特定路径或文件名，所有路径通过 `project.source_root`、`project.config_files`、`project.docs`、`project.adapter_file` 从调用方传入。换一个新项目，只要调用方传入对应的路径列表，skill 就能独立运行，不需要修改 skill 本身。