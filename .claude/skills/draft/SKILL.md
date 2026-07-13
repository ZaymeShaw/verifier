---
name: draft
description: 围绕 objective 自主探索最优路径，固化为 agno 工具/知识，在固定数据上比较 current/draft，按 review 判断目标改善且未见 case 无退化才建议 promotion。
---

# Draft Skill

按 `verifier/spec/draft/draft.md` 工作。核心不是跑一次对比或重写一段 context，而是积累项目优化能力：先探索解决 objective 的最优路径，再把路径里的关键能力固化到 agno 框架，让框架内算法效果随时间抬升。

## 四层结构

```text
探索层  → AI 自主找到解决 objective 的最优路径
固化层  → 把路径里的工具/probe/知识提取成稳定产物
执行层  → 用固化产物跑 current/draft 对比
积累层  → 沉淀为下一轮 baseline，项目优化能力增长
```

没有探索层，后三层都是空的。

## config 与 prompt 分工

- config 管方向，整轮稳定：`objective`、`material`、`mock_source`、`review`、`max_iterations`、`report_path`。
- 运行时 prompt 管执行细节：调哪个函数、试哪个 probe、改哪个点。可以频繁变化。
- 反复要求改 objective 或换数据，说明 config 没写对，应更新 config 而不是在 prompt 临时承载。

## 工作循环

```text
理解 objective 和 material
→ 加载并固定 mock_source（迭代 case + 未见对照 case）
→ 运行 current，找到目标差距
→ 探索层：自主找到解决这类问题的最优路径
   · 手工跑链路、写一次性脚本、验证假设、复现根因
   · 不一定一开始就动 draft 代码
   · 目标是先证明这条路真的能解决这类问题
→ 固化层：从探索路径提取可复用产物
   · 哪些操作可泛化为稳定 tool/probe/agent
   · 哪些洞察可跨 case 复用为知识（gap 模式，不是 case 解法）
   · 哪些步骤可由 agno 框架现有能力承担
→ 执行层：把固化产物写入 draft，跑 current/draft
→ 按 review 判断目标差异（含泛化验证）
→ 用户补充需求 → 回到探索
→ draft 真正优于 current，或记录 blocker
```

## 探索层（核心）

AI 先自己探索最优方案，不在 production/draft 上改，而是先在临时脚本/小范围实验里达到 objective：

- 当前 production 在目标上的真实差距是什么？要运行、要看输出、要找首个偏离点。
- 这个差距由哪段代码/配置/链路导致？动手调用业务项目函数、api、probe、comparator，得到可复现证据。
- 假设改 X 能解决，怎么用最小实验证伪或证实。
- 探索目标是先证明路径可行，再谈固化。

这一层让效果上限从"LLM 单次推理质量"变成"被实验验证过的最优路径"。

## 固化层

探索收敛后回头看：

- 这轮用了哪些手动操作 → 哪些可泛化提取成稳定 tool/probe
- 哪些洞察跨 case 可复用 → 沉淀成知识（不是 case 解法，是 gap 模式）
- 哪些步骤本来可以由 agno 框架现有能力承担 → 直接复用
- 哪些需要新建 agent/tool → 落到 `draft/tools/`、`draft/probes/`

提取自被验证有效的探索路径，所以 agno 这套相对固定的框架也能产出较优算法效果。框架固定，但通过沉淀具体路径的有效工具组合，框架内算法效果可被持续抬升。

## 知识层（一等产物）

和 draft 同等。没有知识，下一轮 AI 仍要从零开始读 material。沉淀位置：`attribute/knowledge.md`、`judge/knowledge.md`。应包含：

- 链路地图：input → output 的关键函数和分支点，哪段验证过正常，哪段是已知 gap。
- gap 模式：这类问题的识别模式，不是这条 case 怎么修。
- probe 库：被验证过有效的 probe 及适用场景。
- 被否决的假设：试过什么、为什么不 work。
- 泛化边界：这个优化在什么范围有效，超出什么边界可能失效。

沉淀的是"这类 gap 怎么识别和定位"，不是"这条 case 怎么修"。promotion 时知识层一起成为新 baseline。

## 泛化（贯穿全程）

- 数据分层：迭代 case + 未见对照 case。前者参与 loop，后者只在 promotion 前跑，检测泛化退化。
- 改动约束：针对链路行为，不针对具体输入。例如不是"识别重疾险"，而是"extra_input_params 中的字段应进入 condition builder"。
- check 阶段：扫描 case id、样本专属数值、历史字段组合硬编码。
- promotion 硬条件：未见对照 case 上无退化，不是"冻结 case 上更优"。
- 知识沉淀：gap 模式而非 case 解法。

## current/draft 对比

- 同一批固定 case，current 和 draft 各跑一遍。
- 对比脚本只保留两边原始结果和异常，不输出通用"更优"结论。
- 是否真正改善由 skill 结合 objective、真实实验、项目已有 comparator/runtime check 和 review 判断。
- 字段更多、文本更长、confidence 更高都不能单独证明改善。
- 异常直接冒泡，不包装成成功。

## draft 实现要求

- 位于 `impl/projects/<project>/draft/<role>.py`。
- 与 production `<role>.py` 结构一致，promotion 时可直接覆盖。
- 实现协议自省得到的 `abstract_methods`，不覆盖模板方法和内部方法。
- 默认不被 production loader 加载；`<role>_draft.enabled: true` 时通过统一 loader 加载。
- 允许自带 `draft/tools/`、`draft/probes/`、`draft/context_builders/`，遵守协议。

## 硬约束

- draft 遵守当前协议，abstract methods 必须实现。
- draft 默认不进入 production，promotion 必须人工确认。
- mock 数据固定，要改必须用户明确更新 config。
- 证据来自当前运行、真实代码链路、业务接口或项目已有检查标准；prompt 声明不是证据。
- 不写死 case，不伪造强度，不把异常包装成成功，不把 fulfilled 强判失败。
- promotion 后关闭 `<role>_draft.enabled`。

## 角色

- attribute：内部技术视角，可探索代码链路，证据强度由当前成功运行的 probe/runtime check 决定。档位 strong/medium/weak/none。
- judge：外部业务视角，默认不读取内部代码；状态只使用 fulfilled/not_fulfilled/not_evaluable；证据不足时保持 not_evaluable。

角色细节见对应 `ROLE.md`，不在 SKILL 预判。

## promotion 条件

全部满足才给 promotion 建议，等人工确认：

1. objective 真正改善，按 review 逐条通过。
2. 固定数据上无退化。
3. 未见对照 case 上无退化（泛化验证）。
4. draft 通过 check 脚本：可编译、可加载、协议实现完整、灰度配置可实例化。
5. 探索路径已被记录，关键工具/probe/知识已被提取固化。
6. 无 overfit、无伪造、无异常被吞。

人工执行：

1. 覆盖 `draft/<role>.py` → `<role>.py`，搬移 `draft/tools/` → `tools/`，知识层进入 baseline，关闭 `<role>_draft.enabled`。
2. 提交 baseline 到主仓：
   ```bash
   git add impl/projects/<project>/<role>.py
   git add impl/projects/<project>/tools/
   git add .claude/skills/draft/<role>/knowledge.md
   git commit -m "draft promotion: <project>/<role> baseline update"
   ```
3. 下一轮 AI 直接读取更新后的 `<role>.py`、`tools/`、`knowledge.md`，站在这一轮之上继续探索。

skill 不自动执行。

## 与 /attribute skill 的关系

当前阶段并存，互不修改。`/draft` 的优势不是在归因细节上一定比 `/attribute` 更强，而是把"自主探索 → 固化工具/知识 → 固定数据验证 → 人工 promotion → 沉淀为新 baseline"做成跨角色、可累积的机制。

## 终态

```text
用户给方向
→ AI 自主探索最优路径
→ 提取工具/probe/知识固化到 agno 框架
→ 用固化产物跑 current/draft，证明目标改善且无退化
→ promotion 后成为新 baseline
→ 下一轮站在上一轮之上
```

关键差异：探索层让效果上限从"LLM 单次推理"变成"被验证过的最优路径"；固化层让这个路径变成 agno 框架内的稳定能力；积累层让每轮探索都站在上一轮之上。

## 找工具

SKILL 不列文件树。执行者找工具、模板和脚本时看 `MAP.md`。

## promotion 前置检查

`check_draft.py --promotion --project <project> --role <role> --unseen-cases <path>` 在常规校验之外，还会：

- 输出 `knowledge.md` 的修改时间，让用户确认本轮探索路径和知识被记录。
- 在未见对照 case 上运行 current/draft，输出两边原始结果用于泛化退化判断。

不做分数阈值或字段匹配判断。是否真正改善、是否有退化，由 skill 结合 `objective`、`review` 和真实实验决定。
