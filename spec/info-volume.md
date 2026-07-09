

完整方案总结

核心定位

两件事，职责严格分开：

归因Skill：离线运行的"系统能力构建者"。通过模拟操作原业务系统、构建 tool、模拟调用归因 agent 做实验，验证 tool
和调用链路的有效性。产出物是"经过实验验证的 tool 体系 + 信息边界声明"。

归因 agent：在线运行的"缺陷定位者"。在 Skill 提供的 tool
体系范围内，基于有限资源推理最可能的业务系统缺陷点，产出"诊断 + 可执行验证步骤 + 定向修复建议"，但不改代码。

---
Skill 设计

职责

确保归因启动时，tool 体系是完整的、经过验证的。不做归因推理，只做"系统能力构建 + 实验验证"。

核心工作流

1. 模拟操作原业务系统
- 用历史 case 的 trace 数据喂给现有 tool，看 actual 是否有信息量
- 调原业务系统 API/函数，理解什么信息对归因有用

2. 构建候选 tool
- 从业务系统源码、配置、API 自动推导出候选 VerifiableTool
- 构建方式：endpoint 自动发现（已有）、源码函数提取、配置规则映射...

3. 模拟调用归因做实验验证
- 用历史 case + 现有 tool catalog，模拟归因 agent 推理
- 观察在哪个环节卡住、哪类信息调不出来
- 加入候选 tool，重新模拟，看归因能不能跑通
- 跑通才确认 tool 有效，跑不通换构建方式

4. 产出
- 经过实验验证的完整 tool 体系
- 信息边界声明（哪些维度真正不可达）
- 建议补齐清单（对无法自动构建的 tool，提示 adapter 扩展）

权限约束

- 自动执行：纯机械生成（如 endpoint 发现扫描落盘），不涉及业务判断
- 只出建议：需要人工拍板的（如业务函数选哪些做成 tool），产出建议清单
- 模拟实验在隔离环境跑，不进真实归因回路

---
归因 agent 设计

输入

- trace + judge 结果
- Skill 提供的 tool catalog（经过验证的完整体系）
- 信息边界声明（不可达维度）

推理使用约束

1. 只基于可达信息推理
归因只在 tool catalog 覆盖范围内规划 tool 调用。不可达维度在结论中标注"受信息边界限制"，不尝试调用、不硬凑。

2. tool 调用基于"信息缺口 × 证据类型"匹配
每个 tool 声明自己的证据类型（纯能力声明，不含操作指引）。LLM 推理路径是"我缺什么证据 → 谁的证据类型匹配 →
调它"，不是按预设顺序。

3. 反思回合
每轮 tool call 后，LLM
产出"当前已知/未知"的轻量反思。下一轮基于信息状态决定调什么。反思只问信息状态，不暗示步骤——链路由 LLM
动态形成，不是人预设的工作流。

4. 不承担"系统缺什么"的判断
imcomplete_reason 只区分"可达信息不足"和"推理链路断裂"，不写"系统缺 X tool"——那是 Skill 的事。

产出

- 最可能缺陷点（suspected_locations + root_cause_hypothesis）
- 可执行验证步骤（"调 X tool 传 Y 参数，若返回 Z 则假设成立"）
- 定向修复建议（指向具体业务函数/配置/规则 + 描述修法，不写代码）
- 证据强度标注（证据强的假设排前面，弱的排后面，无证据的不硬凑）

---
两者关系

Skill（离线）
└─ 模拟操作业务系统 → 构建候选 tool → 模拟归因实验验证 → 产出完整 tool 体系
                                                                ↓
归因 agent（在线）                                                    │
└─ 消费 tool 体系 + 信息边界声明 → 在有限资源内推理 → 产出诊断+验证+修复建议
                                                                │
                                                                ↓
                                                        imcomplete_reason
                                                        反馈给 Skill 重新补 tool
                                                        
反馈回路是异步、跨 case 的——一个 case 归因受阻的反馈，驱动 Skill 改进 tool 体系，后续 case 受益。
                
---
泛化性来源

- Skill 验证逻辑不绑定具体 tool：实验方法（模拟归因、加候选 tool、跑通验证）对所有项目通用
- 归因推理不绑定预设步骤：反思回合只问信息状态，LLM 自主形成推理链路
- tool 体系是声明式的：新 tool 加入时声明证据类型，归因自然能匹配，不需要改归因逻辑
- 不存在"加字段加映射"的脚手架：ToolResult 不填 fills_gap/next_gap_hint，归因不预设中间状态





-----------

我觉得你可以不用假设归因agent的形式，可以有一个建议的方案，但是具体的归因agent的形式可以交由归因Skill来推断（分析可行的基于agno的agent构建链路和所需构建的tool），
1。产出两个东西，一个是协议范围内实现的impl/projects/<project>/draft/attribute.py以及impl/projects/<project>/draft/t 
ools)，后续我们想用的话可以直接搬移这两个东西到impl/projects/<project>/中进行使用。
2。然后归因skill自己本身就有归因的能力，可以做一次性的归因



明白了，你的意思是 Skill 的产出不再只是"tool 体系"，而是两个更具体的东西：

1. 一个可搬运的归因方案：Skill 通过模拟实验，产出该项目的"归因 agent 定义 + 配套 tool 集合"，以
draft/attribute.py 和 draft/tools/ 的形式落盘。后续人工确认后直接搬进项目目录就能用。
2. Skill 自身具备归因能力：Skill 不止是"构建归因方案"，它自己就能做一次性归因——在 draft
产出之前，用模拟实验的过程顺带产出归因结论。

---
这个调整对整体方案的影响

Skill 的产出物从"tool 体系"变成"可搬运的归因方案"

之前 Skill 的产出是"经验证的 tool 体系 + 信息边界声明"，归因 agent 怎么用这套 tool 是归因 agent 自己的事。现在
Skill 的产出直接是"一个完整的归因 agent 定义 + 配套 tool"——也就是把"怎么用 tool 做归因"这件事也一并设计了。

这意味着 Skill 的实验范围扩大了：之前只验证"这个 tool 能不能提供有用证据"，现在要验证"这套 tool 搭配这个 agent
构建方式，能不能跑通归因"。Skill 不仅找 tool，还找"归因 agent 的最佳形态"——是用单轮 agent、多轮反思、还是多
agent 协作——由 agno 框架的 agent 能力决定，Skill 通过实验推出来。

Skill 自带归因能力

这个设计很自然——Skill 在模拟实验过程中，本来就要跑归因来验证 tool
有效性。既然已经跑了，结果直接作为一次性归因产出，不浪费。这个一次性归因可以：
- 作为 draft 归因方案的"效果预览"——证明这套方案能产出什么质量的结论
- 作为当前 case 的即时归因结果——不需要等 draft 搬移、部署，直接就能用

归因 agent 不再需要被"通用层设计"

之前方案里用了一大段讨论归因 agent
的推理约束（反思回合、证据类型匹配、信息边界消费...），现在这些约束不需要硬编码在通用层。归因 agent
的具体形态——用什么 agent 结构、怎么调 tool、反思回合怎么设计——由 Skill 通过实验推出来，落到 draft/attribute.py
里。通用层只保留 agno 桥接能力（build_agno_tools、ToolRegistry、ToolOrchestrator），不规定归因 agent
怎么用它们。

---
修正后的完整方案

Skill（离线，运行在项目根目录下）

输入：项目 spec + 历史 case（trace + judge 结果）+ 业务系统源码/API

实验过程：
1. 模拟操作业务系统，理解什么信息对归因有价值
2. 构建候选 tool，放进 draft/tools/
3. 尝试不同的 agno agent 构建方式（单轮/多轮/反思/多 agent 协作），找到能跑通归因的链路
4. 用模拟归因验证"这套 agent + 这套 tool"能否产出有效归因结论
5. 迭代：tool 不够补 tool，agent 结构不对调结构，直到实验闭环通过

产出物：
- impl/projects/<project>/draft/tools/ — 经过实验验证的归因 tool 集合
- impl/projects/<project>/draft/attribute.py — 经过实验验证的归因 agent 定义（agno agent 构建方式 + 推理逻辑）
- 一次性归因结果（实验过程中顺带产出的，作为即时诊断）

搬运方式：人工确认后，draft/ 下的内容搬进 impl/projects/<project>/ 对应目录，成为正式归因方案。

归因 agent（在线，运行在真实 case 上）

形态：消费 draft/ 搬运后的正式方案（attribute.py + tools/）。具体实现由 Skill 产出的 attribute.py
决定——可能是简单单轮 agent，也可能是多轮反思或多 agent 协作，不做通用层规定。

通用层只保留：agno 桥接（build_agno_tools、ToolRegistry、ToolOrchestrator），不规定归因 agent 怎么用它们。

---
关键变化

┌─────────────────────────────────────┬─────────────────────────────────────────────────────┐
│                之前                 │                        现在                         │
├─────────────────────────────────────┼─────────────────────────────────────────────────────┤
│ 通用层设计归因 agent 的推理约束     │ Skill 通过实验推断归因 agent 的最佳形态，落到 draft │
├─────────────────────────────────────┼─────────────────────────────────────────────────────┤
│ Skill 只产出 tool 体系              │ Skill 产出"归因 agent + tool"的完整方案             │
├─────────────────────────────────────┼─────────────────────────────────────────────────────┤
│ 归因 agent 形态假设一个反思回合模式 │ 不假设，由实验决定——可能是单轮、多轮、多 agent 协作 │
├─────────────────────────────────────┼─────────────────────────────────────────────────────┤
│ Skill 不产归因结论                  │ Skill 自带归因能力，实验过程顺带产出一次性归因      │
└─────────────────────────────────────┴─────────────────────────────────────────────────────┘




--------


既然如此的话，其实就应该把各项目attribute的个性化逻辑，单独划分出来，放到impl/projects/<project>/attribute.py里面，judge也是同理


对，这个划分是顺理成章的。

当前代码里 impl/core/attribute.py 和 impl/core/judge.py 是通用层，但里面其实塞了不少项目个性化逻辑——比如
attribute.py 里 _load_source_code_evidence 那套"优先预加载 prompt/config/field_definition
关键词文件"的逻辑，本质上是 client_search 这类项目的归因策略，不是通用归因逻辑。judge 估计也有类似情况。

按你这个思路拆分后：

impl/core/attribute.py（通用层）：
- 定义归因 agent 的协议、tool 编排入口、agno 桥接调用方式
- 不包含任何项目归因策略

impl/projects/<project>/attribute.py（项目层）：
- 该项目的归因 agent 具体形态——喂什么 prompt、用什么 tool 调用策略、产出什么结构的归因结论
- 项目特有的源码/配置预加载策略、归因中间状态判断、imcomplete_reason 生成逻辑都放这里

impl/projects/<project>/judge.py（项目层）：
- 同理，该项目的判定逻辑——业务预期怎么提取、fulfillment 怎么评、verdict 怎么定
- 通用层只保留 JudgeResult 数据结构和判定协议入口

Skill 的产出就清晰了：Skill 实验后产出的 draft/attribute.py 和 draft/tools/，搬运后直接成为该项目的 attribute.py
    + tools/，对应到 impl/projects/<project>/ 下。Skill 的"实验"本质就是在为这个项目找到最合适的个性化归因形态。

一个要守的约束：通用层的 attribute.py 不调用项目层（避免循环），项目层的 attribute.py
只通过通用层提供的协议入口（agno 桥接、ToolOrchestrator）使用通用能力。这样 Skill 产出的 draft
不需要改通用层就能落地。



    这几个概念是这个项目里 agno 框架使用方式的具体术语：

agno 桥接调用方式：指的是怎么把 VerifiableTool（项目定义的 tool 数据模型）转换成 agno 框架能识别的 Function
对象，然后喂给 agno 的 Agent。当前代码里 protocol.py 的 build_agno_tools() 函数就是做这个转换的——把
VerifiableTool 的 parameters（JSON Schema 格式）直接映射到 agno Function 的入参定义，execute_fn 变成 agno 的
entrypoint。这套转换逻辑就是"桥接"。

tool 编排入口：指的是 ToolRegistry + ToolOrchestrator 这对组合。ToolRegistry 管理所有已注册的
tool（增删查），ToolOrchestrator 负责接收调用请求（tool_id + params），找到对应的 tool，执行 execute_fn，返回
ToolResult。LLM 决定调什么 tool 之后，实际执行是由编排层统一调度的，不是 LLM 直接调业务函数。

为什么通用层要保留这些：不管项目层的 attribute.py 做什么归因策略、用什么 agent 结构，它最终都要通过 agno 框架和
tool 体系来执行。通用层负责"怎么把 tool 安全地注册、调度、喂给 agno"，项目层负责"用哪些 tool +
怎么用它们做归因"。两者分层，Skill 产出的 draft 只需要调用通用层提供好的桥接和编排能力，不需要自己重写这套。



------------



fulfilled 完整描述

核心定义

fulfilled 是 judge 阶段对业务预期达成情况的判定，必须基于业务实际情况得出结论，不是 LLM 凭空猜测。

枚举值（三层，值域统一）

- fulfilled — 业务预期实际达成了。必须有业务实际证据支撑，不是"看起来对"或"LLM 觉得对"。
- not_fulfilled — 业务预期实际没有达成。必须有业务实际证据证明没达成，比如实际输出和预期不符、实际行为没发生。
- not_evaluable — 判断不了。业务上真有问题、报错了、或者信息不足无法判断时填这个，不能假装判断得了。

关键约束：不允许在不具备判断条件时强行填 fulfilled 或 not_fulfilled。业务报错、信息缺失、判断不了，就只能填 not_evaluable，不能为了"给个结论"而硬凑。

两层结构

- 细粒度 fulfilled：每条 business_expectation 单独评估，值域 fulfilled / not_fulfilled / not_evaluable
- 整体 fulfilled：聚合细粒度结果得出的总体业务情况，值域完全相同，依然是 fulfilled / not_fulfilled / not_evaluable，不引入 partial 之类的新枚举

整体只是聚合语义，不发明新状态。

judge 产出

judge 只产出 fulfillment（细粒度 + 整体两层），不产 verdict。verdict（correct/incorrect 之类）这个维度被删掉，因为 fulfilled
已经表达了对错，不需要再引入第二个对错维度。

归因使用方式

- 整体 fulfilled → 归因直接产 no_issue，不追失败根因
- 整体 not_fulfilled 或 not_evaluable → 归因追哪些预期没达成/判断不了的根因
- 根据哪些预期 not_fulfilled / not_evaluable 决定追哪些根因

逻辑比之前用 verdict 直接，因为不用从 correct/incorrect 反推回"哪些预期没满足"，fulfillment 状态本身就是归因输入。






---------once at 20260707



我们总体盘点下，其实之前无轮judge还是attribute，都有大量非通用意义必要的字段在相关schema中，很多是没必要作为各项目通用字段存在的，我觉得需要盘点下，协议角度应该只保留必要的部分

你这个判断是对的。从前面读过的代码看，judge 和 attribute 的 schema 里确实堆了大量项目个性化字段，通用层不该背这些。

该清理的方向

JudgeResult 该砍的：
- intent_model / reconstructed_intent / consumer_contract — 这些是 client_search 类项目为了反推用户意图塞进来的，不是所有项目都有 intent 概念
- semantic_equivalence_checks / verdict_derivation / boundary_decision / evaluation_boundary — 这些是某个项目判定流程的中间产物，不该当通用字段
- judge_basis / judge_method — 项目特有判定方法的标注，通用层不需要
- quality_flags / needs_human_review — 评估流程的元信息，不是判定本身
- verdict — 前面已经讨论要删

JudgeResult 该保留的：
- trace_id / project_id — 标识
- business_expectations — 业务预期列表（细粒度）
- fulfillment_assessments — 每条预期的 fulfilled 状态（细粒度）
- overall_fulfillment — 整体 fulfilled 状态
- evidence / reasoning_summary — 判定依据

AttributeResult 该砍的：
- causal_category / taxonomy — 项目特有分类体系，不该通用化（marketing-planning 和 client_search 的分类完全不同）
- chain_nodes / earliest_divergence — 某类项目为了链路归因塞的结构，不是所有归因都走链路
- evidence_coverage — 归因质量自评指标，是流程字段不是归因结论
- analysis_quality / incomplete_reason — 前面讨论过，归因 agent 不产 incomplete_reason
- verification_steps / patch_direction — 这些是归因产出，但是否所有项目都需要这两类产出值得商榷
- raw_model_output — LLM 调用的原始记录，是 debug 字段不是归因结论
- tool_call_log — 同上，是执行记录

AttributeResult 该保留的：
- trace_id / project_id / case_id — 标识
- suspected_locations — 缺陷点定位
- root_cause_hypothesis — 最可能的根因假设
- evidence — 支撑假设的证据
- 证据强度标注（强/弱/无）— 让结论可信度可表达
- summary — 可读摘要

协议层原则

通用层只保留"任何项目做归因都需要的最小产出"：定位 + 假设 + 证据 + 证据强度。项目特有的产出（分类体系、链路结构、验证步骤、修复方向）全部下沉到
impl/projects/<project>/attribute.py 自己定义，不进通用 schema。impl/projects/<project>/judge.py同理

这样通用 schema 是稳定的，项目加字段不影响通用层；Skill 产出的 draft/attribute.py 也可以自由定义项目特有产出结构，不受通用 schema 限制。







imcomplete_reason：归因 agent 的职责是"在有限资源内做最大限度的推测"，不是"解释为什么做不出来"。即使证据不足，它也应该给出"基于当前证据，最可能的假设是X，但证据强度低，建议验证 Y"——这是有信息量的结论，不是"我做不到"。归因 Skill 需要 imcomplete_reason 来驱动 tool 补齐（"这个 case归因卡住了，原因是什么"），但这个是 Skill 自己的内部诊断，不需要成为归因 agent 的产出字段。