verifier/spec/draft/draft.md

目标

围绕一个明确的优化目标，在固定数据上探索并改进项目层角色实现（attribute / judge / 后续可扩展角色），用真实运行证据判断 draft 是否比 current
更好，再由人工决定是否 promotion。不追求字段更多或报告更完整。

适配范围

适用于 impl/core/<role>_protocol.py 定义的项目层角色。当前覆盖 attribute 和 judge；后续角色按同一机制扩展，不由本 spec 预判扩展点清单。

输入

用户提供 config，真正驱动工作的是其中四项：

- objective：本轮要改善的目标行为，描述到可观察程度。
- material：理解项目和寻找优化路径时应读的源码、配置、文档、trace、已有 tool。
- mock_source：项目已有的固定 mock 数据集，整个 loop 不修改。
- review：用户判断目标是否真正改善的原则，结论必须逐条回答。

其余字段（project_id、role、max_iterations、report_path 等）只承载运行参数，不构成优化目标本身。

工作循环

理解 objective 和 material
→ 加载并固定 mock_source
→ 运行 current，找到目标差距
→ 探索代码/配置/业务链路/已有检查能力，实测优化方向
→ 将有效改动写入 draft
→ 在同一数据上运行 current/draft
→ 按 review 和真实实验判断目标差异 
→ 用户可补充需求 → 修 draft/tool → 再验证
→ draft 真正优于 current，或达到上限后记录 blocker

循环中允许反复回到探索阶段；不要求一次走完。每一轮应留下：

- 目标
- 实际探索与改动
- 关键实验与观察
- current/draft 的目标相关差异
- 按 review 的结论和遗留问题

draft 实现要求

- 位于 impl/projects/<project>/draft/<role>.py。
- 与 production <role>.py 结构一致，promotion 时可直接覆盖，不需要改名或改构造签名。
- 实现协议自省得到的 abstract_methods；不覆盖模板方法和内部方法。
- draft 不被 production loader 自动加载；只有 project.yaml 的 <role>_draft.enabled: true 时通过统一 loader 加载。
- promotion 前所有改动只在 draft/ 下，不动 production。
固定数据

- mock_source 必须指向项目已有数据，不另生成冻结副本。
- loop 中不得修改 mock 数据；要换数据必须用户明确更新 config。
- skill 在加载和每轮运行前后对参与评测的源数据建立摘要基线，变化即终止 loop。
- 用户明确更新 config 后才可建立新基线。

current/draft 对比

- 同一批固定 case，current 和 draft 各跑一遍。
- 对比脚本只保留两边原始结果和异常，不输出通用“更优”结论。
- 是否真正改善由 skill 结合 objective、真实实验、项目已有 comparator/runtime check 和 review 判断。
- 字段更多、文本更长、结构更复杂、confidence 更高都不能单独证明改善。
- 异常直接冒泡，不包装成成功，不生成可用于 promotion 的报告。

硬约束

以下由协议、loader、check 脚本和人工流程共同保证，不需要在 SKILL 中反复陈述：

- draft 遵守当前协议；abstract methods 必须实现；模板方法和内部方法不可覆盖。
- draft 默认不进入 production；promotion 必须人工确认。
- mock 数据固定；要改必须用户明确更新 config。
- 证据来自当前运行、真实代码链路、业务接口或项目已有检查标准；prompt 声明不是证据。
- 不写死 case、不伪造强度、不把异常包装成成功、不把 fulfilled 强判失败。
- promotion 后关闭 <role>_draft.enabled。

角色

attribute：内部技术视角，可探索代码链路，证据强度由当前成功运行的 probe/runtime check 决定。

judge：外部业务视角，默认不读取内部代码；状态只使用 fulfilled / not_fulfilled / not_evaluable；证据不足时保持 not_evaluable。

角色细节由对应 ROLE.md 给，不在本 spec 预判。

promotion

只有满足以下条件时才给出 promotion 建议，并等待人工确认：

- objective 真正改善，并且按 review 逐条通过。
- 固定数据上无退化。
- draft 通过 check 脚本：可编译、可加载、协议实现完整、灰度配置可实例化。
- 无 overfit、无伪造、无异常被吞。

promotion 由人工执行：覆盖 draft/<role>.py → <role>.py，搬移 draft/tools/ → tools/，关闭 <role>_draft.enabled。skill 不自动执行。

不属于本 spec 的事

- 不预判扩展点清单：由协议自省动态发现。
- 不预判 case 字段：由当前 ProjectXxx 模板方法签名派生。
- 不预判 result_summary 字段：由当前 XxxResult schema 决定。
- 不替代项目已有 comparator/runtime check/tool，只复用或补充上下文。
- 不与 /attribute skill 合并；当前阶段两者并存，互不修改。




-----------


三点都合理，按顺序回答。

1. config 与运行时 prompt 的职责平衡

建议这样划分：

config（用户管控方向）

- objective：本轮要改善什么、约束、偏好。
- review：怎样算改善。
- material：探索时应读哪些源码、配置、文档、工具。
- mock_source：固定数据集。
- max_iterations、report_path：运行参数。

config 是“用户给的方向”，一次确定后整轮稳定，不随单次对话漂移。

运行时 prompt（执行细节）

- 某次探索发现具体可疑函数、想试某个 probe；
- 针对当前 case 的临时假设；
- 用户看到某轮结果后补充“再深入 parser 那条分支”。

prompt 是“执行过程中的具体优化点”，可以频繁变化，由 skill 翻译成对当前 draft/实验的调整，但不改 config。

平衡原则：

- config 决定“目标、约束、验收标准”，不由 prompt 覆盖。
- prompt 决定“这一步怎么探索、改哪个点、用什么实验”，但不能改 mock 数据、review 原则或 promotion 判定。
- 若 prompt 反复要求改 config 层面的事（例如改 objective、换数据集），skill 应提示用户更新 config，而不是在 prompt 里临时承载，否则下一轮就丢失方向。

这样既允许灵活补充细节，又防止“config 是形式、实际靠 prompt 驱动”的失控。

2. reference / scripts / template 的管理

同意。建议在 skill 目录下放一个 MAP.md（或 INDEX.md），只做映射，不进 SKILL.md：

.claude/skills/draft/
├── SKILL.md          # 只讲目标和思考方式
├── MAP.md            # 文件用途与调用关系
├── reference/        # 模板与说明
├── scripts/          # 可执行脚本
└── <role>/
├── ROLE.md
└── scripts/

MAP.md 内容示例：    

| 文件 | 用途 | 何时用 |
|---|---|---|
| reference/draft_config_template.yaml | config 字段与项目关联方式 | 用户准备 config 时 |
| scripts/introspect_protocol.py | 协议自省，拿 abstract methods | 写 draft 前 |
| scripts/check_draft.py | 校验 draft 可加载、协议完整 | 每轮修改后 |
| attribute/scripts/compare_attribute.py | 同数据运行 current/draft | 验证阶段 |
| judge/scripts/compare_judge.py | 同上，judge 角色 | 验证阶段 |
| reference/project_yaml_draft_switch_template.yaml | 灰度配置开关 | promotion 时 |

SKILL.md 不再列文件树，只保留目标和思考方式；执行者需要找工具时看 MAP.md。

3. 理想流程：用户给方向，AI 自主探索并固化成 agent/工作流

这个方向我觉得对，且和当前架构一致。落地形态：

用户给 config（objective + material + review + mock_source）
↓
AI 探索 material：读源码、跑 current、定位首个偏离点
↓
AI 构建本轮需要的 agno agent / tool / probe
↓
AI 把有效探索固化成 draft：role 实现 + 必要的 draft tools
↓
AI 在固定数据上自验证，按 review 判断
↓
未达标 → 回到探索；达标 → 给 promotion 建议，等人工确认
↓
promoted 后，draft 成为新的 production baseline

关键点：

- AI 不是被动走流程，而是主动决定“这次该建什么 probe、调什么局部链路、引入什么 tool”。
- 这些产物落在 impl/projects/<project>/draft/ 下，遵循 ProjectXxx 协议和 VerifiableTool。
- 经过多轮后，项目会沉淀出一套稳定可复用的 agent/tool/probe 组合，作为后续优化的基线。
- skill 不只是“跑一次对比”，而是“积累一个可演进的优化体系”。

实现上需要补的：

- 允许 draft 自带 draft/tools/、draft/probes/、draft/context_builders/，只要遵守协议。
- check_draft.py 只校验协议合规与可加载，不限定 draft 内部结构。
- compare 脚本保持中立，提供事实。
- MAP.md 记录沉淀下来的工具与 probe，让下一轮探索可复用。